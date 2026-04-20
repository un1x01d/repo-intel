from __future__ import annotations

from sqlalchemy.orm import Session

from repo_intel.schemas.scan import CreateScanRequest
from repo_intel.services.scan_service import ScanService, normalize_repo_key
from repo_intel.storage.models import Repository


def test_normalize_repo_key() -> None:
    assert normalize_repo_key("https://github.com/Org/Repo.git") == "github.com/org/repo"


def test_create_scan_reuses_repository(db_session: Session) -> None:
    existing_repo = Repository(
        source_type="github",
        repo_url="https://github.com/org/repo",
        normalized_repo_key="github.com/org/repo",
        is_private=False,
    )
    db_session.add(existing_repo)
    db_session.commit()

    service = ScanService(db_session)
    payload = CreateScanRequest(
        repo_url="https://github.com/org/repo",
        ref="main",
        provider="github",
        auth_mode="github_app",
    )
    created = service.create_scan(payload)

    assert created.repository_id == existing_repo.id
