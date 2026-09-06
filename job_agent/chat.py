from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from job_agent.config import load_config
from job_agent.paths import system_prompt_path
from job_agent.repo_tools import call_tool, openai_tools


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        cfg.api_base.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer lm-studio",
        },
        method="POST",
    )
    with urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def system_message() -> dict[str, str]:
    prompt = system_prompt_path().read_text(encoding="utf-8")
    extra = (
        "\nYou are running inside the Job Agent desktop/CLI app. "
        "Use function tools when they can answer from this repository."
    )
    return {"role": "system", "content": prompt + extra}


def complete(user_messages: list[dict[str, Any]], max_tool_rounds: int = 6) -> dict[str, Any]:
    cfg = load_config()
    messages: list[dict[str, Any]] = [system_message(), *user_messages]
    traces: list[dict[str, Any]] = []
    final = ""
    for _ in range(max_tool_rounds):
        data = _post(
            {
                "model": cfg.model,
                "messages": messages,
                "tools": openai_tools(),
                "temperature": 0.3,
            }
        )
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""
        if tool_calls:
            messages.append(message)
            for call in tool_calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                result = call_tool(name, args)
                traces.append({"tool": name, "arguments": args, "result": result[:4000]})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or name,
                        "content": result,
                    }
                )
            continue
        final = content
        break
    return {"content": final, "tools": traces, "model": cfg.model}
