from __future__ import annotations

from sqlalchemy.orm import Session

from repo_intel.core.enums import ScanStatus
from repo_intel.storage.models import Repository, ScanJob


def test_model_creation_sanity(db_session: Session) -> None:
    repo = Repository(
        source_type="github",
        repo_url="https://github.com/org/repo",
        normalized_repo_key="github.com/org/repo",
        is_private=False,
    )
    db_session.add(repo)
    db_session.flush()

    scan = ScanJob(repository_id=repo.id, requested_ref="main", status=ScanStatus.QUEUED)
    db_session.add(scan)
    db_session.commit()

    assert repo.id is not None
    assert scan.id is not None
    assert scan.status == ScanStatus.QUEUED
