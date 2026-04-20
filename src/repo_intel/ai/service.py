from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from repo_intel.ai.prompts.ask import build_ask_prompt
from repo_intel.ai.prompts.hotspot import build_hotspot_prompt
from repo_intel.ai.prompts.summary import build_summary_prompt
from repo_intel.ai.schemas import AIContextPack, AIInsightDraft, AskModelOutput, GroundedInsight, HotspotModelOutput, SummaryModelOutput
from repo_intel.ai.validators import AIValidationError, validate_model_output
from repo_intel.ai.vertex_client import DisabledVertexClient, GoogleGenAIVertexClient, VertexClient, VertexUnavailableError
from repo_intel.core.config import Settings, get_settings
from repo_intel.storage.models import (
    AIInsight,
    Dependency,
    Evidence,
    Finding,
    FindingEvidenceLink,
    InsightEvidenceLink,
    RepoFile,
    Route,
    ScanArtifact,
    ServiceIntegration,
)
from repo_intel.storage.repositories import AIInsightStore, ScanArtifactStore, StructureStore


class AIReasoningService:
    """Build bounded context packs, call Vertex, validate, and persist grounded insights."""

    def __init__(self, session: Session, client: VertexClient, settings: Settings | None = None) -> None:
        self.session = session
        self.client = client
        self.settings = settings or get_settings()
        self.artifacts = ScanArtifactStore(session)
        self.insights = AIInsightStore(session)

    @classmethod
    def from_settings(cls, session: Session, settings: Settings | None = None) -> AIReasoningService:
        resolved = settings or get_settings()
        client: VertexClient = GoogleGenAIVertexClient(resolved) if resolved.ai_enabled else DisabledVertexClient()
        return cls(session=session, client=client, settings=resolved)

    def generate_scan_insights(self, scan_id: UUID) -> list[AIInsight]:
        if not self.settings.ai_enabled:
            return []
        summary_context = self.build_summary_context(scan_id)
        hotspot_context = self.build_hotspot_context(scan_id)
        self.artifacts.upsert(scan_id=scan_id, artifact_type="ai_summary_context", payload=summary_context.model_dump(mode="json"))
        self.artifacts.upsert(scan_id=scan_id, artifact_type="ai_hotspot_context", payload=hotspot_context.model_dump(mode="json"))
        allowed = _allowed_evidence_ids(summary_context, hotspot_context)

        summary_payload = self.client.generate_json(
            prompt=build_summary_prompt(summary_context),
            response_schema=SummaryModelOutput.model_json_schema(),
        )
        summary = validate_model_output(SummaryModelOutput, summary_payload, allowed).summary

        hotspot_payload = self.client.generate_json(
            prompt=build_hotspot_prompt(hotspot_context),
            response_schema=HotspotModelOutput.model_json_schema(),
        )
        hotspots = validate_model_output(HotspotModelOutput, hotspot_payload, allowed).hotspots

        models = [_to_draft("summary", summary), *[_to_draft("hotspot", item) for item in hotspots]]
        insight_rows = [_to_model(scan_id, item) for item in models]
        links = [_link for row, draft in zip(insight_rows, models) for _link in _links(row.id, draft.evidence_ids)]
        self.insights.replace_for_scan_and_types(scan_id, ["summary", "hotspot"], insight_rows, links)
        self.session.commit()
        return insight_rows

    def answer_question(self, scan_id: UUID, question: str, *, persist: bool = True) -> AIInsightDraft:
        if not self.settings.ai_enabled:
            raise VertexUnavailableError("AI reasoning is disabled")
        context = self.build_ask_context(scan_id, question)
        self.artifacts.upsert(scan_id=scan_id, artifact_type="ai_ask_context", payload=context.model_dump(mode="json"))
        allowed = _allowed_evidence_ids(context)
        payload = self.client.generate_json(prompt=build_ask_prompt(context), response_schema=AskModelOutput.model_json_schema())
        answer = validate_model_output(AskModelOutput, payload, allowed).answer
        draft = _to_draft("qa", answer, extra={"question": question})
        if persist:
            row = _to_model(scan_id, draft)
            self.insights.add(row, _links(row.id, draft.evidence_ids))
            self.session.commit()
        return draft

    def build_summary_context(self, scan_id: UUID) -> AIContextPack:
        return self._build_context(scan_id=scan_id, purpose="summary")

    def build_hotspot_context(self, scan_id: UUID) -> AIContextPack:
        return self._build_context(scan_id=scan_id, purpose="hotspot", finding_limit=12)

    def build_ask_context(self, scan_id: UUID, question: str) -> AIContextPack:
        return self._build_context(scan_id=scan_id, purpose="ask", question=question, finding_limit=10, keywords=_keywords(question))

    def _build_context(
        self,
        *,
        scan_id: UUID,
        purpose: str,
        question: str | None = None,
        finding_limit: int = 8,
        keywords: set[str] | None = None,
    ) -> AIContextPack:
        artifacts = {
            artifact.artifact_type: artifact.payload
            for artifact in self.session.execute(select(ScanArtifact).where(ScanArtifact.scan_job_id == scan_id)).scalars()
            if not artifact.artifact_type.startswith("ai_")
        }
        findings = _finding_dicts(self.session, scan_id, limit=finding_limit, keywords=keywords)
        evidence_ids = {UUID(evidence_id) for finding in findings for evidence_id in finding["evidence_ids"]}
        evidence = _evidence_dicts(self.session, evidence_ids)
        return AIContextPack(
            scan_id=scan_id,
            purpose=purpose,
            question=question,
            artifacts=artifacts,
            findings=findings,
            evidence=evidence,
            graph_summary=StructureStore(self.session).graph_counts(scan_id),
            routes=_route_dicts(self.session, scan_id, keywords=keywords),
            integrations=_integration_dicts(self.session, scan_id, keywords=keywords),
            dependencies=_dependency_dicts(self.session, scan_id, keywords=keywords),
        )


