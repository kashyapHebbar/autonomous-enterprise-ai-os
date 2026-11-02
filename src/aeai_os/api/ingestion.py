"""Read-only ingestion history; configuration remains operator-managed."""

import json
import os
from contextlib import closing

from fastapi import APIRouter

from aeai_os.api.auth import AdminUser
from aeai_os.connectors.ingestion import IngestionStore


def build_ingestion_router():
    router = APIRouter(prefix="/ingestion", tags=["ingestion"])

    @router.get("/audit")
    def history(actor: AdminUser):
        store = IngestionStore(os.getenv("AEAI_INGESTION_DB_PATH", "artifacts/ingestion.db"))
        with closing(store.connect()) as db:
            rows = db.execute(
                """SELECT scope,at,changed FROM ingestion_audit
                WHERE json_extract(scope, '$[0]')=? AND json_extract(scope, '$[1]')=?
                ORDER BY at DESC LIMIT 100""",
                (actor.organization_id, actor.workspace_id),
            ).fetchall()
        return [
            {"source_id": json.loads(scope)[2], "at": at, "changed_records": changed}
            for scope, at, changed in rows
        ]

    return router
