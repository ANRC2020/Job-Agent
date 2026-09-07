from __future__ import annotations

import unittest
from unittest.mock import patch

from job_agent import download_progress
from job_agent.readiness import readiness


class DownloadProgressTests(unittest.TestCase):
    def tearDown(self) -> None:
        download_progress.finish()

    def test_percentage_output_updates_the_visible_meter(self) -> None:
        download_progress.begin("qwen/qwen3.5-9b", 1, 4)
        download_progress.consume("\x1b[0K Downloading model… 42.6%")

        state = download_progress.snapshot()
        self.assertTrue(state["active"])
        self.assertEqual("downloading", state["phase"])
        self.assertEqual(42.6, state["percent"])
        self.assertEqual(1, state["attempt"])

    def test_downloaded_and_total_sizes_are_converted_to_percentage(self) -> None:
        download_progress.begin("qwen/qwen3.5-9b", 2, 4)
        download_progress.consume("Downloaded 1.5 GB / 3.0 GB")

        self.assertEqual(50.0, download_progress.snapshot()["percent"])

    @patch(
        "job_agent.readiness.status",
        return_value={
            "ready": False,
            "cliInstalled": True,
            "modelDownloaded": False,
        },
    )
    def test_readiness_exposes_progress_without_a_duplicate_setup_button(self, _status) -> None:
        download_progress.begin("qwen/qwen3.5-9b", 1, 4)
        download_progress.consume("Downloading 25%")

        state = readiness()
        self.assertEqual(25.0, state["download"]["percent"])
        self.assertIsNone(state["recovery"])


if __name__ == "__main__":
    unittest.main()
