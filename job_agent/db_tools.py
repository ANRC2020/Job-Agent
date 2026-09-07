from __future__ import annotations

import json
from typing import Any

from job_agent.storage import (
    DEFAULT_PERSON_ID,
    connect,
    initialize_database,
    json_value,
    new_id,
    transaction,
    utc_now,
)


DOMAIN_TABLES = {
    "person": [
        "person_profile",
        "profile_fact",
        "experience",
        "conversation",
        "message",
        "communication_preference",
        "person_document",
    ],
    "jobs": [
        "organization",
        "job",
        "job_process",
        "job_stage_event",
        "job_contact",
        "job_interaction",
        "application_material",
        "job_process",
        "learning",
        "job_artifact",
    ],
    "learnings": [
        "learning",
        "learning_evidence",
        "preference_signal",
        "recommendation_feedback",
        "strategy_experiment",
        "performance_metric",
        "progress_event",
        "model_run",
    ],
}

WRITABLE_TABLES = frozenset(table for tables in DOMAIN_TABLES.values() for table in tables)

TABLE_GUIDANCE = {
    "person_profile": "The single user's identity, contact data, locale, and consent settings.",
    "profile_fact": (
        "One atomic user fact. Use category + statement; put structured data in value_json. "
        "For inferred facts set confidence and source_id; never present inferred sensitive traits as confirmed."
    ),
    "experience": "A role, project, education item, accomplishment, or reusable personal story.",
    "conversation": "A chat/session container. The app normally creates these automatically.",
    "message": "Immutable conversation messages. The app normally writes these automatically.",
    "communication_preference": (
        "How the user prefers to communicate. Set explicit=1 only when the user directly stated it."
    ),
    "person_document": (
        "Metadata and extracted text for a resume, cover letter, portfolio, bio, or transcript. "
        "storage_uri points to the local file; do not place binary content in text_content."
    ),
    "organization": "An employer or recruiting organization, shared by one or more jobs.",
    "job": "The normalized job posting: title, description, requirements, compensation, location, and source URL.",
    "job_process": (
        "The user's end-to-end pursuit of one job. current_stage is the present state; "
        "also append a job_stage_event whenever the stage changes. fit_summary, why_json, "
        "concerns_json, and standouts_json hold your visible reasoning about the role."
    ),
    "job_stage_event": "Append-only history of a job process stage transition; never rewrite prior events.",
    "job_contact": "A recruiter, interviewer, referral, or other contact within one job process.",
    "job_interaction": "An email, call, interview, task, follow-up, or internal note for a job process.",
    "application_material": (
        "A versioned resume, cover letter, application answer, or portfolio selection. "
        "Create a new version rather than overwriting submitted material."
    ),
    "job_artifact": "A local copy of a posting, attachment, screenshot, take-home file, or other process artifact.",
    "learning": (
        "A derived, revisable hypothesis—not a source fact. Always include confidence and connect "
        "supporting/contradicting records through learning_evidence."
    ),
    "learning_evidence": (
        "Connects a learning to concrete evidence. polarity is supports, contradicts, or neutral."
    ),
    "preference_signal": (
        "A contextual job like/dislike. explicit=1 only for direct user feedback; strength is 0–1."
    ),
    "recommendation_feedback": "Tracks whether a suggestion was accepted, rejected, ignored, edited, or acted on.",
    "strategy_experiment": "A measured change to search, communication, or application strategy.",
    "performance_metric": "A timestamped numeric outcome associated with a process or experiment.",
    "progress_event": (
        "A moment of real progress worth acknowledging, including deciding a role is not worth "
        "pursuing. Never a target or a streak; absence of events is not failure."
    ),
    "model_run": "Audit metadata for an LLM call. The app normally creates these automatically.",
}

JSON_COLUMNS = {
    "location_json",
    "locations_json",
    "consent_json",
    "metadata_json",
    "value_json",
    "skills_json",
    "achievements_json",
    "requirements_json",
    "compensation_json",
    "result_json",
    "output_json",
    "why_json",
    "concerns_json",
    "standouts_json",
    "onboarding_json",
}

