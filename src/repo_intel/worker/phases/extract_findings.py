from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from repo_intel.core.enums import Severity
from repo_intel.storage.models import (
    CommitFileChange,
    Dependency,
    Evidence,
    FileImport,
    Finding,
    FindingEvidenceLink,
    RepoFile,
    Route,
    ServiceIntegration,
)
from repo_intel.storage.repositories import FindingStore

_CRITICAL_TOKENS = ("auth", "config", "db", "database", "routes", "middleware", "payment", "session")


@dataclass(slots=True)
class ExtractFindingsPhase:
    session: Session

    def run(self, scan_id: UUID) -> dict[str, Any]:
        builder = _FindingBuilder(scan_id)
        self._architecture_findings(builder)
        self._change_risk_findings(builder)
        self._dependency_findings(builder)
        self._performance_findings(builder)
        FindingStore(self.session).replace_for_scan(scan_id, builder.findings, builder.evidence, builder.links)
        self.session.commit()
        counts = Counter(finding.category for finding in builder.findings)
        return {"counts": dict(sorted(counts.items()))}

    def _architecture_findings(self, builder: _FindingBuilder) -> None:
        routes_by_file = self._routes_by_file(builder.scan_id)
        for file, count in routes_by_file.items():
            if count >= 5:
                builder.add(
                    category="architecture",
                    subtype="route_concentration",
                    title="Route definitions are concentrated in one file",
                    description=f"The file {file.path} defines {count} routes. This is a concentration signal, not a proven design issue.",
                    severity=Severity.MEDIUM,
                    confidence=0.78,
                    source_scanner="architecture_heuristics",
                    evidence_type="route_definition",
                    file_id=file.id,
                    payload={"metric": "routes_in_file", "path": file.path, "value": count},
                )

        large_files = self.session.execute(
            select(RepoFile).where(RepoFile.scan_job_id == builder.scan_id, RepoFile.language.is_not(None), RepoFile.size_bytes >= 50_000)
        ).scalars()
        for file in large_files:
            builder.add(
                category="architecture",
                subtype="large_source_file",
                title="Large source file detected",
                description=f"The file {file.path} is {file.size_bytes} bytes. Large files can become difficult hotspots.",
                severity=Severity.MEDIUM,
                confidence=0.8,
                source_scanner="architecture_heuristics",
                evidence_type="file_metric",
                file_id=file.id,
                payload={"metric": "size_bytes", "path": file.path, "value": file.size_bytes},
            )

        import_counts = self._resolved_import_counts(builder.scan_id)
        for file, count in import_counts.items():
            if count >= 4:
                builder.add(
                    category="architecture",
                    subtype="central_shared_module",
                    title="Shared module imported by many files",
                    description=f"The file {file.path} is imported by {count} files. Changes here may have broad blast radius.",
                    severity=Severity.MEDIUM,
                    confidence=0.82,
                    source_scanner="architecture_heuristics",
                    evidence_type="import_metric",
                    file_id=file.id,
                    payload={"metric": "inbound_imports", "path": file.path, "value": count},
                )

    def _change_risk_findings(self, builder: _FindingBuilder) -> None:
        churn = self._file_churn(builder.scan_id)
        for file, changes in churn.items():
            critical = any(token in file.path.lower() for token in _CRITICAL_TOKENS)
            if changes >= 3 and critical:
                builder.add(
                    category="change-risk",
                    subtype="high_churn_critical_file",
                    title="Critical-area file changed frequently",
                    description=f"The file {file.path} changed {changes} times in the recent commit window.",
                    severity=Severity.HIGH,
                    confidence=0.86,
                    source_scanner="git_hotspot_extractor",
                    evidence_type="git_metric",
                    file_id=file.id,
                    payload={"metric": "commit_count_last_n", "path": file.path, "value": changes},
                )

    def _dependency_findings(self, builder: _FindingBuilder) -> None:
        deps = list(self.session.execute(select(Dependency).where(Dependency.scan_job_id == builder.scan_id)).scalars())
        prod = sum(1 for dep in deps if dep.dependency_type == "prod")
        dev = sum(1 for dep in deps if dep.dependency_type == "dev")
        if prod >= 25:
            builder.add(
                category="dependency",
                subtype="large_dependency_surface",
                title="Large production dependency surface",
                description=f"The scan found {prod} production npm dependencies. This is a deterministic dependency-surface signal.",
                severity=Severity.MEDIUM,
                confidence=0.74,
                source_scanner="dependency_heuristics",
                evidence_type="dependency_metric",
                payload={"metric": "prod_dependency_count", "value": prod},
            )
        if prod and dev / prod >= 2:
            builder.add(
                category="dependency",
                subtype="high_dev_to_prod_ratio",
                title="High dev-to-production dependency ratio",
                description=f"The scan found {dev} dev dependencies and {prod} production dependencies.",
                severity=Severity.LOW,
                confidence=0.68,
                source_scanner="dependency_heuristics",
                evidence_type="dependency_metric",
                payload={"metric": "dev_to_prod_dependency_ratio", "value": round(dev / prod, 2)},
            )

    def _performance_findings(self, builder: _FindingBuilder) -> None:
        integrations = list(self.session.execute(select(ServiceIntegration).where(ServiceIntegration.scan_job_id == builder.scan_id)).scalars())
        by_file_type: dict[UUID, Counter[str]] = defaultdict(Counter)
        files = {file.id: file for file in self.session.execute(select(RepoFile).where(RepoFile.scan_job_id == builder.scan_id)).scalars()}
        for integration in integrations:
            if integration.file_id:
                by_file_type[integration.file_id][integration.integration_type] += 1
        for file_id, counts in by_file_type.items():
            file = files.get(file_id)
            if file is None:
                continue
            if counts["http_api"] >= 3:
                builder.add(
                    category="performance-risk",
                    subtype="repeated_http_client_usage",
                    title="Repeated outbound HTTP usage in one file",
                    description=f"The file {file.path} contains {counts['http_api']} outbound HTTP integration signals.",
                    severity=Severity.MEDIUM,
                    confidence=0.78,
                    source_scanner="integration_heuristics",
                    evidence_type="http_integration",
                    file_id=file.id,
                    payload={"metric": "http_integration_count", "path": file.path, "value": counts["http_api"]},
                )
            if counts["http_api"] and counts["database"]:
                builder.add(
                    category="performance-risk",
                    subtype="db_and_http_colocated",
                    title="Database and outbound HTTP usage are co-located",
                    description=f"The file {file.path} contains both database and outbound HTTP integration signals.",
                    severity=Severity.MEDIUM,
                    confidence=0.76,
                    source_scanner="integration_heuristics",
                    evidence_type="database_usage",
                    file_id=file.id,
                    payload={"metric": "integration_mix", "path": file.path, "types": dict(counts)},
                )

    def _routes_by_file(self, scan_id: UUID) -> dict[RepoFile, int]:
        rows = self.session.execute(select(Route, RepoFile).join(RepoFile, Route.file_id == RepoFile.id).where(Route.scan_job_id == scan_id)).all()
        counts: Counter[RepoFile] = Counter()
        for _route, file in rows:
            counts[file] += 1
        return dict(counts)

    def _resolved_import_counts(self, scan_id: UUID) -> dict[RepoFile, int]:
        files = {file.id: file for file in self.session.execute(select(RepoFile).where(RepoFile.scan_job_id == scan_id)).scalars()}
        counts: Counter[UUID] = Counter(
            row[0]
            for row in self.session.execute(select(FileImport.resolved_file_id).where(FileImport.scan_job_id == scan_id, FileImport.resolved_file_id.is_not(None))).all()
        )
        return {files[file_id]: count for file_id, count in counts.items() if file_id in files}

    def _file_churn(self, scan_id: UUID) -> dict[RepoFile, int]:
        rows = self.session.execute(
            select(CommitFileChange, RepoFile).join(RepoFile, CommitFileChange.file_id == RepoFile.id).where(CommitFileChange.scan_job_id == scan_id)
        ).all()
        counts: Counter[RepoFile] = Counter()
        for _change, file in rows:
            counts[file] += 1
        return dict(counts)


class _FindingBuilder:
    def __init__(self, scan_id: UUID) -> None:
        self.scan_id = scan_id
        self.findings: list[Finding] = []
        self.evidence: list[Evidence] = []
        self.links: list[FindingEvidenceLink] = []

    def add(
        self,
        *,
        category: str,
        subtype: str,
        title: str,
        description: str,
        severity: Severity,
        confidence: float,
        source_scanner: str,
        evidence_type: str,
        payload: dict[str, Any],
        file_id: UUID | None = None,
    ) -> None:
        finding = Finding(
            id=uuid4(),
            scan_job_id=self.scan_id,
            category=category,
            subtype=subtype,
            title=title,
            description=description,
            severity=severity,
            confidence=confidence,
            source_scanner=source_scanner,
        )
        evidence = Evidence(id=uuid4(), scan_job_id=self.scan_id, evidence_type=evidence_type, file_id=file_id, payload=payload)
        self.findings.append(finding)
        self.evidence.append(evidence)
        self.links.append(FindingEvidenceLink(finding_id=finding.id, evidence_id=evidence.id))
