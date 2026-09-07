from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import onboarding
from job_agent.person import profile_overview
from job_agent.storage import initialize_database, list_progress_events


class OnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_juno_introduces_herself_before_asking_anything(self) -> None:
        state = onboarding.onboarding_state()

        self.assertFalse(state["complete"])
        self.assertEqual("name", state["step"]["id"])
        self.assertIn("I'm Juno", " ".join(state["step"]["say"]))
        self.assertFalse(state["step"]["canFinishEarly"])

    def test_the_name_is_used_in_the_next_question(self) -> None:
        state = onboarding.answer("name", "Sam")

        self.assertEqual("Sam", state["preferredName"])
        self.assertIn("Sam", " ".join(state["step"]["say"]))

    def test_answers_become_readable_profile_facts(self) -> None:
        onboarding.answer("name", "Sam")
        onboarding.answer("situation", "I'm between jobs")
        onboarding.answer("resume", "", skipped=True)
        onboarding.answer("direction", "Customer education, remote")

        sections = {section["id"]: section for section in profile_overview()["sections"]}

        self.assertIn("I'm between jobs", [item["text"] for item in sections["context"]["items"]])
        self.assertIn("Customer education, remote", [item["text"] for item in sections["direction"]["items"]])

    def test_skipping_stores_nothing_but_still_advances(self) -> None:
        onboarding.answer("name", "Sam")
        state = onboarding.answer("situation", "", skipped=True)

        self.assertEqual("resume", state["step"]["id"])
        self.assertEqual([], profile_overview()["sections"])

    def test_juno_offers_to_stop_early_once_she_knows_enough(self) -> None:
        onboarding.answer("name", "Sam")
        onboarding.answer("situation", "Between jobs")
        onboarding.answer("resume", "", skipped=True)
        state = onboarding.answer("direction", "Customer education")

        self.assertTrue(state["step"]["canFinishEarly"])

        finished = onboarding.finish()

        self.assertTrue(finished["complete"])
        self.assertIsNone(finished["step"])
        self.assertIn("That's enough for me to start.", finished["closing"][0])

    def test_answering_every_question_completes_onboarding(self) -> None:
        for step in onboarding.STEPS:
            state = onboarding.answer(step["id"], "", skipped=True)

        self.assertTrue(state["complete"])

    def test_finishing_is_recorded_as_progress_exactly_once(self) -> None:
        onboarding.finish()
        onboarding.finish()

        headlines = [event["headline"] for event in list_progress_events()]

        self.assertEqual(["Told Juno what you're working toward"], headlines)

    def test_an_unknown_step_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            onboarding.answer("favourite_colour", "green")


if __name__ == "__main__":
    unittest.main()
