"""Durable, scoped ingestion. Source configurations are operator-owned, never API input."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

from aeai_os.settings import get_env_secret


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def identifier(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Expected a simple SQL identifier")
    return value


def pages(config: dict, cursor) -> Iterator[tuple[list[dict], object]]:
    """SQL/Snowflake use a unique increasing key; REST uses an opaque cursor.

    S3 replays a bounded object only when its ETag changes. Row hashes prevent
    unchanged records being rewritten. Credentials are resolved only at execution.
    """
    kind = config["kind"]
    if kind in {"sql", "snowflake"}:
        table = identifier(config["table"])
        key = identifier(config["cursor_key"])
        query = f"SELECT * FROM {table} "
        if cursor is not None:
            query += f"WHERE {key} > :cursor "
        query += f"ORDER BY {key} LIMIT 1000"
        if kind == "sql":
            engine = create_engine(get_env_secret(config["connection_env"]))
            try:
                with engine.connect() as connection:
                    rows = [
                        dict(row)
                        for row in connection.execute(text(query), {"cursor": cursor}).mappings()
                    ]
            finally:
                engine.dispose()
        else:
            import snowflake.connector

            credentials = json.loads(get_env_secret(config["connection_env"]))
            with snowflake.connector.connect(**credentials) as connection:
                with connection.cursor(snowflake.connector.DictCursor) as statement:
                    statement.execute(query.replace(":cursor", "%(cursor)s"), {"cursor": cursor})
                    rows = statement.fetchall()
        if rows:
            next_cursor = rows[-1][key]
            if next_cursor is None or next_cursor == cursor:
                raise ValueError("Source cursor must advance")
            yield rows, next_cursor
        return
    if kind == "rest":
        import httpx

        url = config["url"]
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("REST ingestion requires HTTPS without embedded credentials")
        headers = {}
        if config.get("token_env"):
            headers["Authorization"] = "Bearer " + get_env_secret(config["token_env"])
        # Operator-configured fixed endpoint; never follow redirects or a remote next URL.
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            with client.stream(
                "GET", url, headers=headers, params={"cursor": cursor or ""}
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 10 * 1024 * 1024:
                        raise ValueError("REST page exceeds 10 MiB")
        payload = json.loads(body)
        rows = payload["items"]
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("REST items must be an array of at most 10000 records")
        next_cursor = payload.get("next_cursor")
        if rows and (next_cursor is None or next_cursor == cursor):
            raise ValueError("Nonempty REST pages require a new durable next_cursor")
        if rows:
            yield rows, next_cursor
        return
    if kind == "s3":
        import boto3

        client = boto3.client("s3")
        args = {"Bucket": config["bucket"], "Key": config["key"]}
        head = client.head_object(**args)
        etag = head["ETag"]
        if cursor == etag:
            return
        if head["ContentLength"] > 50 * 1024 * 1024:
            raise ValueError("S3 object exceeds 50 MiB")
        with closing(client.get_object(**args, IfMatch=etag)["Body"]) as body:
            content = body.read(50 * 1024 * 1024 + 1)
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("S3 object exceeds 50 MiB")
        yield list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")))), etag
        return
    raise ValueError("Unsupported ingestion connector")


class IngestionStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS checkpoints (
                    scope TEXT PRIMARY KEY, cursor TEXT, due REAL NOT NULL DEFAULT 0,
                    config_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records (
                    scope TEXT, id TEXT, payload TEXT NOT NULL, digest TEXT NOT NULL,
                    PRIMARY KEY(scope,id));
                CREATE TABLE IF NOT EXISTS ingestion_audit (
                    scope TEXT, at REAL, changed INTEGER, cursor TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=60, isolation_level=None)

    @staticmethod
    def scope(config):
        return canonical([config["organization_id"], config["workspace_id"], config["id"]])

    def sync(self, config, *, fetch=pages, force=False):
        scope = self.scope(config)
        digest = hashlib.sha256(canonical(config).encode()).hexdigest()
        interval = int(config.get("interval_seconds", 300))
        if interval < 1:
            raise ValueError("Synchronization interval must be positive")
        # A single transaction serializes workers and commits records, audit and
        # checkpoint together. A crash or source failure leaves the old cursor intact.
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                saved = db.execute(
                    "SELECT cursor,due,config_hash FROM checkpoints WHERE scope=?", (scope,)
                ).fetchone()
                if saved and saved[2] != digest:
                    raise ValueError("Source configuration changed; use a new ingestion ID")
                if saved and saved[1] > time.time() and not force:
                    db.rollback()
                    return 0
                cursor = json.loads(saved[0]) if saved else None
                changed = 0
                for rows, next_cursor in fetch(config, cursor):
                    for row in rows:
                        value = row[config["primary_key"]]
                        if value is None or value == "":
                            raise ValueError("Missing record primary key")
                        payload = canonical(row)
                        row_hash = hashlib.sha256(payload.encode()).hexdigest()
                        result = db.execute(
                            """INSERT INTO records VALUES (?,?,?,?)
                            ON CONFLICT(scope,id) DO UPDATE SET payload=excluded.payload,
                            digest=excluded.digest WHERE records.digest != excluded.digest""",
                            (scope, canonical(value), payload, row_hash),
                        )
                        changed += result.rowcount
                    cursor = next_cursor
                encoded_cursor = canonical(cursor)
                db.execute(
                    "INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?)",
                    (scope, encoded_cursor, time.time() + interval, digest),
                )
                db.execute(
                    "INSERT INTO ingestion_audit VALUES (?,?,?,?)",
                    (scope, time.time(), changed, encoded_cursor),
                )
                db.commit()
                return changed
            except BaseException:
                db.rollback()
                raise

    def export_csv(self, config, destination):
        """Atomically publish a consistent snapshot for the existing six-agent workflow."""
        import tempfile

        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".ingestion-")
        try:
            with os.fdopen(fd, "w", newline="") as output, closing(self.connect()) as db:
                db.execute("BEGIN")
                fields = set()
                for (payload,) in db.execute(
                    "SELECT payload FROM records WHERE scope=?", (self.scope(config),)
                ):
                    fields.update(json.loads(payload))
                writer = csv.DictWriter(output, fieldnames=sorted(fields))
                writer.writeheader()
                for (payload,) in db.execute(
                    "SELECT payload FROM records WHERE scope=? ORDER BY id", (self.scope(config),)
                ):
                    writer.writerow(json.loads(payload))
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
