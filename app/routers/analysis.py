from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.exceptions import BinaryNotFoundError, JobNotFoundError
from app.models.requests import AnalysisRequest
from app.models.responses import JobResponse, JobStatus
from app.services.repo_service import cleanup_job, clone_repo
from app.services.runner import create_job, get_job, run_analysis

router = APIRouter(prefix="/api/v1", tags=["analysis"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=JobResponse, status_code=202)
async def start_analysis(body: AnalysisRequest, background_tasks: BackgroundTasks):
    # Validate binary exists
    if not Path(settings.docu_jarvis_binary).exists():
        raise BinaryNotFoundError(settings.docu_jarvis_binary)

    api_key = body.api_key or settings.anthropic_api_key
    if not api_key:
        raise HTTPException(
            status_code=422,
            detail="An Anthropic API key is required. "
            "Pass it in the request body or set ANTHROPIC_API_KEY on the server.",
        )

    job = create_job(body.mode.value, body.repo_url)
    job.status = JobStatus.cloning

    async def _run():
        try:
            await job.progress_queue.put({"type": "status", "text": "Cloning repository…"})
            # Clone in thread pool to not block the event loop
            loop = asyncio.get_running_loop()
            repo_path = await loop.run_in_executor(
                None, clone_repo, body.repo_url, job.job_id
            )
            await job.progress_queue.put(
                {"type": "status", "text": "Repository cloned. Starting analysis…"}
            )
            await run_analysis(
                job=job,
                repo_path=repo_path,
                target=body.options.target,
                api_key=api_key,
                options=body.options.model_dump(),
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
