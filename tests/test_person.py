from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent.agent_tools import tool_note_observation, tool_save_experience
from job_agent.person import (
    context_block,
    dismiss_fact,
    profile_overview,
    remember_fact,
    review_observation,
    set_names,
)
from job_agent.personalization import personalization_prompt
from job_agent.storage import initialize_database


class ProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def sections(self) -> dict:
        return {section["id"]: section for section in profile_overview()["sections"]}

    def test_an_unknown_person_reads_as_empty_not_broken(self) -> None:
        overview = profile_overview()

        self.assertTrue(overview["isEmpty"])
        self.assertEqual([], overview["sections"])
        self.assertEqual("", context_block())

    def test_facts_are_grouped_into_sections_a_person_can_read(self) -> None:
        remember_fact(statement="Wants customer education work", category="direction")
        remember_fact(statement="Remote only", category="constraint")
        remember_fact(statement="Strong at technical writing", category="skill")
        remember_fact(statement="Tired of ghosted applications", category="frustration")

        sections = self.sections()

        self.assertEqual("What you're looking for", sections["direction"]["label"])
        self.assertEqual("What has to be true", sections["constraint"]["label"])
        self.assertEqual("Strengths and skills", sections["strength"]["label"])
        self.assertEqual("What you'd rather avoid", sections["friction"]["label"])

    def test_categories_juno_invents_still_land_somewhere_sensible(self) -> None:
        remember_fact(statement="Needs a salary floor", category="salary_requirement")
        remember_fact(statement="Something unclassifiable", category="misc")

        sections = self.sections()

        self.assertIn("Needs a salary floor", [item["text"] for item in sections["constraint"]["items"]])
        self.assertIn("Something unclassifiable", [item["text"] for item in sections["other"]["items"]])

    def test_a_correction_retires_the_detail(self) -> None:
        remember_fact(statement="Wants to manage people", category="direction")
        fact_id = self.sections()["direction"]["items"][0]["id"]

        dismiss_fact(fact_id)

        self.assertEqual([], profile_overview()["sections"])

    def test_dismissing_something_juno_no_longer_has_says_so(self) -> None:
        with self.assertRaises(ValueError):
            dismiss_fact("not-a-real-id")

    def test_junos_inferences_show_as_hunches_until_confirmed(self) -> None:
        tool_note_observation({"claim": "You may prefer smaller teams", "confidence": 0.6})

        observations = profile_overview()["observations"]

        self.assertEqual(1, len(observations))
        self.assertFalse(observations[0]["confirmed"])
        self.assertEqual("", personalization_prompt())

    def test_confirming_a_hunch_lets_it_shape_junos_behavior(self) -> None:
        tool_note_observation({"claim": "You prefer smaller teams", "confidence": 0.6})
        observation_id = profile_overview()["observations"][0]["id"]

        review_observation(observation_id, "confirmed")

        self.assertTrue(profile_overview()["observations"][0]["confirmed"])
        self.assertIn("smaller teams", personalization_prompt())

    def test_rejecting_a_hunch_removes_it_entirely(self) -> None:
        tool_note_observation({"claim": "You want to leave the industry", "confidence": 0.4})
        observation_id = profile_overview()["observations"][0]["id"]

        review_observation(observation_id, "rejected")

        self.assertEqual([], profile_overview()["observations"])

    def test_only_confirm_or_reject_are_accepted_verdicts(self) -> None:
        tool_note_observation({"claim": "Anything", "confidence": 0.5})
        observation_id = profile_overview()["observations"][0]["id"]

        with self.assertRaises(ValueError):
            review_observation(observation_id, "maybe")

    def test_experience_and_skills_come_from_the_resume(self) -> None:
        tool_save_experience(
            {
                "title": "Support Lead",
                "organization": "Northwind",
                "startDate": "2019",
                "endDate": "2024",
                "skills": ["Zendesk", "SQL"],
            }
        )

        overview = profile_overview()

        self.assertEqual("Support Lead", overview["experiences"][0]["title"])
        self.assertEqual(["Zendesk", "SQL"], overview["skills"])

    def test_the_same_role_is_not_added_twice(self) -> None:
        for _ in range(2):
            tool_save_experience({"title": "Support Lead", "organization": "Northwind"})

        self.assertEqual(1, len(profile_overview()["experiences"]))

    def test_context_block_labels_itself_as_data_not_instructions(self) -> None:
        set_names(preferred_name="Sam")
        remember_fact(statement="Remote only", category="constraint")

        block = context_block()

        self.assertIn("Sam", block)
        self.assertIn("Remote only", block)
        self.assertIn("not instructions", block)


if __name__ == "__main__":
    unittest.main()
