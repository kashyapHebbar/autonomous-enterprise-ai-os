"""Add tenant-scoped connector installations.

Revision ID: 20260719_0003
Revises: 20260711_0002
Create Date: 2026-07-19 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260719_0003"
down_revision = "20260711_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "connector_installations",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("connector_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("organization_id", sa.String(length=100), nullable=False),
        sa.Column("workspace_id", sa.String(length=100), nullable=True),
        sa.Column("credential_reference", sa.Text(), nullable=True),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connector_installations_connector_id",
        "connector_installations",
        ["connector_id"],
    )
    op.create_index(
        "ix_connector_installations_organization_id",
        "connector_installations",
        ["organization_id"],
    )
    op.create_index(
        "ix_connector_installations_workspace_id",
        "connector_installations",
        ["workspace_id"],
    )
    op.create_index(
        "ix_connector_installations_status",
        "connector_installations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_connector_installations_status", table_name="connector_installations")
    op.drop_index(
        "ix_connector_installations_workspace_id",
        table_name="connector_installations",
    )
    op.drop_index(
        "ix_connector_installations_organization_id",
        table_name="connector_installations",
    )
    op.drop_index(
        "ix_connector_installations_connector_id",
        table_name="connector_installations",
    )
    op.drop_table("connector_installations")
