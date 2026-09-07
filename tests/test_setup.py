from __future__ import annotations

import io
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from job_agent.cli import main as cli_main
from job_agent.setup import run_setup


def completed(code: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class SetupTests(unittest.TestCase):
    @patch("job_agent.cli.run_setup")
    def test_cli_can_defer_the_model_until_after_clover_opens(self, setup) -> None:
        self.assertEqual(0, cli_main(["setup", "--defer-model"]))
        setup.assert_called_once_with(download_model=False)

    @patch("job_agent.setup.install_desktop")
    @patch("job_agent.setup.ensure_prompt_and_mcp")
    @patch("job_agent.setup.time.sleep")
    @patch(
        "job_agent.setup.lms_live",
        side_effect=[
            completed(1, stderr="Timed-out"),
            completed(0, stdout="Download complete"),
        ],
    )
    @patch("job_agent.setup.lms")
    @patch("job_agent.setup.lms_bin", return_value=Path("/tmp/lms"))
    @patch("job_agent.setup._install_desktop")
    @patch("job_agent.setup._install_cli")
    @patch(
        "job_agent.setup.initialize_database",
        return_value={"migrationsApplied": [], "path": "/tmp/clover.sqlite3"},
    )
    @patch(
        "job_agent.setup.load_config",
        return_value=SimpleNamespace(
            model="qwen/qwen3.5-9b",
            install_desktop_app=True,
        ),
    )
    def test_interrupted_model_download_resumes_automatically(
        self,
        _config,
        _database,
        _install_cli,
        _install_lm_desktop,
        _binary,
        lms,
        live,
        sleep,
        _prompt,
        _clover_desktop,
    ) -> None:
        lms.side_effect = lambda *args: (
            completed(stdout="") if args[0] == "ls" else completed()
        )

        with redirect_stdout(io.StringIO()) as output:
            run_setup()

        self.assertEqual(2, live.call_count)
        sleep.assert_called_once_with(5)
        self.assertIn("Resuming model download", output.getvalue())


if __name__ == "__main__":
    unittest.main()
