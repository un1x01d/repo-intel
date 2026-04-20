from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session, joinedload

from repo_intel.ai.service import AIReasoningService
from repo_intel.core.config import get_settings
from repo_intel.core.enums import ScanStatus
from repo_intel.storage.models import ScanJob
from repo_intel.storage.repositories import ScanArtifactStore, ScanJobStore
from repo_intel.worker.context import ScanContext
from repo_intel.worker.phases.clone import ClonePhase
from repo_intel.worker.phases.extract_dependencies import ExtractDependenciesPhase
from repo_intel.worker.phases.extract_findings import ExtractFindingsPhase
from repo_intel.worker.phases.extract_git import ExtractGitPhase, build_hotspot_summary
from repo_intel.worker.phases.extract_integrations import ExtractIntegrationsPhase
from repo_intel.worker.phases.extract_routes import ExtractRoutesPhase
from repo_intel.worker.phases.extract_structure import ExtractStructurePhase
from repo_intel.worker.phases.fingerprint import FingerprintPhase
from repo_intel.worker.phases.inventory import InventoryPhase
from repo_intel.worker.workspace import RepoWorkspace

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunScanJob:
    """Scan job execution contract for workers."""

    scan_id: UUID
    session: Session
    checkout_root: Path | None = None

    def run(self) -> None:
        store = ScanJobStore(self.session)
        artifacts = ScanArtifactStore(self.session)
        scan = self._load_scan()
        if scan is None:
            raise ValueError(f"scan job not found: {self.scan_id}")

        settings = get_settings()
        root = self.checkout_root or Path(settings.worker_checkout_root)
        context = ScanContext(
            scan_id=scan.id,
            repository_url=scan.repository.repo_url,
            requested_ref=scan.requested_ref,
        )

        try:
            scan.started_at = scan.started_at or datetime.now(timezone.utc)
            self.session.commit()

            store.update_status(scan.id, ScanStatus.CLONING)
            self.session.commit()

            with RepoWorkspace(scan.id, root) as workspace:
                context.checkout_path = workspace.path
                ClonePhase().run(context)

                store.update_status(scan.id, ScanStatus.FINGERPRINTING, resolved_commit_sha=context.resolved_commit_sha)
                self.session.commit()
                fingerprint = FingerprintPhase().run(context)
                artifacts.upsert(scan_id=scan.id, artifact_type="fingerprint", payload=fingerprint)
                self.session.commit()

                store.update_status(scan.id, ScanStatus.INVENTORYING)
                self.session.commit()
                inventory_summary = InventoryPhase(self.session).run(context)
                artifacts.upsert(scan_id=scan.id, artifact_type="inventory_summary", payload=inventory_summary)
                self.session.commit()

                store.update_status(scan.id, ScanStatus.EXTRACTING_STRUCTURE)
                self.session.commit()
                structure_summary = ExtractStructurePhase(self.session).run(context)
                artifacts.upsert(scan_id=scan.id, artifact_type="structure_summary", payload=structure_summary)
                route_summary = ExtractRoutesPhase(self.session).run(scan.id)
                artifacts.upsert(scan_id=scan.id, artifact_type="route_summary", payload=route_summary)
                dependency_summary = ExtractDependenciesPhase(self.session).run(context)
                artifacts.upsert(scan_id=scan.id, artifact_type="dependency_summary", payload=dependency_summary)
                self.session.commit()

                store.update_status(scan.id, ScanStatus.EXTRACTING_INTEGRATIONS)
                self.session.commit()
                integration_summary = ExtractIntegrationsPhase(self.session).run(context)
                artifacts.upsert(scan_id=scan.id, artifact_type="integration_summary", payload=integration_summary)
                self.session.commit()

                store.update_status(scan.id, ScanStatus.EXTRACTING_GIT)
                self.session.commit()
                git_summary = ExtractGitPhase(self.session).run(context)
                artifacts.upsert(scan_id=scan.id, artifact_type="git_summary", payload=git_summary)
                artifacts.upsert(scan_id=scan.id, artifact_type="hotspot_summary", payload=build_hotspot_summary(git_summary))
                self.session.commit()

                store.update_status(scan.id, ScanStatus.NORMALIZING)
                self.session.commit()
                finding_summary = ExtractFindingsPhase(self.session).run(scan.id)
                artifacts.upsert(scan_id=scan.id, artifact_type="finding_summary", payload=finding_summary)
                self.session.commit()

                if settings.ai_enabled:
                    try:
                        AIReasoningService.from_settings(self.session, settings=settings).generate_scan_insights(scan.id)
                    except Exception as exc:
                        logger.exception("ai_summary_generation_failed", extra={"scan_id": str(scan.id)})
                        artifacts.upsert(scan_id=scan.id, artifact_type="ai_error", payload={"message": str(exc), "phase": "summary_generation"})
                        self.session.commit()

            scan = self._load_scan()
            if scan is None:
                raise ValueError(f"scan job disappeared during execution: {self.scan_id}")
            scan.status = ScanStatus.COMPLETED
            scan.completed_at = datetime.now(timezone.utc)
            scan.error_message = None
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            store.update_status(scan.id, ScanStatus.FAILED, error_message=str(exc))
            scan.completed_at = datetime.now(timezone.utc)
            self.session.commit()
            raise

    def _load_scan(self) -> ScanJob | None:
        return (
            self.session.query(ScanJob)
            .options(joinedload(ScanJob.repository))
            .filter(ScanJob.id == self.scan_id)
            .one_or_none()
        )
