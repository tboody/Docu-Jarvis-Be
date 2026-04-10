from __future__ import annotations

import asyncio
import logging
import os
import re
import select
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from uuid import uuid4

from app.core.config import settings
from app.core.exceptions import AnalysisError
from app.models.responses import JobStatus

logger = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# In-memory job registry (single-process; swap for Redis in production)
_jobs: dict[str, "AnalysisJob"] = {}


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


class AnalysisJob:
    def __init__(self, job_id: str, mode: str, repo_url: str):
        self.job_id = job_id
        self.mode = mode
        self.repo_url = repo_url
        self.status: JobStatus = JobStatus.pending
        self.error: Optional[str] = None
        self.result: Optional[dict] = None
        self.report_path: Optional[str] = None
        # Unlimited queue — progress events are small
        self.progress_queue: asyncio.Queue = asyncio.Queue()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "mode": self.mode,
            "repo_url": self.repo_url,
            "error": self.error,
            "result": self.result,
        }


def create_job(mode: str, repo_url: str) -> AnalysisJob:
    job_id = str(uuid4())
    job = AnalysisJob(job_id, mode, repo_url)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[AnalysisJob]:
    return _jobs.get(job_id)


def _build_cmd(mode: str, target: str, report_path: str, options: dict) -> list[str]:
    binary = settings.docu_jarvis_binary
    if not Path(binary).exists():
        raise AnalysisError(
            f"docu-jarvis binary not found at '{binary}'. "
            "Set DOCU_JARVIS_BINARY in .env."
        )

    if mode in ("security", "impact", "why"):
        return [binary, f"-{mode}", target, "-report", report_path]

    if mode == "debug":
        from_date = options.get("from_date", "1 month ago")
        to_date = options.get("to_date", "today")
        bug_desc = options.get("bug_description", "unknown bug")
        return [binary, "-debug", from_date, to_date, bug_desc]

    if mode == "explain":
        commit = options.get("commit_hash", "HEAD")
        question = options.get("question", "Explain this commit")
        return [binary, "-explain", commit, question]

    if mode == "update_docs":
        docs_files = options.get("docs_files") or "all"
        cmd = [binary, "-update-docs", docs_files]
        custom_prompt = options.get("custom_prompt", "")
        if custom_prompt:
            cmd += ["-custom", custom_prompt]
        return cmd

    if mode == "write_docs":
        topics = options.get("docs_topics") or options.get("target", "all")
        return [binary, "-write-docs", topics]

    raise AnalysisError(f"Unsupported mode: {mode}")


def _run_with_pty(cmd: list[str], cwd: str, env: dict) -> tuple[int, list[str]]:
    """
    Run *cmd* inside a pseudo-TTY so bubbletea renders correctly.
    Returns (returncode, list_of_clean_lines).
    """
    try:
        import pty  # Unix only

        master_fd, slave_fd = pty.openpty()

        proc = subprocess.Popen(
            cmd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=env,
        )
        os.close(slave_fd)

        lines: list[str] = []
        buf = b""

        while True:
            try:
                readable, _, _ = select.select([master_fd], [], [], 0.2)
                if readable:
                    chunk = os.read(master_fd, 4096)
                    if chunk:
                        buf += chunk
                        text = buf.decode("utf-8", errors="replace")
                        clean = strip_ansi(text)
                        if "\n" in clean:
                            parts = clean.split("\n")
                            for part in parts[:-1]:
                                stripped = part.strip()
                                if stripped:
                                    lines.append(stripped)
                            buf = parts[-1].encode("utf-8", errors="replace")
                else:
                    if proc.poll() is not None:
                        # Flush remaining buffer
                        remaining = strip_ansi(buf.decode("utf-8", errors="replace"))
                        if remaining.strip():
                            lines.append(remaining.strip())
                        break
            except OSError:
                break

        try:
            os.close(master_fd)
        except OSError:
            pass

        rc = proc.wait()
        return rc, lines

    except ImportError:
        # Windows fallback — no pty available
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=settings.job_timeout,
        )
        lines = [
            strip_ansi(l).strip()
            for l in (result.stdout + result.stderr).splitlines()
            if l.strip()
        ]
        return result.returncode, lines


async def run_analysis(
    job: AnalysisJob,
    repo_path: str,
    target: str,
    api_key: str,
    options: dict,
) -> None:
    """
    Async wrapper — runs the Go binary in a thread pool, streams
    progress lines back through job.progress_queue.
    """
    from app.services.parser import parse_report

    loop = asyncio.get_running_loop()

    # Set up report output path
    report_path = str(Path(settings.temp_dir) / job.job_id / "report.html")
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    job.report_path = report_path

    # Build env — pass API key to the Go binary
    env = {**os.environ, "ANTHROPIC_API_KEY": api_key, "TERM": "xterm-256color"}

    try:
        cmd = _build_cmd(job.mode, target, report_path, options)
    except AnalysisError as exc:
        job.status = JobStatus.failed
        job.error = str(exc)
        await job.progress_queue.put({"type": "done", "status": "failed"})
        return

    job.status = JobStatus.running
    await job.progress_queue.put(
        {"type": "status", "text": f"Running {job.mode} analysis…"}
    )

    def _send(line: str) -> None:
        """Thread-safe progress push."""
        loop.call_soon_threadsafe(
            job.progress_queue.put_nowait, {"type": "log", "text": line}
        )

    def _run() -> tuple[int, list[str]]:
        rc, lines = _run_with_pty(cmd, repo_path, env)
        for ln in lines:
            _send(ln)
        return rc, lines

    try:
        rc, output_lines = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=settings.job_timeout,
        )
    except asyncio.TimeoutError:
        job.status = JobStatus.failed
        job.error = "Analysis timed out"
        await job.progress_queue.put({"type": "done", "status": "failed"})
        return
    except Exception as exc:
        logger.exception("Unexpected error during analysis")
        job.status = JobStatus.failed
        job.error = str(exc)
        await job.progress_queue.put({"type": "done", "status": "failed"})
        return

    # Parse HTML report (security / impact / why) or use raw output
    html_path = Path(report_path)
    if html_path.exists():
        try:
            result = parse_report(html_path.read_text(encoding="utf-8"), job.mode)
            job.result = result
            job.status = JobStatus.completed
        except Exception as exc:
            logger.warning("HTML parse failed, falling back to raw output: %s", exc)
            job.result = {"output": "\n".join(output_lines)}
            job.status = JobStatus.completed
    elif output_lines:
        # debug / explain — no HTML report
        job.result = {"output": "\n".join(output_lines)}
        job.status = JobStatus.completed
    else:
        job.status = JobStatus.failed
        job.error = f"Analysis produced no output (exit code {rc})"

    await job.progress_queue.put({"type": "done", "status": job.status.value})
