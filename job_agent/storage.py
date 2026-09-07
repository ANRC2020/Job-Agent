from __future__ import annotations

import json
import os
import platform
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from job_agent.reasoning import strip_thinking

APP_NAME = "Clover"
LEGACY_APP_NAME = "Job Agent"
DEFAULT_PERSON_ID = "local-user"
DATABASE_FILENAMES = ("clover.sqlite3", "job-agent.sqlite3")


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
        return _preferred_data_dir(current, legacy)
    if system == "Windows":
        root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        current = root / APP_NAME
        legacy = root / LEGACY_APP_NAME
        return _preferred_data_dir(current, legacy)
    root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    current = root / "clover"
    legacy = root / "job-agent"
    return _preferred_data_dir(current, legacy)


def _preferred_data_dir(current: Path, legacy: Path) -> Path:
    """Prefer the directory that actually contains data, not merely one that exists.

    Older installers may have created an empty Clover directory before the
    rebrand-aware build first ran. In that case the legacy database remains the
    source of truth. If both directories contain databases, the current Clover
    directory wins and neither file is moved or overwritten.
    """
    current_has_database = any((current / name).is_file() for name in DATABASE_FILENAMES)
    legacy_has_database = any((legacy / name).is_file() for name in DATABASE_FILENAMES)
    if current_has_database:
        return current
    if legacy_has_database:
        return legacy
    if current.exists() or not legacy.exists():
        return current
    return legacy


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
            connection.execute("BEGIN IMMEDIATE")
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


def _execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a migration statement-by-statement inside the caller's transaction.

    sqlite3.executescript() commits before it starts, which can leave half a
    migration behind if a later statement fails. complete_statement() keeps
    trigger bodies intact while allowing normal transaction rollback.
    """
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            if statement.strip():
                connection.execute(statement)
            statement = ""
    if statement.strip():
        raise RuntimeError("Migration ended with an incomplete SQL statement.")


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
            _execute_script(connection, content.decode("utf-8"))
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
    kind: str = "general",
    job_process_id: str | None = None,
) -> str:
    conversation_id = new_id()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO conversation(
                id, person_id, channel, title, started_at, created_at, updated_at,
                kind, job_process_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, person_id, channel, title, now, now, now, kind, job_process_id),
        )
    return conversation_id


def conversation_exists(conversation_id: str) -> bool:
    with transaction() as connection:
        row = connection.execute(
            "SELECT 1 FROM conversation WHERE id = ?",
            (conversation_id,),
        ).fetchone()
    return row is not None


def touch_conversation(conversation_id: str) -> None:
    with transaction() as connection:
        connection.execute(
            "UPDATE conversation SET updated_at = ? WHERE id = ?",
            (utc_now(), conversation_id),
        )


def ensure_thread(
    *,
    kind: str,
    job_process_id: str | None = None,
    title: str | None = None,
    person_id: str = DEFAULT_PERSON_ID,
) -> str:
    """Return the durable thread for a context, creating it on first use.

    Every opportunity keeps one thread for its whole life, so Juno picks up
    where she left off instead of starting over each visit.
    """
    initialize_database()
    conversation_id = new_id()
    now = utc_now()
    with transaction() as connection:
        if job_process_id:
            row = connection.execute(
                """
                SELECT id FROM conversation
                WHERE person_id = ? AND job_process_id = ?
                ORDER BY started_at LIMIT 1
                """,
                (person_id, job_process_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id FROM conversation
                WHERE person_id = ? AND kind = ? AND job_process_id IS NULL
                ORDER BY started_at LIMIT 1
                """,
                (person_id, kind),
            ).fetchone()
        if row is not None:
            return str(row["id"])
        connection.execute(
            """
            INSERT OR IGNORE INTO conversation(
                id, person_id, channel, title, started_at, created_at, updated_at,
                kind, job_process_id
            ) VALUES (?, ?, 'app', ?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, person_id, title, now, now, now, kind, job_process_id),
        )
        if job_process_id:
            row = connection.execute(
                """
                SELECT id FROM conversation
                WHERE person_id = ? AND job_process_id = ?
                ORDER BY started_at, rowid LIMIT 1
                """,
                (person_id, job_process_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT id FROM conversation
                WHERE person_id = ? AND kind = ? AND job_process_id IS NULL
                ORDER BY started_at, rowid LIMIT 1
                """,
                (person_id, kind),
            ).fetchone()
        if row is None:
            raise RuntimeError("Clover could not create a durable conversation thread.")
        return str(row["id"])


