"""
Unit tests for app/services/repo_service.py

Covers: clone_repo URL token injection and cleanup_job.
Network I/O and git.Repo.clone_from are always mocked.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services.repo_service import cleanup_job, clone_repo
from app.core.exceptions import RepoCloneError


# ── clone_repo — token injection ─────────────────────────────────────────────

class TestCloneRepoTokenInjection:
    """Verify the GitHub token is correctly embedded in the clone URL."""

    def _call_clone(self, repo_url: str, token: Optional[str] = None) -> Optional[str]:
        """Call clone_repo with a mocked git.Repo.clone_from and return the URL used."""
        captured: list[str] = []

        def fake_clone(url, dest, **kwargs):
            captured.append(url)
            return MagicMock()

        with patch("app.services.repo_service.git.Repo.clone_from", side_effect=fake_clone), \
             patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = "/tmp/test-docu-jarvis"
            clone_repo(repo_url, "job-test-001", token)

        return captured[0] if captured else None

    def test_no_token_uses_original_url(self):
        url = "https://github.com/owner/repo"
        used = self._call_clone(url)
        assert used == url

    def test_token_is_injected_into_https_url(self):
        url = "https://github.com/owner/repo"
        used = self._call_clone(url, token="ghp_abc123")
        assert "ghp_abc123@github.com" in used

    def test_injected_url_preserves_path(self):
        url = "https://github.com/owner/my-repo"
        used = self._call_clone(url, token="ghp_abc123")
        assert "owner/my-repo" in used

    def test_injected_url_keeps_https_scheme(self):
        url = "https://github.com/owner/repo"
        used = self._call_clone(url, token="token123")
        assert used.startswith("https://")

    def test_none_token_does_not_inject(self):
        url = "https://github.com/owner/repo"
        used = self._call_clone(url, token=None)
        assert "@" not in used

    def test_empty_string_token_does_not_inject(self):
        url = "https://github.com/owner/repo"
        # Empty string is falsy — same as no token
        used = self._call_clone(url, token="")
        assert "@" not in used

    def test_clone_is_shallow_depth_200(self):
        kwargs_captured: list[dict] = []

        def fake_clone(url, dest, **kwargs):
            kwargs_captured.append(kwargs)
            return MagicMock()

        with patch("app.services.repo_service.git.Repo.clone_from", side_effect=fake_clone), \
             patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = "/tmp/test-docu-jarvis"
            clone_repo("https://github.com/owner/repo", "job-002")

        assert kwargs_captured[0]["depth"] == 200

    def test_clone_returns_destination_path(self):
        with patch("app.services.repo_service.git.Repo.clone_from", return_value=MagicMock()), \
             patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = "/tmp/test-docu-jarvis"
            result = clone_repo("https://github.com/owner/repo", "job-abc")

        assert "job-abc" in result
        assert result.endswith("repo")

    def test_git_error_raises_repo_clone_error(self):
        import git as _git

        with patch(
            "app.services.repo_service.git.Repo.clone_from",
            side_effect=_git.GitCommandError("clone", 128),
        ), patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = "/tmp/test-docu-jarvis"

            with pytest.raises(RepoCloneError):
                clone_repo("https://github.com/owner/private-repo", "job-fail", "bad-token")


# ── cleanup_job ───────────────────────────────────────────────────────────────

class TestCleanupJob:
    def test_removes_job_directory(self, tmp_path):
        # Arrange: create a fake job directory
        job_dir = tmp_path / "job-xyz"
        (job_dir / "repo").mkdir(parents=True)
        (job_dir / "repo" / "main.go").write_text("package main")

        with patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = str(tmp_path)
            cleanup_job("job-xyz")

        assert not job_dir.exists()

    def test_does_not_raise_if_directory_missing(self, tmp_path):
        with patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = str(tmp_path)
            # Should not raise even though "nonexistent-job" dir does not exist
            cleanup_job("nonexistent-job")

    def test_only_removes_target_job_directory(self, tmp_path):
        # Arrange: two job directories exist
        (tmp_path / "job-a" / "repo").mkdir(parents=True)
        (tmp_path / "job-b" / "repo").mkdir(parents=True)

        with patch("app.services.repo_service.settings") as mock_settings:
            mock_settings.temp_dir = str(tmp_path)
            cleanup_job("job-a")

        assert not (tmp_path / "job-a").exists()
        assert (tmp_path / "job-b").exists()
