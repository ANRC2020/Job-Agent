from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent.app import _model_messages
from job_agent.compaction import _normalized_summary, compact_conversation
from job_agent.context import build_turn_context
from job_agent.storage import (
    add_message,
    connect,
    create_conversation,
    initialize_database,
    latest_conversation_summary,
    list_messages,
)


def summary_response(text: str) -> dict:
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ]
    }


class ConversationCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()
        self.thread_id = create_conversation(kind="juno", title="Juno")

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def add_turns(self, count: int, *, prefix: str = "turn") -> list[str]:
        return [
            add_message(
                self.thread_id,
                "user" if index % 2 == 0 else "assistant",
                f"{prefix} {index}",
            )
            for index in range(count)
        ]

    def test_old_turns_become_an_append_only_source_linked_summary(self) -> None:
        first_messages = self.add_turns(25)
        first_summary = json.dumps(
            {
                "userStatements": [
                    {
                        "text": "User is exploring several career directions.",
                        "sourceMessageId": first_messages[0],
                    }
                ],
                "assistantCommitments": [],
                "openLoops": [],
            }
        )
        with patch(
            "job_agent.compaction._post",
            return_value=summary_response(first_summary),
        ):
            first = compact_conversation(self.thread_id)

        self.assertIsNotNone(first)
        self.assertEqual(12, first["source_message_count"])
        self.assertEqual(first_messages[0], first["source_start_message_id"])
        self.assertEqual(first_messages[11], first["source_end_message_id"])
        self.assertEqual(13, len(_model_messages(self.thread_id)))

        self.add_turns(8, prefix="new")
        second_summary = json.dumps(
            {
                "userStatements": [
                    {
                        "text": "User values unconventional problem solving.",
                        "sourceMessageId": first_messages[0],
                    }
                ],
                "assistantCommitments": [],
                "openLoops": [],
            }
        )
        with patch(
            "job_agent.compaction._post",
            return_value=summary_response(second_summary),
        ) as post:
            second = compact_conversation(self.thread_id)

        self.assertEqual(20, second["source_message_count"])
        self.assertEqual(first["source_start_message_id"], second["source_start_message_id"])
        self.assertIn(
            "User is exploring several career directions.",
            post.call_args.args[0]["input"][1]["content"],
        )
        with connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM conversation_summary WHERE conversation_id = ?",
                (self.thread_id,),
            ).fetchone()[0]
        self.assertEqual(2, count)

    def test_summary_is_in_context_but_not_promoted_to_personal_memory(self) -> None:
        messages = self.add_turns(25)
        summary = json.dumps(
            {
                "userStatements": [],
                "assistantCommitments": [
                    {
                        "text": "Assistant suggested product engineering.",
                        "status": "proposed",
                        "sourceMessageId": messages[1],
                    }
                ],
                "openLoops": [],
            }
        )
        with patch(
            "job_agent.compaction._post",
            return_value=summary_response(summary),
        ):
            compact_conversation(self.thread_id)

        block = build_turn_context(
            conversation_id=self.thread_id,
            task="What were we discussing?",
        )

        self.assertIn("Assistant suggested product engineering.", block)
        self.assertIn('"conversationSummary"', block)
        with connect() as connection:
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM profile_fact").fetchone()[0],
            )

    def test_compaction_failure_leaves_messages_and_summary_state_untouched(self) -> None:
        self.add_turns(25)
        with patch(
            "job_agent.compaction._post",
            side_effect=RuntimeError("model unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "model unavailable"):
                compact_conversation(self.thread_id)

        self.assertIsNone(latest_conversation_summary(self.thread_id))
        self.assertEqual(25, len(list_messages(self.thread_id)))

    def test_invalid_model_summary_falls_back_to_source_linked_user_words(self) -> None:
        messages = [
            {"id": "user-1", "role": "user", "content": "I value unusual ways of thinking."},
            {
                "id": "assistant-1",
                "role": "assistant",
                "content": "Your resume cannot be accessed.",
            },
        ]

        summary = json.loads(
            _normalized_summary("The user seems confused.", messages, None)
        )

        self.assertEqual(
            "I value unusual ways of thinking.",
            summary["userStatements"][0]["text"],
        )
        self.assertNotIn("resume cannot", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
