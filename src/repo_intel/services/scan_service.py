from __future__ import annotations

import re
from collections import Counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from repo_intel.core.enums import ScanStatus
from repo_intel.schemas.scan import (
    AIInsightListResponse,
    AIInsightResponse,
    AskResponse,
    CreateScanRequest,
    FindingListResponse,
    FindingResponse,
    GraphResponse,
    ProgressResponse,
    ScanArtifactResponse,
    ScanArtifactsResponse,
    ScanSummaryResponse,
    ScanStatusResponse,
)
from repo_intel.ai.service import AIReasoningService
from repo_intel.ai.vertex_client import VertexUnavailableError
from repo_intel.storage.models import AIInsight, RepoFile, ScanJob
from repo_intel.storage.repositories import AIInsightStore, FindingStore, RepositoryStore, ScanArtifactStore, ScanJobStore, StructureStore
from repo_intel.worker.orchestrator import ScanOrchestrator

_PHASE_ORDER = [
    ScanStatus.QUEUED,
    ScanStatus.CLONING,
    ScanStatus.FINGERPRINTING,
    ScanStatus.INVENTORYING,
    ScanStatus.EXTRACTING_STRUCTURE,
    ScanStatus.EXTRACTING_INTEGRATIONS,
    ScanStatus.EXTRACTING_GIT,
    ScanStatus.NORMALIZING,
    ScanStatus.COMPLETED,
]


