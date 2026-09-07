from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from job_agent import opportunities as opp
from job_agent.agent_tools import tool_record_progress
from job_agent.storage import (
    begin_turn,
    initialize_database,
    list_messages,
    list_progress_events,
)


class OpportunityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def save(self, **overrides) -> str:
        values = {
            "title": "Customer Education Manager",
            "company": "Fathom",
            "source_url": "https://example.com/job/1",
            "stage": "suggested",
        }
        values.update(overrides)
        return opp.save_opportunity(**values)["id"]

    def test_stage_names_are_normalized_into_known_lanes(self) -> None:
        self.assertEqual("suggested", opp.normalize_stage("discovered"))
        self.assertEqual("applied", opp.normalize_stage("Submitted"))
        self.assertEqual("closed", opp.normalize_stage("rejected"))
        self.assertEqual("suggested", opp.normalize_stage("nonsense"))
        self.assertEqual("interviewing", opp.lane_for_stage("offer"))

    def test_saving_the_same_posting_twice_updates_one_opportunity(self) -> None:
        first = self.save()
        second = opp.save_opportunity(
            title="Customer Education Manager",
            company="Fathom",
            source_url="https://example.com/job/1",
            fit_summary="Closer to your Northwind work than it looks.",
        )

        self.assertEqual(first, second["id"])
        self.assertFalse(second["created"])
        self.assertEqual(1, opp.list_opportunities()["total"])
        self.assertEqual(
            "Closer to your Northwind work than it looks.",
            opp.get_opportunity(first)["fitSummary"],
        )

    def test_tracking_and_apply_url_variants_deduplicate_to_one_posting(self) -> None:
        first = self.save(
            source_url="https://EXAMPLE.com/job/1/apply?utm_source=email&gh_jid=42"
        )
        second = opp.save_opportunity(
            title="Customer Education Manager",
            company="Fathom",
            source_url="https://example.com/job/1?gh_jid=42",
        )

        self.assertEqual(first, second["id"])
        self.assertEqual(
            "https://example.com/job/1?gh_jid=42",
            opp.get_opportunity(first)["sourceUrl"],
        )

    def test_external_source_id_survives_a_changed_posting_url(self) -> None:
        first = self.save(
            source_url="https://example.com/job/old",
            external_id="ats-42",
        )
        second = opp.save_opportunity(
            title="Customer Education Manager",
            company="Fathom",
            source_url="https://example.com/job/new",
            external_id="ats-42",
        )

        self.assertEqual(first, second["id"])
        self.assertEqual(
            "https://example.com/job/new",
            opp.get_opportunity(first)["sourceUrl"],
        )

    def test_juno_reasoning_is_visible_on_the_summary(self) -> None:
        process_id = self.save(
            why=["You built onboarding docs from scratch"],
            concerns=["They want curriculum design on paper"],
            standouts=["Small team"],
        )
        detail = opp.get_opportunity(process_id)

        self.assertEqual("You built onboarding docs from scratch", detail["keyReason"])
        self.assertEqual("They want curriculum design on paper", detail["mainConcern"])
        self.assertEqual(["Small team"], detail["standouts"])

    def test_verified_listing_facts_and_direct_application_link_are_preserved(self) -> None:
        process_id = self.save(
            apply_url="https://example.com/job/1/apply",
            source_kind="greenhouse",
            workplace_type="hybrid",
            department="Machine Learning",
            seniority="senior",
            requirements=["Python", "Distributed systems"],
            posted_at="2026-09-01T00:00:00+00:00",
            verification_status="verified",
            last_verified_at="2026-09-07T00:00:00+00:00",
            source_metadata={"externalId": "job-1"},
        )

        detail = opp.get_opportunity(process_id)

        self.assertEqual("https://example.com/job/1/apply", detail["applyUrl"])
        self.assertEqual("greenhouse", detail["sourceKind"])
        self.assertEqual("verified", detail["verificationStatus"])
        self.assertEqual(["Python", "Distributed systems"], detail["requirements"])
        self.assertEqual({"externalId": "job-1"}, detail["sourceMetadata"])

        opp.save_opportunity(
            title="Customer Education Manager",
            company="Fathom",
            source_url="https://example.com/job/1",
            fit_summary="Strong fit after reviewing the verified source.",
        )
        refreshed = opp.get_opportunity(process_id)
        self.assertEqual("verified", refreshed["verificationStatus"])
        self.assertEqual({"externalId": "job-1"}, refreshed["sourceMetadata"])

    def test_non_web_application_links_are_not_exposed(self) -> None:
        process_id = self.save(
            source_url="javascript:alert(1)",
            apply_url="file:///tmp/application",
        )
        detail = opp.get_opportunity(process_id)
        self.assertEqual("", detail["sourceUrl"])
        self.assertEqual("", detail["applyUrl"])

    def test_stage_history_is_appended_never_rewritten(self) -> None:
        process_id = self.save()
        opp.set_stage(process_id, "interested")
        opp.set_stage(process_id, "applying")
        opp.set_stage(process_id, "applied", reason="Sent it")

        history = opp.get_opportunity(process_id)["history"]
        transitions = [(event["from_stage"], event["to_stage"]) for event in reversed(history)]

        self.assertEqual(
            [(None, "suggested"), ("suggested", "interested"), ("interested", "applying"), ("applying", "applied")],
            transitions,
        )

    def test_repeating_the_current_stage_adds_no_history(self) -> None:
        process_id = self.save(stage="interested")
        before = len(opp.get_opportunity(process_id)["history"])
        opp.set_stage(process_id, "interested")

        self.assertEqual(before, len(opp.get_opportunity(process_id)["history"]))

    def test_stage_change_preserves_the_next_action(self) -> None:
        process_id = self.save(stage="interested", next_action="Tailor the resume")

        opp.set_stage(process_id, "applying")

        self.assertEqual("Tailor the resume", opp.get_opportunity(process_id)["nextAction"])

    def test_deciding_against_a_role_counts_as_progress(self) -> None:
        process_id = self.save()
        opp.set_stage(process_id, "closed", outcome="not_a_fit", reason="Too much travel")

        headlines = [event["headline"] for event in list_progress_events()]
        self.assertIn("Decided Customer Education Manager wasn't the right fit", headlines)

    def test_materials_are_versioned_rather_than_overwritten(self) -> None:
        process_id = self.save()
        opp.save_material(process_id, kind="cover_letter", content="First draft")
        second = opp.save_material(process_id, kind="cover_letter", content="Second draft")

        materials = opp.get_opportunity(process_id)["materials"]
        by_version = {item["version"]: item for item in materials}

        self.assertEqual(2, second["version"])
        self.assertEqual("First draft", by_version[1]["content"])
        self.assertEqual("superseded", by_version[1]["status"])
        self.assertEqual("draft", by_version[2]["status"])

    def test_each_opportunity_keeps_one_durable_thread(self) -> None:
        first = self.save()
        second = self.save(title="Support Manager", source_url="https://example.com/job/2")

        first_thread = opp.thread_id(first)
        second_thread = opp.thread_id(second)

        self.assertNotEqual(first_thread, second_thread)
        self.assertEqual(first_thread, opp.thread_id(first))
        self.assertEqual(first_thread, opp.get_opportunity(first)["threadId"])
        self.assertEqual([], list_messages(first_thread))

    def test_context_block_carries_the_whole_opportunity(self) -> None:
        process_id = self.save(
            description="Own the onboarding curriculum.",
            concerns=["Curriculum design experience"],
        )
        opp.add_note(process_id, "Recruiter wants a call Thursday", kind="email")
        opp.save_material(process_id, kind="cover_letter", content="Dear Fathom team")

        block = opp.context_block(process_id)

        self.assertIn("CURRENT OPPORTUNITY CONTEXT", block)
        self.assertIn("Fathom", block)
        self.assertIn("Own the onboarding curriculum.", block)
        self.assertIn("Recruiter wants a call Thursday", block)
        self.assertIn("Curriculum design experience", block)
        self.assertIn("stored data, not", block)

    def test_context_block_is_empty_for_an_unknown_opportunity(self) -> None:
        self.assertEqual("", opp.context_block("does-not-exist"))

    def test_location_and_pay_are_formatted_for_people(self) -> None:
        self.assertEqual("Remote · US", opp.format_location({"remote": True, "country": "US"}))
        self.assertEqual("Hybrid · Austin", opp.format_location({"arrangement": "hybrid", "city": "Austin"}))
        self.assertEqual("", opp.format_location({}))
        self.assertEqual(
            "$110k–$130k",
            opp.format_compensation({"min": 110000, "max": 130000, "currency": "USD"}),
        )
        self.assertEqual("Depends on experience", opp.format_compensation({"text": "Depends on experience"}))
        self.assertEqual("", opp.format_compensation({}))

    def test_attention_favors_live_processes_over_untouched_suggestions(self) -> None:
        self.save(stage="suggested")
        interviewing = self.save(title="Support Manager", source_url="https://example.com/job/2")
        opp.set_stage(interviewing, "interviewing")

        attention = opp.needs_attention()

        self.assertEqual(interviewing, attention[0]["id"])

    def test_lane_counts_group_related_stages(self) -> None:
        self.save(stage="applied")
        board = opp.list_opportunities()
        counts = {lane["id"]: lane["count"] for lane in board["lanes"]}

        self.assertEqual(1, counts["applying"])
        self.assertEqual(0, counts["interested"])


