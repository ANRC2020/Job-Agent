"""Small, event-triggered reflection prompts.

Reflection asks for meaning after a meaningful event; it does not infer that
meaning on the user's behalf and it never runs on ordinary chat turns.
"""

from __future__ import annotations

from typing import Any

from job_agent import opportunities
from job_agent.storage import DEFAULT_PERSON_ID

MEANINGFUL_STAGES = {
    "applied": "Now that it’s sent, is there anything about this application you’d want to do differently next time?",
    "screening": "What did the recruiter seem most interested in?",
    "interviewing": "What felt strong in that conversation, and what felt harder than expected?",
    "offer": "Before we evaluate the offer itself, what is your honest first reaction?",
    "closed": "Do you want to capture anything useful from how this ended, or leave it here for now?",
}


def reflection_for_stage(
    process_id: str,
    stage: str,
    *,
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any] | None:
    normalized = opportunities.normalize_stage(stage)
    prompt = MEANINGFUL_STAGES.get(normalized)
    if not prompt:
        return None
    detail = opportunities.get_opportunity(process_id, person_id)
    if detail is None:
        return None
    return {
        "opportunityId": process_id,
        "stage": normalized,
        "prompt": prompt,
        "role": detail["title"],
        "company": detail["company"],
    }
