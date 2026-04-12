from __future__ import annotations

import logging
import shutil
from pathlib import Path
from uuid import uuid4

import git

from app.core.config import settings
from app.core.exceptions import RepoCloneError

logger = logging.getLogger(__name__)


def clone_repo(repo_url: str, job_id: str, github_token: str | None = None) -> str:
    """
    Clone *repo_url* into a job-specific temp directory.
    If *github_token* is provided it is embedded in the clone URL so private
    repos owned by the user are accessible.
    Returns the absolute path to the cloned repo.
    """
    dest = Path(settings.temp_dir) / job_id / "repo"
    dest.mkdir(parents=True, exist_ok=True)

    # Inject token into HTTPS URL: https://TOKEN@github.com/...
    clone_url = repo_url
    if github_token:
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(repo_url)
        if parsed.scheme in ("http", "https"):
            authed = parsed._replace(netloc=f"{github_token}@{parsed.hostname}")
            clone_url = urlunparse(authed)

    try:
        logger.info("Cloning %s → %s", repo_url, dest)
        git.Repo.clone_from(
            clone_url,
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
