"""
Unit tests for app/models/requests.py

Covers: AnalysisMode enum, AnalysisOptions defaults,
        AnalysisRequest construction, and URL validator.
"""
import pytest
from pydantic import ValidationError

from app.models.requests import AnalysisMode, AnalysisOptions, AnalysisRequest


# ── AnalysisMode enum ────────────────────────────────────────────────────────

class TestAnalysisMode:
    def test_all_seven_modes_exist(self):
        modes = {m.value for m in AnalysisMode}
        assert modes == {
            "security", "impact", "why",
            "debug", "explain", "update_docs", "write_docs",
        }

    def test_mode_is_string_subclass(self):
        assert isinstance(AnalysisMode.security, str)

    def test_mode_equality_with_plain_string(self):
        assert AnalysisMode.security == "security"
        assert AnalysisMode.update_docs == "update_docs"


# ── AnalysisOptions defaults ─────────────────────────────────────────────────

class TestAnalysisOptions:
    def test_default_target_is_dot(self):
        opts = AnalysisOptions()
        assert opts.target == "."

    def test_optional_fields_default_to_none(self):
        opts = AnalysisOptions()
        assert opts.from_date is None
        assert opts.to_date is None
        assert opts.bug_description is None
        assert opts.commit_hash is None
        assert opts.question is None
        assert opts.docs_files is None
        assert opts.custom_prompt is None
        assert opts.docs_topics is None

    def test_custom_target_is_stored(self):
        opts = AnalysisOptions(target="src/auth")
        assert opts.target == "src/auth"

    def test_all_optional_fields_can_be_set(self):
        opts = AnalysisOptions(
            target="main.go",
            from_date="2024-01-01",
            to_date="2024-12-31",
            bug_description="null pointer",
            commit_hash="abc123",
            question="why is this here?",
            docs_files="api.md,db.md",
            custom_prompt="summarise",
            docs_topics="auth,payments",
        )
        assert opts.from_date == "2024-01-01"
        assert opts.commit_hash == "abc123"
        assert opts.docs_topics == "auth,payments"


# ── AnalysisRequest URL validator ────────────────────────────────────────────

class TestAnalysisRequestUrlValidator:
    def _make(self, url: str, mode: str = "security") -> AnalysisRequest:
        return AnalysisRequest(repo_url=url, mode=mode)

    # ── Valid URLs ────────────────────────────────────────────────────────────

    def test_accepts_https_github_url(self):
        req = self._make("https://github.com/owner/repo")
        assert req.repo_url == "https://github.com/owner/repo"

    def test_accepts_https_github_url_with_git_suffix(self):
        req = self._make("https://github.com/owner/repo.git")
        assert "github.com" in req.repo_url

    def test_accepts_https_gitlab_url(self):
        req = self._make("https://gitlab.com/owner/repo")
        assert req.repo_url == "https://gitlab.com/owner/repo"

    def test_accepts_ssh_git_at_url(self):
        req = self._make("git@github.com:owner/repo.git")
        assert req.repo_url == "git@github.com:owner/repo.git"

    def test_strips_leading_and_trailing_whitespace(self):
        req = self._make("  https://github.com/owner/repo  ")
        assert req.repo_url == "https://github.com/owner/repo"

    # ── Invalid URLs ──────────────────────────────────────────────────────────

    def test_rejects_arbitrary_https_url(self):
        with pytest.raises(ValidationError) as exc_info:
            self._make("https://example.com/owner/repo")
        assert "GitHub / GitLab" in str(exc_info.value)

    def test_rejects_http_github_url(self):
        with pytest.raises(ValidationError):
            self._make("http://github.com/owner/repo")

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            self._make("")

    def test_rejects_plain_string(self):
        with pytest.raises(ValidationError):
            self._make("not-a-url")

    # ── Mode validation ───────────────────────────────────────────────────────

    def test_rejects_invalid_mode(self):
        with pytest.raises(ValidationError):
            self._make("https://github.com/owner/repo", mode="nonexistent")

    def test_accepts_all_valid_modes(self):
        for mode in ["security", "impact", "why", "debug", "explain", "update_docs", "write_docs"]:
            req = self._make("https://github.com/owner/repo", mode=mode)
            assert req.mode.value == mode

    # ── Optional fields default correctly ────────────────────────────────────

    def test_options_default_to_empty_options(self):
        req = self._make("https://github.com/owner/repo")
        assert req.options.target == "."

    def test_api_key_defaults_to_none(self):
        req = self._make("https://github.com/owner/repo")
        assert req.api_key is None

    def test_github_token_defaults_to_none(self):
        req = self._make("https://github.com/owner/repo")
        assert req.github_token is None

    def test_github_token_is_stored_when_provided(self):
        req = AnalysisRequest(
            repo_url="https://github.com/owner/repo",
            mode="security",
            github_token="ghp_abc123",
        )
        assert req.github_token == "ghp_abc123"
