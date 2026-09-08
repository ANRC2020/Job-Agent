from __future__ import annotations

from io import BytesIO
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

from job_agent.chat import (
    EMPTY_RESPONSE_FALLBACK,
    MAX_OUTPUT_TOKENS,
    TOOL_CALL_RETRY_OUTPUT_TOKENS,
    _job_search_requested,
    _payload,
    _post,
    _run_calls,
    activity_for,
    complete_json,
    stream,
)
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
        self.assertIn("search_web", names)
        self.assertIn("search_jobs", names)
        self.assertIn("visit_page", names)
        self.assertIn("import_job_posting", names)
        self.assertNotIn("read_repo_file", names)
        self.assertNotIn("create_database_record", names)

    def test_import_job_posting_requires_an_official_source_url(self) -> None:
        tools = {
            tool["function"]["name"]: tool["function"]
            for tool in openai_tools(CHAT_TOOL_NAMES)
        }

        schema = tools["import_job_posting"]["parameters"]
        self.assertEqual(["sourceUrl"], schema["required"])
        self.assertIn("fitSummary", schema["properties"])
        self.assertIn("concerns", schema["properties"])

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

    def test_active_opportunity_cannot_be_overridden_by_a_tool_call(self) -> None:
        messages = []
        traces = []
        with patch("job_agent.chat.call_tool") as call:
            _run_calls(
                [
                    {
                        "id": "call-1",
                        "name": "get_opportunity",
                        "arguments": '{"opportunityId":"other-opportunity"}',
                    }
                ],
                messages,
                traces,
                opportunity_id="active-opportunity",
            )

        call.assert_not_called()
        self.assertIn("different opportunity", traces[0]["result"])

    def test_opportunity_chat_cannot_list_other_opportunities_or_create_person_patterns(self) -> None:
        messages = []
        traces = []
        with patch("job_agent.chat.call_tool", return_value='{"found":true}') as call:
            _run_calls(
                [{"id": "call-1", "name": "get_opportunities", "arguments": "{}"}],
                messages,
                traces,
                opportunity_id="active-opportunity",
            )
            _run_calls(
                [
                    {
                        "id": "call-2",
                        "name": "note_observation",
                        "arguments": '{"claim":"A broad pattern","scope":"person"}',
                    }
                ],
                messages,
                traces,
                opportunity_id="active-opportunity",
            )

        self.assertEqual("get_opportunity", call.call_args_list[0].args[0])
        observation_arguments = call.call_args_list[1].args[1]
        self.assertEqual("opportunity", observation_arguments["scope"])
        self.assertEqual("active-opportunity", observation_arguments["opportunityId"])


class StructuredOutputTests(unittest.TestCase):
    def test_structured_completion_reads_schema_constrained_reasoning_output(self) -> None:
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": '{"fields":[]}',
                        }
                    }
                ]
            }
        ).encode()
        schema = {
            "type": "object",
            "properties": {"fields": {"type": "array", "items": {"type": "string"}}},
            "required": ["fields"],
        }
        with patch("job_agent.chat.wait_for_server", return_value=True):
            with patch("job_agent.chat.urlopen", return_value=response) as request:
                result = complete_json("Return fields.", schema=schema, name="fields")

        self.assertEqual({"fields": []}, result)
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual("json_schema", payload["response_format"]["type"])
        self.assertEqual(schema, payload["response_format"]["json_schema"]["schema"])


