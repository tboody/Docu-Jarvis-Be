from __future__ import annotations

import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Default API key (optional — users can override per-request)
    anthropic_api_key: str = ""

    # Path to the compiled docu-jarvis Go binary
    docu_jarvis_binary: str = str(
        Path(__file__).parent.parent.parent.parent
        / "FYP-AI"
        / "docu-jarvis"
    )

    # Directory for cloned repos and temp reports
    temp_dir: str = "/tmp/docu-jarvis"

    # CORS allowed origins
    cors_origins: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Job timeout in seconds
    job_timeout: int = 600


settings = Settings()

# Ensure temp directory exists
Path(settings.temp_dir).mkdir(parents=True, exist_ok=True)