def _finding_dicts(session: Session, scan_id: UUID, *, limit: int, keywords: set[str] | None) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Finding)
        .where(Finding.scan_job_id == scan_id)
        .order_by(Finding.severity.desc(), Finding.created_at)
    ).scalars()
    evidence_by_finding = _evidence_ids_by_finding(session, scan_id)
    results = []
    for finding in rows:
        text = " ".join(filter(None, [finding.category, finding.subtype, finding.title, finding.description])).lower()
        if keywords and not any(keyword in text for keyword in keywords):
            continue
        results.append(
            {
                "id": str(finding.id),
                "category": finding.category,
                "subtype": finding.subtype,
                "title": finding.title,
                "description": finding.description,
                "severity": finding.severity.value,
                "confidence": finding.confidence,
                "evidence_ids": [str(item) for item in evidence_by_finding.get(finding.id, [])],
            }
        )
        if len(results) >= limit:
            break
    if not results and keywords:
        return _finding_dicts(session, scan_id, limit=limit, keywords=None)
    return results


def _evidence_ids_by_finding(session: Session, scan_id: UUID) -> dict[UUID, list[UUID]]:
    rows = session.execute(
        select(FindingEvidenceLink.finding_id, FindingEvidenceLink.evidence_id)
        .join(Finding, FindingEvidenceLink.finding_id == Finding.id)
        .where(Finding.scan_job_id == scan_id)
    ).all()
    grouped: dict[UUID, list[UUID]] = {}
    for finding_id, evidence_id in rows:
        grouped.setdefault(finding_id, []).append(evidence_id)
    return grouped


def _evidence_dicts(session: Session, evidence_ids: set[UUID]) -> list[dict[str, Any]]:
    if not evidence_ids:
        return []
    rows = session.execute(
        select(Evidence, RepoFile)
        .outerjoin(RepoFile, Evidence.file_id == RepoFile.id)
        .where(Evidence.id.in_(evidence_ids))
        .limit(20)
    ).all()
    return [
        {
            "id": str(evidence.id),
            "type": evidence.evidence_type,
            "file": file.path if file else None,
            "payload": evidence.payload,
        }
        for evidence, file in rows
    ]


def _route_dicts(session: Session, scan_id: UUID, keywords: set[str] | None) -> list[dict[str, Any]]:
    rows = session.execute(select(Route, RepoFile).join(RepoFile, Route.file_id == RepoFile.id).where(Route.scan_job_id == scan_id).limit(20)).all()
    items = [{"method": route.method, "path": route.path, "framework": route.framework, "file": file.path} for route, file in rows]
    return _filter(items, keywords)


def _integration_dicts(session: Session, scan_id: UUID, keywords: set[str] | None) -> list[dict[str, Any]]:
    rows = session.execute(
        select(ServiceIntegration, RepoFile).outerjoin(RepoFile, ServiceIntegration.file_id == RepoFile.id).where(ServiceIntegration.scan_job_id == scan_id).limit(20)
    ).all()
    items = [{"type": item.integration_type, "provider": item.provider, "file": file.path if file else None, "line": item.line_start} for item, file in rows]
    return _filter(items, keywords)


def _dependency_dicts(session: Session, scan_id: UUID, keywords: set[str] | None) -> list[dict[str, Any]]:
    rows = session.execute(select(Dependency).where(Dependency.scan_job_id == scan_id).limit(30)).scalars()
    items = [{"package": dep.package_name, "type": dep.dependency_type, "version": dep.version_spec} for dep in rows]
    return _filter(items, keywords)


def _filter(items: list[dict[str, Any]], keywords: set[str] | None) -> list[dict[str, Any]]:
    if not keywords:
        return items
    filtered = [item for item in items if any(keyword in " ".join(str(value).lower() for value in item.values()) for keyword in keywords)]
    return filtered or items[:5]


def _keywords(question: str) -> set[str]:
    return {part.lower() for part in question.replace("/", " ").replace("_", " ").replace("-", " ").split() if len(part) >= 3}


def _allowed_evidence_ids(*contexts: AIContextPack) -> set[UUID]:
    return {UUID(str(item["id"])) for context in contexts for item in context.evidence}


def _to_draft(insight_type: str, insight: GroundedInsight, extra: dict[str, Any] | None = None) -> AIInsightDraft:
    return AIInsightDraft(
        insight_type=insight_type,
        title=insight.title,
        body=insight.body,
        confidence=insight.confidence,
        impacted_entities=insight.impacted_entities,
        evidence_ids=insight.evidence_ids,
        payload={"impacted_entities": insight.impacted_entities, "evidence_ids": [str(item) for item in insight.evidence_ids], **(extra or {})},
    )


def _to_model(scan_id: UUID, draft: AIInsightDraft) -> AIInsight:
    return AIInsight(
        id=uuid4(),
        scan_job_id=scan_id,
        insight_type=draft.insight_type,
        title=draft.title,
        body=draft.body,
        confidence=draft.confidence,
        payload=draft.payload,
    )


def _links(insight_id: UUID, evidence_ids: list[UUID]) -> list[InsightEvidenceLink]:
    return [InsightEvidenceLink(insight_id=insight_id, evidence_id=evidence_id) for evidence_id in evidence_ids]
