"""
Unit tests for app/core/exceptions.py

Covers: BinaryNotFoundError, RepoCloneError,
        JobNotFoundError, AnalysisError.
"""
import pytest
from fastapi import HTTPException

from app.core.exceptions import (
    AnalysisError,
    BinaryNotFoundError,
    JobNotFoundError,
    RepoCloneError,
)


# ── BinaryNotFoundError ───────────────────────────────────────────────────────

class TestBinaryNotFoundError:
    def test_is_http_exception(self):
        err = BinaryNotFoundError("/usr/local/bin/docu-jarvis")
        assert isinstance(err, HTTPException)

    def test_status_code_is_503(self):
        err = BinaryNotFoundError("/usr/local/bin/docu-jarvis")
        assert err.status_code == 503

    def test_detail_contains_binary_path(self):
        err = BinaryNotFoundError("/custom/path/to/binary")
        assert "/custom/path/to/binary" in err.detail

    def test_detail_contains_env_hint(self):
        err = BinaryNotFoundError("/bin/docu-jarvis")
        assert "DOCU_JARVIS_BINARY" in err.detail

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException) as exc_info:
            raise BinaryNotFoundError("/missing")
        assert exc_info.value.status_code == 503


# ── RepoCloneError ────────────────────────────────────────────────────────────

class TestRepoCloneError:
    def test_is_http_exception(self):
        err = RepoCloneError("https://github.com/o/r", "authentication failed")
        assert isinstance(err, HTTPException)

    def test_status_code_is_422(self):
        err = RepoCloneError("https://github.com/o/r", "authentication failed")
        assert err.status_code == 422

    def test_detail_contains_repo_url(self):
        err = RepoCloneError("https://github.com/owner/repo", "not found")
        assert "https://github.com/owner/repo" in err.detail

    def test_detail_contains_reason(self):
        err = RepoCloneError("https://github.com/o/r", "repository does not exist")
        assert "repository does not exist" in err.detail

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException) as exc_info:
            raise RepoCloneError("https://github.com/o/r", "timeout")
        assert exc_info.value.status_code == 422


# ── JobNotFoundError ──────────────────────────────────────────────────────────

class TestJobNotFoundError:
    def test_is_http_exception(self):
        err = JobNotFoundError("abc-123")
        assert isinstance(err, HTTPException)

    def test_status_code_is_404(self):
        err = JobNotFoundError("abc-123")
        assert err.status_code == 404

    def test_detail_contains_job_id(self):
        err = JobNotFoundError("my-job-id-999")
        assert "my-job-id-999" in err.detail

    def test_can_be_raised_and_caught_as_http_exception(self):
        with pytest.raises(HTTPException) as exc_info:
            raise JobNotFoundError("xyz")
        assert exc_info.value.status_code == 404


# ── AnalysisError ─────────────────────────────────────────────────────────────

class TestAnalysisError:
    def test_is_plain_exception(self):
        err = AnalysisError("something failed")
        assert isinstance(err, Exception)

    def test_is_not_http_exception(self):
        err = AnalysisError("something failed")
        assert not isinstance(err, HTTPException)

    def test_message_is_preserved(self):
        err = AnalysisError("unsupported mode: xyz")
        assert str(err) == "unsupported mode: xyz"

    def test_can_be_raised_and_caught(self):
        with pytest.raises(AnalysisError, match="unsupported mode"):
            raise AnalysisError("unsupported mode: xyz")
