from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import opportunities
from job_agent.strategy import strategy_summary
from job_agent.storage import initialize_database


class StrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def save(self, suffix: str) -> str:
        return opportunities.save_opportunity(
            title=f"Senior Product Writer {suffix}",
            company=f"Company {suffix}",
            source_url=f"https://example.test/{suffix}",
        )["id"]

    def test_rates_are_withheld_until_the_sample_is_large_enough(self) -> None:
        process_id = self.save("one")
        opportunities.set_stage(process_id, "applied")

        summary = strategy_summary()

        self.assertFalse(summary["sample"]["enoughForRates"])
        self.assertEqual([], summary["findings"])

    def test_funnel_summary_uses_stage_history_and_shows_evidence(self) -> None:
        ids = [self.save(str(index)) for index in range(3)]
        for process_id in ids:
            opportunities.set_stage(process_id, "applied")
        opportunities.set_stage(ids[0], "interviewing")
        opportunities.set_stage(ids[1], "interviewing")
        opportunities.set_stage(ids[0], "offer")

        summary = strategy_summary()

        self.assertTrue(summary["sample"]["enoughForRates"])
        self.assertEqual(3, summary["funnel"]["applied"])
        self.assertEqual(2, summary["funnel"]["response"])
        self.assertEqual(1, summary["funnel"]["offer"])
        self.assertEqual("response_rate", summary["findings"][0]["kind"])
        self.assertEqual(set(ids), set(summary["findings"][0]["processIds"]))


if __name__ == "__main__":
    unittest.main()
