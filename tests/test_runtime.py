from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import call, patch

from job_agent.runtime import start_runtime, switch_model


def result(code: int = 0, stdout: str = "ok", stderr: str = ""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class RuntimeStartupTests(unittest.TestCase):
    @patch("job_agent.runtime.start_runtime", return_value="session")
    @patch("job_agent.setup.ensure_model")
    @patch("job_agent.runtime.lms_bin", return_value=Path("/tmp/lms"))
    @patch("job_agent.runtime.lms", return_value=result())
    @patch("job_agent.runtime.save_model")
    @patch("job_agent.runtime.load_config")
    def test_model_upgrade_uses_visible_resumable_download(
        self, config, save, _lms, _binary, ensure, _start
    ) -> None:
        config.return_value.model = "qwen/qwen3.5-4b"

        self.assertEqual("session", switch_model("qwen/qwen3.5-9b"))

        save.assert_called_once_with("qwen/qwen3.5-9b")
        ensure.assert_called_once()

    @patch("job_agent.runtime._wait_for", return_value=True)
    @patch("job_agent.runtime.server_reachable", return_value=True)
    @patch("job_agent.runtime.loaded_context_length", return_value=16384)
    @patch("job_agent.runtime.lms_bin", return_value=Path("/tmp/lms"))
    @patch(
        "job_agent.runtime.status",
        return_value={"daemonRunning": True, "modelLoaded": True},
    )
    @patch("job_agent.runtime.lms", return_value=result())
    def test_loaded_model_is_reconfigured_to_clovers_context(
        self, lms, _status, _binary, _context, _reachable, _wait
    ) -> None:
        start_runtime(log=lambda _message: None)

        self.assertIn(call("unload", "--all"), lms.call_args_list)
        self.assertIn(
            call(
                "load",
                "qwen/qwen3.5-4b",
                "-c",
                "16384",
                "--identifier",
                "clover-juno",
            ),
            lms.call_args_list,
        )

    @patch("job_agent.runtime._wait_for", return_value=True)
    @patch("job_agent.runtime.server_reachable", return_value=False)
    @patch("job_agent.runtime.loaded_context_length", return_value=None)
    @patch("job_agent.runtime.lms_bin", return_value=Path("/tmp/lms"))
    @patch(
        "job_agent.runtime.status",
        return_value={"daemonRunning": False, "modelLoaded": False},
    )
    @patch("job_agent.runtime.lms", return_value=result())
    def test_start_waits_for_every_service_and_forces_the_configured_port(
        self, lms, _status, _binary, _context, _reachable, wait
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
