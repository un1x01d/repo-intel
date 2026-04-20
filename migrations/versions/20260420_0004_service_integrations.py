"""add service integrations

Revision ID: 20260420_0004
Revises: 20260420_0003
Create Date: 2026-04-20 00:00:03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260420_0004"
down_revision = "20260420_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scan_job_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=True),
        sa.Column("integration_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["repo_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["scan_job_id"], ["scan_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("service_integrations")
