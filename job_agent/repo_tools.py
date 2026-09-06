from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from job_agent.paths import repo_root, system_prompt_path

ROOT = repo_root()


def _safe_path(rel: str) -> Path:
    if not rel or rel.strip() != rel:
        raise ValueError("Path is required")
    target = (ROOT / rel).resolve()
    try:
        target.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError("Path must stay inside the job-agent repository") from exc
    return target


def tool_list_repo_files(arguments: dict[str, Any]) -> str:
    rel = arguments.get("path") or "."
    target = _safe_path(str(rel))
    if not target.exists():
        return f"Not found: {rel}"
    if target.is_file():
        return str(target.relative_to(ROOT))
    entries = []
    for child in sorted(target.iterdir()):
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.relative_to(ROOT)}{suffix}")
    return "\n".join(entries) or "(empty)"


def tool_read_repo_file(arguments: dict[str, Any]) -> str:
    target = _safe_path(str(arguments.get("path") or ""))
    if not target.is_file():
        return f"Not a file: {arguments.get('path')}"
    if target.stat().st_size > 512_000:
        return "File is larger than 512KB; choose a smaller file."
    return target.read_text(encoding="utf-8", errors="replace")


def tool_get_system_prompt(_: dict[str, Any]) -> str:
    prompt = system_prompt_path()
    if not prompt.is_file():
        return "System prompt is missing."
    return prompt.read_text(encoding="utf-8")


TOOLS: dict[str, dict[str, Any]] = {
    "list_repo_files": {
        "description": "List files and folders inside the job-agent repository.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from the repo root. Defaults to .",
                }
            },
        },
        "handler": tool_list_repo_files,
    },
    "read_repo_file": {
        "description": "Read a UTF-8 text file from the job-agent repository.",
        "schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path from the repo root.",
                }
            },
            "required": ["path"],
        },
        "handler": tool_read_repo_file,
    },
    "get_system_prompt": {
        "description": "Return the Job Agent system prompt shipped with this repo.",
        "schema": {"type": "object", "properties": {}},
        "handler": tool_get_system_prompt,
    },
}


def openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["schema"] or {"type": "object", "properties": {}},
            },
        }
        for name, spec in TOOLS.items()
    ]


def call_tool(name: str, arguments: dict[str, Any] | None) -> str:
    spec = TOOLS.get(name)
    if spec is None:
        return f"Unknown tool: {name}"
    handler: Callable[[dict[str, Any]], str] = spec["handler"]
    try:
        return handler(arguments or {})
    except Exception as exc:  # noqa: BLE001
        return f"Tool error: {exc}"