class ProgressReportingTests(unittest.TestCase):
    """One action the user took should appear once, however many things report it."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()
        # "suggested" records nothing on its own, so each test starts from zero.
        self.process_id = opp.save_opportunity(
            title="Customer Education Manager",
            company="Fathom",
            source_url="https://example.com/cem",
            stage="suggested",
        )["id"]
        self.assertEqual([], self.progress())

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def progress(self):
        return list_progress_events(limit=20)

    def test_junos_own_report_defers_to_what_clover_already_recorded(self) -> None:
        begin_turn()
        opp.save_material(self.process_id, kind="cover_letter", content="Dear Fathom team,")

        # Juno then reports the same action under a name of her own choosing, so
        # neither the kind nor the opportunity id lines up with Clover's record.
        tool_record_progress({"kind": "resume", "headline": "Drafted cover letter for Fathom role"})

        headlines = [event["headline"] for event in self.progress()]
        self.assertEqual(1, len(headlines))
        self.assertNotIn("Drafted cover letter for Fathom role", headlines)

    def test_progress_juno_notices_on_her_own_is_still_recorded(self) -> None:
        begin_turn()

        tool_record_progress({"kind": "insight", "headline": "Named the kind of work you want to avoid"})

        self.assertEqual(
            ["Named the kind of work you want to avoid"],
            [event["headline"] for event in self.progress()],
        )

    def test_a_later_turn_can_record_progress_again(self) -> None:
        begin_turn()
        opp.set_stage(self.process_id, "applied")

        begin_turn()
        tool_record_progress({"kind": "insight", "headline": "Worked out why that role appealed to you"})

        self.assertEqual(2, len(self.progress()))


LETTER = """Dear Fathom team,

