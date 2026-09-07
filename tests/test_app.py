from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from job_agent.app import _bind_server, _model_messages
from job_agent.storage import initialize_database


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

    def test_extension_routes_require_a_paired_bearer_token(self) -> None:
        pairing = json.loads(self.post("/api/settings/extension/pairing-code", {}))
        paired = json.loads(self.post("/api/extension/pair", {"code": pairing["code"]}))
        page = {"url": "https://jobs.example.test/42", "title": "Writer", "fields": []}

        unauthenticated = Request(
            self.base + "/api/extension/resolve-page",
            data=json.dumps({"page": page}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as denied:
            urlopen(unauthenticated, timeout=5)
        self.assertEqual(401, denied.exception.code)

        authenticated = Request(
            self.base + "/api/extension/resolve-page",
            data=json.dumps({"page": page}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {paired['token']}",
            },
            method="POST",
        )
        with urlopen(authenticated, timeout=5) as response:
            result = json.loads(response.read())
        self.assertFalse(result["matched"])

        gated = Request(
            self.base + "/api/extension/analyze",
            data=json.dumps({"page": page}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {paired['token']}",
            },
            method="POST",
        )
        with patch(
            "job_agent.app.readiness",
            return_value={"ready": False, "state": "installing"},
        ):
            with self.assertRaises(HTTPError) as unavailable:
                urlopen(gated, timeout=5)
        self.assertEqual(503, unavailable.exception.code)

    def test_extension_payload_limit_is_enforced_before_json_parsing(self) -> None:
        request = Request(
            self.base + "/api/extension/pair",
            data=b"x" * 512_001,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as rejected:
            urlopen(request, timeout=5)
        self.assertEqual(413, rejected.exception.code)

    def test_extension_origin_is_confined_to_extension_routes(self) -> None:
        generic = Request(
            self.base + "/api/settings",
            headers={"Origin": "chrome-extension://test-extension"},
        )
        with self.assertRaises(HTTPError) as rejected:
            urlopen(generic, timeout=5)
        self.assertEqual(403, rejected.exception.code)

        browser_page = Request(
            self.base + "/api/extension/status",
            headers={"Origin": "https://malicious.example"},
        )
        with self.assertRaises(HTTPError) as rejected_page:
            urlopen(browser_page, timeout=5)
        self.assertEqual(403, rejected_page.exception.code)


if __name__ == "__main__":
    unittest.main()
