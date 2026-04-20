from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from repo_intel.parsers.typescript.integrations import parse_integrations
from repo_intel.storage.models import RepoFile, ServiceIntegration
from repo_intel.storage.repositories import RepoFileStore, StructureStore
from repo_intel.worker.context import ScanContext

_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


@dataclass(slots=True)
class ExtractIntegrationsPhase:
    session: Session

    def run(self, context: ScanContext) -> dict[str, Any]:
        if context.checkout_path is None:
            raise ValueError("checkout path is required before integration extraction")

        files = RepoFileStore(self.session).list_for_scan(context.scan_id)
        integrations: list[ServiceIntegration] = []
        for repo_file in files:
            if not _should_scan(repo_file):
                continue
            path = context.checkout_path / repo_file.path
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for parsed in parse_integrations(source):
                integrations.append(
                    ServiceIntegration(
                        scan_job_id=context.scan_id,
                        file_id=repo_file.id,
                        integration_type=parsed.integration_type,
                        provider=parsed.provider,
                        symbol_name=parsed.symbol_name,
                        evidence_text=parsed.evidence_text,
                        line_start=parsed.line_start,
                    )
                )

        StructureStore(self.session).replace_integrations(context.scan_id, integrations)
        self.session.commit()
        return integration_summary(integrations)


def integration_summary(integrations: list[ServiceIntegration]) -> dict[str, Any]:
    return {
        "integration_counts": dict(sorted(Counter(item.integration_type for item in integrations).items())),
        "providers": dict(sorted(Counter(item.provider for item in integrations).items())),
    }


def _should_scan(repo_file: RepoFile) -> bool:
    return (
        Path(repo_file.path).suffix.lower() in _SOURCE_SUFFIXES
        and repo_file.file_type != "binary"
        and not repo_file.is_generated
        and (repo_file.size_bytes is None or repo_file.size_bytes <= _MAX_SOURCE_BYTES)
    )
