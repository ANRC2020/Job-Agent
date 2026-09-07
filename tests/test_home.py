from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import opportunities as opp
from job_agent.home import home_overview
from job_agent.person import remember_fact
from job_agent.storage import initialize_database


class HomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def save(self, title: str, *, stage: str = "interested", location=None) -> str:
        return opp.save_opportunity(
            title=title,
            company=f"{title} Co",
            source_url=f"https://example.com/{title.replace(' ', '-')}",
            stage=stage,
            location=location or {},
        )["id"]

    def test_a_brand_new_user_is_invited_rather_than_shown_an_empty_screen(self) -> None:
        data = home_overview()

        self.assertEqual(0, data["totalOpportunities"])
        self.assertIn("only just met", data["observation"]["text"])
        self.assertEqual("juno", data["observation"]["action"]["kind"])

    def test_someone_juno_knows_is_asked_for_a_role_instead(self) -> None:
        remember_fact(statement="Wants customer education work", category="direction")

        data = home_overview()

        self.assertIn("Bring me one", data["observation"]["text"])
        self.assertEqual("add", data["observation"]["action"]["kind"])

    def test_an_interview_in_motion_outranks_everything_else(self) -> None:
        self.save("Support Manager", stage="suggested")
        interviewing = self.save("Docs Lead", stage="interviewing")

        data = home_overview()

        self.assertIn("interview process moving", data["observation"]["text"])
        self.assertEqual(interviewing, data["observation"]["action"]["id"])

    def test_juno_notices_saved_roles_drifting_from_a_stated_preference(self) -> None:
        remember_fact(statement="Remote work matters to me", category="constraint")
        self.save("Hybrid Role", location={"arrangement": "hybrid", "city": "Austin"})
        self.save("Onsite Role", location={"city": "Denver"})

        data = home_overview()

        self.assertIn("remote work matters", data["observation"]["text"])
        self.assertIn("2 of the roles", data["observation"]["text"])
        self.assertEqual("juno", data["observation"]["action"]["kind"])

    def test_matching_remote_roles_raise_no_contradiction(self) -> None:
        remember_fact(statement="Remote work matters to me", category="constraint")
        self.save("Remote Role", location={"remote": True})

        # With nothing worth remarking on, Juno stays quiet rather than filling space.
        observation = home_overview()["observation"]

        self.assertTrue(observation is None or "remote work matters" not in observation["text"])

    def test_several_saved_roles_with_no_application_started_is_named_gently(self) -> None:
        for title in ("One", "Two", "Three"):
            self.save(title)

        text = home_overview()["observation"]["text"]

        self.assertIn("3 roles saved", text)
        self.assertIn("Starting one is usually easier", text)

    def test_pending_suggestions_frame_passing_as_a_real_choice(self) -> None:
        self.save("Support Manager", stage="suggested")

        text = home_overview()["observation"]["text"]

        self.assertIn("1 role is waiting", text)
        self.assertIn("Passing on one is a decision too", text)

    def test_the_single_next_action_points_at_a_live_opportunity(self) -> None:
        process_id = self.save("Docs Lead", stage="applying")

        data = home_overview()

        self.assertIsNone(data["observation"])
        self.assertEqual(process_id, data["nextAction"]["action"]["id"])
        self.assertIn("Docs Lead", data["nextAction"]["context"])

    def test_home_does_not_ask_for_the_same_thing_twice(self) -> None:
        # Juno's note and the "one thing to do" card would both point at this
        # interview, so only her own voice should carry it.
        self.save("Docs Lead", stage="interviewing")

        data = home_overview()

        self.assertIn("interview process moving", data["observation"]["text"])
        self.assertEqual("Prepare with Juno", data["observation"]["action"]["label"])
        self.assertIsNone(data["nextAction"])

    def test_an_empty_home_offers_one_way_in_not_three(self) -> None:
        remember_fact(statement="Wants technical writing work", category="direction")

        data = home_overview()

        self.assertEqual("add", data["observation"]["action"]["kind"])
        self.assertIsNone(data["nextAction"])

    def test_progress_appears_without_any_target_to_measure_against(self) -> None:
        process_id = self.save("Docs Lead", stage="suggested")
        opp.set_stage(process_id, "closed", outcome="not_a_fit")

        data = home_overview()

        self.assertEqual(1, len(data["progress"]))
        self.assertIn("wasn't the right fit", data["progress"][0]["headline"])
        self.assertNotIn("goal", data)
        self.assertNotIn("streak", data)


if __name__ == "__main__":
    unittest.main()
