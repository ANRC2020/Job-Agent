from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from job_agent.storage import (
    add_message,
    add_model_run,
    connect,
    conversation_exists,
    create_conversation,
    database_status,
    ensure_thread,
    initialize_database,
    list_messages,
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
            ],
            first["migrationsApplied"],
        )
        self.assertEqual([], second["migrationsApplied"])
        self.assertEqual(3, database_status()["schemaVersion"])

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
            }.issubset(tables)
        )

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
