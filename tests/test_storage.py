from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from job_agent.storage import (
    _execute_script,
    _preferred_data_dir,
    add_message,
    add_model_run,
    connect,
    conversation_exists,
    create_conversation,
    database_status,
    ensure_thread,
    initialize_database,
    list_messages,
    migrations_dir,
    tool_action_status,
)


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_initialization_is_idempotent(self) -> None:
        first = initialize_database()
        second = initialize_database()

        self.assertEqual(
            [
                "001_initial.sql",
                "002_person_memory_search.sql",
                "003_opportunity_context.sql",
                "004_behavioral_learning.sql",
                "005_browser_extension.sql",
                "006_conversation_compaction.sql",
                "007_opportunity_enrichment.sql",
                "008_job_external_identity.sql",
                "009_remove_extension_auth.sql",
                "010_application_answer_cache.sql",
            ],
            first["migrationsApplied"],
        )
        self.assertEqual([], second["migrationsApplied"])
        self.assertEqual(10, database_status()["schemaVersion"])

    def test_all_three_domains_are_installed(self) -> None:
        initialize_database()
        with connect() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertTrue(
            {
                "person_profile",
                "profile_fact",
                "experience",
                "conversation",
                "job",
                "job_process",
                "application_material",
                "learning",
                "learning_evidence",
                "preference_signal",
                "conversation_summary",
            }.issubset(tables)
        )
        self.assertNotIn("extension_pairing_code", tables)
        self.assertNotIn("extension_token", tables)

    def test_conversations_and_model_runs_are_persisted_and_searchable(self) -> None:
        initialize_database()
        conversation_id = create_conversation(title="Career goals")
        self.assertTrue(conversation_exists(conversation_id))
        add_message(conversation_id, "user", "I want mission-driven climate work.")
        run_id = add_model_run(
            provider="lm-studio",
            model="qwen/test",
            output={"content": "Understood"},
        )
        add_message(
            conversation_id,
            "assistant",
            "I will prioritize mission-driven climate roles.",
            model_run_id=run_id,
        )

        with connect() as connection:
            messages = connection.execute(
                "SELECT role, content FROM message WHERE conversation_id = ? ORDER BY occurred_at",
                (conversation_id,),
            ).fetchall()
            search = connection.execute(
                "SELECT message_id FROM message_fts WHERE message_fts MATCH ?",
                ("climate",),
            ).fetchall()

        self.assertEqual(["user", "assistant"], [row["role"] for row in messages])
        self.assertEqual(2, len(search))

    def test_foreign_keys_are_enforced(self) -> None:
        initialize_database()
        with self.assertRaises(sqlite3.IntegrityError):
            add_message("missing-conversation", "user", "hello")

    def test_ensure_thread_is_atomic_under_concurrency(self) -> None:
        initialize_database()
        with ThreadPoolExecutor(max_workers=8) as executor:
            thread_ids = list(
                executor.map(lambda _: ensure_thread(kind="juno", title="Juno"), range(24))
            )

        self.assertEqual(1, len(set(thread_ids)))
        with connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM conversation WHERE kind = 'juno'"
            ).fetchone()[0]
        self.assertEqual(1, count)

    def test_legacy_database_wins_over_empty_current_directory(self) -> None:
        root = Path(self.temp_dir.name)
        current = root / "Clover"
        legacy = root / "Job Agent"
        current.mkdir()
        legacy.mkdir()
        (legacy / "job-agent.sqlite3").touch()

        self.assertEqual(legacy, _preferred_data_dir(current, legacy))

        (current / "clover.sqlite3").touch()
        self.assertEqual(current, _preferred_data_dir(current, legacy))

    def test_existing_version_three_database_upgrades_without_losing_threads(self) -> None:
        target = Path(self.temp_dir.name) / "upgrade.sqlite3"
        connection = sqlite3.connect(target)
        connection.execute(
            """
            CREATE TABLE schema_migration (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for migration in sorted(migrations_dir().glob("00[1-3]_*.sql")):
            content = migration.read_bytes()
            connection.executescript(content.decode())
            connection.execute(
                "INSERT INTO schema_migration VALUES (?, ?, ?, ?)",
                (
                    int(migration.name[:3]),
                    migration.name,
                    hashlib.sha256(content).hexdigest(),
                    "2026-09-06T00:00:00+00:00",
                ),
            )
        connection.execute(
            """
            INSERT INTO person_profile(id, created_at, updated_at)
            VALUES ('local-user', '2026-09-06', '2026-09-06')
            """
        )
        for index in (1, 2):
            connection.execute(
                """
                INSERT INTO conversation(
                    id, person_id, channel, started_at, created_at, updated_at, kind
                ) VALUES (?, 'local-user', 'app', ?, ?, ?, 'juno')
                """,
                (f"thread-{index}", f"2026-09-0{index}", f"2026-09-0{index}", f"2026-09-0{index}"),
            )
            connection.execute(
                """
                INSERT INTO message(
                    id, conversation_id, role, content, occurred_at, created_at, updated_at
                ) VALUES (?, ?, 'user', ?, ?, ?, ?)
                """,
                (
                    f"message-{index}",
                    f"thread-{index}",
                    f"turn {index}",
                    f"2026-09-0{index}",
                    f"2026-09-0{index}",
                    f"2026-09-0{index}",
                ),
            )
        connection.execute(
            """
            INSERT INTO learning(
                id, person_id, domain, scope, claim, confidence, review_state,
                status, created_at, updated_at
            ) VALUES (
                'confirmed-learning', 'local-user', 'other', 'person',
                'A confirmed legacy belief', 0.8, 'confirmed',
                'active', '2026-09-01', '2026-09-01'
            )
            """
        )
        connection.commit()
        connection.close()

        result = initialize_database(target)

        self.assertEqual(
            [
                "004_behavioral_learning.sql",
                "005_browser_extension.sql",
                "006_conversation_compaction.sql",
                "007_opportunity_enrichment.sql",
                "008_job_external_identity.sql",
                "009_remove_extension_auth.sql",
                "010_application_answer_cache.sql",
            ],
            result["migrationsApplied"],
        )
        with sqlite3.connect(target) as upgraded:
            self.assertEqual(
                1,
                upgraded.execute("SELECT COUNT(*) FROM conversation WHERE kind = 'juno'").fetchone()[0],
            )
            self.assertEqual(2, upgraded.execute("SELECT COUNT(*) FROM message").fetchone()[0])
            lifecycle = upgraded.execute(
                "SELECT lifecycle_state FROM learning WHERE id = 'confirmed-learning'"
            ).fetchone()[0]
            self.assertEqual("confirmed", lifecycle)

    def test_tool_action_status_distinguishes_failures_and_approvals(self) -> None:
        self.assertEqual("failed", tool_action_status("Tool error: unavailable"))
        self.assertEqual("failed", tool_action_status('{"ok":false}'))
        self.assertEqual("pending", tool_action_status('{"approvalRequired":true}'))
        self.assertEqual("completed", tool_action_status('{"ok":true}'))

    def test_failed_migration_script_rolls_back_earlier_statements(self) -> None:
        target = Path(self.temp_dir.name) / "atomic.sqlite3"
        connection = sqlite3.connect(target)
        with self.assertRaises(sqlite3.OperationalError):
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                _execute_script(
                    connection,
                    """
                    CREATE TABLE should_rollback(id INTEGER PRIMARY KEY);
                    INSERT INTO should_rollback(id) VALUES (1);
                    INSERT INTO missing_table(id) VALUES (1);
                    """,
                )
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
        ).fetchone()
        connection.close()
        self.assertIsNone(table)


class StoredReplyTests(unittest.TestCase):
    """A reply written by an older build can carry a leaked reasoning tag."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_leaked_reasoning_is_not_replayed_out_of_storage(self) -> None:
        thread = ensure_thread(kind="juno", title="Juno")
        add_message(thread, "assistant", "</think>\n\nHere's what I found.")
        add_message(thread, "user", "What about </think> in my own text?")

        turns = list_messages(thread)

        self.assertEqual("Here's what I found.", turns[0]["content"])
        # The user's words are theirs, and are left exactly as typed.
        self.assertEqual("What about </think> in my own text?", turns[1]["content"])


if __name__ == "__main__":
    unittest.main()
