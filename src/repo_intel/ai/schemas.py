from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class GroundedInsight(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    impacted_entities: list[str] = Field(default_factory=list)
    evidence_ids: list[UUID] = Field(default_factory=list)

    @field_validator("evidence_ids")
    @classmethod
    def require_evidence(cls, value: list[UUID]) -> list[UUID]:
        if not value:
            raise ValueError("AI insights must cite at least one evidence_id")
        return value


class SummaryModelOutput(BaseModel):
    summary: GroundedInsight


class HotspotModelOutput(BaseModel):
    hotspots: list[GroundedInsight] = Field(default_factory=list, max_length=5)


class AskModelOutput(BaseModel):
    answer: GroundedInsight


class AIContextPack(BaseModel):
    scan_id: UUID
    purpose: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    graph_summary: dict[str, int] = Field(default_factory=dict)
    routes: list[dict[str, Any]] = Field(default_factory=list)
    integrations: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[dict[str, Any]] = Field(default_factory=list)
    question: str | None = None


class AIInsightDraft(BaseModel):
    insight_type: str
    title: str
    body: str
    confidence: float
    impacted_entities: list[str]
    evidence_ids: list[UUID]
    payload: dict[str, Any] = Field(default_factory=dict)
