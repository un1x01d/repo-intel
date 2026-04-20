from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from repo_intel.worker.jobs.run_scan import RunScanJob


class ScanOrchestrator:
    """Queue-facing orchestration entrypoint for scan execution."""

    def run_scan_now(self, scan_id: UUID, session: Session, checkout_root: Path | None = None) -> None:
        RunScanJob(scan_id=scan_id, session=session, checkout_root=checkout_root).run()

    def enqueue_scan(self, scan_id: UUID) -> None:
        # Queue integration intentionally deferred for MVP.
        _ = scan_id
