from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from unittest.mock import patch

from job_agent.app import _bind_server
from job_agent.storage import initialize_database


class AppApiTests(unittest.TestCase):
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

    def test_chat_persists_reply_and_action_transparency(self) -> None:
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

    def test_strategy_and_settings_endpoints_are_available(self) -> None:
        strategy = self.get("/api/strategy")
        settings = self.get("/api/settings")

        self.assertIn("funnel", strategy)
        self.assertEqual([], settings["pendingActions"])


if __name__ == "__main__":
    unittest.main()