PROTECTED_UPDATE_COLUMNS = {"id", "created_at"}
APP_MANAGED_CREATE_TABLES = frozenset(
    {
        "message",
        "job_stage_event",
        "learning_evidence",
        "progress_event",
        "model_run",
        "application_material",
        "job_process",
        "learning",
    }
)
IMMUTABLE_UPDATE_TABLES = frozenset(
    {
        "message",
        "job_stage_event",
        "learning_evidence",
        "progress_event",
        "model_run",
        "application_material",
    }
)
PRODUCT_MANAGED_UPDATE_FIELDS = {
    "job_process": {"current_stage", "status", "outcome"},
    "learning": {
        "review_state",
        "status",
        "lifecycle_state",
        "support_count",
        "contradiction_count",
        "last_evidence_at",
        "last_decayed_at",
        "reviewed_at",
        "review_note",
    },
}

SEARCH_TARGETS = {
    "person": ("person_memory_fts", ["entity_type", "entity_id", "content"]),
    "conversations": ("message_fts", ["message_id", "content"]),
    "jobs": ("job_fts", ["job_id", "title", "description"]),
    "interactions": ("interaction_fts", ["interaction_id", "summary", "raw_content"]),
    "learnings": ("learning_fts", ["learning_id", "claim"]),
}


def _table_name(arguments: dict[str, Any]) -> str:
    table = str(arguments.get("table") or "")
    if table not in WRITABLE_TABLES:
        raise ValueError(
            f"Unknown or protected table: {table}. Call describe_database first for allowed tables."
        )
    return table


