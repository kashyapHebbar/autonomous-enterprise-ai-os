#!/usr/bin/env python3
"""Local, point-in-time backup of the Upgrade 11 SQLite workspace.

No external services. Optional artifact backup may contain sensitive datasets.
The SQLite backup API is used so the database is consistent even while open.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

MAX_ARTIFACT_BYTES = 250 * 1024 * 1024


def backup(root: Path, destination: Path, include_artifacts: bool = False) -> Path:
    root = root.resolve()
    artifact_root = root / "artifacts"
    database = artifact_root / "aeai-local-runs.db"
    catalog = artifact_root / "aeai-local-sources.json"
    if not database.is_file() or database.is_symlink():
        raise ValueError("No regular SQLite run database found at artifacts/aeai-local-runs.db")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ValueError("Backup target already exists; refusing to overwrite it.")
    # Use the database's online backup API, not a live filesystem copy of WAL files.
    with tempfile.TemporaryDirectory() as tmp:
        copied_db = Path(tmp) / "runs-snapshot.db"
        with sqlite3.connect(str(database)) as source, sqlite3.connect(str(copied_db)) as target:
            source.backup(target)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as file_handle:
                with ZipFile(file_handle, "w", ZIP_DEFLATED, compresslevel=6) as archive:
                    archive.write(copied_db, "workspace/runs.db")
                    if catalog.is_file() and not catalog.is_symlink():
                        archive.write(catalog, "workspace/local-data-sources.json")
                    if include_artifacts:
                        consumed = 0
                        for file in artifact_root.rglob("*"):
                            if (
                                not file.is_file()
                                or file.is_symlink()
                                or file in {database, catalog}
                            ):
                                continue
                            relative = file.relative_to(artifact_root)
                            if any(part.startswith(".") for part in relative.parts):
                                continue
                            consumed += file.stat().st_size
                            if consumed > MAX_ARTIFACT_BYTES:
                                raise ValueError(
                                    "Artifact backup exceeds 250 MB; no completed archive retained."
                                )
                            archive.write(file, "workspace/artifacts/" + str(relative))
            os.chmod(destination, 0o600)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Secure local AI OS workspace backup")
    parser.add_argument(
        "--include-artifacts",
        action="store_true",
        help="Include saved reports, evidence and potentially sensitive uploaded data",
    )
    parser.add_argument("--output", type=Path, help="A new backup ZIP path; never overwritten")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output or (
        root / "artifacts" / "backups" / f"aeai-workspace-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip"
    )
    try:
        saved = backup(root, output, include_artifacts=args.include_artifacts)
    except (OSError, ValueError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"Backup failed: {error}\n")
    print(f"Workspace backup created: {saved}")
    if not args.include_artifacts:
        print("Database and local source catalog only; saved artifact files are NOT included.")
