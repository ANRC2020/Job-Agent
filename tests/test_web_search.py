from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from job_agent.web_search import (
    _enrich_job_result,
    _job_posting_json_ld,
    _validate_public_url,
    search_jobs,
    search_web,
    visit_page,
)


class WebSearchTests(unittest.TestCase):
    @patch("job_agent.web_search.DDGS")
    def test_general_search_returns_bounded_live_sources(self, ddgs) -> None:
        ddgs.return_value.text.return_value = [
            {
                "title": "Python",
                "href": "https://www.python.org/doc/",
                "body": "Official documentation.",
            },
            {"title": "Unsafe", "href": "file:///tmp/private", "body": "No"},
        ]

        result = json.loads(search_web({"query": "  Python   documentation  ", "limit": 2}))

        self.assertTrue(result["searchedLive"])
        self.assertEqual("Python documentation", result["query"])
        self.assertEqual(["https://www.python.org/doc/"], [
            item["url"] for item in result["results"]
        ])

    @patch(
        "job_agent.web_search._enrich_job_results",
        side_effect=lambda results: (results, []),
    )
    @patch("job_agent.web_search._text_search")
    def test_job_search_fans_out_and_keeps_direct_sources(self, search, _enrich) -> None:
        def results(query: str, **_kwargs):
            if "ashbyhq" in query:
                return [
                    {
                        "title": "Product Engineer",
                        "url": "https://jobs.ashbyhq.com/acme/job-1/application",
                        "snippet": "San Francisco",
                        "source": "jobs.ashbyhq.com",
                        "publishedAt": None,
                    }
                ]
            if "greenhouse" in query:
                return [
                    {
                        "title": "Software Engineer",
                        "url": "https://boards.greenhouse.io/acme/jobs/2",
                        "snippet": "AI systems",
                        "source": "boards.greenhouse.io",
                        "publishedAt": None,
                    }
                ]
            return [
                {
                    "title": "Aggregator copy",
                    "url": "https://www.indeed.com/viewjob/3",
                    "snippet": "copy",
                    "source": "indeed.com",
                    "publishedAt": None,
                }
            ]

        search.side_effect = results
        result = json.loads(
            search_jobs(
                {
                    "role": "product engineer",
                    "location": "San Francisco",
                    "limit": 5,
                }
            )
        )

        self.assertEqual(4, search.call_count)
        self.assertTrue(result["directSourcesOnly"])
        self.assertEqual(2, len(result["results"]))
        self.assertNotIn("indeed.com", json.dumps(result["results"]))
        self.assertEqual(
            "https://jobs.ashbyhq.com/acme/job-1",
            next(
                item["url"]
                for item in result["results"]
                if "ashbyhq.com" in item["url"]
            ),
        )

    @patch(
        "job_agent.web_search._text_search",
        side_effect=RuntimeError("provider throttled"),
    )
    def test_job_search_does_not_report_provider_failure_as_no_jobs(self, _search) -> None:
        with self.assertRaisesRegex(RuntimeError, "temporarily unavailable"):
            search_jobs({"role": "product engineer"})

    @patch(
        "job_agent.web_search.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("127.0.0.1", 80))],
    )
    def test_page_reader_blocks_private_network_targets(self, _resolve) -> None:
        with self.assertRaisesRegex(ValueError, "private network"):
            _validate_public_url("http://example.test/admin")

    @patch("job_agent.web_search._validate_public_url", side_effect=lambda value: value)
    @patch("job_agent.web_search._fetch_json")
    def test_ashby_pages_use_the_official_public_feed(self, fetch, _validate) -> None:
        fetch.return_value = {
            "jobs": [
                {
                    "id": "job-1",
                    "title": " Product Engineer ",
                    "location": "San Francisco",
                    "employmentType": "FullTime",
                    "descriptionHtml": "<h1>Role</h1><p>Build useful systems.</p>",
                    "jobUrl": "https://jobs.ashbyhq.com/acme/job-1",
                    "applyUrl": "https://jobs.ashbyhq.com/acme/job-1/application",
                }
            ]
        }

        result = json.loads(
            visit_page({"url": "https://jobs.ashbyhq.com/acme/job-1"})
        )

        self.assertIn("/posting-api/job-board/acme", fetch.call_args.args[0])
        self.assertEqual("Product Engineer", result["title"])
        self.assertIn("Build useful systems.", result["content"])
        self.assertTrue(result["fetchedLive"])

    @patch("job_agent.web_search._validate_public_url", side_effect=lambda value: value)
    @patch("job_agent.web_search._generic_page")
    def test_generic_page_reader_marks_content_untrusted(self, page, _validate) -> None:
        page.return_value = {
            "url": "https://example.com/careers",
            "title": "Careers",
            "content": "Current openings",
        }

        result = json.loads(
            visit_page({"url": "https://example.com/careers"})
        )

        self.assertEqual("Current openings", result["content"])
        self.assertIn("untrusted", result["warning"])

    @patch("job_agent.web_search._validate_public_url", side_effect=lambda value: value)
    @patch("job_agent.web_search._ashby_page")
    def test_job_enrichment_formats_verified_source_facts(self, ashby, _validate) -> None:
        ashby.return_value = {
            "url": "https://jobs.ashbyhq.com/acme/job-1",
            "applyUrl": "https://jobs.ashbyhq.com/acme/job-1/application",
            "title": "Senior ML Engineer",
            "company": "Acme",
            "location": ["Remote - US"],
            "employmentType": "FullTime",
            "workplaceType": "Remote",
            "department": "AI",
            "publishedAt": "2026-09-01",
            "externalId": "job-1",
            "content": (
                "Qualifications\n"
                "5 years of Python experience\n"
                "Experience with distributed systems\n"
                "Ability to design reliable production machine learning platforms\n"
                "Compensation\n$180,000 - $220,000"
            ),
        }

        result = _enrich_job_result(
            {
                "url": "https://jobs.ashbyhq.com/acme/job-1",
                "title": "Result title",
                "snippet": "Result snippet",
            }
        )

        self.assertEqual("verified", result["verificationStatus"])
        self.assertEqual("https://jobs.ashbyhq.com/acme/job-1/application", result["applyUrl"])
        self.assertEqual("senior", result["seniority"])
        self.assertTrue(result["location"]["remote"])
        self.assertEqual(180000, result["compensation"]["min"])
        self.assertIn("5 years of Python experience", result["requirements"])

    def test_json_ld_reader_finds_nested_job_posting(self) -> None:
        source = """
        <script type="application/ld+json">
        {"@graph":[{"@type":"Organization","name":"Acme"},{"@type":"JobPosting","title":"ML Engineer"}]}
        </script>
        """
        self.assertEqual("ML Engineer", _job_posting_json_ld(source)["title"])


if __name__ == "__main__":
    unittest.main()
