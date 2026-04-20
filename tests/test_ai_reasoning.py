from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from repo_intel.ai.schemas import AskModelOutput, SummaryModelOutput
from repo_intel.ai.service import AIReasoningService
from repo_intel.ai.validators import AIValidationError, validate_model_output
from repo_intel.core.config import Settings
from repo_intel.core.enums import ScanStatus, Severity
from repo_intel.storage.models import AIInsight, Evidence, Finding, FindingEvidenceLink, Repository, ScanArtifact, ScanJob


class FakeVertexClient:
    def __init__(self, evidence_id: str) -> None:
        self.evidence_id = evidence_id
        self.calls: list[str] = []

    def generate_json(self, *, prompt: str, response_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(prompt)
        schema_text = str(response_schema)
        if "answer" in schema_text:
            return {
                "answer": {
                    "title": "Redis affects cached paths",
                    "body": "The provided evidence indicates cache-related risk. No unsupported runtime behavior is inferred.",
                    "confidence": 0.8,
                    "impacted_entities": ["src/cache.ts"],
                    "evidence_ids": [self.evidence_id],
                }
            }
        if "hotspots" in schema_text:
            return {
                "hotspots": [
                    {
                        "title": "Cache file is a hotspot signal",
                        "body": "The deterministic finding marks the cache file as a bounded risk signal.",
                        "confidence": 0.77,
                        "impacted_entities": ["src/cache.ts"],
                        "evidence_ids": [self.evidence_id],
                    }
                ]
            }
        return {
            "summary": {
                "title": "TypeScript service with cache risk signal",
                "body": "The repository summary is based only on supplied deterministic artifacts and evidence.",
                "confidence": 0.82,
                "impacted_entities": ["src/cache.ts"],
                "evidence_ids": [self.evidence_id],
            }
        }


def test_ai_context_assembly_and_summary_persistence(db_session: Session) -> None:
    scan, evidence = _make_scan_with_evidence(db_session)
    service = AIReasoningService(
        db_session,
        FakeVertexClient(str(evidence.id)),
        Settings(ai_enabled=True, vertex_project_id="project"),
    )

    context = service.build_summary_context(scan.id)
    insights = service.generate_scan_insights(scan.id)

    assert context.evidence[0]["id"] == str(evidence.id)
    assert {insight.insight_type for insight in insights} == {"summary", "hotspot"}
    persisted = db_session.execute(select(AIInsight).where(AIInsight.scan_job_id == scan.id)).scalars().all()
    assert len(persisted) == 2
    artifact_types = {artifact.artifact_type for artifact in db_session.execute(select(ScanArtifact).where(ScanArtifact.scan_job_id == scan.id)).scalars()}
    assert {"ai_summary_context", "ai_hotspot_context"} <= artifact_types


def test_ask_persists_evidence_backed_answer(db_session: Session) -> None:
    scan, evidence = _make_scan_with_evidence(db_session)
    service = AIReasoningService(
        db_session,
        FakeVertexClient(str(evidence.id)),
        Settings(ai_enabled=True, vertex_project_id="project"),
    )

    answer = service.answer_question(scan.id, "How does redis affect this service?")

    assert answer.evidence_ids == [evidence.id]
    persisted = db_session.execute(select(AIInsight).where(AIInsight.scan_job_id == scan.id, AIInsight.insight_type == "qa")).scalar_one()
    assert persisted.payload["question"] == "How does redis affect this service?"


def test_invalid_model_output_is_rejected(db_session: Session) -> None:
    scan, evidence = _make_scan_with_evidence(db_session)
    _ = scan

    with pytest.raises(AIValidationError):
        validate_model_output(
            SummaryModelOutput,
            {"summary": {"title": "Bad", "body": "Missing evidence", "confidence": 0.5, "evidence_ids": []}},
            {evidence.id},
        )

    with pytest.raises(AIValidationError):
        validate_model_output(
            AskModelOutput,
            {"answer": {"title": "Bad", "body": "Wrong evidence", "confidence": 0.5, "evidence_ids": ["11111111-1111-1111-1111-111111111111"]}},
            {evidence.id},
        )


def test_ask_endpoint_returns_disabled_when_ai_disabled(client: TestClient, db_session: Session) -> None:
    scan, _evidence = _make_scan_with_evidence(db_session)

    response = client.post(f"/scans/{scan.id}/ask", json={"question": "What are the risks?"})

    assert response.status_code == 503


def test_summary_and_ask_endpoints_with_mocked_vertex(client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    scan, evidence = _make_scan_with_evidence(db_session)
    fake = FakeVertexClient(str(evidence.id))

    def fake_from_settings(session: Session, settings: Settings | None = None) -> AIReasoningService:
        return AIReasoningService(session, fake, Settings(ai_enabled=True, vertex_project_id="project"))

    monkeypatch.setattr("repo_intel.services.scan_service.AIReasoningService.from_settings", fake_from_settings)
    AIReasoningService(db_session, fake, Settings(ai_enabled=True, vertex_project_id="project")).generate_scan_insights(scan.id)

    summary_response = client.get(f"/scans/{scan.id}/summary")
    ask_response = client.post(f"/scans/{scan.id}/ask", json={"question": "What does Redis affect?"})

    assert summary_response.status_code == 200
    assert summary_response.json()["summary"]["evidence_ids"] == [str(evidence.id)]
    assert ask_response.status_code == 200
    assert ask_response.json()["answer"]["evidence_ids"] == [str(evidence.id)]


def _make_scan_with_evidence(db_session: Session) -> tuple[ScanJob, Evidence]:
    repository = Repository(source_type="github", repo_url="https://github.com/org/repo", normalized_repo_key="github.com/org/repo")
    db_session.add(repository)
    db_session.flush()
    scan = ScanJob(repository_id=repository.id, requested_ref="main", status=ScanStatus.COMPLETED)
    db_session.add(scan)
    db_session.flush()
    db_session.add_all(
        [
            ScanArtifact(scan_job_id=scan.id, artifact_type="fingerprint", payload={"languages": ["typescript"]}),
            ScanArtifact(scan_job_id=scan.id, artifact_type="integration_summary", payload={"providers": {"redis": 1}}),
        ]
    )
    finding = Finding(
        scan_job_id=scan.id,
        category="performance-risk",
        subtype="cache_hotspot",
        title="Cache file has a deterministic risk signal",
        description="Redis/cache usage appears in a concentrated file.",
        severity=Severity.MEDIUM,
        confidence=0.8,
        source_scanner="test",
    )
    evidence = Evidence(scan_job_id=scan.id, evidence_type="database_usage", payload={"path": "src/cache.ts", "provider": "redis"})
    db_session.add_all([finding, evidence])
    db_session.flush()
    db_session.add(FindingEvidenceLink(finding_id=finding.id, evidence_id=evidence.id))
    db_session.commit()
    return scan, evidence