def _columns(connection, table: str) -> dict[str, dict[str, Any]]:
    return {
        str(row["name"]): {
            "type": str(row["type"]),
            "required": bool(row["notnull"]) and row["dflt_value"] is None,
            "default": row["dflt_value"],
            "primaryKey": bool(row["pk"]),
        }
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def _decode_row(row) -> dict[str, Any]:
    result = dict(row)
    for column in JSON_COLUMNS.intersection(result):
        value = result[column]
        if isinstance(value, str):
            try:
                result[column] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return result


def _normalize_values(
    table: str,
    values: dict[str, Any],
    columns: dict[str, dict[str, Any]],
    *,
    creating: bool,
) -> dict[str, Any]:
    unknown = set(values) - set(columns)
    if unknown:
        raise ValueError(f"Unknown fields for {table}: {', '.join(sorted(unknown))}")
    normalized = dict(values)
    if creating:
        normalized.setdefault("id", new_id())
        if "person_id" in columns:
            normalized.setdefault("person_id", DEFAULT_PERSON_ID)
        now = utc_now()
        if "created_at" in columns:
            normalized.setdefault("created_at", now)
        if "updated_at" in columns:
            normalized.setdefault("updated_at", now)
    else:
        forbidden = PROTECTED_UPDATE_COLUMNS.intersection(normalized)
        if forbidden:
            raise ValueError(f"Cannot update protected fields: {', '.join(sorted(forbidden))}")
        if "updated_at" in columns:
            normalized["updated_at"] = utc_now()
    for column in JSON_COLUMNS.intersection(normalized):
        if not isinstance(normalized[column], str):
            normalized[column] = json_value(normalized[column])
    for column, value in list(normalized.items()):
        if isinstance(value, bool):
            normalized[column] = int(value)
    return normalized


def describe_database(arguments: dict[str, Any]) -> str:
    """Describe database domains, relationships, fields, and safe usage.

    Use this before creating unfamiliar records. Pass domain=person, jobs, or
    learnings to keep the result small. Omit domain for a high-level overview.
    """
    initialize_database()
    domain = str(arguments.get("domain") or "").lower()
    if domain and domain not in DOMAIN_TABLES:
        raise ValueError("domain must be person, jobs, or learnings")
    selected = {domain: DOMAIN_TABLES[domain]} if domain else DOMAIN_TABLES
    result: dict[str, Any] = {
        "rules": [
            "Source facts and AI-derived learnings are different records.",
            "Use profile_fact for direct facts; use learning for interpretations.",
            "Set explicit=true only for statements the user directly made.",
            "Machine-derived claims need confidence and learning_evidence.",
            "Use data_source/source_id to preserve provenance when available.",
            "Job stage changes require both job_process.current_stage and a new job_stage_event.",
            "Submitted materials are immutable; create a new application_material version.",
            "Never infer or use sensitive traits as job filters without explicit user direction.",
        ],
        "domains": {},
    }
    with connect() as connection:
        for domain_name, tables in selected.items():
            domain_result = {}
            for table in tables:
                foreign_keys = [
                    {
                        "field": row["from"],
                        "references": f"{row['table']}.{row['to']}",
                        "onDelete": row["on_delete"],
                    }
                    for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
                ]
                domain_result[table] = {
                    "purpose": TABLE_GUIDANCE[table],
                    "fields": _columns(connection, table),
                    "foreignKeys": foreign_keys,
                }
            result["domains"][domain_name] = domain_result
    return json.dumps(result, ensure_ascii=False)


def list_database_records(arguments: dict[str, Any]) -> str:
    """Read records using exact-match filters.

    Use for known structured lookups such as active job processes, confirmed
    profile facts, or learnings by domain. This intentionally does not accept
    raw SQL. For free-text discovery use search_database instead.
    """
    initialize_database()
    table = _table_name(arguments)
    filters = arguments.get("filters") or {}
    if not isinstance(filters, dict):
        raise ValueError("filters must be an object")
    limit = max(1, min(int(arguments.get("limit") or 25), 100))
    with connect() as connection:
        columns = _columns(connection, table)
        unknown = set(filters) - set(columns)
        if unknown:
            raise ValueError(f"Unknown filter fields for {table}: {', '.join(sorted(unknown))}")
        clauses: list[str] = []
        params: list[Any] = []
        for field, value in filters.items():
            if value is None:
                clauses.append(f'"{field}" IS NULL')
            else:
                clauses.append(f'"{field}" = ?')
                params.append(json_value(value) if field in JSON_COLUMNS and not isinstance(value, str) else value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "updated_at DESC" if "updated_at" in columns else "rowid DESC"
        rows = connection.execute(
            f'SELECT * FROM "{table}"{where} ORDER BY {order} LIMIT ?',
            (*params, limit),
        ).fetchall()
    return json.dumps(
        {"table": table, "count": len(rows), "records": [_decode_row(row) for row in rows]},
        ensure_ascii=False,
    )


def get_database_record(arguments: dict[str, Any]) -> str:
    """Get one record by table and id when an earlier tool returned its id."""
    initialize_database()
    table = _table_name(arguments)
    record_id = str(arguments.get("id") or "")
    if not record_id:
        raise ValueError("id is required")
    with connect() as connection:
        row = connection.execute(
            f'SELECT * FROM "{table}" WHERE id = ?',
            (record_id,),
        ).fetchone()
    return json.dumps(
        {"table": table, "record": _decode_row(row) if row else None},
        ensure_ascii=False,
    )


def create_database_record(arguments: dict[str, Any]) -> str:
    """Create one structured record.

    Call describe_database for the domain first. IDs and timestamps are
    generated automatically; person_id defaults to local-user. Supply referenced
    IDs returned by prior calls. Prefer small atomic profile facts and learnings.
    """
    initialize_database()
    table = _table_name(arguments)
    if table in APP_MANAGED_CREATE_TABLES:
        raise ValueError(
            f"{table} is app-managed. Use Clover's dedicated product tool so history and provenance stay intact."
        )
    values = arguments.get("values") or {}
    if not isinstance(values, dict):
        raise ValueError("values must be an object")
    if table == "learning":
        forbidden = {
            key
            for key in ("review_state", "status", "lifecycle_state")
            if key in values
            and values[key] not in {"unreviewed", "active", "hypothesis"}
        }
        if forbidden:
            raise ValueError(
                "New learnings must begin as active, unreviewed hypotheses. "
                "Use the review operation after the user responds."
            )
    with transaction() as connection:
        columns = _columns(connection, table)
        normalized = _normalize_values(table, values, columns, creating=True)
        names = list(normalized)
        placeholders = ", ".join("?" for _ in names)
        quoted_names = ", ".join(f'"{name}"' for name in names)
        connection.execute(
            f'INSERT INTO "{table}" ({quoted_names}) VALUES ({placeholders})',
            [normalized[name] for name in names],
        )
        row = connection.execute(
            f'SELECT * FROM "{table}" WHERE id = ?',
            (normalized["id"],),
        ).fetchone()
    return json.dumps({"created": _decode_row(row)}, ensure_ascii=False)


def update_database_record(arguments: dict[str, Any]) -> str:
    """Update a mutable record by id.

    Do not rewrite messages, stage history, submitted materials, or evidence;
    append a new record/version instead. Use this for corrections, current job
    stage, review state, next action, status, and other mutable fields.
    """
    initialize_database()
    table = _table_name(arguments)
    if table in IMMUTABLE_UPDATE_TABLES:
        raise ValueError(
            f"{table} is append-only or versioned and cannot be changed through generic database tools."
        )
    record_id = str(arguments.get("id") or "")
    changes = arguments.get("changes") or {}
    if not record_id:
        raise ValueError("id is required")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty object")
    protected = PRODUCT_MANAGED_UPDATE_FIELDS.get(table, set()).intersection(changes)
    if protected:
        raise ValueError(
            f"{table} fields require a dedicated product operation: {', '.join(sorted(protected))}"
        )
    with transaction() as connection:
        columns = _columns(connection, table)
        normalized = _normalize_values(table, changes, columns, creating=False)
        assignments = ", ".join(f'"{name}" = ?' for name in normalized)
        cursor = connection.execute(
            f'UPDATE "{table}" SET {assignments} WHERE id = ?',
            [*normalized.values(), record_id],
        )
        if cursor.rowcount == 0:
            raise ValueError(f"No {table} record found with id {record_id}")
        row = connection.execute(
            f'SELECT * FROM "{table}" WHERE id = ?',
            (record_id,),
        ).fetchone()
    return json.dumps({"updated": _decode_row(row)}, ensure_ascii=False)


def search_database(arguments: dict[str, Any]) -> str:
    """Full-text search conversations, documents, jobs, interactions, and learnings.

    Use this to recall relevant history before answering personal questions,
    tailoring materials, recommending jobs, or creating new learnings. Pass
    scopes to limit retrieval and avoid pulling unrelated personal context.
    """
    initialize_database()
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    requested = arguments.get("scopes") or list(SEARCH_TARGETS)
    if not isinstance(requested, list):
        raise ValueError("scopes must be an array")
    unknown = set(requested) - set(SEARCH_TARGETS)
    if unknown:
        raise ValueError(f"Unknown search scopes: {', '.join(sorted(unknown))}")
    limit = max(1, min(int(arguments.get("limit") or 10), 50))
    process_id = str(arguments.get("opportunityId") or "").strip() or None
    results: dict[str, list[dict[str, Any]]] = {}
    with connect() as connection:
        for scope in requested:
            fts_table, columns = SEARCH_TARGETS[scope]
            selected = ", ".join(f'f."{column}"' for column in columns)
            join = ""
            scope_clause = ""
            params: list[Any] = [query]
            if process_id and scope == "conversations":
                join = "JOIN message m ON m.id = f.message_id JOIN conversation c ON c.id = m.conversation_id"
                scope_clause = "AND c.job_process_id = ?"
                params.append(process_id)
            elif process_id and scope == "jobs":
                join = "JOIN job_process p ON p.job_id = f.job_id"
                scope_clause = "AND p.id = ?"
                params.append(process_id)
            elif process_id and scope == "interactions":
                join = "JOIN job_interaction i ON i.id = f.interaction_id"
                scope_clause = "AND i.process_id = ?"
                params.append(process_id)
            elif process_id and scope == "learnings":
                join = "JOIN learning l ON l.id = f.learning_id"
                scope_clause = "AND (l.scope IN ('person', 'market') OR l.process_id = ?)"
                params.append(process_id)
            params.append(limit)
            rows = connection.execute(
                f"""
                SELECT {selected}, f.rank
                FROM "{fts_table}" AS f
                {join}
                WHERE "{fts_table}" MATCH ?
                {scope_clause}
                ORDER BY f.rank
                LIMIT ?
                """,
                params,
            ).fetchall()
            results[scope] = [dict(row) for row in rows]
    return json.dumps(
        {"query": query, "opportunityId": process_id, "results": results},
        ensure_ascii=False,
    )

