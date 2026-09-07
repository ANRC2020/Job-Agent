from __future__ import annotations

import json
import time
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from job_agent.config import MODEL_INSTANCE_ID, load_config
from job_agent.lmstudio import wait_for_server
from job_agent.paths import system_prompt_path
from job_agent.reasoning import strip_thinking
from job_agent.repo_tools import CHAT_TOOL_NAMES, call_tool, openai_tools
from job_agent.storage import begin_turn

# What the user sees while Juno works. Never tool names.
TOOL_ACTIVITY: dict[str, str] = {
    "get_opportunities": "Looking over your opportunities",
    "get_opportunity": "Reading this opportunity's history",
    "save_opportunity": "Saving this role",
    "set_opportunity_stage": "Updating where this stands",
    "add_opportunity_note": "Writing that down",
    "save_application_material": "Saving your draft",
    "read_my_document": "Reading your resume",
    "remember_about_user": "Remembering that",
    "note_observation": "Noting a pattern",
    "record_progress": "Marking your progress",
    "save_experience": "Adding to your background",
    "search_memory": "Looking through what I remember",
}

OPPORTUNITY_BOUND_TOOLS = {
    "get_opportunity",
    "set_opportunity_stage",
    "add_opportunity_note",
    "save_application_material",
    "note_observation",
    "record_progress",
    "search_memory",
    "search_database",
}

EMPTY_RESPONSE_RETRY = (
    "Your previous generation contained no user-visible answer. Respond now with a concise, "
    "direct answer to the user's latest message. Do not output private reasoning."
)
EMPTY_RESPONSE_FALLBACK = (
    "I lost the thread for a moment. Please ask me that once more."
)
MODEL_REQUEST_TIMEOUT = 60
MODEL_TURN_TIMEOUT = 90
MAX_OUTPUT_TOKENS = 640


class ModelResponseTimeout(TimeoutError):
    """The local model exceeded Clover's bounded response window."""


def activity_for(tool_name: str) -> str:
    return TOOL_ACTIVITY.get(tool_name, "Checking something")


def _request(payload: dict[str, Any]) -> Request:
    cfg = load_config()
    body = json.dumps(payload).encode("utf-8")
    return Request(
        cfg.api_base.rstrip("/").removesuffix("/v1") + "/v1/responses",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="POST",
    )


def _post(payload: dict[str, Any], *, timeout: float = MODEL_REQUEST_TIMEOUT) -> dict[str, Any]:
    if not wait_for_server(120):
        raise ConnectionError("Juno's local engine did not finish starting.")
    deadline = time.monotonic() + timeout
    for attempt in range(2):
        try:
            with urlopen(
                _request(payload),
                timeout=max(1, deadline - time.monotonic()),
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if attempt == 0 and exc.code >= 500 and "model unloaded" in detail.lower():
                time.sleep(0.5)
                continue
            raise RuntimeError(f"LM Studio rejected Juno's request: {detail[:500]}") from exc
        except TimeoutError as exc:
            raise ModelResponseTimeout(
                "Juno took too long to answer, so Clover stopped that attempt."
            ) from exc
    raise RuntimeError("LM Studio could not keep Juno's model loaded.")


def system_message(context: str = "") -> dict[str, str]:
    prompt = system_prompt_path().read_text(encoding="utf-8")
    return {
        "role": "system",
        "content": prompt + context,
    }


def _payload(messages: list[dict[str, Any]], tool_names: tuple[str, ...] | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        # Address the exact instance Clover loaded at its bounded context size.
        # Using the catalog key lets LM Studio silently auto-load a second,
        # default-context instance.
        "model": MODEL_INSTANCE_ID,
        "input": messages,
        "temperature": 0.4,
        "reasoning": {"effort": "none"},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "stream": False,
        "store": False,
    }
    tools = openai_tools(tool_names) if tool_names else []
    if tools:
        payload["tools"] = [
            {"type": "function", **tool["function"]}
            for tool in tools
        ]
    return payload


def _response_content(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    return strip_thinking("".join(parts)).strip()


def _response_calls(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item.get("call_id") or item.get("id") or item.get("name") or ""),
            "name": str(item.get("name") or ""),
            "arguments": str(item.get("arguments") or "{}"),
            "item": item,
        }
        for item in data.get("output") or []
        if item.get("type") == "function_call" and item.get("name")
    ]


