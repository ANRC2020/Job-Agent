"""Typed writers for Clover's canonical opportunity history.

The database intentionally keeps stage changes, interactions, materials,
reactions, and progress in their purpose-built tables. This module is the
single facade callers use so those records cannot drift into a second ledger.
"""

from __future__ import annotations

from typing import Any

from job_agent import opportunities
from job_agent.storage import DEFAULT_PERSON_ID, add_progress_event


def transition_stage(
    process_id: str,
    stage: str,
    *,
    reason: str = "",
    outcome: str = "",
    actor: str = "user",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    """Update current state and append stage history in one transaction."""
    return opportunities.set_stage(
        process_id,
        stage,
        reason=reason,
        outcome=outcome,
        actor=actor,
        person_id=person_id,
    )


def record_interaction(
    process_id: str,
    text: str,
    *,
    kind: str = "note",
    person_id: str = DEFAULT_PERSON_ID,
) -> str:
    """Append an interaction or internal note to one opportunity."""
    return opportunities.add_note(process_id, text, kind=kind, person_id=person_id)


def record_reaction(
    process_id: str,
    reaction: str,
    *,
    person_id: str = DEFAULT_PERSON_ID,
) -> None:
    """Store the user's current reaction without turning it into a preference."""
    opportunities.record_reaction(process_id, reaction, person_id=person_id)


def record_material(
    process_id: str,
    *,
    kind: str,
    content: str,
    filename: str = "",
    person_id: str = DEFAULT_PERSON_ID,
    announce: bool = True,
) -> dict[str, Any]:
    """Create a new material version; existing submitted content is untouched."""
    return opportunities.save_material(
        process_id,
        kind=kind,
        content=content,
        filename=filename,
        person_id=person_id,
        announce=announce,
    )


def record_progress(
    *,
    kind: str,
    headline: str,
    detail: str | None = None,
    process_id: str | None = None,
    person_id: str = DEFAULT_PERSON_ID,
    metadata: Any = None,
) -> str:
    """Append one real progress event with Clover's deduplication policy."""
    return add_progress_event(
        kind=kind,
        headline=headline,
        detail=detail,
        process_id=process_id,
        person_id=person_id,
        metadata=metadata,
    )
