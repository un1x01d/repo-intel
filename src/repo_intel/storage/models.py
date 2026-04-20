from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from repo_intel.core.enums import ScanStatus, Severity


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_type: Mapped[str] = mapped_column(String(32))
    repo_url: Mapped[str] = mapped_column(String(1024))
    normalized_repo_key: Mapped[str] = mapped_column(String(512), unique=True)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    scan_jobs: Mapped[list[ScanJob]] = relationship(back_populates="repository", cascade="all, delete-orphan")


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    requested_ref: Mapped[str] = mapped_column(String(255))
    resolved_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scanstatus", values_callable=lambda enum: [item.value for item in enum]),
        default=ScanStatus.QUEUED,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    repository: Mapped[Repository] = relationship(back_populates="scan_jobs")


class RepoFile(Base):
    __tablename__ = "repo_files"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(2048))
    file_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    is_config: Mapped[bool] = mapped_column(Boolean, default=False)
    is_entrypoint: Mapped[bool] = mapped_column(Boolean, default=False)


class ScanArtifact(Base):
    __tablename__ = "scan_artifacts"
    __table_args__ = (UniqueConstraint("scan_job_id", "artifact_type", name="uq_scan_artifact_type"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    artifact_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Commit(Base):
    __tablename__ = "commits"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    commit_sha: Mapped[str] = mapped_column(String(64))
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    authored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    insertions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletions: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Symbol(Base):
    __tablename__ = "symbols"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("repo_files.id", ondelete="SET NULL"), nullable=True)
    symbol_name: Mapped[str] = mapped_column(String(255))
    symbol_kind: Mapped[str] = mapped_column(String(64))
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exported: Mapped[bool] = mapped_column(Boolean, default=False)


class Dependency(Base):
    __tablename__ = "dependencies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    package_name: Mapped[str] = mapped_column(String(255))
    version_spec: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dependency_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ecosystem: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(ForeignKey("repo_files.id", ondelete="CASCADE"))
    framework: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(1024))
    handler_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceIntegration(Base):
    __tablename__ = "service_integrations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("repo_files.id", ondelete="SET NULL"), nullable=True)
    integration_type: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(128))
    symbol_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(64))
    subtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity", values_callable=lambda enum: [item.value for item in enum]),
        default=Severity.MEDIUM,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_scanner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remediation_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    evidence_type: Mapped[str] = mapped_column(String(64))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("repo_files.id", ondelete="SET NULL"), nullable=True)
    symbol_id: Mapped[UUID | None] = mapped_column(ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AIInsight(Base):
    __tablename__ = "ai_insights"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    insight_type: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileImport(Base):
    __tablename__ = "file_imports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    source_file_id: Mapped[UUID] = mapped_column(ForeignKey("repo_files.id", ondelete="CASCADE"))
    imported_path: Mapped[str] = mapped_column(String(2048))
    resolved_file_id: Mapped[UUID | None] = mapped_column(ForeignKey("repo_files.id", ondelete="SET NULL"), nullable=True)
    import_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SymbolCall(Base):
    __tablename__ = "symbol_calls"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    caller_symbol_id: Mapped[UUID] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    callee_name: Mapped[str] = mapped_column(String(255))
    resolved_callee_symbol_id: Mapped[UUID | None] = mapped_column(ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True)
    call_type: Mapped[str | None] = mapped_column(String(64), nullable=True)


class FindingEvidenceLink(Base):
    __tablename__ = "finding_evidence_links"

    finding_id: Mapped[UUID] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)


class InsightEvidenceLink(Base):
    __tablename__ = "insight_evidence_links"

    insight_id: Mapped[UUID] = mapped_column(ForeignKey("ai_insights.id", ondelete="CASCADE"), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), primary_key=True)


class CommitFileChange(Base):
    __tablename__ = "commit_file_changes"
    __table_args__ = (UniqueConstraint("commit_id", "file_id", name="uq_commit_file_change"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    scan_job_id: Mapped[UUID] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"))
    commit_id: Mapped[UUID] = mapped_column(ForeignKey("commits.id", ondelete="CASCADE"))
    file_id: Mapped[UUID] = mapped_column(ForeignKey("repo_files.id", ondelete="CASCADE"))
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
