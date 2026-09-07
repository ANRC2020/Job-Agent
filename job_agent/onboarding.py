"""Meeting Juno.

Onboarding is a short conversation, not a form. It runs entirely locally with
no model call, so a user can meet Juno and tell her about themselves while the
local engine is still warming up in the background.
"""

from __future__ import annotations

import json
from typing import Any

from job_agent.person import remember_fact, set_names
from job_agent.storage import (
    DEFAULT_PERSON_ID,
    add_progress_event,
    connect,
    initialize_database,
    transaction,
    utc_now,
)

# Each step is one thing Juno wants to know, in the order she'd naturally ask.
# `fact` is the profile_fact category the answer becomes.
STEPS: list[dict[str, Any]] = [
    {
        "id": "name",
        "say": [
            "Hi — I'm Juno.",
            "I help with the parts of job searching that are tiring to carry alone: figuring out what "
            "you actually want, finding roles worth your time, and keeping track of everything so you "
            "don't have to.",
            "What should I call you?",
        ],
        "input": "short",
        "placeholder": "Your first name, or whatever you go by",
        "optional": True,
        "skipLabel": "I'd rather not say",
    },
    {
        "id": "situation",
        "say": ["Good to meet you{name}.", "Where are you with work right now?"],
        "input": "choice",
        "choices": [
            "I'm between jobs",
            "I'm working but looking",
            "I'm coming back after a break",
            "I'm not sure yet",
        ],
        "placeholder": "Or describe it in your own words",
        "fact": "situation",
        "optional": True,
    },
    {
        "id": "resume",
        "say": [
            "If you have a resume handy, I'll read it so you never have to retype your history.",
            "A PDF, Word file, or plain text all work. You can also skip this and we'll build it up as we talk.",
        ],
        "input": "resume",
        "optional": True,
        "skipLabel": "I don't have one right now",
    },
    {
        "id": "direction",
        "say": [
            "What kind of work are you hoping to move toward?",
            "A rough answer is fine. \"I don't know\" is also a real answer — plenty of people start there.",
        ],
        "input": "long",
        "choices": ["I honestly don't know yet"],
        "placeholder": "Roles, industries, or just the shape of it",
        "fact": "direction",
        "optional": True,
    },
    {
        "id": "constraints",
        "say": ["Anything that has to be true for a job to work for you?"],
        "input": "long",
        "choices": ["Remote only", "Hybrid is fine", "Needs to be near me", "Nothing rigid"],
        "placeholder": "Location, hours, salary floor, visa, care responsibilities…",
        "fact": "constraint",
        "optional": True,
    },
    {
        "id": "frustration",
        "say": [
            "Last one, and it's optional.",
            "What's been the most draining part of looking so far? Knowing that helps me not add to it.",
        ],
        "input": "long",
        "placeholder": "Applications going nowhere, not knowing what I qualify for, the whole thing…",
        "fact": "frustration",
        "optional": True,
        "skipLabel": "Skip this",
    },
]

# From this step on, Juno already knows enough to be useful.
EARLY_FINISH_FROM = 3

CLOSING = [
    "That's enough for me to start. We can fill in the rest as we go.",
    "Whenever you're ready, bring me a role you're curious about — a link or a pasted description — and "
    "I'll tell you honestly what I think of the fit.",
]


def _state(connection, person_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT onboarding_json FROM person_profile WHERE id = ?",
        (person_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(row["onboarding_json"] or "{}")
    except json.JSONDecodeError:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_state(connection, person_id: str, state: dict[str, Any]) -> None:
    connection.execute(
        "UPDATE person_profile SET onboarding_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(state, ensure_ascii=False), utc_now(), person_id),
    )


def _step_payload(index: int, preferred_name: str) -> dict[str, Any] | None:
    if index >= len(STEPS):
        return None
    step = dict(STEPS[index])
    greeting = f", {preferred_name}" if preferred_name else ""
    step["say"] = [line.replace("{name}", greeting) for line in step["say"]]
    step.pop("fact", None)
    step["index"] = index
    step["total"] = len(STEPS)
    step["canFinishEarly"] = index >= EARLY_FINISH_FROM
    return step


def onboarding_state(person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        state = _state(connection, person_id)
        row = connection.execute(
            "SELECT preferred_name FROM person_profile WHERE id = ?",
            (person_id,),
        ).fetchone()
    preferred_name = str((row["preferred_name"] if row else "") or "")
    status = str(state.get("status") or "not_started")
    index = int(state.get("index") or 0)
    return {
        "status": status,
        "complete": status == "complete",
        "preferredName": preferred_name,
        "step": _step_payload(index, preferred_name) if status != "complete" else None,
        "closing": CLOSING,
    }


def answer(
    step_id: str,
    value: str = "",
    *,
    skipped: bool = False,
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    """Record one answer and hand back the next thing Juno wants to know."""
    initialize_database()
    index = next((position for position, step in enumerate(STEPS) if step["id"] == step_id), None)
    if index is None:
        raise ValueError("Juno isn't asking about that right now.")
    step = STEPS[index]
    clean = (value or "").strip()
    if not clean and not skipped and not step.get("optional"):
        raise ValueError("Juno needs something to go on here.")

    if clean:
        if step_id == "name":
            set_names(preferred_name=clean, person_id=person_id)
        elif step.get("fact"):
            remember_fact(statement=clean, category=str(step["fact"]), person_id=person_id)

    with transaction() as connection:
        state = _state(connection, person_id)
        answers = state.get("answers") if isinstance(state.get("answers"), dict) else {}
        answers[step_id] = {"value": clean, "skipped": bool(skipped and not clean)}
        state.update(
            {
                "status": "in_progress",
                "index": index + 1,
                "answers": answers,
                "startedAt": state.get("startedAt") or utc_now(),
            }
        )
        if index + 1 >= len(STEPS):
            state["status"] = "complete"
            state["completedAt"] = utc_now()
        _save_state(connection, person_id, state)

    if state["status"] == "complete":
        _celebrate(person_id)
    return onboarding_state(person_id)


def finish(person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    """Let the user stop early once Juno has enough to work with."""
    initialize_database()
    with transaction() as connection:
        state = _state(connection, person_id)
        already = state.get("status") == "complete"
        state.update(
            {
                "status": "complete",
                "index": len(STEPS),
                "startedAt": state.get("startedAt") or utc_now(),
                "completedAt": state.get("completedAt") or utc_now(),
            }
        )
        _save_state(connection, person_id, state)
    if not already:
        _celebrate(person_id)
    return onboarding_state(person_id)


def _celebrate(person_id: str) -> None:
    add_progress_event(
        kind="direction",
        headline="Told Juno what you're working toward",
        detail="She'll use this to judge whether a role is actually worth your time.",
        person_id=person_id,
    )
