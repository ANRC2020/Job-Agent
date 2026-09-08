from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent.application_answers import cached_answers, quick_answers, remember_answers
from job_agent.documents import save_document
from job_agent.storage import DEFAULT_PERSON_ID, initialize_database, transaction, utc_now


def field(field_id: str, label: str, field_type: str = "text") -> dict:
    return {
        "fieldId": field_id,
        "label": label,
        "name": field_id,
        "type": field_type,
        "currentValue": "",
        "options": [],
    }


class FastApplicationAnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()
        with transaction() as connection:
            connection.execute(
                """
                UPDATE person_profile
                SET display_name = ?, preferred_name = ?, email = ?, updated_at = ?
                WHERE id = ?
                """,
                ("Abbas", "Abbas", "abbas@example.test", utc_now(), DEFAULT_PERSON_ID),
            )
        save_document(
            filename="resume.txt",
            data=(
                b"Abbas Siddiqui\n+1 (415) 555-0199\n"
                b"https://www.linkedin.com/in/abbas-siddiqui\n"
            ),
        )

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_common_identity_fields_are_resolved_without_a_model(self) -> None:
        answers = quick_answers(
            [
                field("first", "First name"),
                field("last", "Last name"),
                field("email", "Email address"),
                field("phone", "Mobile phone number"),
                field("linkedin", "LinkedIn profile"),
            ]
        )

        values = {item["fieldId"]: item["value"] for item in answers}
        self.assertEqual("Abbas", values["first"])
        self.assertEqual("Siddiqui", values["last"])
        self.assertEqual("abbas@example.test", values["email"])
        self.assertIn("415", values["phone"])
        self.assertIn("linkedin.com/in/abbas-siddiqui", values["linkedin"])

    def test_only_verified_identity_answers_enter_the_reuse_cache(self) -> None:
        fields = [
            field("phone", "Phone number"),
            field("essay", "Why do you want this job?", "textarea"),
        ]
        remember_answers(
            fields,
            [
                {
                    "fieldId": "phone",
                    "value": "415-555-0199",
                    "source": "resume",
                    "confidence": 0.98,
                },
                {
                    "fieldId": "essay",
                    "value": "Role-specific answer",
                    "source": "resume",
                    "confidence": 0.99,
                },
            ],
        )

        cached = cached_answers(fields)

        self.assertEqual(["phone"], [item["fieldId"] for item in cached])
        self.assertEqual("415-555-0199", cached[0]["value"])


if __name__ == "__main__":
    unittest.main()
