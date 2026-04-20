from __future__ import annotations

import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from repo_intel.core.enums import ScanStatus
from repo_intel.core.config import Settings
from repo_intel.storage.models import Commit, Finding, RepoFile, Repository, ScanArtifact, ScanJob, ServiceIntegration, Symbol
from repo_intel.worker.jobs.run_scan import RunScanJob
from repo_intel.worker.phases.fingerprint import build_fingerprint
from repo_intel.worker.phases.inventory import FileClassifier, InventoryPhase, is_binary, is_generated_path, read_sample


def test_run_scan_clones_fingerprints_and_inventories(db_session: Session, tmp_path: Path) -> None:
    source_repo = _make_git_repo(tmp_path / "source")
    repository = Repository(
        source_type="git",
        repo_url=str(source_repo),
        normalized_repo_key=str(source_repo),
        is_private=False,
    )
    db_session.add(repository)
    db_session.flush()
    scan = ScanJob(repository_id=repository.id, requested_ref="main", status=ScanStatus.QUEUED)
    db_session.add(scan)
    db_session.commit()

    RunScanJob(scan_id=scan.id, session=db_session, checkout_root=tmp_path / "checkouts").run()

    db_session.refresh(scan)
    files = db_session.execute(select(RepoFile).where(RepoFile.scan_job_id == scan.id)).scalars().all()

    assert scan.status == ScanStatus.COMPLETED
    assert scan.resolved_commit_sha is not None
    assert scan.started_at is not None
    assert scan.completed_at is not None
    assert scan.error_message is None
    assert {file.path for file in files} == {"README.md", "src/app.py"}
    app_file = next(file for file in files if file.path == "src/app.py")
    assert app_file.language == "python"
    assert app_file.file_type == "text"
    assert app_file.is_entrypoint is True
    assert len(app_file.sha256 or "") == 64
    artifacts = db_session.execute(select(ScanArtifact).where(ScanArtifact.scan_job_id == scan.id)).scalars().all()
    assert {artifact.artifact_type for artifact in artifacts} == {
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


def test_worker_marks_scan_failed_when_clone_fails(db_session: Session, tmp_path: Path) -> None:
    repository = Repository(
        source_type="git",
        repo_url=str(tmp_path / "missing"),
        normalized_repo_key="missing",
        is_private=False,
    )
    db_session.add(repository)
    db_session.flush()
    scan = ScanJob(repository_id=repository.id, requested_ref="main", status=ScanStatus.QUEUED)
    db_session.add(scan)
    db_session.commit()

    try:
        RunScanJob(scan_id=scan.id, session=db_session, checkout_root=tmp_path / "checkouts").run()
    except Exception:
        pass

    db_session.refresh(scan)
    assert scan.status == ScanStatus.FAILED
    assert scan.error_message
    assert scan.completed_at is not None


def test_fingerprint_detects_languages_tools_and_frameworks(tmp_path: Path) -> None:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text('{"dependencies": {"express": "^4.0.0"}}', encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
    (tmp_path / "src" / "server.ts").write_text("console.log('ok')\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text("terraform {}\n", encoding="utf-8")

    fingerprint = build_fingerprint(tmp_path)

    assert fingerprint["languages"] == ["hcl", "typescript"]
    assert fingerprint["package_managers"] == ["npm"]
    assert fingerprint["framework_hints"] == ["express"]
    assert fingerprint["has_docker"] is True
    assert fingerprint["has_github_actions"] is True
    assert fingerprint["has_terraform"] is True
    assert fingerprint["entrypoint_candidates"] == ["src/server.ts"]


def test_inventory_classifier_detects_binary_generated_config_and_entrypoint(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    binary_path = tmp_path / "image.bin"
    generated_path = tmp_path / "dist" / "app.min.js"
    config_path = tmp_path / "pyproject.toml"
    entrypoint_path = tmp_path / "src" / "server.ts"
    generated_path.parent.mkdir()
    binary_path.write_bytes(b"\x00\x01")
    generated_path.write_text("minified", encoding="utf-8")
    config_path.write_text("[project]\n", encoding="utf-8")
    entrypoint_path.write_text("console.log('ok')\n", encoding="utf-8")

    classifier = FileClassifier()

    assert is_binary(binary_path.read_bytes()) is True
    assert is_generated_path("dist/app.min.js") is True
    assert classifier.classify(tmp_path, config_path)["is_config"] is True
    assert classifier.classify(tmp_path, entrypoint_path)["is_entrypoint"] is True


def test_inventory_reads_bounded_binary_sample(tmp_path: Path) -> None:
    large_path = tmp_path / "large.bin"
    large_path.write_bytes(b"a" * 9000)

    assert len(read_sample(large_path)) == 8192


def test_inventory_phase_persists_files_and_summary(db_session: Session, tmp_path: Path) -> None:
    repository, scan = _make_scan(db_session, repo_url=str(tmp_path))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "server.ts").write_text("console.log('ok')\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text("terraform {}\n", encoding="utf-8")
    _ = repository

    from repo_intel.worker.context import ScanContext

    summary = InventoryPhase(db_session).run(
        ScanContext(scan_id=scan.id, repository_url=str(tmp_path), requested_ref="main", checkout_path=tmp_path)
    )

    assert summary["total_files"] == 2
    assert summary["languages"] == {"hcl": 1, "typescript": 1}


def test_structure_extraction_skips_generated_source_files(db_session: Session, tmp_path: Path) -> None:
    repository, scan = _make_scan(db_session, repo_url=str(tmp_path))
    (tmp_path / "dist").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "dist" / "bundle.min.js").write_text("function generated() {}\n", encoding="utf-8")
    (tmp_path / "src" / "server.ts").write_text("export function serve() {}\n", encoding="utf-8")
    _ = repository

    from repo_intel.worker.context import ScanContext
    from repo_intel.worker.phases.extract_structure import ExtractStructurePhase

    context = ScanContext(scan_id=scan.id, repository_url=str(tmp_path), requested_ref="main", checkout_path=tmp_path)
    InventoryPhase(db_session).run(context)
    summary = ExtractStructurePhase(db_session).run(context)

    symbols = db_session.execute(select(Symbol).where(Symbol.scan_job_id == scan.id)).scalars().all()
    assert summary["source_files_processed"] == 1
    assert [symbol.symbol_name for symbol in symbols] == ["serve"]


def test_worker_extracts_integrations_git_and_findings(db_session: Session, tmp_path: Path) -> None:
    source_repo = _make_intel_git_repo(tmp_path / "intel-source")
    repository, scan = _make_scan(db_session, repo_url=str(source_repo))
    _ = repository

    RunScanJob(scan_id=scan.id, session=db_session, checkout_root=tmp_path / "checkouts").run()

    integrations = db_session.execute(select(ServiceIntegration).where(ServiceIntegration.scan_job_id == scan.id)).scalars().all()
    commits = db_session.execute(select(Commit).where(Commit.scan_job_id == scan.id)).scalars().all()
    findings = db_session.execute(select(Finding).where(Finding.scan_job_id == scan.id)).scalars().all()
    artifacts = {
        artifact.artifact_type: artifact.payload
        for artifact in db_session.execute(select(ScanArtifact).where(ScanArtifact.scan_job_id == scan.id)).scalars().all()
    }

    assert scan.status == ScanStatus.COMPLETED
    assert {integration.provider for integration in integrations} >= {"axios", "postgresql", "redis"}
    assert len(commits) >= 3
    assert any(finding.category == "change-risk" for finding in findings)
    assert "integration_summary" in artifacts
    assert "git_summary" in artifacts
    assert "hotspot_summary" in artifacts
    assert "finding_summary" in artifacts


def test_worker_completes_when_ai_generation_fails(db_session: Session, tmp_path: Path, monkeypatch) -> None:
    source_repo = _make_intel_git_repo(tmp_path / "ai-fail-source")
    _repository, scan = _make_scan(db_session, repo_url=str(source_repo))

    class FailingAIService:
        @classmethod
        def from_settings(cls, session, settings=None):
            _ = session, settings
            return cls()

        def generate_scan_insights(self, scan_id):
            _ = scan_id
            raise RuntimeError("vertex unavailable")

    monkeypatch.setattr("repo_intel.worker.jobs.run_scan.get_settings", lambda: Settings(ai_enabled=True, vertex_project_id="project"))
    monkeypatch.setattr("repo_intel.worker.jobs.run_scan.AIReasoningService", FailingAIService)

    RunScanJob(scan_id=scan.id, session=db_session, checkout_root=tmp_path / "checkouts").run()

    db_session.refresh(scan)
    artifacts = {
        artifact.artifact_type: artifact.payload
        for artifact in db_session.execute(select(ScanArtifact).where(ScanArtifact.scan_job_id == scan.id)).scalars().all()
    }
    assert scan.status == ScanStatus.COMPLETED
    assert artifacts["ai_error"]["phase"] == "summary_generation"


def _make_git_repo(path: Path) -> Path:
    path.mkdir()
    (path / "src").mkdir()
    (path / "README.md").write_text("# Example\n", encoding="utf-8")
    (path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    _git(path, "init", "-b", "main")
    _git(path, "add", ".")
    _git(path, "-c", "user.email=test@example.com", "-c", "user.name=Test User", "commit", "-m", "initial")
    return path


def _make_intel_git_repo(path: Path) -> Path:
    path.mkdir()
    (path / "src" / "middleware").mkdir(parents=True)
    (path / "src" / "routes").mkdir()
    (path / "package.json").write_text('{"dependencies":{"axios":"^1.0.0","pg":"^8.0.0","ioredis":"^5.0.0"}}', encoding="utf-8")
    (path / "src" / "middleware" / "auth.ts").write_text(
        'import axios from "axios";\nimport { Pool } from "pg";\nconst Redis = require("ioredis");\nexport function auth() { return fetch("/token"); }\n',
        encoding="utf-8",
    )
    (path / "src" / "routes" / "users.ts").write_text('app.get("/users", auth)\n', encoding="utf-8")
    _git(path, "init", "-b", "main")
    _git(path, "add", ".")
    _git(path, "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-m", "initial")
    for index in range(3):
        with (path / "src" / "middleware" / "auth.ts").open("a", encoding="utf-8") as handle:
            handle.write(f"// change {index}\n")
        _git(path, "add", ".")
        _git(path, "-c", "user.email=a@example.com", "-c", "user.name=A", "commit", "-m", f"auth change {index}")
    return path


def _make_scan(db_session: Session, repo_url: str) -> tuple[Repository, ScanJob]:
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
    return repository, scan


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
