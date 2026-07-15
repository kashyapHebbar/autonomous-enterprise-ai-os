# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from aeai_os.runs.archive import export_run_archive, import_run_archive
from aeai_os.runs.factory import build_run_repository
from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository
from aeai_os.settings import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export and import portable run archives.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Use a SQLAlchemy repository at this URL instead of configured settings.",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create repository tables before export/import when --database-url is set.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export a run archive.")
    export_parser.add_argument("run_id")
    export_parser.add_argument("--output", type=Path, required=True)

    import_parser = subparsers.add_parser("import", help="Import a run archive.")
    import_parser.add_argument("--input", type=Path, required=True)
    import_parser.add_argument("--overwrite", action="store_true")

    replay_parser = subparsers.add_parser(
        "replay",
        help="Alias for import; restores an archive for offline inspection.",
    )
    replay_parser.add_argument("--input", type=Path, required=True)
    replay_parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args(argv)
    repository = _build_repository(args.database_url, create_schema=args.create_schema)

    if args.command == "export":
        archive = export_run_archive(repository, args.run_id)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(archive, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"Exported run archive: {args.output}")
        return 0

    if args.command in {"import", "replay"}:
        archive = json.loads(args.input.read_text(encoding="utf-8"))
        run = import_run_archive(repository, archive, overwrite=args.overwrite)
        print(f"Imported run archive: {run.id}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


def _build_repository(database_url: str | None, *, create_schema: bool):
    if database_url:
        return SQLAlchemyRunRepository.from_url(database_url, create_schema=create_schema)
    return build_run_repository(get_settings())


if __name__ == "__main__":
    raise SystemExit(main())
