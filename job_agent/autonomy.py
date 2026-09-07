"""Code-level autonomy policy for actions Juno can propose or perform."""

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

AUTOMATIC_READS = {
    "get_opportunities",
    "get_opportunity",
    "read_my_document",
    "search_memory",
    "search_database",
    "describe_database",
    "list_database_records",
    "get_database_record",
    "list_repo_files",
    "read_repo_file",
    "get_system_prompt",
}
AUTOMATIC_LOCAL_RECORDS = {
    "save_opportunity",
    "set_opportunity_stage",
    "add_opportunity_note",
    "save_application_material",
    "remember_about_user",
    "record_progress",
    "save_experience",
    "create_database_record",
    "update_database_record",
}
REVIEW_REQUIRED = {"note_observation"}
APPROVAL_REQUIRED = {
    "submit_application",
    "send_email",
    "send_message",
    "schedule_interview",
    "publish_profile",
    "delete_external_record",
}


def action_class(tool_name: str) -> str:
    if tool_name in AUTOMATIC_READS:
        return "automatic_read"
    if tool_name in AUTOMATIC_LOCAL_RECORDS:
        return "automatic_local_record"
    if tool_name in REVIEW_REQUIRED:
        return "review_required_inference"
    if tool_name in APPROVAL_REQUIRED:
        return "approval_required"
    # Unknown actions get the safest treatment.
    return "approval_required"


def consent_preferences(person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT consent_json FROM person_profile WHERE id = ?",
            (person_id,),
        ).fetchone()
    try:
        data = json.loads(str((row["consent_json"] if row else "") or "{}"))
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def can_run_automatically(tool_name: str, person_id: str = DEFAULT_PERSON_ID) -> bool:
    del person_id
    classification = action_class(tool_name)
    return classification in {
        "automatic_read",
        "automatic_local_record",
        "review_required_inference",
    }


def queue_approval(
    *,
    action_name: str,
    arguments: dict[str, Any],
    explanation: str,
    conversation_id: str | None = None,
    person_id: str = DEFAULT_PERSON_ID,
) -> str:
    if action_class(action_name) != "approval_required":
        raise ValueError("Only consequential actions belong in the approval queue.")
    action_id = new_id()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO pending_action(
                id, person_id, conversation_id, action_name, action_class,
                arguments_json, explanation, status, requested_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'approval_required', ?, ?, 'pending', ?, ?, ?)
            """,
            (
                action_id,
                person_id,
                conversation_id,
                action_name,
                json_value(arguments),
                explanation.strip() or f"Juno wants permission to {action_name}.",
                now,
                now,
                now,
            ),
        )
    return action_id


def list_pending_actions(person_id: str = DEFAULT_PERSON_ID) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, conversation_id, action_name, action_class, arguments_json,
                   explanation, status, requested_at, resolved_at
            FROM pending_action
            WHERE person_id = ? AND status = 'pending'
            ORDER BY requested_at
            """,
            (person_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["arguments"] = json.loads(item.pop("arguments_json"))
        except (json.JSONDecodeError, TypeError):
            item["arguments"] = {}
            item.pop("arguments_json", None)
        result.append(item)
    return result


def resolve_approval(
    action_id: str,
    approved: bool,
    *,
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    now = utc_now()
    with transaction() as connection:
        row = connection.execute(
            """
            SELECT action_name, arguments_json, explanation
            FROM pending_action
            WHERE id = ? AND person_id = ? AND status = 'pending'
            """,
            (action_id, person_id),
        ).fetchone()
        if row is None:
            raise ValueError("That approval request is no longer pending.")
        cursor = connection.execute(
            """
            UPDATE pending_action
            SET status = ?, resolved_at = ?, updated_at = ?
            WHERE id = ? AND person_id = ? AND status = 'pending'
            """,
            ("approved" if approved else "rejected", now, now, action_id, person_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("That approval request is no longer pending.")
    try:
        arguments = json.loads(str(row["arguments_json"] or "{}"))
    except json.JSONDecodeError:
        arguments = {}
    return {
        "id": action_id,
        "approved": approved,
        "actionName": str(row["action_name"]),
        "arguments": arguments if isinstance(arguments, dict) else {},
        "explanation": str(row["explanation"]),
    }


def complete_approval(
    action_id: str,
    *,
    succeeded: bool,
    person_id: str = DEFAULT_PERSON_ID,
) -> None:
    with transaction() as connection:
        connection.execute(
            """
            UPDATE pending_action SET status = ?, updated_at = ?
            WHERE id = ? AND person_id = ? AND status = 'approved'
            """,
            ("completed" if succeeded else "failed", utc_now(), action_id, person_id),
        )
