from __future__ import annotations

import unittest

from job_agent.chat import activity_for
from job_agent.reasoning import ThinkingFilter, strip_thinking
from job_agent.repo_tools import CHAT_TOOL_NAMES, openai_tools


def filtered(chunks: list[str]) -> str:
    stripper = ThinkingFilter()
    return "".join([*(stripper.feed(chunk) for chunk in chunks), stripper.flush()])


class ThinkingFilterTests(unittest.TestCase):
    """A reasoning model's working-out is not something to show a person."""

    def test_a_complete_reasoning_block_is_removed(self) -> None:
        self.assertEqual("Hello there.", filtered(["<think>weighing options</think>Hello there."]))

    def test_tags_split_across_chunks_are_still_caught(self) -> None:
        self.assertEqual(
            "Hello there.",
            filtered(["<th", "ink>", "weighing ", "options", "</th", "ink>", "Hello there."]),
        )

    def test_a_close_tag_with_no_open_tag_is_dropped(self) -> None:
        # Happens when a previous round of the same turn ended mid-thought.
        self.assertEqual("Real answer.", filtered(["</think>", "Real answer."]).strip())

    def test_reasoning_that_never_closes_yields_nothing_visible(self) -> None:
        self.assertEqual("", filtered(["<think>still going and then cut off"]))

    def test_text_around_a_block_survives(self) -> None:
        self.assertEqual("before  after", filtered(["before <think>mid</think> after"]))

    def test_the_thinking_tag_variant_is_handled(self) -> None:
        self.assertEqual("Visible", filtered(["<thinking>hidden</thinking>Visible"]))

    def test_ordinary_angle_brackets_are_left_alone(self) -> None:
        self.assertEqual("if a < b then c", filtered(["if a < b then c"]))

    def test_the_filter_reports_when_it_is_suppressing(self) -> None:
        stripper = ThinkingFilter()
        stripper.feed("<think>working")
        self.assertTrue(stripper.thinking)
        stripper.feed("</think>done")
        self.assertFalse(stripper.thinking)

    def test_whole_replies_are_cleaned_the_same_way(self) -> None:
        self.assertEqual("Answer.", strip_thinking("<think>reasoning</think>\n\nAnswer."))
        self.assertEqual("Answer.", strip_thinking("</think>\n\nAnswer."))
        self.assertEqual("", strip_thinking("<think>unterminated"))
        self.assertEqual("Answer.", strip_thinking("Answer."))


class ToolSurfaceTests(unittest.TestCase):
    def test_juno_gets_product_actions_and_recall_but_not_the_repository(self) -> None:
        names = {tool["function"]["name"] for tool in openai_tools(CHAT_TOOL_NAMES)}

        self.assertIn("save_opportunity", names)
        self.assertIn("set_opportunity_stage", names)
        self.assertIn("read_my_document", names)
        self.assertIn("search_memory", names)
        self.assertNotIn("read_repo_file", names)
        self.assertNotIn("create_database_record", names)

    def test_every_tool_offered_has_a_description_and_schema(self) -> None:
        for tool in openai_tools(CHAT_TOOL_NAMES):
            function = tool["function"]
            self.assertTrue(function["description"].strip(), function["name"])
            self.assertEqual("object", function["parameters"]["type"], function["name"])

    def test_activity_labels_never_leak_tool_names(self) -> None:
        for name in CHAT_TOOL_NAMES:
            label = activity_for(name)
            self.assertNotIn("_", label)
            self.assertTrue(label[0].isupper())


if __name__ == "__main__":
    unittest.main()
