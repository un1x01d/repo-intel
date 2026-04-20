from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from repo_intel.core.enums import ScanStatus
from repo_intel.storage.models import Repository, ScanJob


def test_create_scan(client: TestClient) -> None:
    payload = {
        "repo_url": "https://github.com/org/repo",
        "ref": "main",
        "provider": "github",
        "auth_mode": "github_app",
        "options": {
            "enable_ai_summary": True,
            "enable_security": True,
            "enable_performance": True,
            "enable_git_analysis": True,
        },
    }

    response = client.post("/scans", json=payload)
    body = response.json()

    assert response.status_code == 201
    assert body["status"] == "queued"
    assert body["repo"]["url"] == "https://github.com/org/repo"
    assert body["repo"]["ref"] == "main"


def test_get_scan(client: TestClient) -> None:
    payload = {
        "repo_url": "https://github.com/org/repo",
        "ref": "main",
        "provider": "github",
        "auth_mode": "github_app",
        "options": {
            "enable_ai_summary": True,
            "enable_security": True,
            "enable_performance": True,
            "enable_git_analysis": True,
        },
    }
    create_response = client.post("/scans", json=payload)
    scan_id = create_response.json()["scan_id"]

    get_response = client.get(f"/scans/{scan_id}")
    body = get_response.json()

    assert get_response.status_code == 200
    assert body["scan_id"] == scan_id
    assert body["status"] == "queued"
    assert body["requested_ref"] == "main"
    assert body["resolved_commit_sha"] is None
    assert body["progress"]["current_phase"] == "queued"
    assert body["progress"]["completed_phases"] == []


def test_get_scan_not_found(client: TestClient) -> None:
    response = client.get("/scans/1d7c0318-71f1-42ca-a90c-5057e73f005d")
    assert response.status_code == 404


def test_run_scan_endpoint(client: TestClient, db_session: Session, tmp_path: Path) -> None:
    source_repo = _make_git_repo(tmp_path / "source")
    scan = _make_scan(db_session, str(source_repo))

    response = client.post(f"/scans/{scan.id}/run")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["resolved_commit_sha"] is not None
    assert body["artifact_types"] == [
        "dependency_summary",
        "finding_summary",
        "fingerprint",
        "git_summary",
        "hotspot_summary",
        "integration_summary",
        "inventory_summary",
        "route_summary",
        "structure_summary",
    ]


def test_get_scan_artifacts_endpoint(client: TestClient, db_session: Session, tmp_path: Path) -> None:
    source_repo = _make_git_repo(tmp_path / "source")
    scan = _make_scan(db_session, str(source_repo))
    client.post(f"/scans/{scan.id}/run")

    response = client.get(f"/scans/{scan.id}/artifacts")
    body = response.json()

    assert response.status_code == 200
    assert body["scan_id"] == str(scan.id)
    artifact_types = {artifact["artifact_type"] for artifact in body["artifacts"]}
    assert artifact_types == {
        "dependency_summary",
        "finding_summary",
        "fingerprint",
        "git_summary",
        "hotspot_summary",
        "integration_summary",
        "inventory_summary",
        "route_summary",
        "structure_summary",
    }


def test_get_scan_graph_endpoint(client: TestClient, db_session: Session, tmp_path: Path) -> None:
    source_repo = _make_git_repo(tmp_path / "source")
    scan = _make_scan(db_session, str(source_repo))
    client.post(f"/scans/{scan.id}/run")

    response = client.get(f"/scans/{scan.id}/graph")
    body = response.json()

    assert response.status_code == 200
    assert body["scan_id"] == str(scan.id)
    assert body["summary"]["files"] >= 2
    assert body["summary"]["symbols"] >= 1
    assert body["summary"]["routes"] == 1
    assert body["summary"]["imports"] >= 1
    assert body["summary"]["dependencies"] >= 1
    assert body["summary"]["integrations"] >= 1
    assert body["summary"]["commits"] >= 1
    assert body["summary"]["findings"] >= 0
    assert body["nodes"]
    assert body["edges"]
    assert {"type": "imports", "from": "file:src/server.ts", "to": "file:src/auth.ts"} in body["edges"]


def test_get_scan_findings_endpoint(client: TestClient, db_session: Session, tmp_path: Path) -> None:
    source_repo = _make_risky_git_repo(tmp_path / "risky-source")
    scan = _make_scan(db_session, str(source_repo))
    client.post(f"/scans/{scan.id}/run")

    response = client.get(f"/scans/{scan.id}/findings?category=change-risk")
    body = response.json()

    assert response.status_code == 200
    assert body["scan_id"] == str(scan.id)
    assert body["counts"]["change-risk"] >= 1
    assert body["items"][0]["evidence_ids"]


def test_run_scan_endpoint_returns_failed_scan_when_clone_fails(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    scan = _make_scan(db_session, str(tmp_path / "missing"))

    response = client.post(f"/scans/{scan.id}/run")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "failed"
    assert body["error_message"]
    assert body["completed_at"] is not None


def _make_scan(db_session: Session, repo_url: str) -> ScanJob:
    repository = Repository(
        source_type="git",
        repo_url=repo_url,
        normalized_repo_key=repo_url,
        is_private=False,
    )
    db_session.add(repository)
    db_session.flush()
    scan = ScanJob(repository_id=repository.id, requested_ref="main", status=ScanStatus.QUEUED)
    db_session.add(scan)
    db_session.commit()
    return scan


def _make_git_repo(path: Path) -> Path:
    path.mkdir()
    (path / "src").mkdir()
    (path / "src" / "auth.ts").write_text("export function login() {}\n", encoding="utf-8")
    (path / "src" / "server.ts").write_text(
        'import axios from "axios";\nimport { login } from "./auth";\napp.get("/health", login)\n',
        encoding="utf-8",
    )
    (path / "package.json").write_text('{"dependencies": {"express": "^4.0.0"}}', encoding="utf-8")
    _git(path, "init", "-b", "main")
    _git(path, "add", ".")
    _git(path, "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", "initial")
    return path


def _make_risky_git_repo(path: Path) -> Path:
    path.mkdir()
    (path / "src" / "middleware").mkdir(parents=True)
    (path / "src" / "middleware" / "auth.ts").write_text("export function auth() { return true; }\n", encoding="utf-8")
    (path / "package.json").write_text('{"dependencies":{"axios":"^1.0.0"}}', encoding="utf-8")
    _git(path, "init", "-b", "main")
    _git(path, "add", ".")
    _git(path, "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", "initial")
    for index in range(3):
        with (path / "src" / "middleware" / "auth.ts").open("a", encoding="utf-8") as handle:
            handle.write(f"// churn {index}\n")
        _git(path, "add", ".")
        _git(path, "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", f"auth {index}")
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
