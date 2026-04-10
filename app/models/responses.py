from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    pending = "pending"
    cloning = "cloning"
    running = "running"
    completed = "completed"
    failed = "failed"


# ── Security ──────────────────────────────────────────────────────────────────

class SecurityFinding(BaseModel):
    id: str
    rule_id: str
    category: str
    severity: str
    title: str
    file: str
    line: int
    snippet: str
    description: str
    explanation: str
    why_dangerous: str
    how_to_fix: str
    detected_by: str


class SecurityResult(BaseModel):
    files_scanned: int
    lines_scanned: int
    scan_duration_ms: int
    total: int
    critical: int
    high: int
    medium: int
    low: int
    findings: List[SecurityFinding]
    raw_html: str


# ── Impact ────────────────────────────────────────────────────────────────────

class ImpactResult(BaseModel):
    risk_level: str
    risk_score: int
    direct_callers: int
    total_callers: int
    max_graph_depth: int
    affected_packages: int
    critical_systems: List[str]
    has_tests: bool
    what_changing: str
    direct_impact: str
    indirect_impact: str
    critical_paths: str
    safety_net: str
    risk_assessment: str
    testing_strategy: str
    next_steps: str
    unknowns: str
    raw_html: str


# ── Why ───────────────────────────────────────────────────────────────────────

class WhyResult(BaseModel):
    classification: str
    confidence: str
    confidence_score: int
    still_needed: str
    risk_level: str
    what_it_does: str
    most_likely_reason: str
    evidence_summary: str
    still_needed_reason: str
    what_breaks: str
    next_steps: str
    unknowns: str
    total_commits: int
    history_days: int
    raw_html: str


# ── Debug / Explain (raw text) ────────────────────────────────────────────────

class RawTextResult(BaseModel):
    output: str


# ── Job ───────────────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    mode: str
    repo_url: str
    error: Optional[str] = None
    result: Optional[Any] = None  # SecurityResult | ImpactResult | WhyResult | …


class ProgressEvent(BaseModel):
    type: str  # "log" | "status" | "done"
    text: Optional[str] = None
    status: Optional[str] = None
