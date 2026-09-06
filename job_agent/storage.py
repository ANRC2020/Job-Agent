from __future__ import annotations

import json
import os
import platform
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


APP_NAME = "Clover"
LEGACY_APP_NAME = "Job Agent"
DEFAULT_PERSON_ID = "local-user"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def app_data_dir() -> Path:
    override = os.environ.get("JOB_AGENT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        root = Path.home() / "Library" / "Application Support"
        current = root / APP_NAME
        legacy = root / LEGACY_APP_NAME
        return current if current.exists() or not legacy.exists() else legacy
    if system == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        current = root / APP_NAME
        legacy = root / LEGACY_APP_NAME
        return current if current.exists() or not legacy.exists() else legacy
    root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    current = root / "clover"
    legacy = root / "job-agent"
    return current if current.exists() or not legacy.exists() else legacy


def database_path() -> Path:
    data_dir = app_data_dir()
    legacy = data_dir / "job-agent.sqlite3"
    return legacy if legacy.exists() else data_dir / "clover.sqlite3"


def documents_dir() -> Path:
    return app_data_dir() / "documents"


def migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _configure(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        target.parent.chmod(0o700)
    connection = sqlite3.connect(target, timeout=5)
    if os.name != "nt":
        target.chmod(0o600)
    _configure(connection)
    return connection


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _migration_files() -> list[Path]:
    return sorted(migrations_dir().glob("[0-9][0-9][0-9]_*.sql"))


def _checksum(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


def initialize_database(path: Path | None = None) -> dict[str, Any]:
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    documents_dir().mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        target.parent.chmod(0o700)
        documents_dir().chmod(0o700)
    applied: list[str] = []

    with transaction(target) as connection:
        _ensure_migration_table(connection)
        existing = {
            int(row["version"]): str(row["checksum"])
            for row in connection.execute("SELECT version, checksum FROM schema_migration")
        }
        for migration in _migration_files():
            version_text, _, _ = migration.stem.partition("_")
            version = int(version_text)
            content = migration.read_bytes()
            checksum = _checksum(content)
            if version in existing:
                if existing[version] != checksum:
                    raise RuntimeError(
                        f"Migration {migration.name} changed after it was applied. "
                        "Add a new migration instead of editing an applied migration."
                    )
                continue
            connection.executescript(content.decode("utf-8"))
            connection.execute(
                """
                INSERT INTO schema_migration(version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (version, migration.name, checksum, utc_now()),
            )
            applied.append(migration.name)

        now = utc_now()
        connection.execute(
            """
            INSERT INTO person_profile(id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (DEFAULT_PERSON_ID, now, now),
        )

    return {
        "path": str(target),
        "documentsPath": str(documents_dir()),
        "migrationsApplied": applied,
        "schemaVersion": schema_version(target),
    }


def schema_version(path: Path | None = None) -> int:
    target = path or database_path()
    if not target.exists():
        return 0
    with connect(target) as connection:
        row = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migration").fetchone()
        return int(row["version"]) if row else 0


def database_status(path: Path | None = None) -> dict[str, Any]:
    target = path or database_path()
    if not target.exists():
        return {
            "installed": False,
            "path": str(target),
            "schemaVersion": 0,
            "sizeBytes": 0,
            "tableCount": 0,
        }
    with connect(target) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM sqlite_master
            WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%'
            """
        ).fetchone()
        return {
            "installed": True,
            "path": str(target),
            "documentsPath": str(documents_dir()),
            "schemaVersion": schema_version(target),
            "sizeBytes": target.stat().st_size,
            "tableCount": int(row["count"]) if row else 0,
        }


def new_id() -> str:
    return str(uuid.uuid4())


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def create_conversation(
    *,
    person_id: str = DEFAULT_PERSON_ID,
    channel: str = "app",
    title: str | None = None,
) -> str:
    conversation_id = new_id()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO conversation(
                id, person_id, channel, title, started_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, person_id, channel, title, now, now, now),
        )
    return conversation_id


def conversation_exists(conversation_id: str) -> bool:
    with transaction() as connection:
        row = connection.execute(
            "SELECT 1 FROM conversation WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return row is not None


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    *,
    model_run_id: str | None = None,
    source_id: str | None = None,
) -> str:
    message_id = new_id()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO message(
                id, conversation_id, source_id, role, content, occurred_at,
                model_run_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                source_id,
                role,
                content,
                now,
                model_run_id,
                now,
                now,
            ),
        )
    return message_id


def add_model_run(
    *,
    provider: str,
    model: str,
    output: Any,
    prompt_version: str = "1",
    input_hash: str | None = None,
    latency_ms: int | None = None,
) -> str:
    run_id = new_id()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO model_run(
                id, provider, model, prompt_version, input_hash, output_json,
                latency_ms, started_at, completed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                provider,
                model,
                prompt_version,
                input_hash,
                json_value(output),
                latency_ms,
                now,
                now,
                now,
                now,
            ),
        )
    return run_id
