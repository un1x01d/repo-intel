"""initial schema

Revision ID: 20260420_0001
Revises:
Create Date: 2026-04-20 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0001"
down_revision = None
branch_labels = None
depends_on = None


scan_status_enum = sa.Enum(
    "queued",
    "cloning",
    "fingerprinting",
    "extracting_structure",
    "extracting_integrations",
    "extracting_git",
    "extracting_security",
    "extracting_performance",
    "normalizing",
    "reasoning",
    "completed",
    "failed",
    name="scanstatus",
)


severity_enum = sa.Enum("low", "medium", "high", "critical", name="severity")


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("repo_url", sa.String(length=1024), nullable=False),
        sa.Column("normalized_repo_key", sa.String(length=512), nullable=False),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_repo_key"),
    )

    op.create_table(
        "scan_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("requested_ref", sa.String(length=255), nullable=False),
        sa.Column("resolved_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("status", scan_status_enum, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "repo_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("file_type", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_config", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_entrypoint", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "commits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("author_name", sa.String(length=255), nullable=True),
        sa.Column("author_email", sa.String(length=320), nullable=True),
        sa.Column("authored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("files_changed", sa.Integer(), nullable=True),
        sa.Column("insertions", sa.Integer(), nullable=True),
        sa.Column("deletions", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "symbols",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("symbol_name", sa.String(length=255), nullable=False),
        sa.Column("symbol_kind", sa.String(length=64), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("exported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "dependencies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("package_name", sa.String(length=255), nullable=False),
        sa.Column("version_spec", sa.String(length=128), nullable=True),
        sa.Column("locked_version", sa.String(length=128), nullable=True),
        sa.Column("dependency_type", sa.String(length=64), nullable=True),
        sa.Column("ecosystem", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("subtype", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", severity_enum, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_scanner", sa.String(length=128), nullable=True),
        sa.Column("remediation_hint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("symbol_id", sa.Uuid(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["symbol_id"], ["symbols.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "ai_insights",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("insight_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "file_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("imported_path", sa.String(length=2048), nullable=False),
        sa.Column("resolved_file_id", sa.Uuid(), nullable=True),
        sa.Column("import_kind", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["resolved_file_id"], ["repo_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "symbol_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("caller_symbol_id", sa.Uuid(), nullable=False),
        sa.Column("callee_name", sa.String(length=255), nullable=False),
        sa.Column("resolved_callee_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("call_type", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["caller_symbol_id"], ["symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_callee_symbol_id"], ["symbols.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "finding_evidence_links",
        sa.Column("finding_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("finding_id", "evidence_id"),
    )

    op.create_table(
        "insight_evidence_links",
        sa.Column("insight_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["insight_id"], ["ai_insights.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("insight_id", "evidence_id"),
    )

    op.create_table(
        "commit_file_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("commit_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("additions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["commit_id"], ["commits.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("commit_id", "file_id", name="uq_commit_file_change"),
    )


def downgrade() -> None:
    op.drop_table("commit_file_changes")
    op.drop_table("insight_evidence_links")
    op.drop_table("finding_evidence_links")
    op.drop_table("symbol_calls")
    op.drop_table("file_imports")
    op.drop_table("ai_insights")
    op.drop_table("evidence")
    op.drop_table("findings")
    op.drop_table("dependencies")
    op.drop_table("symbols")
    op.drop_table("commits")
    op.drop_table("repo_files")
    op.drop_table("scan_jobs")
    op.drop_table("repositories")
    severity_enum.drop(op.get_bind(), checkfirst=True)
    scan_status_enum.drop(op.get_bind(), checkfirst=True)
