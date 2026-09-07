from __future__ import annotations

import os
import tempfile
import unittest
import json
from unittest.mock import patch

from job_agent.autonomy import (
    action_class,
    can_run_automatically,
    complete_approval,
    list_pending_actions,
    queue_approval,
    resolve_approval,
)
from job_agent.repo_tools import TOOLS, call_tool
from job_agent.storage import initialize_database


class AutonomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_actions_have_safe_default_classes(self) -> None:
        self.assertEqual("automatic_read", action_class("search_memory"))
        self.assertEqual("automatic_local_record", action_class("save_opportunity"))
        self.assertEqual("review_required_inference", action_class("note_observation"))
        self.assertEqual("approval_required", action_class("send_email"))
        self.assertTrue(can_run_automatically("note_observation"))
        self.assertFalse(can_run_automatically("send_email"))
        self.assertFalse(can_run_automatically("unknown_future_action"))

    def test_consequential_action_can_be_approved_or_rejected(self) -> None:
        action_id = queue_approval(
            action_name="send_email",
            arguments={"to": "recruiter@example.test"},
            explanation="Send the drafted follow-up to the recruiter.",
        )
        pending = list_pending_actions()
        self.assertEqual(action_id, pending[0]["id"])
        self.assertNotIn("arguments_json", pending[0])

        resolve_approval(action_id, False)
        self.assertEqual([], list_pending_actions())

    def test_approved_action_executes_once_through_the_registered_handler(self) -> None:
        calls = []
        fake = {
            "description": "Send a message after explicit approval.",
            "schema": {"type": "object", "properties": {}},
            "handler": lambda arguments: calls.append(arguments) or '{"ok":true}',
        }
        with patch.dict(TOOLS, {"send_email": fake}):
            queued = json.loads(call_tool("send_email", {"subject": "Hello"}))
            resolution = resolve_approval(queued["actionId"], True)
            result = call_tool(
                resolution["actionName"],
                resolution["arguments"],
                approval_granted=True,
            )
            complete_approval(queued["actionId"], succeeded=True)

        self.assertEqual('{"ok":true}', result)
        self.assertEqual([{"subject": "Hello"}], calls)
        self.assertEqual([], list_pending_actions())


if __name__ == "__main__":
    unittest.main()
