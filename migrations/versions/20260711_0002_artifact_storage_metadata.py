"""Add first-class artifact storage metadata.

Revision ID: 20260711_0002
Revises: 20260708_0001
Create Date: 2026-07-11 00:00:00.000000
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa

revision = "20260711_0002"
down_revision = "20260708_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifacts", sa.Column("content_type", sa.String(length=128), nullable=True))
    op.add_column("artifacts", sa.Column("storage_backend", sa.String(length=64), nullable=True))
    op.add_column("artifacts", sa.Column("storage_key", sa.Text(), nullable=True))
    op.add_column("artifacts", sa.Column("size_bytes", sa.Integer(), nullable=True))
    op.create_index("ix_artifacts_storage_backend", "artifacts", ["storage_backend"])
    _backfill_artifact_storage_metadata()


def downgrade() -> None:
    op.drop_index("ix_artifacts_storage_backend", table_name="artifacts")
    op.drop_column("artifacts", "size_bytes")
    op.drop_column("artifacts", "storage_key")
    op.drop_column("artifacts", "storage_backend")
    op.drop_column("artifacts", "content_type")


def _backfill_artifact_storage_metadata() -> None:
    artifact_table = sa.table(
        "artifacts",
        sa.column("id", sa.String(length=96)),
        sa.column("metadata_json", sa.JSON()),
        sa.column("content_type", sa.String(length=128)),
        sa.column("storage_backend", sa.String(length=64)),
        sa.column("storage_key", sa.Text()),
        sa.column("size_bytes", sa.Integer()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(artifact_table.c.id, artifact_table.c.metadata_json)
    ).mappings()

    for row in rows:
        metadata = row["metadata_json"] if isinstance(row["metadata_json"], dict) else {}
        connection.execute(
            artifact_table.update()
            .where(artifact_table.c.id == row["id"])
            .values(
                content_type=_optional_string(metadata.get("content_type")),
                storage_backend=_optional_string(metadata.get("storage_backend")),
                storage_key=_optional_string(metadata.get("storage_key")),
                size_bytes=_optional_int(metadata.get("size_bytes")),
            )
        )


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
