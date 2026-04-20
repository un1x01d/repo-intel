from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from repo_intel.core.enums import ScanStatus, Severity


class ScanOptions(BaseModel):
    enable_ai_summary: bool = True
    enable_security: bool = True
    enable_performance: bool = True
    enable_git_analysis: bool = True


class CreateScanRequest(BaseModel):
    repo_url: HttpUrl
    ref: str = Field(default="main", min_length=1, max_length=255)
    provider: str = Field(default="github", min_length=1, max_length=32)
    auth_mode: str = Field(default="github_app", min_length=1, max_length=32)
    options: ScanOptions = Field(default_factory=ScanOptions)


class RepoRefResponse(BaseModel):
    url: str
    ref: str


class CreateScanResponse(BaseModel):
    scan_id: UUID
    status: ScanStatus
    repo: RepoRefResponse


class ProgressResponse(BaseModel):
    current_phase: ScanStatus
    completed_phases: list[ScanStatus]


class ScanStatusResponse(BaseModel):
    scan_id: UUID
    status: ScanStatus
    requested_ref: str
    resolved_commit_sha: str | None
    progress: ProgressResponse
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    artifact_types: list[str] = Field(default_factory=list)


class ScanArtifactResponse(BaseModel):
    artifact_type: str
    payload: dict[str, Any]
    created_at: datetime


class ScanArtifactsResponse(BaseModel):
    scan_id: UUID
    artifacts: list[ScanArtifactResponse]


class FindingResponse(BaseModel):
    id: UUID
    category: str
    subtype: str | None = None
    title: str
    description: str | None = None
    severity: Severity
    confidence: float | None = None
    source_scanner: str | None = None
    impacted_entities: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)


class FindingListResponse(BaseModel):
    scan_id: UUID
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[FindingResponse] = Field(default_factory=list)


class GraphResponse(BaseModel):
    scan_id: UUID
    summary: dict[str, int]
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class SummaryResponse(BaseModel):
    scan_id: UUID
    summary: FindingResponse | None = None
    hotspots: list[FindingResponse] = Field(default_factory=list)


class AIInsightResponse(BaseModel):
    id: UUID | None = None
    title: str
    body: str
    confidence: float | None = None
    impacted_entities: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ScanSummaryResponse(BaseModel):
    scan_id: UUID
    summary: AIInsightResponse | None = None
    hotspots: list[AIInsightResponse] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class AskResponse(BaseModel):
    scan_id: UUID
    answer: AIInsightResponse


class AIInsightListResponse(BaseModel):
    scan_id: UUID
    insights: list[AIInsightResponse] = Field(default_factory=list)