def list_messages(conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """Return visible turns for a thread, oldest first."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, role, content, occurred_at, model_run_id
            FROM message
            WHERE conversation_id = ? AND role IN ('user', 'assistant')
            ORDER BY occurred_at DESC, rowid DESC
            LIMIT ?
            """,
            (conversation_id, max(1, min(limit, 500))),
        ).fetchall()

    # A database written by an earlier build can hold reasoning tags that leaked
    # into a stored reply. Scrub on the way out so they neither show up in the
    # conversation nor get replayed into the model's context.
    turns = []
    for row in reversed(rows):
        turn = dict(row)
        if turn["role"] == "assistant":
            turn["content"] = strip_thinking(str(turn["content"] or ""))
        turns.append(turn)
    return turns


def latest_conversation_summary(conversation_id: str) -> dict[str, Any] | None:
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, conversation_id, summary_text, source_start_message_id,
                   source_end_message_id, source_message_count, model,
                   created_at, updated_at
            FROM conversation_summary
            WHERE conversation_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def list_messages_after(
    conversation_id: str,
    message_id: str | None,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return visible messages appended after a source boundary, oldest first."""
    initialize_database()
    with connect() as connection:
        boundary = 0
        if message_id:
            row = connection.execute(
                "SELECT rowid FROM message WHERE id = ? AND conversation_id = ?",
                (message_id, conversation_id),
            ).fetchone()
            if row is None:
                raise ValueError("Conversation summary source boundary no longer exists.")
            boundary = int(row["rowid"])
        rows = connection.execute(
            """
            SELECT id, role, content, occurred_at, model_run_id
            FROM message
            WHERE conversation_id = ? AND role IN ('user', 'assistant') AND rowid > ?
            ORDER BY rowid
            LIMIT ?
            """,
            (conversation_id, boundary, max(1, min(limit, 2_000))),
        ).fetchall()
    turns = []
    for row in rows:
        turn = dict(row)
        if turn["role"] == "assistant":
            turn["content"] = strip_thinking(str(turn["content"] or ""))
        turns.append(turn)
    return turns


def add_conversation_summary(
    conversation_id: str,
    *,
    summary_text: str,
    source_start_message_id: str,
    source_end_message_id: str,
    source_message_count: int,
    model: str,
) -> dict[str, Any]:
    clean = summary_text.strip()
    if not clean:
        raise ValueError("Conversation summary cannot be empty.")
    now = utc_now()
    summary_id = new_id()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO conversation_summary(
                id, conversation_id, summary_text, source_start_message_id,
                source_end_message_id, source_message_count, model,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id, source_end_message_id) DO NOTHING
            """,
            (
                summary_id,
                conversation_id,
                clean,
                source_start_message_id,
                source_end_message_id,
                source_message_count,
                model,
                now,
                now,
            ),
        )
        row = connection.execute(
            """
            SELECT id, conversation_id, summary_text, source_start_message_id,
                   source_end_message_id, source_message_count, model,
                   created_at, updated_at
            FROM conversation_summary
            WHERE conversation_id = ? AND source_end_message_id = ?
            """,
            (conversation_id, source_end_message_id),
        ).fetchone()
    if row is None:
        raise RuntimeError("Clover could not save the conversation summary.")
    return dict(row)


PROGRESS_DEDUPE_SECONDS = 600

# Clover records progress itself whenever it changes something, and Juno may also
# report the same action in the same turn — under a different name, so matching on
# kind alone can't catch it. Anything Clover recorded during the current turn is
# tracked here so her own report can defer to it.
_turn = threading.local()


