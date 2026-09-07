from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from job_agent import opportunities
from job_agent.learning import apply_decay, learning_detail, record_hypothesis, review_learning
from job_agent.storage import connect, initialize_database


class LearningLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def opportunity(self, suffix: str) -> str:
        return opportunities.save_opportunity(
            title=f"Product Writer {suffix}",
            company=f"Company {suffix}",
            source_url=f"https://example.test/{suffix}",
        )["id"]

    def test_hypotheses_deduplicate_and_attach_contradicting_evidence(self) -> None:
        process_id = self.opportunity("one")
        first = record_hypothesis(
            claim="Interview examples may need clearer outcomes.",
            domain="application",
            scope="opportunity",
            process_id=process_id,
            evidence=[
                {
                    "entityType": "job_process",
                    "entityId": process_id,
                    "polarity": "supports",
                    "excerpt": "The recruiter asked twice about outcomes.",
                }
            ],
        )
        contradiction_id = opportunities.add_note(
            process_id,
            "The interviewer praised the concrete outcomes.",
            kind="interview",
        )
        second = record_hypothesis(
            claim="Interview examples may need clearer outcomes.",
            domain="application",
            scope="opportunity",
            process_id=process_id,
            evidence=[
                {
                    "entityType": "job_interaction",
                    "entityId": contradiction_id,
                    "polarity": "contradicts",
                    "excerpt": "The interviewer praised the concrete outcomes.",
                }
            ],
        )

        self.assertEqual(first["id"], second["id"])
        detail = learning_detail(first["id"])
        self.assertEqual(1, detail["support_count"])
        self.assertEqual(1, detail["contradiction_count"])
        self.assertEqual(2, len(detail["evidence"]))

    def test_evidence_free_hypothesis_does_not_gain_confidence(self) -> None:
        result = record_hypothesis(claim="A weak unsupported hunch.", confidence=0.35)
        repeated = record_hypothesis(claim="A weak unsupported hunch.", confidence=0.35)

        self.assertEqual(result["id"], repeated["id"])
        self.assertEqual(0.35, learning_detail(result["id"])["confidence"])

    def test_evidence_must_reference_a_real_record_in_the_same_opportunity(self) -> None:
        process_id = self.opportunity("one")
        with self.assertRaises(ValueError):
            record_hypothesis(
                claim="Fabricated support",
                scope="opportunity",
                process_id=process_id,
                evidence=[
                    {
                        "entityType": "job_interaction",
                        "entityId": "does-not-exist",
                        "polarity": "supports",
                    }
                ],
            )

    def test_person_pattern_requires_two_opportunities(self) -> None:
        first_process = self.opportunity("one")
        second_process = self.opportunity("two")
        claim = "Roles with hands-on writing seem to produce stronger conversations."
        for process_id in (first_process, second_process):
            record_hypothesis(
                claim=claim,
                domain="job_preference",
                scope="opportunity",
                process_id=process_id,
                evidence=[
                    {
                        "entityType": "job_process",
                        "entityId": process_id,
                        "polarity": "supports",
                    }
                ],
            )

        with connect() as connection:
            promoted = connection.execute(
                "SELECT * FROM learning WHERE scope = 'person' AND claim = ?",
                (claim,),
            ).fetchone()
        self.assertIsNotNone(promoted)
        self.assertEqual("pattern", promoted["lifecycle_state"])
        self.assertEqual("unreviewed", promoted["review_state"])

    def test_new_evidence_reuses_a_disputed_person_pattern(self) -> None:
        processes = [self.opportunity(str(index)) for index in range(3)]
        claim = "Writing-heavy roles may be a stronger fit."
        for process_id in processes[:2]:
            record_hypothesis(
                claim=claim,
                domain="job_preference",
                scope="opportunity",
                process_id=process_id,
                evidence=[
                    {
                        "entityType": "job_process",
                        "entityId": process_id,
                        "polarity": "supports",
                    }
                ],
            )
        with connect() as connection:
            parent_id = connection.execute(
                "SELECT id FROM learning WHERE scope = 'person' AND claim = ?",
                (claim,),
            ).fetchone()["id"]
        review_learning(parent_id, "disputed")

        record_hypothesis(
            claim=claim,
            domain="job_preference",
            scope="opportunity",
            process_id=processes[2],
            evidence=[
                {
                    "entityType": "job_process",
                    "entityId": processes[2],
                    "polarity": "supports",
                }
            ],
        )

        with connect() as connection:
            parents = connection.execute(
                "SELECT id, status FROM learning WHERE scope = 'person' AND claim = ?",
                (claim,),
            ).fetchall()
        self.assertEqual(1, len(parents))
        self.assertEqual("disputed", parents[0]["status"])

    def test_user_can_edit_dispute_and_retire_a_learning(self) -> None:
        learning_id = record_hypothesis(claim="Prefers terse answers.")["id"]
        review_learning(learning_id, "edited", edited_claim="Prefers concise answers with context.")
        edited = learning_detail(learning_id)
        self.assertEqual("confirmed", edited["lifecycle_state"])
        self.assertEqual("edited", edited["review_state"])
        self.assertEqual("Prefers concise answers with context.", edited["claim"])

        review_learning(learning_id, "disputed", note="Depends on the topic.")
        disputed = learning_detail(learning_id)
        self.assertEqual("disputed", disputed["status"])

        review_learning(learning_id, "retired")
        retired = learning_detail(learning_id)
        self.assertEqual("archived", retired["status"])
        self.assertEqual("retired", retired["lifecycle_state"])

    def test_stale_unreviewed_learning_decays_but_confirmed_learning_does_not(self) -> None:
        stale_id = record_hypothesis(claim="A stale hunch.", confidence=0.5)["id"]
        confirmed_id = record_hypothesis(claim="A confirmed belief.", confidence=0.5)["id"]
        review_learning(confirmed_id, "confirmed")
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        with connect() as connection:
            connection.execute(
                "UPDATE learning SET updated_at = ?, last_evidence_at = NULL WHERE id IN (?, ?)",
                (old, stale_id, confirmed_id),
            )
            connection.commit()

        apply_decay()

        self.assertLess(learning_detail(stale_id)["confidence"], 0.5)
        self.assertEqual(0.5, learning_detail(confirmed_id)["confidence"])

    def test_decay_is_not_reapplied_for_the_same_time_window(self) -> None:
        learning_id = record_hypothesis(claim="A time-bound hunch.", confidence=0.5)["id"]
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=90)).isoformat()
        with connect() as connection:
            connection.execute(
                "UPDATE learning SET updated_at = ?, last_evidence_at = ? WHERE id = ?",
                (old, old, learning_id),
            )
            connection.commit()

        apply_decay(now=now)
        first = learning_detail(learning_id)["confidence"]
        apply_decay(now=now)
        second = learning_detail(learning_id)["confidence"]

        self.assertEqual(first, second)

    def test_contradiction_temporarily_removes_a_confirmed_learning(self) -> None:
        process_id = self.opportunity("one")
        support_id = opportunities.add_note(
            process_id,
            "The user preferred the take-home format.",
            kind="reflection",
        )
        learning_id = record_hypothesis(
            claim="Prefers take-home exercises.",
            scope="opportunity",
            process_id=process_id,
            evidence=[
                {
                    "entityType": "job_interaction",
                    "entityId": support_id,
                    "polarity": "supports",
                }
            ],
        )["id"]
        review_learning(learning_id, "confirmed")
        contradiction_ids = [
            opportunities.add_note(
                process_id,
                f"The user found take-home step {index} too burdensome.",
                kind="reflection",
            )
            for index in (1, 2)
        ]
        record_hypothesis(
            claim="Prefers take-home exercises.",
            scope="opportunity",
            process_id=process_id,
            evidence=[
                {
                    "entityType": "job_interaction",
                    "entityId": contradiction_ids[0],
                    "polarity": "contradicts",
                },
                {
                    "entityType": "job_interaction",
                    "entityId": contradiction_ids[1],
                    "polarity": "contradicts",
                },
            ],
        )

        detail = learning_detail(learning_id)
        self.assertEqual("disputed", detail["status"])
        self.assertEqual("disputed", detail["lifecycle_state"])


if __name__ == "__main__":
    unittest.main()
