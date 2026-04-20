from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(slots=True)
class ScanContext:
    """Mutable state shared by worker phases for one scan."""

    scan_id: UUID
    repository_url: str
    requested_ref: str
    checkout_path: Path | None = None
    resolved_commit_sha: str | None = None
