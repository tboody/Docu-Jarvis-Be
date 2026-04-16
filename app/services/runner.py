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

# Braille + block spinner characters used by bubbletea/charmbracelet spinners
_SPINNER_CHARS = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷")

# In-memory job registry (single-process; swap for Redis in production)
_jobs: dict[str, "AnalysisJob"] = {}


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _make_spinner_filter(on_line):
    """
    Wraps *on_line* to:
      1. Collapse bubbletea spinner frame spam (identical consecutive lines)
      2. Detect Claude spending-cap / auth errors and surface a clear message
    """
    _last: list = [None]
    _cap_seen: list = [False]

    def filtered(line: str) -> None:
        lower = line.lower()

        # ── Spending cap / auth error detection ──────────────────────────────
        if "spending cap" in lower or "spending cap reached" in lower:
            _cap_seen[0] = True
            on_line("✗ Claude usage limit reached — your spending cap has been hit. "
                    "Visit https://claude.ai to increase your limit or wait for it to reset.")
            return

        # Generic CLI exit-code-1 error — enrich if we already saw cap message
        if "cli process error (exit code 1)" in lower or "failed to read stderr" in lower:
            if _cap_seen[0]:
                on_line("✗ Analysis failed due to Claude spending cap (see above)")
            else:
                on_line("✗ Claude CLI error (exit code 1) — check that 'claude' is "
                        "authenticated and your usage limit has not been reached")
            return

        # ── Spinner frame deduplication ───────────────────────────────────────
        if line and line[0] in _SPINNER_CHARS:
            content = line[1:].strip()
            if content == _last[0]:
                return  # duplicate frame — suppress
            _last[0] = content
            on_line(content or line)
        else:
            _last[0] = None
            on_line(line)

    return filtered


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
        if options.get("docs_folder"):
            cmd += ["-docs-folder", options["docs_folder"]]
        return cmd

    if mode == "write_docs":
        topics = options.get("docs_topics") or options.get("target", "all")
        cmd = [binary, "-write-docs", topics]
        if options.get("docs_folder"):
            cmd += ["-docs-folder", options["docs_folder"]]
        return cmd

    raise AnalysisError(f"Unsupported mode: {mode}")


def _run_with_pty(cmd: list[str], cwd: str, env: dict, on_line) -> int:
    """
    Run *cmd* inside a pseudo-TTY so bubbletea renders correctly.
    Calls *on_line(str)* for every clean output line in real-time.
    Returns the exit code.
    """
    on_line = _make_spinner_filter(on_line)  # collapse spinner frame spam
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

        buf = b""

        while True:
            try:
                readable, _, _ = select.select([master_fd], [], [], 0.2)
                if readable:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        # EIO — PTY slave closed (process exited on macOS/Linux)
                        break
                    if not chunk:
                        # EOF on some systems
                        break
                    buf += chunk
                    text = buf.decode("utf-8", errors="replace")
                    clean = strip_ansi(text)
                    # Split on \r or \n to handle carriage-return progress bars
                    parts = re.split(r"\r|\n", clean)
                    for part in parts[:-1]:
                        stripped = part.strip()
                        if stripped:
                            on_line(stripped)
                    buf = parts[-1].encode("utf-8")
                else:
                    if proc.poll() is not None:
                        # Flush remaining buffer
                        remaining = strip_ansi(buf.decode("utf-8", errors="replace")).strip()
                        if remaining:
                            on_line(remaining)
                        break
            except OSError:
                break

        try:
            os.close(master_fd)
        except OSError:
            pass

        return proc.wait()

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
        for line in (result.stdout + result.stderr).splitlines():
            stripped = strip_ansi(line).strip()
            if stripped:
                on_line(stripped)
        return result.returncode


async def run_analysis(
    job: AnalysisJob,
    repo_path: str,
    target: str,
    api_key: str,
    options: dict,
) -> None:
    """
    Async wrapper — runs the Go binary in a thread pool, streams
    progress lines back through job.progress_queue in real time.
    """
    from app.services.parser import parse_report

    loop = asyncio.get_running_loop()

    # Set up report output path
    report_path = str(Path(settings.temp_dir) / job.job_id / "report.html")
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    job.report_path = report_path

    # Build env — pass repo URL to the Go binary.
    # DO NOT set ANTHROPIC_API_KEY here: the Go binary calls the claude CLI
    # which uses its own stored auth (~/.claude/).  Overriding with a raw
    # API key breaks the claude CLI and causes exit-code-1 failures.
    # NO_INTERACTIVE=1 tells the binary to skip post-run prompts (browser, download, push).
    env = {**os.environ, "REPO_URL": job.repo_url, "TERM": "xterm-256color", "NO_INTERACTIVE": "1"}
    # Expose token so the Go binary can use it for git operations if needed
    if options.get("github_token"):
        env["GITHUB_TOKEN"] = options["github_token"]

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
        """Thread-safe real-time progress push from worker thread."""
        loop.call_soon_threadsafe(
            job.progress_queue.put_nowait, {"type": "log", "text": line}
        )

    # Capture lines via closure so they're available after the executor finishes
    output_lines: list[str] = []

    def _run() -> int:
        def on_line(line: str) -> None:
            output_lines.append(line)
            _send(line)  # stream each line to the client as it arrives

        return _run_with_pty(cmd, repo_path, env, on_line)

    try:
        rc = await asyncio.wait_for(
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

    # Yield to the event loop so all call_soon_threadsafe-scheduled put_nowait
    # callbacks from _send() are processed BEFORE we enqueue the "done" event.
    await asyncio.sleep(0)

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
