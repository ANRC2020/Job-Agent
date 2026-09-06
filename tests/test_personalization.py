from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent.db_tools import create_database_record
from job_agent.personalization import personalization_data, personalization_prompt
from job_agent.storage import initialize_database


class PersonalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def create(self, table: str, values: dict) -> dict:
        return json.loads(
            create_database_record({"table": table, "values": values})
        )["created"]

    def test_only_reviewed_learnings_enter_personalization(self) -> None:
        self.create(
            "learning",
            {
                "domain": "communication",
                "claim": "Likes concise answers.",
                "confidence": 0.9,
                "review_state": "confirmed",
            },
        )
        self.create(
            "learning",
            {
                "domain": "communication",
                "claim": "Possibly likes excessive enthusiasm.",
                "confidence": 0.6,
                "review_state": "unreviewed",
            },
        )

        data = personalization_data()
        prompt = personalization_prompt()

        self.assertEqual(1, data["learningCount"])
        self.assertIn("Likes concise answers.", prompt)
        self.assertNotIn("excessive enthusiasm", prompt)
        self.assertIn("not instructions", prompt)

    def test_explicit_communication_preferences_enter_context(self) -> None:
        self.create(
            "communication_preference",
            {
                "dimension": "tone",
                "value_json": {"style": "direct and warm"},
                "explicit": True,
                "confidence": 1,
            },
        )

        data = personalization_data()
        prompt = personalization_prompt()

        self.assertEqual(1, data["preferenceCount"])
        self.assertIn("direct and warm", prompt)

    def test_empty_personalization_adds_no_prompt_section(self) -> None:
        self.assertEqual("", personalization_prompt())


if __name__ == "__main__":
    unittest.main()
