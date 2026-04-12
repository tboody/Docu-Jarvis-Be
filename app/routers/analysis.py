from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import git as _git
import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import settings
from app.core.exceptions import BinaryNotFoundError, JobNotFoundError
from app.models.requests import AnalysisRequest
from app.models.responses import JobResponse, JobStatus
from app.services.repo_service import cleanup_job, clone_repo
from app.services.runner import create_job, get_job, run_analysis

router = APIRouter(prefix="/api/v1", tags=["analysis"])
logger = logging.getLogger(__name__)


class PushReportBody(BaseModel):
    github_token: str
    markdown_content: str


@router.post("/analyze", response_model=JobResponse, status_code=202)
async def start_analysis(body: AnalysisRequest, background_tasks: BackgroundTasks):
    # Validate binary exists
    if not Path(settings.docu_jarvis_binary).exists():
        raise BinaryNotFoundError(settings.docu_jarvis_binary)

    job = create_job(body.mode.value, body.repo_url)
    job.status = JobStatus.cloning

    async def _run():
        try:
            await job.progress_queue.put({"type": "status", "text": "Cloning repository…"})
            # Clone in thread pool to not block the event loop
            loop = asyncio.get_running_loop()
            repo_path = await loop.run_in_executor(
                None, clone_repo, body.repo_url, job.job_id, body.github_token
            )
            await job.progress_queue.put(
                {"type": "status", "text": "Repository cloned. Starting analysis…"}
            )
            opts = body.options.model_dump()
            if body.github_token:
                opts["github_token"] = body.github_token
            await run_analysis(
                job=job,
                repo_path=repo_path,
                target=body.options.target,
                api_key="",
                options=opts,
            )
        except Exception as exc:
            logger.exception("Job %s failed", job.job_id)
            job.status = JobStatus.failed
            job.error = str(exc)
            await job.progress_queue.put({"type": "done", "status": "failed"})

    background_tasks.add_task(_run)
    return job.to_dict()


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    return job.to_dict()


@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(job_id: str):
    """Server-Sent Events stream for real-time analysis progress."""
    job = get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)

    async def _event_generator():
        while True:
            try:
                event = await asyncio.wait_for(job.progress_queue.get(), timeout=30)
            except asyncio.TimeoutError:
                # Keep-alive ping
                yield "event: ping\ndata: {}\n\n"
                continue

            data = json.dumps(event)
            yield f"data: {data}\n\n"

            if event.get("type") == "done":
                break

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """Clean up job temp files."""
    job = get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    cleanup_job(job_id)


_MODE_TO_FILE = {
    "security": "docs/security-report.md",
    "impact": "docs/impact-analysis.md",
    "why": "docs/why-analysis.md",
    "debug": "docs/debug-report.md",
    "explain": "docs/commit-explanation.md",
}


@router.post("/jobs/{job_id}/push-to-repo")
async def push_report_to_repo(job_id: str, body: PushReportBody):
    """Convert analysis report to markdown, push branch, and open a PR."""
    job = get_job(job_id)
    if job is None:
        raise JobNotFoundError(job_id)
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not completed yet")

    repo_path = Path(settings.temp_dir) / job_id / "repo"
    if not repo_path.exists():
        raise HTTPException(
            status_code=410,
            detail="Cloned repository is no longer available — please re-run the analysis first",
        )

    # Parse owner/repo from GitHub URL
    match = re.match(r"https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", job.repo_url)
    if not match:
        raise HTTPException(status_code=400, detail="Cannot parse GitHub repository URL")
    owner, repo_name = match.group(1), match.group(2)

    file_path = _MODE_TO_FILE.get(job.mode, f"docs/{job.mode}-report.md")

    gh_headers = {
        "Authorization": f"token {body.github_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Get default branch
    async with httpx.AsyncClient(timeout=20) as client:
        info_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo_name}",
            headers=gh_headers,
        )
    default_branch = (
        info_resp.json().get("default_branch", "main") if info_resp.is_success else "main"
    )

    branch_name = f"codeflowai-{job.mode}-{datetime.now().strftime('%Y%m%d-%H%M')}"

    # Git operations
    try:
        git_repo = _git.Repo(str(repo_path))
        git_repo.git.checkout(default_branch)
        git_repo.git.checkout("-b", branch_name)

        full_path = repo_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body.markdown_content, encoding="utf-8")

        git_repo.git.add(file_path)
        git_repo.git.config("user.email", "codeflowai@bot.local")
        git_repo.git.config("user.name", "CodeFlowAI")
        git_repo.git.commit("-m", f"docs: add {job.mode} analysis report by CodeFlowAI")

        auth_remote = f"https://{body.github_token}@github.com/{owner}/{repo_name}.git"
        git_repo.git.push(auth_remote, branch_name)
    except _git.GitCommandError as exc:
        raise HTTPException(status_code=500, detail=f"Git error: {exc.stderr.strip()[:300]}")

    # Create PR
    async with httpx.AsyncClient(timeout=30) as client:
        pr_resp = await client.post(
            f"https://api.github.com/repos/{owner}/{repo_name}/pulls",
            headers=gh_headers,
            json={
                "title": f"[CodeFlowAI] {job.mode.replace('_', ' ').title()} Report",
                "body": (
                    f"Automated analysis report generated by **CodeFlowAI**.\n\n"
                    f"**Mode:** `{job.mode}`  \n"
                    f"**Repository:** {job.repo_url}  \n"
                    f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
                    f"---\n*Report saved at `{file_path}`*"
                ),
                "head": branch_name,
                "base": default_branch,
            },
        )

    if pr_resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create PR: {pr_resp.json().get('message', 'Unknown error')[:200]}",
        )

    return {
        "pr_url": pr_resp.json()["html_url"],
        "file_path": file_path,
        "branch": branch_name,
    }
