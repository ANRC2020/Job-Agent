"""The calm overview: where things stand, one honest observation, one next step.

Observations are computed locally from stored data rather than generated, so
Home is instant, stable, and never says something the data doesn't support.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from job_agent.onboarding import onboarding_state
from job_agent.opportunities import list_opportunities, needs_attention
from job_agent.person import profile_overview
from job_agent.storage import DEFAULT_PERSON_ID, connect, initialize_database, list_progress_events


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _days_since(value: Any) -> int | None:
    parsed = _parse(value)
    if parsed is None:
        return None
    return max(0, (datetime.now(timezone.utc) - parsed).days)


def _greeting(name: str) -> str:
    hour = datetime.now().hour
    if hour < 12:
        part = "Good morning"
    elif hour < 18:
        part = "Good afternoon"
    else:
        part = "Good evening"
    return f"{part}, {name}" if name else part


def _stated_preferences(person_id: str) -> str:
    with connect() as connection:
        facts = connection.execute(
            "SELECT statement FROM profile_fact WHERE person_id = ? AND status = 'active'",
            (person_id,),
        ).fetchall()
        learnings = connection.execute(
            """
            SELECT claim FROM learning
            WHERE person_id = ? AND status = 'active' AND review_state IN ('confirmed', 'edited')
            """,
            (person_id,),
        ).fetchall()
    parts = [str(row["statement"]) for row in facts] + [str(row["claim"]) for row in learnings]
    return " ".join(parts).lower()


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _observation(
    opportunities: list[dict[str, Any]],
    preferences: str,
    progress: list[dict[str, Any]],
    profile_known: bool,
) -> dict[str, Any] | None:
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for item in opportunities:
        by_stage.setdefault(item["stage"], []).append(item)

    interviewing = by_stage.get("interviewing", []) + by_stage.get("offer", [])
    if interviewing:
        role = interviewing[0]
        return {
            "text": (
                f"You have an interview process moving with {role['company']}. "
                "Preparing a little now tends to feel better than preparing a lot later."
            ),
            "action": {
                "kind": "opportunity",
                "id": role["id"],
                "label": "Prepare with Juno",
            },
        }

    recent_close = next(
        (event for event in progress if event["kind"] == "closed" and (_days_since(event["occurred_at"]) or 99) <= 7),
        None,
    )
    if recent_close:
        return {
            "text": (
                "You closed something out this week. That's a real decision, not a setback — "
                "and it's fine if the next move takes a few days."
            ),
            "action": {
                "kind": "juno",
                "label": "Talk it through",
                "prompt": "I want to talk about the role I just closed out.",
            },
        }

    saved = (
        by_stage.get("interested", [])
        + by_stage.get("applying", [])
        + by_stage.get("applied", [])
    )
    if "remote" in preferences:
        not_remote = [
            item
            for item in saved
            if item["location"] and "remote" not in item["location"].lower()
        ]
        if len(not_remote) >= 2:
            return {
                "text": (
                    f"You've told me remote work matters, but {len(not_remote)} of the roles you've saved "
                    "lately aren't remote. I'm not sure whether your preference shifted or these were "
                    "worth an exception."
                ),
                "action": {
                    "kind": "juno",
                    "label": "Clear this up",
                    "prompt": "Let's talk about whether remote work is still a hard requirement for me.",
                },
            }

    stale = [
        item
        for item in by_stage.get("applied", [])
        if (_days_since(item["updatedAt"]) or 0) >= 14
    ]
    if stale:
        role = stale[0]
        days = _days_since(role["updatedAt"])
        return {
            "text": (
                f"It's been about {days} days since you applied to {role['title']}. "
                "Silence this long usually says more about their process than about you."
            ),
            "action": {
                "kind": "opportunity",
                "id": role["id"],
                "label": "Open it",
            },
        }

    interested = by_stage.get("interested", [])
    if len(interested) >= 3 and not by_stage.get("applying") and not by_stage.get("applied"):
        return {
            "text": (
                f"You have {len(interested)} roles saved and haven't started an application yet. "
                "Starting one is usually easier than choosing between all of them."
            ),
            "action": {
                "kind": "opportunity",
                "id": interested[0]["id"],
                "label": f"Start with {interested[0]['company']}",
            },
        }

    suggested = by_stage.get("suggested", [])
    if suggested:
        count = len(suggested)
        return {
            "text": (
                f"{count} {_plural(count, 'role')} {_plural(count, 'is', 'are')} waiting on a yes or no "
                "from you. Passing on one is a decision too, and it clears space."
            ),
            "action": {"kind": "route", "route": "opportunities", "label": "Take a look"},
        }

    if not opportunities and profile_known:
        return {
            "text": (
                "I know enough about you to weigh roles properly now. Bring me one you're curious "
                "about — a link or a pasted description — and I'll tell you what I actually think."
            ),
            "action": {"kind": "add", "label": "Add a role"},
        }

    if not opportunities:
        return {
            "text": (
                "We've only just met, so I'd rather ask than assume. Tell me about the work you're "
                "circling and I'll start from there."
            ),
            "action": {
                "kind": "juno",
                "label": "Talk to Juno",
                "prompt": "I'm not sure what I'm looking for yet.",
            },
        }
    return None


def _target(action: dict[str, Any] | None) -> tuple[str, str]:
    """What an action actually points at, so the same ask isn't made twice."""
    if not action:
        return ("", "")
    kind = str(action.get("kind") or "")
    return (kind, str(action.get("id") or action.get("route") or ""))


def _next_action(
    attention: list[dict[str, Any]],
    opportunities: list[dict[str, Any]],
    observation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if attention:
        role = attention[0]
        candidate = {
            "text": role["nextAction"],
            "context": f"{role['title']} · {role['company']}",
            "action": {"kind": "opportunity", "id": role["id"], "label": "Open"},
        }
    elif not opportunities:
        candidate = {
            "text": "Add the first role you're curious about",
            "context": "A link or a pasted description is enough",
            "action": {"kind": "add", "label": "Add a role"},
        }
    else:
        return None

    # Juno already said it in her own voice; repeating it as a task is noise.
    if _target(candidate["action"]) == _target((observation or {}).get("action")):
        return None
    return candidate


def home_overview(person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    initialize_database()
    onboarding = onboarding_state(person_id)
    profile = profile_overview(person_id)
    board = list_opportunities(person_id)
    progress = list_progress_events(person_id=person_id, limit=6)
    attention = needs_attention(person_id, limit=3)
    name = onboarding["preferredName"] or profile["preferredName"]
    profile_known = not profile["isEmpty"]
    observation = _observation(
        board["opportunities"],
        _stated_preferences(person_id),
        progress,
        profile_known,
    )

    return {
        "greeting": _greeting(name),
        "preferredName": name,
        "observation": observation,
        "attention": attention,
        "progress": progress,
        "nextAction": _next_action(attention, board["opportunities"], observation),
        "lanes": board["lanes"],
        "totalOpportunities": board["total"],
        "onboardingComplete": onboarding["complete"],
    }