class EmptyResponseTests(unittest.TestCase):
    def test_transient_model_unloaded_error_is_retried(self) -> None:
        unloaded = HTTPError(
            "http://localhost/v1/responses",
            500,
            "Internal Server Error",
            {},
            BytesIO(b'{"error":{"message":"Model unloaded."}}'),
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"output":[]}'
        with patch("job_agent.chat.wait_for_server", return_value=True):
            with patch(
                "job_agent.chat.urlopen", side_effect=[unloaded, response]
            ) as request:
                with patch("job_agent.chat.time.sleep"):
                    self.assertEqual(
                        {"output": []}, _post({"model": "test"}, timeout=5)
                    )

        self.assertEqual(2, request.call_count)

    def test_truncated_tool_call_is_retried_with_a_larger_output_budget(self) -> None:
        truncated = HTTPError(
            "http://localhost/v1/responses",
            500,
            "Internal Server Error",
            {},
            BytesIO(
                b'{"error":{"message":"Failed to parse tool call: Unexpected end of content."}}'
            ),
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"output":[]}'
        with patch("job_agent.chat.wait_for_server", return_value=True):
            with patch(
                "job_agent.chat.urlopen", side_effect=[truncated, response]
            ) as request:
                result = _post(
                    {
                        "model": "test",
                        "max_output_tokens": MAX_OUTPUT_TOKENS,
                        "temperature": 0.4,
                    },
                    timeout=5,
                )

        retry_request = request.call_args_list[1].args[0]
        retry_payload = json.loads(retry_request.data)
        self.assertEqual({"output": []}, result)
        self.assertEqual(
            TOOL_CALL_RETRY_OUTPUT_TOKENS,
            retry_payload["max_output_tokens"],
        )
        self.assertEqual(0.2, retry_payload["temperature"])

    def test_reasoning_only_generation_is_retried_for_a_visible_answer(self) -> None:
        first = {"output": [{"type": "reasoning", "content": "private reasoning"}]}
        second = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "Yes — I can see your resume."}
                    ],
                }
            ]
        }
        with patch("job_agent.chat._post", side_effect=[first, second]) as post:
            events = list(
                stream(
                    [{"role": "user", "content": "Can you see my resume?"}],
                    tool_names=None,
                )
            )

        self.assertEqual(2, post.call_count)
        self.assertEqual("Yes — I can see your resume.", events[-1]["content"])
        self.assertTrue(any(event.get("type") == "delta" for event in events))

    def test_two_empty_generations_return_a_visible_fallback(self) -> None:
        with patch(
            "job_agent.chat._post",
            side_effect=[{"output": []}, {"output": []}],
        ):
            events = list(stream([{"role": "user", "content": "Hello"}], tool_names=None))

        self.assertEqual(EMPTY_RESPONSE_FALLBACK, events[-1]["content"])
        self.assertEqual(EMPTY_RESPONSE_FALLBACK, events[-2]["text"])

    def test_responses_requests_disable_reasoning_and_bound_output(self) -> None:
        payload = _payload([{"role": "user", "content": "Hello"}], CHAT_TOOL_NAMES)

        self.assertEqual({"effort": "none"}, payload["reasoning"])
        self.assertEqual(MAX_OUTPUT_TOKENS, payload["max_output_tokens"])
        self.assertEqual("clover-juno", payload["model"])
        self.assertTrue(payload["tools"])
        self.assertNotIn("messages", payload)

    def test_explicit_job_search_forces_the_enriched_discovery_tool(self) -> None:
        messages = [{"role": "user", "content": "Please look for current ML engineer listings"}]
        self.assertTrue(_job_search_requested(messages))
        payload = _payload(messages, CHAT_TOOL_NAMES, forced_tool="search_jobs")
        self.assertEqual("required", payload["tool_choice"])
        self.assertEqual(["search_jobs"], [tool["name"] for tool in payload["tools"]])
        self.assertFalse(
            _job_search_requested(
                [{"role": "user", "content": "Which direction sounds strongest for me?"}]
            )
        )

    def test_responses_function_call_is_returned_to_the_model(self) -> None:
        tool_call = {
            "id": "fc-1",
            "call_id": "call-1",
            "type": "function_call",
            "name": "read_my_document",
            "arguments": "{}",
        }
        answer = {
            "type": "message",
            "content": [{"type": "output_text", "text": "I read your resume."}],
        }
        with patch(
                "job_agent.chat._post",
                side_effect=[{"output": [tool_call]}, {"output": [answer]}],
            ) as post:
            with patch(
                "job_agent.chat.call_tool", return_value='{"text":"Resume"}'
            ):
                events = list(
                    stream(
                    [{"role": "user", "content": "Use the stored document tool"}],
                        tool_names=("read_my_document",),
                    )
                )

        continued_input = post.call_args_list[1].args[0]["input"]
        self.assertIn(tool_call, continued_input)
        self.assertTrue(
            any(item.get("type") == "function_call_output" for item in continued_input)
        )
        self.assertEqual("I read your resume.", events[-1]["content"])

    def test_resume_questions_preload_the_document_without_model_discretion(self) -> None:
        answer = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "You build AI systems."}
                    ],
                }
            ]
        }
        with patch("job_agent.chat._post", return_value=answer) as post:
            with patch(
                "job_agent.chat.call_tool",
                return_value='{"found":true,"text":"Founding Engineer"}',
            ) as tool:
                events = list(
                    stream(
                        [{"role": "user", "content": "What are my skills?"}],
                        tool_names=CHAT_TOOL_NAMES,
                    )
                )

        tool.assert_called_once_with("read_my_document", {"kind": "resume"})
        model_input = post.call_args.args[0]["input"]
        self.assertTrue(
            any(item.get("type") == "function_call_output" for item in model_input)
        )
        self.assertEqual("You build AI systems.", events[-1]["content"])


if __name__ == "__main__":
    unittest.main()
