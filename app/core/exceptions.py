from fastapi import HTTPException


class BinaryNotFoundError(HTTPException):
    def __init__(self, path: str):
        super().__init__(
            status_code=503,
            detail=f"docu-jarvis binary not found at '{path}'. "
            "Set DOCU_JARVIS_BINARY in .env to the correct path.",
        )


class RepoCloneError(HTTPException):
    def __init__(self, url: str, reason: str):
        super().__init__(
            status_code=422,
            detail=f"Failed to clone repository '{url}': {reason}",
        )


class JobNotFoundError(HTTPException):
    def __init__(self, job_id: str):
        super().__init__(status_code=404, detail=f"Job '{job_id}' not found.")


class AnalysisError(Exception):
    pass
