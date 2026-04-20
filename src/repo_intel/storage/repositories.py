from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from repo_intel.core.enums import ScanStatus
from repo_intel.storage.models import (
    AIInsight,
    Commit,
    CommitFileChange,
    Dependency,
    Evidence,
    FileImport,
    Finding,
    FindingEvidenceLink,
    InsightEvidenceLink,
    RepoFile,
    Repository,
    Route,
    ScanArtifact,
    ScanJob,
    ServiceIntegration,
    Symbol,
)


class RepositoryStore:
    """Persistence operations for repositories."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_normalized_key(self, normalized_key: str) -> Repository | None:
        stmt = select(Repository).where(Repository.normalized_repo_key == normalized_key)
        return self.session.execute(stmt).scalar_one_or_none()

    def create(self, *, source_type: str, repo_url: str, normalized_repo_key: str, is_private: bool = False) -> Repository:
        repository = Repository(
            source_type=source_type,
            repo_url=repo_url,
            normalized_repo_key=normalized_repo_key,
            is_private=is_private,
        )
        self.session.add(repository)
        self.session.flush()
        return repository


class ScanJobStore:
    """Persistence operations for scan jobs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, repository_id: UUID, requested_ref: str, status: ScanStatus = ScanStatus.QUEUED) -> ScanJob:
        scan_job = ScanJob(repository_id=repository_id, requested_ref=requested_ref, status=status)
        self.session.add(scan_job)
        self.session.flush()
        return scan_job

    def get(self, scan_id: UUID) -> ScanJob | None:
        stmt = select(ScanJob).where(ScanJob.id == scan_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def update_status(
        self,
        scan_id: UUID,
        status: ScanStatus,
        *,
        error_message: str | None = None,
        resolved_commit_sha: str | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status, "error_message": error_message}
        if resolved_commit_sha is not None:
            values["resolved_commit_sha"] = resolved_commit_sha
        stmt = update(ScanJob).where(ScanJob.id == scan_id).values(**values)
        self.session.execute(stmt)


class RepoFileStore:
    """Persistence operations for repository file inventory."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_scan(self, scan_id: UUID, files: list[RepoFile]) -> None:
        self.session.execute(delete(RepoFile).where(RepoFile.scan_job_id == scan_id))
        self.session.add_all(files)

    def list_for_scan(self, scan_id: UUID) -> list[RepoFile]:
        stmt = select(RepoFile).where(RepoFile.scan_job_id == scan_id).order_by(RepoFile.path)
        return list(self.session.execute(stmt).scalars().all())

    def map_by_path(self, scan_id: UUID) -> dict[str, RepoFile]:
        return {file.path: file for file in self.list_for_scan(scan_id)}


class StructureStore:
    """Persistence operations for extracted code structure."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_symbols(self, scan_id: UUID, symbols: list[Symbol]) -> None:
        self.session.execute(delete(Symbol).where(Symbol.scan_job_id == scan_id))
        self.session.add_all(symbols)

    def replace_imports(self, scan_id: UUID, imports: list[FileImport]) -> None:
        self.session.execute(delete(FileImport).where(FileImport.scan_job_id == scan_id))
        self.session.add_all(imports)

    def replace_routes(self, scan_id: UUID, routes: list[Route]) -> None:
        self.session.execute(delete(Route).where(Route.scan_job_id == scan_id))
        self.session.add_all(routes)

    def replace_dependencies(self, scan_id: UUID, dependencies: list[Dependency]) -> None:
        self.session.execute(delete(Dependency).where(Dependency.scan_job_id == scan_id))
        self.session.add_all(dependencies)

    def replace_integrations(self, scan_id: UUID, integrations: list[ServiceIntegration]) -> None:
        self.session.execute(delete(ServiceIntegration).where(ServiceIntegration.scan_job_id == scan_id))
        self.session.add_all(integrations)

    def graph_counts(self, scan_id: UUID) -> dict[str, int]:
        return {
            "files": self._count(RepoFile, scan_id),
            "symbols": self._count(Symbol, scan_id),
            "routes": self._count(Route, scan_id),
            "imports": self._count(FileImport, scan_id),
            "dependencies": self._count(Dependency, scan_id),
            "integrations": self._count(ServiceIntegration, scan_id),
            "commits": self._count(Commit, scan_id),
            "findings": self._count(Finding, scan_id),
        }

    def sample_nodes(self, scan_id: UUID, limit: int = 10) -> list[dict[str, str]]:
        per_kind = max(limit // 6, 1)
        files = self.session.execute(select(RepoFile).where(RepoFile.scan_job_id == scan_id).order_by(RepoFile.path).limit(per_kind)).scalars()
        nodes = [{"id": f"file:{file.path}", "type": "file", "label": file.path} for file in files]
        symbols = self.session.execute(select(Symbol).where(Symbol.scan_job_id == scan_id).order_by(Symbol.symbol_name).limit(per_kind)).scalars()
        nodes.extend({"id": f"symbol:{symbol.id}", "type": "symbol", "label": symbol.symbol_name} for symbol in symbols)
        routes = self.session.execute(select(Route).where(Route.scan_job_id == scan_id).order_by(Route.path).limit(per_kind)).scalars()
        nodes.extend({"id": f"route:{route.id}", "type": "route", "label": f"{route.method} {route.path}"} for route in routes)
        integrations = self.session.execute(
            select(ServiceIntegration).where(ServiceIntegration.scan_job_id == scan_id).order_by(ServiceIntegration.provider).limit(per_kind)
        ).scalars()
        nodes.extend({"id": f"integration:{integration.id}", "type": "integration", "label": integration.provider} for integration in integrations)
        commits = self.session.execute(
            select(Commit).where(Commit.scan_job_id == scan_id).order_by(Commit.authored_at.desc().nullslast()).limit(per_kind)
        ).scalars()
        nodes.extend({"id": f"commit:{commit.commit_sha}", "type": "commit", "label": commit.commit_sha[:12]} for commit in commits)
        findings = self.session.execute(
            select(Finding).where(Finding.scan_job_id == scan_id).order_by(Finding.created_at).limit(per_kind)
        ).scalars()
        nodes.extend({"id": f"finding:{finding.id}", "type": "finding", "label": finding.title} for finding in findings)
        return nodes

    def sample_edges(self, scan_id: UUID, limit: int = 10) -> list[dict[str, str]]:
        edges: list[dict[str, str]] = []
        per_kind = max(limit // 6, 1)
        files_by_id = {file.id: file for file in RepoFileStore(self.session).list_for_scan(scan_id)}
        rows = self.session.execute(
            select(Symbol, RepoFile)
            .join(RepoFile, Symbol.file_id == RepoFile.id)
            .where(Symbol.scan_job_id == scan_id)
            .order_by(RepoFile.path, Symbol.symbol_name)
            .limit(per_kind)
        ).all()
        for symbol, file in rows:
            edges.append({"type": "defines", "from": f"file:{file.path}", "to": f"symbol:{symbol.id}"})

        imports = self.session.execute(
            select(FileImport, RepoFile)
            .join(RepoFile, FileImport.source_file_id == RepoFile.id)
            .where(FileImport.scan_job_id == scan_id)
            .order_by(RepoFile.path, FileImport.imported_path)
            .limit(per_kind)
        ).all()
        for file_import, source_file in imports:
            resolved_file = files_by_id.get(file_import.resolved_file_id) if file_import.resolved_file_id else None
            target = f"file:{resolved_file.path}" if resolved_file is not None else file_import.imported_path
            edges.append({"type": "imports", "from": f"file:{source_file.path}", "to": target})

        integrations = self.session.execute(
            select(ServiceIntegration, RepoFile)
            .join(RepoFile, ServiceIntegration.file_id == RepoFile.id)
            .where(ServiceIntegration.scan_job_id == scan_id)
            .order_by(RepoFile.path, ServiceIntegration.provider)
            .limit(per_kind)
        ).all()
        for integration, file in integrations:
            edges.append({"type": "uses_integration", "from": f"file:{file.path}", "to": f"integration:{integration.id}"})

        routes = self.session.execute(
            select(Route, RepoFile)
            .join(RepoFile, Route.file_id == RepoFile.id)
            .where(Route.scan_job_id == scan_id)
            .order_by(RepoFile.path, Route.path)
            .limit(per_kind)
        ).all()
        for route, file in routes:
            edges.append({"type": "route_handler", "from": f"file:{file.path}", "to": f"route:{route.id}"})

        changes = self.session.execute(
            select(CommitFileChange, Commit, RepoFile)
            .join(Commit, CommitFileChange.commit_id == Commit.id)
            .join(RepoFile, CommitFileChange.file_id == RepoFile.id)
            .where(CommitFileChange.scan_job_id == scan_id)
            .order_by(Commit.authored_at.desc().nullslast(), RepoFile.path)
            .limit(per_kind)
        ).all()
        for _change, commit, file in changes:
            edges.append({"type": "changed_in_commit", "from": f"commit:{commit.commit_sha}", "to": f"file:{file.path}"})

        finding_targets = self.session.execute(
            select(Finding, Evidence, RepoFile)
            .join(FindingEvidenceLink, FindingEvidenceLink.finding_id == Finding.id)
            .join(Evidence, FindingEvidenceLink.evidence_id == Evidence.id)
            .join(RepoFile, Evidence.file_id == RepoFile.id)
            .where(Finding.scan_job_id == scan_id)
            .order_by(Finding.created_at, RepoFile.path)
            .limit(per_kind)
        ).all()
        for finding, _evidence, file in finding_targets:
            edges.append({"type": "finding_targets", "from": f"finding:{finding.id}", "to": f"file:{file.path}"})
        return edges

    def _count(
        self,
        model: (
            type[RepoFile]
            | type[Symbol]
            | type[Route]
            | type[FileImport]
            | type[Dependency]
            | type[ServiceIntegration]
            | type[Commit]
            | type[Finding]
        ),
        scan_id: UUID,
    ) -> int:
        return self.session.execute(select(func.count()).select_from(model).where(model.scan_job_id == scan_id)).scalar_one()


class FindingStore:
    """Persistence operations for normalized findings and evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_scan(self, scan_id: UUID, findings: list[Finding], evidence: list[Evidence], links: list[FindingEvidenceLink]) -> None:
        self.session.execute(delete(FindingEvidenceLink).where(FindingEvidenceLink.finding_id.in_(select(Finding.id).where(Finding.scan_job_id == scan_id))))
        self.session.execute(delete(Evidence).where(Evidence.scan_job_id == scan_id))
        self.session.execute(delete(Finding).where(Finding.scan_job_id == scan_id))
        self.session.add_all(findings)
        self.session.add_all(evidence)
        self.session.flush()
        self.session.add_all(links)

    def list_for_scan(self, scan_id: UUID, *, category: str | None = None, severity: str | None = None) -> list[Finding]:
        stmt = select(Finding).where(Finding.scan_job_id == scan_id).order_by(Finding.severity.desc(), Finding.created_at)
        if category:
            stmt = stmt.where(Finding.category == category)
        if severity:
            stmt = stmt.where(Finding.severity == severity)
        return list(self.session.execute(stmt).scalars().all())

    def evidence_ids_by_finding(self, scan_id: UUID) -> dict[UUID, list[UUID]]:
        rows = self.session.execute(
            select(FindingEvidenceLink.finding_id, FindingEvidenceLink.evidence_id)
            .join(Finding, FindingEvidenceLink.finding_id == Finding.id)
            .where(Finding.scan_job_id == scan_id)
        ).all()
        grouped: dict[UUID, list[UUID]] = {}
        for finding_id, evidence_id in rows:
            grouped.setdefault(finding_id, []).append(evidence_id)
        return grouped


class AIInsightStore:
    """Persistence operations for grounded AI insights."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_scan_and_types(self, scan_id: UUID, insight_types: list[str], insights: list[AIInsight], links: list[InsightEvidenceLink]) -> None:
        old_ids = select(AIInsight.id).where(AIInsight.scan_job_id == scan_id, AIInsight.insight_type.in_(insight_types))
        self.session.execute(delete(InsightEvidenceLink).where(InsightEvidenceLink.insight_id.in_(old_ids)))
        self.session.execute(delete(AIInsight).where(AIInsight.scan_job_id == scan_id, AIInsight.insight_type.in_(insight_types)))
        self.session.add_all(insights)
        self.session.flush()
        self.session.add_all(links)

    def add(self, insight: AIInsight, links: list[InsightEvidenceLink]) -> AIInsight:
        self.session.add(insight)
        self.session.flush()
        self.session.add_all(links)
        return insight

    def list_for_scan(self, scan_id: UUID, insight_type: str | None = None) -> list[AIInsight]:
        stmt = select(AIInsight).where(AIInsight.scan_job_id == scan_id).order_by(AIInsight.created_at)
        if insight_type:
            stmt = stmt.where(AIInsight.insight_type == insight_type)
        return list(self.session.execute(stmt).scalars().all())


class ScanArtifactStore:
    """Persistence operations for structured scan artifacts."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, *, scan_id: UUID, artifact_type: str, payload: dict[str, object]) -> ScanArtifact:
        stmt = select(ScanArtifact).where(
            ScanArtifact.scan_job_id == scan_id,
            ScanArtifact.artifact_type == artifact_type,
        )
        artifact = self.session.execute(stmt).scalar_one_or_none()
        if artifact is None:
            artifact = ScanArtifact(scan_job_id=scan_id, artifact_type=artifact_type, payload=payload)
            self.session.add(artifact)
        else:
            artifact.payload = payload
        self.session.flush()
        return artifact

    def list_for_scan(self, scan_id: UUID) -> list[ScanArtifact]:
        stmt = select(ScanArtifact).where(ScanArtifact.scan_job_id == scan_id).order_by(ScanArtifact.artifact_type)
        return list(self.session.execute(stmt).scalars().all())

    def list_types(self, scan_id: UUID) -> list[str]:
        stmt = select(ScanArtifact.artifact_type).where(ScanArtifact.scan_job_id == scan_id).order_by(
            ScanArtifact.artifact_type
        )
        return list(self.session.execute(stmt).scalars().all())
