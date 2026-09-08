from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from job_agent.app import _bind_server, _model_messages, _supervise_runtime
from job_agent.autonomy import list_pending_actions, queue_approval
from job_agent.storage import initialize_database


class RuntimeSupervisorTests(unittest.TestCase):
    @patch("job_agent.app.start_runtime", return_value="repaired-session")
    @patch(
        "job_agent.app.runtime_ready",
        side_effect=[True, False],
    )
    @patch("job_agent.app.ensure_model")
    def test_server_drop_is_repaired_while_clover_stays_open(
        self, ensure, _status, start
    ) -> None:
        stop = threading.Event()
        holder: dict = {"session": None}
        start.side_effect = lambda: (stop.set(), "repaired-session")[1]

        _supervise_runtime(stop, holder, health_interval=0, retry_base=0)

        ensure.assert_called_once()
        start.assert_called_once()
        self.assertEqual("repaired-session", holder["session"])

    @patch("job_agent.app.runtime_ready", return_value=False)
    @patch("job_agent.app.ensure_model")
    def test_transient_start_failure_retries_without_repeating_setup(
        self, ensure, _status
    ) -> None:
        stop = threading.Event()
        holder: dict = {"session": None}
        logs: list[str] = []
        attempts = 0

        def start() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary failure")
            stop.set()
            return "healthy-session"

        with patch("job_agent.app.start_runtime", side_effect=start):
            _supervise_runtime(
                stop,
                holder,
                health_interval=0,
                retry_base=0,
                log=logs.append,
            )

        ensure.assert_called_once()
        self.assertEqual(2, attempts)
        self.assertEqual("healthy-session", holder["session"])
        self.assertTrue(any("retrying" in message for message in logs))


