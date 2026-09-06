from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from job_agent.db_tools import (
    create_database_record,
    describe_database,
    get_database_record,
    list_database_records,
    search_database,
    update_database_record,
)
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
        "description": "Return Juno's system prompt shipped with Clover.",
        "schema": {"type": "object", "properties": {}},
        "handler": tool_get_system_prompt,
    },
    "describe_database": {
        "description": (
            "Describe Clover's local database, including table purposes, fields, foreign keys, "
            "and behavioral rules. Use before writing an unfamiliar record or when deciding whether "
            "information is a source fact, job-process record, or derived learning. Pass a domain to "
            "reduce context; omit it only for a broad overview."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "enum": ["person", "jobs", "learnings"],
                    "description": "Optional domain to inspect. Omit for all domains.",
                }
            },
        },
        "handler": describe_database,
    },
    "list_database_records": {
        "description": (
            "Read structured records from one allowed database table using exact-match filters. "
            "Use for lookups such as active job processes, profile facts by category, or confirmed "
            "learnings. This does not accept raw SQL. Call describe_database when fields are unclear; "
            "use search_database for free-text recall."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "table": {
                    "type": "string",
                    "description": "Allowed domain table name returned by describe_database.",
                },
                "filters": {
                    "type": "object",
                    "description": "Optional exact-match field/value filters joined with AND.",
                    "additionalProperties": True,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum records; defaults to 25.",
                },
            },
            "required": ["table"],
        },
        "handler": list_database_records,
    },
    "get_database_record": {
        "description": (
            "Read one complete database record by table and id. Use after search_database or "
            "list_database_records returns an id and full structured context is needed."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Allowed domain table name."},
                "id": {"type": "string", "description": "Record UUID or stable id."},
            },
            "required": ["table", "id"],
        },
        "handler": get_database_record,
    },
    "create_database_record": {
        "description": (
            "Create one record in an allowed database table. Use describe_database first. The tool "
            "generates id and timestamps, and defaults person_id to local-user. Preserve provenance "
            "with source_id when available. Direct user facts belong in profile_fact; interpretations "
            "belong in learning with confidence and separate learning_evidence. Never silently infer "
            "sensitive traits. Append stage events and material versions rather than rewriting history."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Allowed domain table name."},
                "values": {
                    "type": "object",
                    "description": "Field/value object. JSON columns accept objects or arrays.",
                    "additionalProperties": True,
                },
            },
            "required": ["table", "values"],
        },
        "handler": create_database_record,
    },
    "update_database_record": {
        "description": (
            "Update mutable fields on one database record. Use for corrections, statuses, review "
            "states, next actions, and current job stage. Do not rewrite messages, stage events, "
            "evidence, or submitted materials; create an appended record or new version instead."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "table": {"type": "string", "description": "Allowed domain table name."},
                "id": {"type": "string", "description": "Record id to update."},
                "changes": {
                    "type": "object",
                    "description": "Mutable fields and new values. id and created_at are protected.",
                    "additionalProperties": True,
                },
            },
            "required": ["table", "id", "changes"],
        },
        "handler": update_database_record,
    },
    "search_database": {
        "description": (
            "Search text across prior conversations, personal documents, jobs, job interactions, "
            "and learnings. Use before answering from memory, tailoring application materials, "
            "recommending jobs, or recording a potentially duplicate learning. Limit scopes to the "
            "minimum relevant context. Results contain ids; use get_database_record for full details."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQLite FTS5 search expression."},
                "scopes": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["person", "conversations", "jobs", "interactions", "learnings"],
                    },
                    "description": "Optional search areas. Defaults to all.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum results per scope; defaults to 10.",
                },
            },
            "required": ["query"],
        },
        "handler": search_database,
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
