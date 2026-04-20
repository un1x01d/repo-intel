from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from repo_intel.storage.models import Route


class ExtractRoutesPhase:
    """Build route summary artifacts from persisted route rows."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self, scan_id: UUID) -> dict[str, Any]:
        routes = list(self.session.execute(select(Route).where(Route.scan_job_id == scan_id)).scalars().all())
        methods = Counter(route.method for route in routes)
        frameworks = sorted({route.framework for route in routes})
        return {
            "frameworks": frameworks,
            "route_count": len(routes),
            "methods": dict(sorted(methods.items())),
        }
