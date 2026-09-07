from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import call, patch

from job_agent.runtime import start_runtime


def result(code: int = 0, stdout: str = "ok", stderr: str = ""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class RuntimeStartupTests(unittest.TestCase):
    @patch("job_agent.runtime._wait_for", return_value=True)
    @patch("job_agent.runtime.server_reachable", return_value=False)
    @patch("job_agent.runtime.lms_bin", return_value=Path("/tmp/lms"))
    @patch(
        "job_agent.runtime.status",
        return_value={"daemonRunning": False, "modelLoaded": False},
    )
    @patch("job_agent.runtime.lms", return_value=result())
    def test_start_waits_for_every_service_and_forces_the_configured_port(
        self, lms, _status, _binary, _reachable, wait
    ) -> None:
        session = start_runtime(log=lambda _message: None)

        self.assertTrue(session.started_daemon)
        self.assertTrue(session.loaded_model)
        self.assertTrue(session.started_server)
        self.assertIn(
            call("server", "start", "--port", "1234"),
            lms.call_args_list,
        )
        self.assertEqual(3, wait.call_count)

    @patch("job_agent.runtime.lms_bin", return_value=Path("/tmp/lms"))
    @patch(
        "job_agent.runtime.status",
        return_value={"daemonRunning": False, "modelLoaded": False},
    )
    @patch("job_agent.runtime.lms", return_value=result(1, "", "daemon failed"))
    def test_daemon_failure_is_reported_instead_of_opening_a_broken_app(
        self, _lms, _status, _binary
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "daemon failed"):
            start_runtime(log=lambda _message: None)

    @patch("job_agent.runtime._wait_for", return_value=True)
    @patch("job_agent.runtime.lms_bin", return_value=Path("/tmp/lms"))
    @patch(
        "job_agent.runtime.status",
        return_value={"daemonRunning": True, "modelLoaded": False},
    )
    @patch("job_agent.runtime.lms", return_value=result(1, "", "model failed"))
    def test_model_failure_is_not_mistaken_for_readiness(
        self, _lms, _status, _binary, _wait
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            start_runtime(log=lambda _message: None)


if __name__ == "__main__":
    unittest.main()
