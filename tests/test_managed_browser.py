from __future__ import annotations

import unittest
from unittest.mock import patch

from job_agent.managed_browser import CAPTURE_SCRIPT, ManagedBrowser


def page(
    *,
    value: str = "",
    submit: bool = False,
    continue_button: bool = False,
    unresolved: list[dict] | None = None,
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
        self.remember = patch("job_agent.managed_browser.remember_answers")
        self.quick.start()
        self.remember.start()

    def tearDown(self) -> None:
        self.remember.stop()
        self.quick.stop()

    @patch("job_agent.managed_browser.document_file", return_value=None)
    @patch("job_agent.managed_browser.suggest_fields")
    def test_only_high_confidence_grounded_answers_are_filled(
        self,
        suggest,
        _document,
    ) -> None:
        suggest.return_value = {
            "suggestions": [
                {"fieldId": "name", "value": "Abbas", "source": "resume", "confidence": 0.98},
                {"fieldId": "bio", "value": "Guess", "source": "inferred", "confidence": 0.99},
            ]
        }
        browser = ManagedBrowser()
        fake = FakePage([page(), page(), page(), page(value="Abbas", submit=True)])
        browser._page = fake
        browser._state.update({"running": True, "phase": "watching"})

        browser._tick(force=True)

        self.assertEqual(["name"], [item["fieldId"] for item in fake.filled])
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


if __name__ == "__main__":
    unittest.main()
