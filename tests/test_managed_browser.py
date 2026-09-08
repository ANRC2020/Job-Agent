from __future__ import annotations

import unittest
from unittest.mock import patch

from job_agent.managed_browser import (
    CAPTURE_SCRIPT,
    CHOICE_FILL_SCRIPT,
    COMBOBOX_IDS_SCRIPT,
    ManagedBrowser,
)


def page(
    *,
    value: str = "",
    submit: bool = False,
    continue_button: bool = False,
    unresolved: list[dict] | None = None,
    optional: list[dict] | None = None,
) -> dict:
    return {
        "url": "https://jobs.example.test/apply",
        "title": "Engineer",
        "company": "Example",
        "postingText": "A real job posting",
        "fields": [
            {
                "fieldId": "name",
                "label": "Full name",
                "name": "name",
                "type": "text",
                "required": True,
                "maxLength": 100,
                "currentValue": value,
                "options": [],
                "sensitive": False,
            }
        ],
        "application": {
            "fileFields": [],
            "unresolvedRequired": unresolved or [],
            "optionalQuestions": optional or [],
            "submit": {"available": submit, "ambiguous": False, "label": "Submit application" if submit else ""},
        },
        "navigation": {
            "available": continue_button,
            "ambiguous": False,
            "label": "Continue" if continue_button else "",
        },
        "listing": {},
        "capturedAt": "2026-09-07T00:00:00+00:00",
    }


class FakePage:
    def __init__(self, captures: list[dict]) -> None:
        self.captures = captures
        self.filled: list[dict] = []
        self.clicks = 0
        self.selected = ""
        self.upload = None

    def is_closed(self) -> bool:
        return False

    def evaluate(self, script: str, argument=None):
        if script == CAPTURE_SCRIPT:
            return self.captures.pop(0)
        if script == COMBOBOX_IDS_SCRIPT:
            return []
        if script == CHOICE_FILL_SCRIPT:
            return {"handled": [], "filled": 0, "skipped": 0}
        self.filled = list(argument or [])
        return {"filled": len(self.filled), "skipped": 0}

    def locator(self, selector: str):
        self.selected = selector
        return self

    def click(self) -> None:
        self.clicks += 1

    def wait_for_timeout(self, _milliseconds: int) -> None:
        pass

    def set_input_files(self, payload) -> None:
        self.upload = payload


class ManagedBrowserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.quick = patch("job_agent.managed_browser.quick_answers", return_value=[])
        self.cached = patch("job_agent.managed_browser.cached_answers", return_value=[])
        self.remember = patch("job_agent.managed_browser.remember_answers")
        self.remember_user = patch("job_agent.managed_browser.remember_user_answers")
        self.quick.start()
        self.cached_mock = self.cached.start()
        self.remember.start()
        self.remember_user_mock = self.remember_user.start()

    def tearDown(self) -> None:
        self.remember_user.stop()
        self.remember.stop()
        self.cached.stop()
        self.quick.stop()

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields")
    def test_grounded_answers_and_role_specific_drafts_are_filled(
        self,
        suggest,
        _document,
    ) -> None:
        suggest.return_value = {
            "suggestions": [
                {"fieldId": "name", "value": "Abbas", "source": "resume", "confidence": 0.98},
                {
                    "fieldId": "bio",
                    "value": "A role-specific grounded draft",
                    "source": "opportunity",
                    "confidence": 0.8,
                },
            ]
        }
        browser = ManagedBrowser()
        fake = FakePage([page(), page(), page(), page(value="Abbas", submit=True)])
        browser._page = fake
        browser._state.update({"running": True, "phase": "watching"})

        browser._tick(force=True)

        self.assertEqual(["name", "bio"], [item["fieldId"] for item in fake.filled])
        self.assertEqual("ready_to_submit", browser.status()["phase"])

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields", return_value={"suggestions": []})
    def test_sensitive_required_questions_pause_for_the_person(
        self,
        _suggest,
        _document,
    ) -> None:
        sensitive = [{"label": "Veteran status", "type": "radio", "sensitive": True}]
        browser = ManagedBrowser()
        browser._page = FakePage(
            [
                page(unresolved=sensitive),
                page(unresolved=sensitive),
                page(unresolved=sensitive),
                page(unresolved=sensitive),
            ]
        )
        browser._state.update({"running": True, "phase": "watching"})

        browser._tick(force=True)

        state = browser.status()
        self.assertEqual("needs_input", state["phase"])
        self.assertTrue(state["unresolved"][0]["sensitive"])

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields", return_value={"suggestions": []})
    def test_continue_must_actually_advance_before_runner_proceeds(
        self,
        _suggest,
        _document,
    ) -> None:
        unchanged = page(value="Already complete", continue_button=True)
        browser = ManagedBrowser()
        fake = FakePage([unchanged, unchanged, unchanged, unchanged, unchanged])
        browser._page = fake
        browser._state.update({"running": True, "phase": "watching"})

        browser._tick(force=True)

        self.assertEqual(1, fake.clicks)
        self.assertEqual("needs_input", browser.status()["phase"])
        self.assertIn("did not advance", browser.status()["message"])

    @patch(
        "job_agent.managed_browser.document_file",
        return_value={
            "filename": "resume.pdf",
            "mimeType": "application/pdf",
            "data": b"resume",
        },
    )
    def test_hidden_greenhouse_resume_is_distinguished_from_cover_letter(
        self,
        _document,
    ) -> None:
        browser = ManagedBrowser()
        fake = FakePage([])
        browser._page = fake
        raw = {
            "application": {
                "fileFields": [
                    {
                        "fieldId": "clover-file-0",
                        "label": "Attach resume",
                        "hasFile": False,
                    },
                    {
                        "fieldId": "clover-file-1",
                        "label": "Attach cover_letter",
                        "hasFile": False,
                    },
                ]
            }
        }

        uploaded = browser._upload_resume(raw)

        self.assertTrue(uploaded)
        self.assertIn("clover-file-0", fake.selected)
        self.assertEqual("resume.pdf", fake.upload["name"])

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch(
        "job_agent.managed_browser.suggest_fields",
        side_effect=ValueError("Juno did not return structured field answers."),
    )
    def test_invalid_model_json_does_not_abort_application_runner(
        self,
        _suggest,
        _document,
    ) -> None:
        unresolved = [{"label": "School", "type": "text", "sensitive": False}]
        current = page(unresolved=unresolved)
        browser = ManagedBrowser()
        browser._page = FakePage([current, current, current, current])
        browser._state.update({"running": True, "phase": "watching"})

        browser._tick(force=True)

        state = browser.status()
        self.assertEqual("needs_input", state["phase"])
        self.assertIn("could not prepare", state["message"])
        self.assertIn("structured field answers", state["timing"]["modelWarning"])

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields", return_value={"suggestions": []})
    def test_person_can_answer_required_question_from_clover(
        self,
        _suggest,
        _document,
    ) -> None:
        question = {
            "fieldId": "name",
            "label": "Are you authorized to work?",
            "type": "text",
            "options": ["Yes", "No"],
            "sensitive": False,
        }
        complete = page(value="Yes", submit=True)
        browser = ManagedBrowser()
        fake = FakePage(
            [
                page(unresolved=[question]),
                complete,
                complete,
                complete,
                complete,
            ]
        )
        browser._page = fake
        browser._state.update({"running": True, "phase": "needs_input"})

        state = browser._answer_questions([{"fieldId": "name", "value": "Yes"}])

        self.assertEqual([{"fieldId": "name", "value": "Yes"}], fake.filled)
        self.assertEqual("ready_to_submit", state["phase"])
        self.remember_user_mock.assert_called_once()

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields", return_value={"suggestions": []})
    def test_person_can_skip_optional_personal_questions(
        self,
        _suggest,
        _document,
    ) -> None:
        question = {
            "fieldId": "demographic",
            "label": "Demographic response",
            "type": "text",
            "options": [],
            "sensitive": True,
            "optional": True,
        }
        current = page(submit=True, optional=[question])
        browser = ManagedBrowser()
        browser._page = FakePage([current, current, current, current, current])
        browser._state.update({"running": True, "phase": "needs_input"})

        state = browser._skip_optional_questions(["demographic"])

        self.assertEqual("ready_to_submit", state["phase"])
        self.assertIn("Demographic response", browser._skipped_optional_questions)

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields", return_value={"suggestions": []})
    def test_remembered_personal_answer_is_reused_automatically(
        self,
        _suggest,
        _document,
    ) -> None:
        question = {
            "fieldId": "demographic",
            "label": "Veteran status",
            "type": "text",
            "options": ["No", "Prefer not to answer"],
            "sensitive": True,
            "optional": True,
        }
        waiting = page(optional=[question])
        complete = page(value="Complete", submit=True)
        self.cached_mock.return_value = [
            {
                "fieldId": "demographic",
                "value": "Prefer not to answer",
                "source": "user",
                "confidence": 1.0,
            }
        ]
        browser = ManagedBrowser()
        fake = FakePage([waiting, waiting, waiting, waiting, complete])
        browser._page = fake
        browser._state.update({"running": True, "phase": "watching"})

        browser._tick(force=True)

        self.assertEqual("ready_to_submit", browser.status()["phase"])
        self.assertEqual("Prefer not to answer", fake.filled[0]["value"])

    @patch(
        "job_agent.managed_browser.confirm_application_received",
        return_value={"stage": "applied", "status": "confirmed"},
    )
    def test_employer_receipt_is_detected_without_person_confirmation(
        self,
        confirm,
    ) -> None:
        receipt = page()
        receipt["url"] = "https://jobs.example.test/application/thank-you"
        receipt["application"]["receipt"] = {"detected": True, "source": "url"}
        browser = ManagedBrowser()
        browser._page = FakePage([receipt])
        browser._state.update(
            {
                "running": True,
                "phase": "awaiting_receipt",
                "submission": {"actionId": "submit-1"},
            }
        )

        browser._check_receipt()

        self.assertEqual("completed", browser.status()["phase"])
        confirm.assert_called_once()
        self.assertFalse(confirm.call_args.kwargs["confirmed_by_user"])

    @patch(
        "job_agent.managed_browser.record_application_sent",
        return_value={"stage": "applied", "status": "sent"},
    )
    def test_missing_receipt_does_not_pause_completed_submission(
        self,
        record_sent,
    ) -> None:
        submitted = page()
        submitted["application"]["receipt"] = {"detected": False, "source": ""}
        browser = ManagedBrowser()
        browser._page = FakePage([submitted])
        browser._state.update(
            {
                "running": True,
                "phase": "awaiting_receipt",
                "submission": {"actionId": "submit-1"},
            }
        )
        browser._receipt_started_at = 0

        browser._check_receipt()

        self.assertEqual("completed", browser.status()["phase"])
        record_sent.assert_called_once()
        self.assertEqual("submit-1", record_sent.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
