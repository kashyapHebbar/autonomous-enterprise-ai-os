from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse


def postgres_environment(database_url: str) -> tuple[dict[str, str], str]:
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("A PostgreSQL database URL is required.")
    database_name = parsed.path.lstrip("/")
    if not database_name:
        raise ValueError("The PostgreSQL URL must include a database name.")
    env = dict(os.environ)
    env.update(
        {
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": unquote(parsed.username or ""),
            "PGPASSWORD": unquote(parsed.password or ""),
            "PGDATABASE": database_name,
        }
    )
    return env, database_name


def create_backup(database_url: str, output: Path) -> dict[str, str | int]:
    pg_env, database_name = postgres_environment(database_url)
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pg_dump", "--format=custom", "--no-owner", "--file", str(output)],
        env=pg_env,
        check=True,
    )
    with output.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    manifest: dict[str, str | int] = {
        "database": database_name,
        "created_at": datetime.now(UTC).isoformat(),
        "file": output.name,
        "size_bytes": output.stat().st_size,
        "sha256": digest,
    }
    output.with_suffix(output.suffix + ".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def restore_backup(database_url: str, backup: Path, *, allow_target: str) -> None:
    pg_env, database_name = postgres_environment(database_url)
    if allow_target not in database_name:
        raise ValueError(
            f"Restore target database must contain the safety marker {allow_target!r}."
        )
    if not backup.is_file():
        raise ValueError(f"Backup file does not exist: {backup}")
    _verify_backup_manifest(backup)
    subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            database_name,
            str(backup),
        ],
        env=pg_env,
        check=True,
    )


def _verify_backup_manifest(backup: Path) -> None:
    manifest_path = backup.with_suffix(backup.suffix + ".json")
    if not manifest_path.is_file():
        raise ValueError(f"Backup checksum manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with backup.open("rb") as handle:
        actual_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if manifest.get("sha256") != actual_digest:
        raise ValueError("Backup checksum does not match its recovery manifest.")
    if manifest.get("size_bytes") != backup.stat().st_size:
        raise ValueError("Backup size does not match its recovery manifest.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and restore PostgreSQL recovery backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--database-url-env", default="AEAI_DATABASE_URL")
    backup.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore-drill")
    restore.add_argument("--database-url-env", default="AEAI_RESTORE_DATABASE_URL")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--target-marker", default="restore_drill")
    args = parser.parse_args(argv)

    database_url = os.getenv(args.database_url_env, "").strip()
    if not database_url:
        print(f"ERROR: {args.database_url_env} is not configured.", file=sys.stderr)
        return 1
    try:
        if args.command == "backup":
            print(json.dumps(create_backup(database_url, args.output), indent=2))
        else:
            restore_backup(database_url, args.backup, allow_target=args.target_marker)
            print("Restore drill completed successfully.")
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
