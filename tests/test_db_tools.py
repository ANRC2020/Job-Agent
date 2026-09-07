from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import opportunities
from job_agent.db_tools import (
    create_database_record,
    describe_database,
    get_database_record,
    list_database_records,
    search_database,
    update_database_record,
)
from job_agent.learning import record_hypothesis
from job_agent.repo_tools import TOOLS, call_tool
from job_agent.storage import initialize_database


class DatabaseToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def create(self, table: str, values: dict) -> dict:
        return json.loads(
            create_database_record({"table": table, "values": values})
        )["created"]

    def test_tools_are_exposed_with_usage_descriptions(self) -> None:
        for name in (
            "describe_database",
            "list_database_records",
            "get_database_record",
            "create_database_record",
            "update_database_record",
            "search_database",
        ):
            self.assertIn(name, TOOLS)
            self.assertGreater(len(TOOLS[name]["description"]), 80)

    def test_schema_guidance_includes_provenance_and_learning_rules(self) -> None:
        result = json.loads(describe_database({"domain": "learnings"}))
        self.assertIn("learning", result["domains"]["learnings"])
        self.assertTrue(any("Source facts" in rule for rule in result["rules"]))
        self.assertIn("confidence", result["domains"]["learnings"]["learning"]["fields"])

    def test_create_list_get_and_update_job_records(self) -> None:
        organization = self.create(
            "organization",
            {"name": "Example Climate Co", "website": "https://example.test"},
        )
        job = self.create(
            "job",
            {
                "organization_id": organization["id"],
                "title": "Climate Data Engineer",
                "description": "Build tools for renewable energy forecasting.",
                "requirements_json": ["Python", "data modeling"],
            },
        )
        updated = json.loads(
            update_database_record(
                {
                    "table": "job",
                    "id": job["id"],
                    "changes": {"source_url": "https://example.test/jobs/climate"},
                }
            )
        )["updated"]
        listed = json.loads(
            list_database_records(
                {
                    "table": "job",
                    "filters": {"title": "Climate Data Engineer"},
                }
            )
        )
        fetched = json.loads(
            get_database_record({"table": "job", "id": job["id"]})
        )["record"]

        self.assertEqual("https://example.test/jobs/climate", updated["source_url"])
        self.assertEqual(1, listed["count"])
        self.assertEqual(["Python", "data modeling"], fetched["requirements_json"])

    def test_search_finds_person_memory_jobs_and_learnings(self) -> None:
        fact = self.create(
            "profile_fact",
            {
                "category": "values",
                "statement": "I care deeply about climate resilience.",
                "confidence": 1,
                "confirmed_at": "2026-09-06T00:00:00+00:00",
            },
        )
        job = self.create(
            "job",
            {
                "title": "Resilience Analyst",
                "description": "Climate adaptation and resilience planning.",
            },
        )
        learning = record_hypothesis(
            domain="job_preference",
            claim="Prefers climate resilience roles.",
            confidence=0.6,
        )

        result = json.loads(
            search_database(
                {
                    "query": "climate",
                    "scopes": ["person", "jobs", "learnings"],
                }
            )
        )["results"]

        self.assertEqual(fact["id"], result["person"][0]["entity_id"])
        self.assertEqual(job["id"], result["jobs"][0]["job_id"])
        self.assertEqual(learning["id"], result["learnings"][0]["learning_id"])

    def test_arbitrary_sql_and_protected_tables_are_not_exposed(self) -> None:
        result = call_tool(
            "create_database_record",
            {"table": "schema_migration", "values": {"version": 999}},
        )
        self.assertIn("Unknown or protected table", result)

    def test_generic_tools_cannot_rewrite_history_or_bypass_review(self) -> None:
        conversation = self.create(
            "conversation",
            {
                "started_at": "2026-09-06T00:00:00+00:00",
                "kind": "general",
            },
        )
        blocked_create = call_tool(
            "create_database_record",
            {
                "table": "message",
                "values": {
                    "conversation_id": conversation["id"],
                    "role": "user",
                    "content": "Rewrite me",
                    "occurred_at": "2026-09-06T00:00:00+00:00",
                },
            },
        )
        self.assertIn("app-managed", blocked_create)
        blocked_process = call_tool(
            "create_database_record",
            {
                "table": "job_process",
                "values": {
                    "job_id": "missing",
                    "started_at": "2026-09-06T00:00:00+00:00",
                    "current_stage": "offer",
                },
            },
        )
        self.assertIn("app-managed", blocked_process)

        learning = record_hypothesis(
            domain="other",
            claim="A tentative pattern",
            confidence=0.4,
        )
        blocked_review = call_tool(
            "update_database_record",
            {
                "table": "learning",
                "id": learning["id"],
                "changes": {"review_state": "confirmed"},
            },
        )
        self.assertIn("dedicated product operation", blocked_review)

    def test_new_learning_cannot_start_confirmed(self) -> None:
        result = call_tool(
            "create_database_record",
            {
                "table": "learning",
                "values": {
                    "domain": "other",
                    "claim": "Skip review",
                    "confidence": 0.9,
                    "review_state": "confirmed",
                },
            },
        )
        self.assertIn("app-managed", result)

    def test_search_can_be_hard_scoped_to_one_opportunity(self) -> None:
        first = opportunities.save_opportunity(
            title="Writer One",
            source_url="https://example.test/one",
        )["id"]
        second = opportunities.save_opportunity(
            title="Writer Two",
            source_url="https://example.test/two",
        )["id"]
        opportunities.add_note(first, "Discussed portfolio examples", kind="interview")
        opportunities.add_note(second, "Discussed portfolio ownership", kind="interview")

        result = json.loads(
            search_database(
                {
                    "query": "portfolio",
                    "scopes": ["interactions"],
                    "opportunityId": first,
                }
            )
        )

        self.assertEqual(1, len(result["results"]["interactions"]))
        self.assertIn("examples", result["results"]["interactions"][0]["summary"])

        result = call_tool(
            "list_database_records",
            {"table": "job; DROP TABLE job;--"},
        )
        self.assertIn("Unknown or protected table", result)


if __name__ == "__main__":
    unittest.main()
