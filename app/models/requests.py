from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, field_validator


class AnalysisMode(str, Enum):
    security = "security"
    impact = "impact"
    why = "why"
    debug = "debug"
    explain = "explain"
    update_docs = "update_docs"
    write_docs = "write_docs"


class AnalysisOptions(BaseModel):
    # impact / why / security
    target: str = "."  # path inside repo, function name, etc.

    # debug mode
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    bug_description: Optional[str] = None

    # explain mode
    commit_hash: Optional[str] = None
    question: Optional[str] = None

    # update-docs mode — comma-separated file names or "all"
    docs_files: Optional[str] = None
    custom_prompt: Optional[str] = None

    # write-docs mode — comma-separated topics
    docs_topics: Optional[str] = None


class AnalysisRequest(BaseModel):
    repo_url: str
    mode: AnalysisMode
    options: AnalysisOptions = AnalysisOptions()
    # User can supply their own API key; falls back to server .env
    api_key: Optional[str] = None

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("https://github.com/", "https://gitlab.com/", "git@")):
            raise ValueError("Only GitHub / GitLab URLs are supported.")
        return v
