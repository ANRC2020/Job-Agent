from __future__ import annotations

import json
from typing import Any, Iterator
from urllib.request import Request, urlopen

from job_agent.config import load_config
from job_agent.lmstudio import wait_for_server
from job_agent.paths import system_prompt_path
from job_agent.reasoning import ThinkingFilter, strip_thinking
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


def activity_for(tool_name: str) -> str:
    return TOOL_ACTIVITY.get(tool_name, "Checking something")


def _request(payload: dict[str, Any], *, stream: bool) -> Request:
    cfg = load_config()
    body = json.dumps({**payload, "stream": stream}).encode("utf-8")
    return Request(
        cfg.api_base.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="POST",
    )


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    if not wait_for_server(120):
        raise ConnectionError("Juno's local engine did not finish starting.")
    with urlopen(_request(payload, stream=False), timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_stream(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    if not wait_for_server(120):
        raise ConnectionError("Juno's local engine did not finish starting.")
    with urlopen(_request(payload, stream=True), timeout=600) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


def system_message(context: str = "") -> dict[str, str]:
    prompt = system_prompt_path().read_text(encoding="utf-8")
    return {
        "role": "system",
        "content": prompt + context,
    }


def _payload(messages: list[dict[str, Any]], tool_names: tuple[str, ...] | None) -> dict[str, Any]:
    cfg = load_config()
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "temperature": 0.4,
    }
    tools = openai_tools(tool_names) if tool_names else []
    if tools:
        payload["tools"] = tools
    return payload


def _run_calls(
    calls: list[dict[str, str]],
    messages: list[dict[str, Any]],
    traces: list[dict[str, Any]],
    said: str = "",
    opportunity_id: str | None = None,
) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": said or None,
            "tool_calls": [
                {
                    "id": call["id"] or call["name"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
                }
                for call in calls
            ],
        }
    )
    for call in calls:
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
                "role": "tool",
                "tool_call_id": call["id"] or call["name"],
                "content": result,
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
    for _ in range(max_tool_rounds):
        data = _post(_payload(messages, tool_names))
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = strip_thinking(message.get("content") or "")
        raw_calls = message.get("tool_calls") or []
        if content:
            spoken.append(content)
        if not raw_calls:
            if not content and not retried_empty:
                retried_empty = True
                messages.append({"role": "system", "content": EMPTY_RESPONSE_RETRY})
                continue
            break
        _run_calls(
            [
                {
                    "id": str(call.get("id") or ""),
                    "name": str((call.get("function") or {}).get("name") or ""),
                    "arguments": str((call.get("function") or {}).get("arguments") or "{}"),
                }
                for call in raw_calls
            ],
            messages,
            traces,
            content,
            opportunity_id,
        )
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

    for _ in range(max_tool_rounds):
        parts: list[str] = []
        pending: dict[int, dict[str, str]] = {}
        announced_thinking = False
        thinking = ThinkingFilter()

        for chunk in _post_stream(_payload(messages, tool_names)):
            delta = ((chunk.get("choices") or [{}])[0].get("delta")) or {}
            raw = delta.get("content")
            if raw:
                text = thinking.feed(raw)
                if text:
                    parts.append(text)
                    yield {"type": "delta", "text": text}
            if (thinking.thinking or delta.get("reasoning_content")) and not announced_thinking:
                announced_thinking = True
                yield {"type": "activity", "text": "Thinking it through"}
            for call in delta.get("tool_calls") or []:
                entry = pending.setdefault(
                    int(call.get("index") or 0),
                    {"id": "", "name": "", "arguments": ""},
                )
                if call.get("id"):
                    entry["id"] = str(call["id"])
                function = call.get("function") or {}
                if function.get("name"):
                    entry["name"] = str(function["name"])
                if function.get("arguments"):
                    entry["arguments"] += str(function["arguments"])

        tail = thinking.flush()
        if tail:
            parts.append(tail)
            yield {"type": "delta", "text": tail}
        joined = "".join(parts).strip()
        if joined:
            spoken.append(joined)
        if not pending:
            if not joined and not retried_empty:
                retried_empty = True
                messages.append({"role": "system", "content": EMPTY_RESPONSE_RETRY})
                yield {"type": "activity", "text": "Finishing the thought"}
                continue
            break

        calls = [pending[index] for index in sorted(pending) if pending[index]["name"]]
        if not calls:
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