def begin_turn() -> None:
    """Start of one of Juno's turns."""
    _turn.recorded = []


def progress_recorded_this_turn() -> bool:
    return bool(getattr(_turn, "recorded", None))


def add_progress_event(
    *,
    kind: str,
    headline: str,
    detail: str | None = None,
    process_id: str | None = None,
    person_id: str = DEFAULT_PERSON_ID,
    metadata: Any = None,
) -> str:
    """Record a moment of progress.

    A repeat of the same kind on the same opportunity within a few minutes is
    treated as the same moment rather than a second one.
    """
    event_id = new_id()
    now = utc_now()
    with transaction() as connection:
        recent = connection.execute(
            """
            SELECT id FROM progress_event
            WHERE person_id = ?
              AND kind = ?
              AND COALESCE(process_id, '') = COALESCE(?, '')
              AND occurred_at > datetime(?, ?)
            LIMIT 1
            """,
            (person_id, kind, process_id, now, f"-{PROGRESS_DEDUPE_SECONDS} seconds"),
        ).fetchone()
        if recent is not None:
            return str(recent["id"])
        connection.execute(
            """
            INSERT INTO progress_event(
                id, person_id, process_id, kind, headline, detail,
                occurred_at, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                person_id,
                process_id,
                kind,
                headline,
                detail,
                now,
                json_value(metadata or {}),
                now,
                now,
            ),
        )
    if hasattr(_turn, "recorded"):
        _turn.recorded.append(event_id)
    return event_id


def list_progress_events(
    *,
    person_id: str = DEFAULT_PERSON_ID,
    limit: int = 12,
) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, kind, headline, detail, occurred_at, process_id
            FROM progress_event
            WHERE person_id = ?
            ORDER BY occurred_at DESC, rowid DESC
            LIMIT ?
            """,
            (person_id, max(1, min(limit, 100))),
        ).fetchall()
    return [dict(row) for row in rows]


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


def add_tool_actions(
    conversation_id: str,
    model_run_id: str,
    actions: list[dict[str, Any]],
) -> list[str]:
    """Persist compact tool traces for transparency and future turn context."""
    if not actions:
        return []
    now = utc_now()
    action_ids: list[str] = []
    with transaction() as connection:
        for action in actions:
            action_id = new_id()
            action_ids.append(action_id)
            connection.execute(
                """
                INSERT INTO tool_action(
                    id, conversation_id, model_run_id, tool_name, activity,
                    arguments_json, result_summary, status,
                    occurred_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    conversation_id,
                    model_run_id,
                    str(action.get("tool") or "unknown"),
                    str(action.get("activity") or "") or None,
                    json_value(action.get("arguments") or {}),
                    str(action.get("result") or "")[:4_000] or None,
                    tool_action_status(str(action.get("result") or "")),
                    now,
                    now,
                    now,
                ),
            )
    return action_ids


def tool_action_status(result: str) -> str:
    clean = (result or "").strip()
    if clean.startswith(("Tool error:", "Unknown tool:")):
        return "failed"
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError:
        return "completed"
    if isinstance(payload, dict) and payload.get("approvalRequired"):
        return "pending"
    if isinstance(payload, dict) and payload.get("ok") is False:
        return "failed"
    return "completed"


def list_tool_actions(conversation_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent actions in chronological order for replay and UI disclosure."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, model_run_id, tool_name, activity, arguments_json,
                   result_summary, status, occurred_at
            FROM tool_action
            WHERE conversation_id = ?
            ORDER BY occurred_at DESC, rowid DESC
            LIMIT ?
            """,
            (conversation_id, max(1, min(limit, 200))),
        ).fetchall()
    actions = []
    for row in reversed(rows):
        item = dict(row)
        try:
            item["arguments"] = json.loads(item.pop("arguments_json"))
        except (json.JSONDecodeError, TypeError):
            item["arguments"] = {}
            item.pop("arguments_json", None)
        actions.append(item)
    return actions