class ScanService:
    """Application service for creating and querying scan jobs."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository_store = RepositoryStore(session)
        self.scan_store = ScanJobStore(session)
        self.artifact_store = ScanArtifactStore(session)
        self.structure_store = StructureStore(session)
        self.finding_store = FindingStore(session)
        self.ai_store = AIInsightStore(session)

    def create_scan(self, payload: CreateScanRequest) -> ScanJob:
        repo_url = str(payload.repo_url)
        normalized = normalize_repo_key(repo_url)
        repository = self.repository_store.get_by_normalized_key(normalized)
        if repository is None:
            repository = self.repository_store.create(
                source_type=payload.provider,
                repo_url=repo_url,
                normalized_repo_key=normalized,
            )

        scan_job = self.scan_store.create(
            repository_id=repository.id,
            requested_ref=payload.ref,
            status=ScanStatus.QUEUED,
        )
        self.session.commit()
        self.session.refresh(scan_job)
        return scan_job

    def get_scan(self, scan_id: UUID) -> ScanJob | None:
        return (
            self.session.query(ScanJob)
            .options(joinedload(ScanJob.repository))
            .filter(ScanJob.id == scan_id)
            .one_or_none()
        )

    def to_scan_status_response(self, scan: ScanJob) -> ScanStatusResponse:
        progress = synthesize_progress(scan.status)
        return ScanStatusResponse(
            scan_id=scan.id,
            status=scan.status,
            requested_ref=scan.requested_ref,
            resolved_commit_sha=scan.resolved_commit_sha,
            progress=progress,
            started_at=scan.started_at,
            completed_at=scan.completed_at,
            error_message=scan.error_message,
            artifact_types=self.artifact_store.list_types(scan.id),
        )

    def run_scan(self, scan_id: UUID) -> ScanJob | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        try:
            ScanOrchestrator().run_scan_now(scan_id=scan_id, session=self.session)
        except Exception:
            self.session.rollback()
        return self.get_scan(scan_id)

    def get_artifacts(self, scan_id: UUID) -> ScanArtifactsResponse | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        artifacts = [
            ScanArtifactResponse(
                artifact_type=artifact.artifact_type,
                payload=artifact.payload,
                created_at=artifact.created_at,
            )
            for artifact in self.artifact_store.list_for_scan(scan_id)
        ]
        return ScanArtifactsResponse(scan_id=scan_id, artifacts=artifacts)

    def get_graph(self, scan_id: UUID) -> GraphResponse | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        return GraphResponse(
            scan_id=scan_id,
            summary=self.structure_store.graph_counts(scan_id),
            nodes=self.structure_store.sample_nodes(scan_id),
            edges=self.structure_store.sample_edges(scan_id),
        )

    def get_findings(self, scan_id: UUID, *, category: str | None = None, severity: str | None = None) -> FindingListResponse | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        findings = self.finding_store.list_for_scan(scan_id, category=category, severity=severity)
        evidence_ids = self.finding_store.evidence_ids_by_finding(scan_id)
        files = {file.id: file.path for file in self.session.execute(select(RepoFile).where(RepoFile.scan_job_id == scan_id)).scalars()}
        return FindingListResponse(
            scan_id=scan_id,
            counts=dict(sorted(Counter(finding.category for finding in findings).items())),
            items=[
                FindingResponse(
                    id=finding.id,
                    category=finding.category,
                    subtype=finding.subtype,
                    title=finding.title,
                    description=finding.description,
                    severity=finding.severity,
                    confidence=finding.confidence,
                    source_scanner=finding.source_scanner,
                    impacted_entities=[files[finding_file_id]]
                    if (finding_file_id := _finding_file_id(finding.id, evidence_ids, self.session)) in files
                    else [],
                    evidence_ids=evidence_ids.get(finding.id, []),
                )
                for finding in findings
            ],
        )

    def get_summary(self, scan_id: UUID) -> ScanSummaryResponse | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        insights = self.ai_store.list_for_scan(scan_id)
        summary = next((item for item in insights if item.insight_type == "summary"), None)
        hotspots = [item for item in insights if item.insight_type == "hotspot"]
        return ScanSummaryResponse(
            scan_id=scan_id,
            summary=_ai_response(summary) if summary else None,
            hotspots=[_ai_response(item) for item in hotspots],
        )

    def get_insights(self, scan_id: UUID) -> AIInsightListResponse | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        return AIInsightListResponse(scan_id=scan_id, insights=[_ai_response(item) for item in self.ai_store.list_for_scan(scan_id)])

    def ask(self, scan_id: UUID, question: str) -> AskResponse | None:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        draft = AIReasoningService.from_settings(self.session).answer_question(scan_id, question)
        return AskResponse(scan_id=scan_id, answer=AIInsightResponse(title=draft.title, body=draft.body, confidence=draft.confidence, impacted_entities=draft.impacted_entities, evidence_ids=draft.evidence_ids))


def normalize_repo_key(repo_url: str) -> str:
    normalized = repo_url.strip().lower()
    normalized = re.sub(r"^https?://", "", normalized)
    normalized = normalized.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def synthesize_progress(status: ScanStatus) -> ProgressResponse:
    if status == ScanStatus.FAILED:
        return ProgressResponse(current_phase=status, completed_phases=[])

    completed = [phase for phase in _PHASE_ORDER if _PHASE_ORDER.index(phase) < _PHASE_ORDER.index(status)]
    return ProgressResponse(current_phase=status, completed_phases=completed)


def _finding_file_id(finding_id: UUID, evidence_ids: dict[UUID, list[UUID]], session: Session) -> UUID | None:
    from repo_intel.storage.models import Evidence

    ids = evidence_ids.get(finding_id, [])
    if not ids:
        return None
    return session.execute(select(Evidence.file_id).where(Evidence.id == ids[0])).scalar_one_or_none()


def _ai_response(insight: AIInsight) -> AIInsightResponse:
    payload = insight.payload or {}
    return AIInsightResponse(
        id=insight.id,
        title=insight.title,
        body=insight.body,
        confidence=insight.confidence,
        impacted_entities=list(payload.get("impacted_entities", [])),
        evidence_ids=_insight_evidence_ids(insight),
    )


def _insight_evidence_ids(insight: AIInsight) -> list[UUID]:
    # Evidence IDs are stored redundantly in payload for API projection; the join table remains source-of-truth for relational queries.
    payload = insight.payload or {}
    return [UUID(str(item)) for item in payload.get("evidence_ids", [])]
