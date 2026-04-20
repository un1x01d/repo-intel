from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from repo_intel.parsers.typescript.dependencies import apply_package_lock, parse_package_json
from repo_intel.storage.models import Dependency
from repo_intel.storage.repositories import StructureStore
from repo_intel.worker.context import ScanContext


class ExtractDependenciesPhase:
    """Extract first-pass npm dependency metadata."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(self, context: ScanContext) -> dict[str, Any]:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before dependency extraction")
        package_json = context.checkout_path / "package.json"
        parsed = parse_package_json(package_json) if package_json.exists() else []
        parsed = apply_package_lock(parsed, context.checkout_path / "package-lock.json")
        dependencies = [
            Dependency(
                scan_job_id=context.scan_id,
                package_name=dependency.package_name,
                version_spec=dependency.version_spec,
                locked_version=dependency.locked_version,
                dependency_type=dependency.dependency_type,
                ecosystem=dependency.ecosystem,
            )
            for dependency in parsed
        ]
        StructureStore(self.session).replace_dependencies(context.scan_id, dependencies)
        self.session.commit()
        return _summary(dependencies)


def _summary(dependencies: list[Dependency]) -> dict[str, Any]:
    counts = Counter(dependency.dependency_type for dependency in dependencies)
    return {
        "ecosystem": "npm",
        "prod_dependencies": counts.get("prod", 0),
        "dev_dependencies": counts.get("dev", 0),
        "peer_dependencies": counts.get("peer", 0),
        "optional_dependencies": counts.get("optional", 0),
    }
