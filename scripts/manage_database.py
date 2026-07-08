# ruff: noqa: E402

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from aeai_os.settings import get_settings
from aeai_os.storage.migrations import upgrade_database, validate_persistent_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage persistent platform database schema.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL. Defaults to AEAI_DATABASE_URL or the application default.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    upgrade_parser = subparsers.add_parser("upgrade", help="Apply database migrations.")
    upgrade_parser.add_argument(
        "--revision",
        default="head",
        help="Alembic revision target to upgrade to.",
    )

    subparsers.add_parser("validate", help="Validate required tables and indexes.")

    args = parser.parse_args()
    database_url = args.database_url or get_settings().database_url

    if args.command == "upgrade":
        upgrade_database(database_url, revision=args.revision)
        print(f"Database upgraded to {args.revision}")
        return 0

    if args.command == "validate":
        errors = validate_persistent_schema(database_url)
        if errors:
            for error in errors:
                print(error)
            return 1
        print("Persistent platform schema validation passed")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
