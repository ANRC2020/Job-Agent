from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent.learning_extraction import extract_turn_learning
from job_agent.storage import (
    connect,
    ensure_thread,
    initialize_database,
    add_message,
)


class TurnLearningExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()
        self.thread_id = ensure_thread(kind="juno", title="Juno")

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_direct_fact_and_grounded_hypothesis_are_persisted_separately(self) -> None:
        user_message = (
            "I really like collecting different lenses and cracking the case in unexpected ways."
        )
        message_id = add_message(self.thread_id, "user", user_message)
        extracted = {
            "facts": [
                {
                    "category": "preference",
                    "evidence": (
                        "I really like collecting different lenses and cracking the case "
                        "in unexpected ways."
                    ),
                }
            ],
            "hypotheses": [
                {
                    "claim": "They may prefer investigative work with room for unconventional approaches.",
                    "domain": "job_preference",
                    "evidence": "cracking the case in unexpected ways",
                }
            ],
        }

        with patch("job_agent.learning_extraction.complete_json", return_value=extracted):
            result = extract_turn_learning(
                conversation_id=self.thread_id,
                user_message_id=message_id,
                user_message=user_message,
                assistant_message="That may point toward investigative technical work.",
            )

        self.assertEqual({"facts": 1, "hypotheses": 1}, result)
        with connect() as connection:
            fact = connection.execute("SELECT * FROM profile_fact").fetchone()
            learning = connection.execute("SELECT * FROM learning").fetchone()
            evidence = connection.execute("SELECT * FROM learning_evidence").fetchone()
        self.assertEqual(user_message, fact["statement"])
        self.assertIsNotNone(fact["confirmed_at"])
        self.assertEqual("unreviewed", learning["review_state"])
        self.assertEqual("message", evidence["entity_type"])
        self.assertEqual(message_id, evidence["entity_id"])

    def test_unsupported_model_outputs_are_discarded(self) -> None:
        user_message = "I am unsure which role direction is right for me."
        message_id = add_message(self.thread_id, "user", user_message)
        extracted = {
            "facts": [{"category": "direction", "evidence": "I prefer management roles"}],
            "hypotheses": [
                {
                    "claim": "They prefer management.",
                    "domain": "job_preference",
                    "evidence": "management roles",
                }
            ],
        }

        with patch("job_agent.learning_extraction.complete_json", return_value=extracted):
            result = extract_turn_learning(
                conversation_id=self.thread_id,
                user_message_id=message_id,
                user_message=user_message,
                assistant_message="We can explore that without committing.",
            )

        self.assertEqual({"facts": 0, "hypotheses": 0}, result)
        with connect() as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM profile_fact").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM learning").fetchone()[0])

    def test_duplicate_direct_fact_is_not_inserted_twice(self) -> None:
        user_message = "I prefer remote roles with occasional office time."
        extracted = {
            "facts": [{"category": "preference", "evidence": user_message}],
            "hypotheses": [],
        }
        with patch("job_agent.learning_extraction.complete_json", return_value=extracted):
            for _ in range(2):
                message_id = add_message(self.thread_id, "user", user_message)
                extract_turn_learning(
                    conversation_id=self.thread_id,
                    user_message_id=message_id,
                    user_message=user_message,
                    assistant_message="I'll keep that in mind.",
                )

        with connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM profile_fact").fetchone()[0]
        self.assertEqual(1, count)


if __name__ == "__main__":
    unittest.main()
