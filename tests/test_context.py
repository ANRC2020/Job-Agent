from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import opportunities
from job_agent.context import MAX_CONTEXT_CHARS, build_turn_context
from job_agent.documents import save_pasted_text
from job_agent.learning import record_hypothesis, review_learning
from job_agent.person import remember_fact
from job_agent.storage import (
    add_model_run,
    add_tool_actions,
    connect,
    initialize_database,
)


class ScopedContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def save(self, suffix: str) -> str:
        return opportunities.save_opportunity(
            title=f"Writer {suffix}",
            company=f"Company {suffix}",
            description=f"Private description {suffix}",
            source_url=f"https://example.test/{suffix}",
        )["id"]

    def payload(self, block: str) -> dict:
        return json.loads(block.strip().splitlines()[2])

    def test_context_is_valid_bounded_and_opportunity_isolated(self) -> None:
        first = self.save("alpha")
        second = self.save("beta")
        opportunities.add_note(first, "Alpha-only interview detail", kind="interview")
        opportunities.add_note(second, "Beta-only confidential detail", kind="interview")
        remember_fact(statement="Enjoys practical writing work", category="interest")
        sensitive_id = remember_fact(statement="Private health context", category="context")
        with connect() as connection:
            connection.execute(
                "UPDATE profile_fact SET sensitivity = 'sensitive' WHERE id = ?",
                (sensitive_id,),
            )
            connection.commit()

        first_learning = record_hypothesis(
            claim="Alpha-specific hunch",
            scope="opportunity",
            process_id=first,
        )["id"]
        second_learning = record_hypothesis(
            claim="Beta-specific hunch",
            scope="opportunity",
            process_id=second,
        )["id"]
        review_learning(first_learning, "confirmed")
        review_learning(second_learning, "confirmed")
        thread_id = opportunities.thread_id(first)

        block = build_turn_context(
            conversation_id=thread_id,
            process_id=first,
            task="Help prepare for the interview",
        )
        data = self.payload(block)

        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False)), MAX_CONTEXT_CHARS)
        self.assertEqual(first, data["scope"]["opportunityId"])
        self.assertIn("Alpha-only interview detail", block)
        self.assertIn("Alpha-specific hunch", block)
        self.assertNotIn("Beta-only confidential detail", block)
        self.assertNotIn("Beta-specific hunch", block)
        self.assertNotIn("Private health context", block)

    def test_recent_tool_actions_are_replayed_as_compact_summaries(self) -> None:
        process_id = self.save("alpha")
        thread_id = opportunities.thread_id(process_id)
        run_id = add_model_run(provider="lm-studio", model="test", output={})
        add_tool_actions(
            thread_id,
            run_id,
            [
                {
                    "tool": "save_application_material",
                    "activity": "Saving your draft",
                    "arguments": {"content": "full private draft"},
                    "result": "Saved version 2",
                }
            ],
        )

        block = build_turn_context(
            conversation_id=thread_id,
            process_id=process_id,
            task="What did you save?",
        )

        self.assertIn("Saved version 2", block)
        self.assertNotIn("full private draft", block)

    def test_single_oversized_records_cannot_break_the_context_budget(self) -> None:
        process_id = self.save("alpha")
        remember_fact(statement="x" * 50_000, category="context")

        block = build_turn_context(
            conversation_id=opportunities.thread_id(process_id),
            process_id=process_id,
            task="Help",
        )

        self.assertLessEqual(len(block), MAX_CONTEXT_CHARS)
        self.payload(block)

    def test_active_resume_text_is_present_on_every_turn(self) -> None:
        resume = (
            "Taylor Example\nProduct writer\n"
            "Built onboarding guides that reduced support requests by thirty percent.\n"
            "Skilled in research, information architecture, and customer education."
        )
        save_pasted_text(text=resume)
        thread_id = opportunities.thread_id(self.save("alpha"))
        run_id = add_model_run(provider="lm-studio", model="test", output={})
        add_tool_actions(
            thread_id,
            run_id,
            [
                {
                    "tool": "read_my_document",
                    "activity": "Reading your resume",
                    "arguments": {},
                    "result": "CORRUPTED HISTORICAL RESUME TEXT",
                }
            ],
        )

        block = build_turn_context(
            conversation_id=thread_id,
            task="Can you see my resume?",
        )

        self.assertIn("pasted-resume.txt", block)
        self.assertIn("Built onboarding guides", block)
        self.assertNotIn("CORRUPTED HISTORICAL RESUME TEXT", block)


if __name__ == "__main__":
    unittest.main()
