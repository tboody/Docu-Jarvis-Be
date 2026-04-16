"""
Unit tests for app/services/runner.py

Covers: strip_ansi, _make_spinner_filter, AnalysisJob,
        create_job, get_job, _build_cmd.
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from app.services.runner import (
    strip_ansi,
    _make_spinner_filter,
    AnalysisJob,
    create_job,
    get_job,
    _build_cmd,
)
from app.models.responses import JobStatus
from app.core.exceptions import AnalysisError


# ── strip_ansi() ─────────────────────────────────────────────────────────────

class TestStripAnsi:
    def test_removes_colour_escape_sequence(self):
        assert strip_ansi("\x1b[32mhello\x1b[0m") == "hello"

    def test_removes_bold_escape_sequence(self):
        assert strip_ansi("\x1b[1mBOLD\x1b[0m") == "BOLD"

    def test_leaves_plain_text_unchanged(self):
        assert strip_ansi("plain text") == "plain text"

    def test_removes_multiple_sequences(self):
        result = strip_ansi("\x1b[31mred\x1b[0m and \x1b[34mblue\x1b[0m")
        assert result == "red and blue"

    def test_empty_string(self):
        assert strip_ansi("") == ""

    def test_sequence_only(self):
        assert strip_ansi("\x1b[2J") == ""


# ── _make_spinner_filter() ───────────────────────────────────────────────────

class TestSpinnerFilter:
    def _collect(self, inputs: list[str]) -> list[str]:
        """Run inputs through the filter and return collected output lines."""
        collected: list[str] = []
        f = _make_spinner_filter(collected.append)
        for line in inputs:
            f(line)
        return collected

    def test_passes_normal_lines_through(self):
        out = self._collect(["analysing files...", "done"])
        assert out == ["analysing files...", "done"]

    def test_deduplicates_consecutive_spinner_frames(self):
        # Braille spinner characters followed by same content should be collapsed
        out = self._collect([
            "⠋ scanning...",
            "⠙ scanning...",
            "⠹ scanning...",
        ])
        # Only the first unique content should appear
        assert len(out) == 1
        assert "scanning..." in out[0]

    def test_different_spinner_content_is_not_deduplicated(self):
        out = self._collect([
            "⠋ step one",
            "⠙ step two",
        ])
        assert len(out) == 2

    def test_spending_cap_message_is_surfaced(self):
        out = self._collect(["error: spending cap reached"])
        assert len(out) == 1
        assert "spending cap" in out[0].lower()
        assert "https://claude.ai" in out[0]

    def test_spending_cap_suppresses_original_line(self):
        out = self._collect(["Your spending cap has been reached"])
        # Original line should be replaced, not duplicated
        assert not any("Your spending cap" in line for line in out)

    def test_cli_exit_code_1_after_cap_gives_enriched_message(self):
        out = self._collect([
            "Your spending cap has been reached",
            "CLI process error (exit code 1)",
        ])
        combined = " ".join(out)
        assert "spending cap" in combined.lower()

    def test_cli_exit_code_1_without_cap_gives_generic_error(self):
        out = self._collect(["CLI process error (exit code 1)"])
        assert len(out) == 1
        assert "claude" in out[0].lower()

    def test_non_spinner_lines_reset_dedup_state(self):
        out = self._collect([
            "⠋ loading",
            "normal line",
            "⠙ loading",  # same text but after normal line — should appear
        ])
        assert any("loading" in line for line in out)
        assert "normal line" in out


# ── AnalysisJob ───────────────────────────────────────────────────────────────

class TestAnalysisJob:
    def test_initial_status_is_pending(self):
        job = AnalysisJob("job-1", "security", "https://github.com/o/r")
        assert job.status == JobStatus.pending

    def test_fields_are_stored(self):
        job = AnalysisJob("job-1", "security", "https://github.com/o/r")
        assert job.job_id == "job-1"
        assert job.mode == "security"
        assert job.repo_url == "https://github.com/o/r"

    def test_error_defaults_to_none(self):
        job = AnalysisJob("job-1", "security", "https://github.com/o/r")
        assert job.error is None

    def test_result_defaults_to_none(self):
        job = AnalysisJob("job-1", "security", "https://github.com/o/r")
        assert job.result is None

    def test_to_dict_contains_required_keys(self):
        job = AnalysisJob("job-1", "security", "https://github.com/o/r")
        d = job.to_dict()
        assert d["job_id"] == "job-1"
        assert d["mode"] == "security"
        assert d["repo_url"] == "https://github.com/o/r"
        assert d["status"] == JobStatus.pending
        assert d["error"] is None
        assert d["result"] is None

    def test_progress_queue_is_empty_initially(self):
        job = AnalysisJob("job-1", "security", "https://github.com/o/r")
        assert job.progress_queue.empty()


# ── create_job / get_job ──────────────────────────────────────────────────────

class TestCreateAndGetJob:
    def test_create_job_returns_analysis_job(self):
        job = create_job("impact", "https://github.com/o/r")
        assert isinstance(job, AnalysisJob)

    def test_create_job_generates_unique_ids(self):
        j1 = create_job("security", "https://github.com/o/r")
        j2 = create_job("security", "https://github.com/o/r")
        assert j1.job_id != j2.job_id

    def test_get_job_returns_created_job(self):
        job = create_job("why", "https://github.com/o/r")
        retrieved = get_job(job.job_id)
        assert retrieved is job

    def test_get_job_returns_none_for_unknown_id(self):
        assert get_job("does-not-exist-xyz") is None


# ── _build_cmd() ─────────────────────────────────────────────────────────────

class TestBuildCmd:
    BINARY = "/usr/local/bin/docu-jarvis"

    def _build(self, mode: str, target: str = ".", options: dict = None) -> list[str]:
        with patch.object(Path, "exists", return_value=True), \
             patch("app.services.runner.settings") as mock_settings:
            mock_settings.docu_jarvis_binary = self.BINARY
            return _build_cmd(mode, target, "/tmp/report.json", options or {})

    def test_security_mode_command(self):
        cmd = self._build("security", "src/auth")
        assert cmd == [self.BINARY, "-security", "src/auth", "-report", "/tmp/report.json"]

    def test_impact_mode_command(self):
        cmd = self._build("impact", "validateToken")
        assert cmd == [self.BINARY, "-impact", "validateToken", "-report", "/tmp/report.json"]

    def test_why_mode_command(self):
        cmd = self._build("why", "internal/auth/token.go")
        assert cmd == [self.BINARY, "-why", "internal/auth/token.go", "-report", "/tmp/report.json"]

    def test_debug_mode_uses_options(self):
        cmd = self._build("debug", options={
            "from_date": "2024-01-01",
            "to_date": "2024-12-31",
            "bug_description": "null pointer",
        })
        assert cmd == [self.BINARY, "-debug", "2024-01-01", "2024-12-31", "null pointer"]

    def test_debug_mode_defaults_when_options_missing(self):
        cmd = self._build("debug")
        assert self.BINARY in cmd
        assert "-debug" in cmd

    def test_explain_mode_command(self):
        cmd = self._build("explain", options={
            "commit_hash": "abc1234",
            "question": "Why was this added?",
        })
        assert cmd == [self.BINARY, "-explain", "abc1234", "Why was this added?"]

    def test_update_docs_mode_with_files(self):
        cmd = self._build("update_docs", options={"docs_files": "api.md,db.md"})
        assert cmd == [self.BINARY, "-update-docs", "api.md,db.md"]

    def test_update_docs_mode_with_custom_prompt(self):
        cmd = self._build("update_docs", options={
            "docs_files": "all",
            "custom_prompt": "focus on security",
        })
        assert "-custom" in cmd
        assert "focus on security" in cmd

    def test_update_docs_defaults_to_all(self):
        cmd = self._build("update_docs", options={})
        assert "all" in cmd

    def test_write_docs_mode_uses_topics(self):
        cmd = self._build("write_docs", options={"docs_topics": "auth,payments"})
        assert cmd == [self.BINARY, "-write-docs", "auth,payments"]

    def test_write_docs_falls_back_to_target(self):
        cmd = self._build("write_docs", target="auth", options={})
        assert self.BINARY in cmd
        assert "-write-docs" in cmd

    def test_unsupported_mode_raises_analysis_error(self):
        with patch.object(Path, "exists", return_value=True), \
             patch("app.services.runner.settings") as mock_settings:
            mock_settings.docu_jarvis_binary = self.BINARY
            with pytest.raises(AnalysisError, match="Unsupported mode"):
                _build_cmd("nonexistent", ".", "/tmp/report.json", {})

    def test_raises_when_binary_not_found(self):
        with patch.object(Path, "exists", return_value=False), \
             patch("app.services.runner.settings") as mock_settings:
            mock_settings.docu_jarvis_binary = "/missing/binary"
            with pytest.raises(AnalysisError, match="binary not found"):
                _build_cmd("security", ".", "/tmp/report.json", {})
