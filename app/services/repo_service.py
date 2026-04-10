from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

import git

from app.core.config import settings
from app.core.exceptions import RepoCloneError

logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, job_id: str) -> str:
    """
    Clone *repo_url* into a job-specific temp directory.
    Returns the absolute path to the cloned repo.
    """
    dest = Path(settings.temp_dir) / job_id / "repo"
    dest.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("Cloning %s → %s", repo_url, dest)
        git.Repo.clone_from(
            repo_url,
            str(dest),
            depth=200,  # sufficient for history-based analyses
            single_branch=True,
        )
        return str(dest)
    except git.GitCommandError as exc:
        shutil.rmtree(str(dest.parent), ignore_errors=True)
        raise RepoCloneError(repo_url, str(exc)) from exc


def cleanup_job(job_id: str) -> None:
    """Remove all temp files for a job."""
    job_dir = Path(settings.temp_dir) / job_id
    if job_dir.exists():
        shutil.rmtree(str(job_dir), ignore_errors=True)
        logger.info("Cleaned up job directory: %s", job_dir)