def _needs_resume_context(messages: list[dict[str, Any]]) -> bool:
    latest = next(
        (
            str(message.get("content") or "").lower()
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    return any(
        phrase in latest
        for phrase in (
            "resume",
            "résumé",
            "my background",
            "my experience",
            "my skills",
            "who am i",
            "who i am",
            "about me",
        )
    )


def _preload_resume(
    messages: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    tool_names: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if (
        not tool_names
        or "read_my_document" not in tool_names
        or not _needs_resume_context(messages)
    ):
        return tool_names
    _run_calls(
        [
            {
                "id": "clover-resume-context",
                "name": "read_my_document",
                "arguments": '{"kind":"resume"}',
            }
        ],
        messages,
        traces,
    )
    return tuple(name for name in tool_names if name != "read_my_document")


def _run_calls(
    calls: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    said: str = "",
    opportunity_id: str | None = None,
) -> None:
    if said:
        messages.append({"role": "assistant", "content": said})
    for call in calls:
        messages.append(
            call.get("item")
            or {
                "type": "function_call",
                "call_id": call["id"] or call["name"],
                "name": call["name"],
                "arguments": call["arguments"] or "{}",
            }
        )
        try:
            arguments = json.loads(call["arguments"] or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        invoked_name = call["name"]
        if opportunity_id and call["name"] == "get_opportunities":
            invoked_name = "get_opportunity"
            arguments = {"opportunityId": opportunity_id}
        if opportunity_id and call["name"] in OPPORTUNITY_BOUND_TOOLS:
            requested = str(arguments.get("opportunityId") or "").strip()
            if requested and requested != opportunity_id:
                result = "Tool error: that action belongs to a different opportunity context"
            else:
                arguments["opportunityId"] = opportunity_id
                if call["name"] == "note_observation":
                    arguments["scope"] = "opportunity"
                result = call_tool(invoked_name, arguments)
        else:
            result = call_tool(invoked_name, arguments)
        traces.append(
            {
                "tool": call["name"],
                "activity": activity_for(call["name"]),
                "arguments": arguments,
                "result": result[:4000],
            }
        )
        messages.append(
            {
                "type": "function_call_output",
                "call_id": call["id"] or call["name"],
                "output": result,
            }
        )


def complete(
    user_messages: list[dict[str, Any]],
    max_tool_rounds: int = 6,
    *,
    context: str = "",
    tool_names: tuple[str, ...] | None = CHAT_TOOL_NAMES,
    opportunity_id: str | None = None,
) -> dict[str, Any]:
    cfg = load_config()
    begin_turn()
    messages: list[dict[str, Any]] = [system_message(context), *user_messages]
    traces: list[dict[str, Any]] = []
    spoken: list[str] = []
    retried_empty = False
    tool_names = _preload_resume(messages, traces, tool_names)
    deadline = time.monotonic() + MODEL_TURN_TIMEOUT
    for _ in range(max_tool_rounds):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelResponseTimeout("Juno's turn exceeded Clover's time limit.")
        data = _post(
            _payload(messages, tool_names),
            timeout=min(MODEL_REQUEST_TIMEOUT, remaining),
        )
        content = _response_content(data)
        calls = _response_calls(data)
        if content:
            spoken.append(content)
        if not calls:
            if not content and not retried_empty:
                retried_empty = True
                messages.append({"role": "system", "content": EMPTY_RESPONSE_RETRY})
                continue
            break
        _run_calls(calls, messages, traces, content, opportunity_id)
    content = "\n\n".join(spoken).strip() or EMPTY_RESPONSE_FALLBACK
    return {"content": content, "tools": traces, "model": cfg.model}


def stream(
    user_messages: list[dict[str, Any]],
    *,
    context: str = "",
    tool_names: tuple[str, ...] | None = CHAT_TOOL_NAMES,
    max_tool_rounds: int = 6,
    opportunity_id: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield Juno's turn as it happens: activity, text deltas, then a final result."""
    cfg = load_config()
    begin_turn()
    messages: list[dict[str, Any]] = [system_message(context), *user_messages]
    traces: list[dict[str, Any]] = []
    spoken: list[str] = []
    retried_empty = False
    should_preload = bool(
        tool_names
        and "read_my_document" in tool_names
        and _needs_resume_context(messages)
    )
    if should_preload:
        yield {"type": "activity", "text": activity_for("read_my_document")}
    tool_names = _preload_resume(messages, traces, tool_names)
    deadline = time.monotonic() + MODEL_TURN_TIMEOUT

    for _ in range(max_tool_rounds):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ModelResponseTimeout("Juno's turn exceeded Clover's time limit.")
        yield {"type": "activity", "text": "Putting that together"}
        data = _post(
            _payload(messages, tool_names),
            timeout=min(MODEL_REQUEST_TIMEOUT, remaining),
        )
        joined = _response_content(data)
        calls = _response_calls(data)
        if joined:
            spoken.append(joined)
            yield {"type": "delta", "text": joined}
        if not calls:
            if not joined and not retried_empty:
                retried_empty = True
                messages.append({"role": "system", "content": EMPTY_RESPONSE_RETRY})
                yield {"type": "activity", "text": "Finishing the thought"}
                continue
            break

        for call in calls:
            yield {"type": "activity", "text": activity_for(call["name"])}
        _run_calls(calls, messages, traces, joined, opportunity_id)
        if joined:
            yield {"type": "break"}

    content = strip_thinking("\n\n".join(spoken))
    if not content:
        content = EMPTY_RESPONSE_FALLBACK
        yield {"type": "delta", "text": content}
    yield {
        "type": "done",
        # The stream was filtered as it arrived; scrub the result too, since this
        # is the copy that gets stored and replayed on every later turn.
        "content": content,
        "tools": traces,
        "model": cfg.model,
    }
