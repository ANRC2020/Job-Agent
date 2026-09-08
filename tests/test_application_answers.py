from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent.application_answers import (
    cached_answers,
    quick_answers,
    remember_answers,
    remember_user_answers,
)
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
                b"linkedin.com/in/abbas-siddiqui\n"
                b"https://portfolio.example.test\n"
                b"EDUCATION\nExample University August 2022 - May 2024\n"
                b"Master of Science in Data Science GPA: 3.9\n"
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
                field("website", "Website"),
                field("school", "School"),
                field("degree", "Degree"),
                field("discipline", "Discipline"),
                field("end-year", "End date year", "number"),
            ]
        )

        values = {item["fieldId"]: item["value"] for item in answers}
        self.assertEqual("Abbas", values["first"])
        self.assertEqual("Siddiqui", values["last"])
        self.assertEqual("abbas@example.test", values["email"])
        self.assertIn("415", values["phone"])
        self.assertIn("linkedin.com/in/abbas-siddiqui", values["linkedin"])
        self.assertEqual("https://portfolio.example.test", values["website"])
        self.assertEqual("Example University", values["school"])
        self.assertEqual("Master of Science", values["degree"])
        self.assertEqual("Data Science", values["discipline"])
        self.assertEqual("2024", values["end-year"])

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

    def test_explicit_reusable_answers_are_remembered_but_role_drafts_are_not(self) -> None:
        fields = [
            field("authorization", "Are you legally authorized to work?"),
            field("motivation", "Why do you want this role?", "textarea"),
        ]
        remember_user_answers(
            fields,
            [
                {"fieldId": "authorization", "value": "Yes"},
                {"fieldId": "motivation", "value": "Because this role is a fit."},
            ],
        )

        lookup = [
            field("authorization", "Are you legally authorized to work?", "select"),
            fields[1],
        ]
        lookup[0]["options"] = ["Yes", "No"]
        cached = cached_answers(lookup)

        self.assertEqual(["authorization"], [item["fieldId"] for item in cached])
        self.assertEqual("Yes", cached[0]["value"])
        self.assertEqual("user", cached[0]["source"])


if __name__ == "__main__":
    unittest.main()