class AppApiTests(unittest.TestCase):
    @patch("job_agent.app.list_messages")
    def test_model_history_starts_with_user_and_alternates_roles(self, messages) -> None:
        messages.return_value = [
            {"role": "assistant", "content": "orphaned reply"},
            {"role": "user", "content": "first failed request"},
            {"role": "user", "content": "second request"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "sure"},
        ]

        history = _model_messages("thread")

        self.assertEqual(["user", "assistant", "user"], [item["role"] for item in history])
        self.assertIn("first failed request\n\nsecond request", history[0]["content"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()
        self.server, _ = _bind_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.env.stop()
        self.temp_dir.cleanup()

    def get(self, path: str) -> dict:
        with urlopen(self.base + path, timeout=5) as response:
            return json.loads(response.read())

    def post(self, path: str, payload: dict) -> str:
        request = Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return response.read().decode()

    @patch("job_agent.app.readiness", return_value={"ready": True})
    def test_chat_persists_reply_and_action_transparency(self, _readiness) -> None:
        result = {
            "type": "done",
            "content": "You have one role worth looking at.",
            "model": "test-model",
            "tools": [
                {
                    "tool": "get_opportunities",
                    "activity": "Looking over your opportunities",
                    "arguments": {},
                    "result": '{"total":1}',
                }
            ],
        }
        with patch("job_agent.app.chat_stream", return_value=iter([result])):
            stream = self.post("/api/chat", {"message": "What should I focus on?"})

        self.assertIn('"type": "end"', stream)
        self.assertIn('"actions":', stream)
        thread = self.get("/api/thread")
        self.assertEqual(["user", "assistant"], [item["role"] for item in thread["messages"]])
        self.assertEqual("get_opportunities", thread["actions"][0]["tool_name"])

    @patch(
        "job_agent.app.readiness",
        return_value={
            "ready": False,
            "state": "installing",
            "headline": "Juno is still setting herself up",
        },
    )
    def test_chat_is_locked_without_persisting_a_message_during_download(
        self, _readiness
    ) -> None:
        request = Request(
            self.base + "/api/chat",
            data=json.dumps({"message": "Hello"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as unavailable:
            urlopen(request, timeout=5)
        self.assertEqual(503, unavailable.exception.code)
        self.assertEqual([], self.get("/api/thread")["messages"])

    @patch("job_agent.app.technical_status", return_value={"ready": True})
    def test_strategy_and_settings_endpoints_are_available(self, _status) -> None:
        strategy = self.get("/api/strategy")
        settings = self.get("/api/settings")

        self.assertIn("funnel", strategy)
        self.assertEqual([], settings["pendingActions"])

    def test_opportunity_api_returns_enriched_listing_and_apply_link(self) -> None:
        created = json.loads(
            self.post(
                "/api/opportunities",
                {
                    "role": "ML Engineer",
                    "company": "Acme",
                    "sourceUrl": "https://jobs.example.test/roles/1",
                    "applyUrl": "https://jobs.example.test/roles/1/apply",
                    "sourceKind": "company_careers",
                    "workplaceType": "Remote",
                    "department": "AI",
                    "requirements": ["Python"],
                    "verificationStatus": "verified",
                    "lastVerifiedAt": "2026-09-07T00:00:00+00:00",
                },
            )
        )

        detail = self.get(f"/api/opportunities/{created['id']}")

        self.assertEqual("https://jobs.example.test/roles/1/apply", detail["applyUrl"])
        self.assertEqual("verified", detail["verificationStatus"])
        self.assertEqual(["Python"], detail["requirements"])

    def test_extension_origins_cannot_call_clover(self) -> None:
        generic = Request(
            self.base + "/api/settings",
            headers={"Origin": "chrome-extension://test-extension"},
        )
        with self.assertRaises(HTTPError) as rejected:
            urlopen(generic, timeout=5)
        self.assertEqual(403, rejected.exception.code)

    @patch("job_agent.app.managed_browser")
    @patch("job_agent.app.readiness", return_value={"ready": True})
    def test_guided_application_starts_in_managed_browser(
        self,
        _readiness,
        browser,
    ) -> None:
        browser.start.return_value = {
            "running": True,
            "phase": "watching",
            "opportunityId": "opportunity-1",
        }

        result = json.loads(
            self.post(
                "/api/browser/start",
                {
                    "url": "https://jobs.example.test/apply",
                    "opportunityId": "opportunity-1",
                },
            )
        )

        self.assertEqual("watching", result["phase"])
        browser.start.assert_called_once_with(
            "https://jobs.example.test/apply",
            "opportunity-1",
        )

    @patch("job_agent.app.managed_browser")
    @patch("job_agent.app.readiness", return_value={"ready": True})
    def test_application_questions_can_be_answered_inside_clover(
        self,
        _readiness,
        browser,
    ) -> None:
        answers = [{"fieldId": "authorization", "value": "Yes"}]
        browser.answer_questions.return_value = {
            "running": True,
            "phase": "ready_to_submit",
        }

        result = json.loads(self.post("/api/browser/answers", {"answers": answers}))

        self.assertEqual("ready_to_submit", result["phase"])
        browser.answer_questions.assert_called_once_with(answers)

    @patch("job_agent.app.managed_browser")
    @patch("job_agent.app.readiness", return_value={"ready": True})
    def test_optional_application_questions_can_be_skipped(
        self,
        _readiness,
        browser,
    ) -> None:
        browser.skip_optional_questions.return_value = {
            "running": True,
            "phase": "ready_to_submit",
        }

        result = json.loads(
            self.post(
                "/api/browser/questions/skip",
                {"fieldIds": ["demographic"]},
            )
        )

        self.assertEqual("ready_to_submit", result["phase"])
        browser.skip_optional_questions.assert_called_once_with(["demographic"])

    def test_managed_browser_submission_requires_live_page_confirmation(self) -> None:
        action_id = queue_approval(
            action_name="submit_application",
            arguments={"url": "https://jobs.example.test/apply"},
            explanation="Submit the application.",
        )
        request = Request(
            self.base + f"/api/approvals/{action_id}",
            data=json.dumps({"approved": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with self.assertRaises(HTTPError) as rejected:
            urlopen(request, timeout=5)

        self.assertEqual(409, rejected.exception.code)
        self.assertEqual(action_id, list_pending_actions()[0]["id"])


if __name__ == "__main__":
    unittest.main()