I've spent the last six years turning confused new users into confident ones, most
recently by rebuilding an onboarding curriculum that cut support tickets by a third.
Your customer education role reads like the job I've been quietly assembling for
myself, so I'd love to talk about it.

I'd bring a bias toward writing things down, teaching in public, and measuring
whether any of it actually helped.

Best,
Robin"""


class UnsavedDraftTests(unittest.TestCase):
    """A local model often writes a letter, says it saved it, and doesn't."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()
        self.process_id = opp.save_opportunity(
            title="Customer Education Manager",
            company="Fathom",
            stage="interested",
        )["id"]
        begin_turn()  # The letter arrives in a later turn than the save.

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def materials(self):
        return opp.get_opportunity(self.process_id)["materials"]

    def test_a_letter_juno_forgot_to_save_is_kept_anyway(self) -> None:
        reply = "Here's a first pass — tell me what sounds unlike you.\n\n" + LETTER

        kept = opp.keep_unsaved_draft(self.process_id, reply)

        self.assertIsNotNone(kept)
        materials = self.materials()
        self.assertEqual(1, len(materials))
        self.assertEqual("cover_letter", materials[0]["kind"])
        self.assertTrue(materials[0]["content"].startswith("Dear Fathom team,"))
        self.assertTrue(materials[0]["content"].rstrip().endswith("Robin"))
        # The conversational lead-in is not part of the letter.
        self.assertNotIn("first pass", materials[0]["content"])

    def test_the_progress_entry_names_the_role_it_belongs_to(self) -> None:
        opp.keep_unsaved_draft(self.process_id, LETTER)

        prepared = [e for e in list_progress_events(limit=20) if e["kind"] == "prepared"]
        self.assertEqual(["Drafted a cover letter"], [e["headline"] for e in prepared])
        self.assertEqual("Customer Education Manager at Fathom", prepared[0]["detail"])

    def test_a_kept_letter_juno_already_claimed_credit_for_is_not_listed_twice(self) -> None:
        tool_record_progress({"kind": "prepared", "headline": "Wrote your cover letter"})

        opp.keep_unsaved_draft(self.process_id, LETTER)

        self.assertEqual(1, len(self.materials()))
        self.assertEqual(
            ["Wrote your cover letter"],
            [e["headline"] for e in list_progress_events(limit=20) if e["kind"] == "prepared"],
        )

    def test_ordinary_conversation_is_not_mistaken_for_a_draft(self) -> None:
        reply = (
            "Hi Robin, before I draft anything I want to check something. You said remote "
            "matters, but this role is hybrid three days a week in Denver. Is that a hard no, "
            "or worth a conversation? Either answer is fine, I just don't want to write toward "
            "the wrong thing. Thanks for bearing with the question."
        )

        self.assertIsNone(opp.keep_unsaved_draft(self.process_id, reply))
        self.assertEqual([], self.materials())

    def test_a_short_fragment_is_not_saved_as_a_letter(self) -> None:
        reply = "Dear Fathom team,\n\nI'd love to apply.\n\nBest,\nRobin"

        self.assertIsNone(opp.keep_unsaved_draft(self.process_id, reply))
        self.assertEqual([], self.materials())

    def test_the_same_letter_is_not_kept_twice(self) -> None:
        opp.keep_unsaved_draft(self.process_id, LETTER)

        self.assertIsNone(opp.keep_unsaved_draft(self.process_id, "As promised:\n\n" + LETTER))
        self.assertEqual(1, len(self.materials()))

    def test_the_senders_contact_header_is_part_of_the_letter(self) -> None:
        reply = (
            "Here's a tailored cover letter for the Customer Education Manager role:\n\n"
            "---\n\n"
            "Robin Vaz\n"
            "robin.vaz@example.com | Denver, CO (remote preferred)\n\n"
            + LETTER
            + "\n\n---\n\nWant me to make it shorter?"
        )

        opp.keep_unsaved_draft(self.process_id, reply)

        content = self.materials()[0]["content"]
        self.assertTrue(content.startswith("Robin Vaz\nrobin.vaz@example.com"))
        self.assertIn("Dear Fathom team,", content)
        self.assertNotIn("tailored cover letter", content)
        self.assertNotIn("shorter", content)

    def test_a_loosely_spaced_header_is_captured_whole(self) -> None:
        reply = (
            "Here's a draft of the cover letter:\n\n"
            "---\n\n"
            "**Robin Vaz**\n"
            "Denver, CO (remote preferred)\n"
            "robin.vaz@example.com\n\n"
            "Fathom Customer Education Application\n\n"
            + LETTER
        )

        opp.keep_unsaved_draft(self.process_id, reply)

        content = self.materials()[0]["content"]
        self.assertTrue(content.startswith("**Robin Vaz**"))
        for expected in ("Denver, CO", "robin.vaz@example.com", "Fathom Customer Education Application"):
            self.assertIn(expected, content)
        self.assertNotIn("Here's a draft", content)

    def test_markdown_fences_around_the_letter_are_dropped(self) -> None:
        reply = "Draft below.\n\n---\n\n" + LETTER + "\n\n---\n\nWant it warmer?"

        opp.keep_unsaved_draft(self.process_id, reply)

        content = self.materials()[0]["content"]
        self.assertTrue(content.startswith("Dear Fathom team,"))
        self.assertNotIn("Want it warmer?", content)


if __name__ == "__main__":
    unittest.main()
