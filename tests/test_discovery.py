from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import opportunities
from job_agent.agent_tools import tool_import_job_posting, tool_search_jobs
from job_agent.storage import initialize_database


class OpportunityDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    @patch("job_agent.agent_tools.live_search_jobs")
    def test_verified_search_results_become_rich_suggested_opportunities(self, search) -> None:
        search.return_value = json.dumps(
            {
                "query": "ML engineer",
                "results": [
                    {
                        "title": "Senior ML Engineer",
                        "company": "Acme",
                        "sourceUrl": "https://jobs.example.test/1",
                        "applyUrl": "https://jobs.example.test/1/apply",
                        "sourceKind": "ashby",
                        "verificationStatus": "verified",
                        "lastVerifiedAt": "2026-09-07T00:00:00+00:00",
                        "postedAt": "2026-09-01",
                        "location": {"text": "Remote - US", "remote": True},
                        "workplaceType": "Remote",
                        "employmentType": "FullTime",
                        "department": "AI",
                        "seniority": "senior",
                        "compensation": {"min": 180000, "max": 220000, "currency": "USD"},
                        "requirements": ["Python", "Distributed systems"],
                        "description": "Full verified posting text.",
                        "sourceMetadata": {"externalId": "job-1"},
                    },
                    {
                        "title": "Unreadable result",
                        "sourceUrl": "https://jobs.example.test/2",
                        "verificationStatus": "failed",
                    },
                ],
                "partialFailure": True,
            }
        )

        response = json.loads(tool_search_jobs({"role": "ML engineer"}))
        board = opportunities.list_opportunities()
        detail = opportunities.get_opportunity(board["opportunities"][0]["id"])

        self.assertEqual(1, board["total"])
        self.assertEqual("suggested", detail["stage"])
        self.assertEqual("https://jobs.example.test/1/apply", detail["applyUrl"])
        self.assertEqual("verified", detail["verificationStatus"])
        self.assertEqual(["Python", "Distributed systems"], detail["requirements"])
        self.assertEqual(1, response["unverifiedResultsExcluded"])
        self.assertNotIn("Full verified posting text.", json.dumps(response))

    @patch("job_agent.agent_tools.enrich_job_url")
    def test_import_job_posting_fills_source_facts_and_junos_assessment(self, enrich) -> None:
        enrich.return_value = {
            "title": "Staff Agent Engineer",
            "company": "Acme",
            "sourceUrl": "https://jobs.example.test/staff-agent",
            "applyUrl": "https://jobs.example.test/staff-agent/apply",
            "sourceKind": "ashby",
            "verificationStatus": "verified",
            "lastVerifiedAt": "2026-09-07T20:00:00+00:00",
            "postedAt": "2026-09-01",
            "location": {"text": "New York or remote", "remote": True},
            "workplaceType": "Remote",
            "employmentType": "FullTime",
            "department": "AI",
            "seniority": "staff",
            "compensation": {
                "min": 200000,
                "max": 250000,
                "currency": "USD",
                "period": "year",
            },
            "requirements": ["Python", "Production agent systems"],
            "description": "Build and operate reliable agent systems in production.",
            "companyWebsite": "https://example.test/",
            "sourceMetadata": {"externalId": "agent-42"},
        }

        response = json.loads(
            tool_import_job_posting(
                {
                    "sourceUrl": "https://jobs.example.test/staff-agent",
                    "fitSummary": "A strong systems match with one scope question.",
                    "whyItFits": ["Built production agent infrastructure"],
                    "concerns": ["Staff-level organizational scope is unclear"],
                    "standsOut": ["Owns reliability end to end"],
                    "fitScore": 0.82,
                    "nextAction": "Review the leadership expectations.",
                }
            )
        )
        detail = opportunities.get_opportunity(response["opportunityId"])

        self.assertTrue(response["created"])
        self.assertEqual("verified", detail["verificationStatus"])
        self.assertEqual("https://jobs.example.test/staff-agent/apply", detail["applyUrl"])
        self.assertEqual(["Python", "Production agent systems"], detail["requirements"])
        self.assertEqual("A strong systems match with one scope question.", detail["fitSummary"])
        self.assertEqual(["Staff-level organizational scope is unclear"], detail["concerns"])
        self.assertTrue(response["fieldsFilled"]["description"])
        self.assertTrue(response["fieldsFilled"]["compensation"])

    @patch("job_agent.agent_tools.enrich_job_url")
    def test_import_rejects_unverified_pages(self, enrich) -> None:
        enrich.return_value = {
            "title": "Maybe a job",
            "sourceUrl": "https://example.test/maybe",
            "verificationStatus": "failed",
        }

        with self.assertRaisesRegex(ValueError, "could not verify"):
            tool_import_job_posting({"sourceUrl": "https://example.test/maybe"})

        self.assertEqual(0, opportunities.list_opportunities()["total"])


if __name__ == "__main__":
    unittest.main()
