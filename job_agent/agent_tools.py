"""The actions Juno can take inside Clover.

These sit above the raw table tools on purpose. They encode the behavior we
always want — history stays append-only, materials get versioned, interpretations
land as reviewable observations rather than facts — so Juno gets it right without
having to reason about the schema every turn.
"""

from __future__ import annotations

import json
from typing import Any

from job_agent import opportunities as opp
from job_agent.documents import document_text
from job_agent.person import remember_fact
from job_agent.storage import (
    DEFAULT_PERSON_ID,
    add_progress_event,
    initialize_database,
    new_id,
    progress_recorded_this_turn,
    transaction,
    utc_now,
)

LEARNING_DOMAINS = ("communication", "job_preference", "application", "consistency", "other")


def _ok(message: str, **extra: Any) -> str:
    return json.dumps({"ok": True, "message": message, **extra}, ensure_ascii=False)


def tool_get_opportunities(arguments: dict[str, Any]) -> str:
    """List the user's opportunities and where each one stands."""
    stage = str(arguments.get("stage") or "").strip().lower()
    board = opp.list_opportunities()
    items = board["opportunities"]
    if stage:
        wanted = opp.normalize_stage(stage)
        items = [item for item in items if item["stage"] == wanted]
    return json.dumps(
        {
            "total": len(items),
            "opportunities": [
                {
                    "opportunityId": item["id"],
                    "role": item["title"],
                    "company": item["company"],
                    "stage": item["stageLabel"],
                    "location": item["location"],
                    "compensation": item["compensation"],
                    "fitSummary": item["fitSummary"],
                    "concerns": item["concerns"],
                    "nextAction": item["nextAction"],
                    "updatedAt": item["updatedAt"],
                }
                for item in items[:40]
            ],
        },
        ensure_ascii=False,
    )


def tool_get_opportunity(arguments: dict[str, Any]) -> str:
    """Read the full stored context for one opportunity."""
    process_id = str(arguments.get("opportunityId") or "").strip()
    if not process_id:
        raise ValueError("opportunityId is required")
    detail = opp.get_opportunity(process_id)
    if detail is None:
        return json.dumps({"found": False}, ensure_ascii=False)
    description = detail["description"]
    return json.dumps(
        {
            "found": True,
            "opportunityId": detail["id"],
            "role": detail["title"],
            "company": detail["company"],
            "stage": detail["stageLabel"],
            "location": detail["location"],
            "compensation": detail["compensation"],
            "sourceUrl": detail["sourceUrl"],
            "fitSummary": detail["fitSummary"],
            "whyItFits": detail["why"],
            "concerns": detail["concerns"],
            "standsOut": detail["standouts"],
            "requirements": detail["requirements"][:25],
            "jobDescription": description[:8_000],
            "materials": [
                {"kind": item["kind"], "version": item["version"], "status": item["status"]}
                for item in detail["materials"]
            ],
            "notes": [
                {"when": item["occurred_at"], "kind": item["kind"], "summary": item["summary"]}
                for item in detail["interactions"][:15]
            ],
            "stageHistory": [
                {"from": item["fromLabel"], "to": item["toLabel"], "when": item["occurred_at"]}
                for item in detail["history"][:15]
            ],
        },
        ensure_ascii=False,
    )


def tool_save_opportunity(arguments: dict[str, Any]) -> str:
    """Add a role to the user's opportunities together with your reasoning."""
    result = opp.save_opportunity(
        title=str(arguments.get("role") or ""),
        company=str(arguments.get("company") or ""),
        description=str(arguments.get("jobDescription") or ""),
        source_url=str(arguments.get("sourceUrl") or ""),
        location=arguments.get("location"),
        compensation=arguments.get("compensation"),
        employment_type=str(arguments.get("employmentType") or ""),
        requirements=arguments.get("requirements"),
        stage=str(arguments.get("stage") or "suggested"),
        fit_summary=str(arguments.get("fitSummary") or ""),
        why=arguments.get("whyItFits"),
        concerns=arguments.get("concerns"),
        standouts=arguments.get("standsOut"),
        fit_score=arguments.get("fitScore"),
        next_action=str(arguments.get("nextAction") or ""),
        company_website=str(arguments.get("companyWebsite") or ""),
    )
    verb = "Added" if result["created"] else "Updated"
    return _ok(
        f"{verb} this opportunity in Clover. It now has its own context where everything about it lives.",
        opportunityId=result["id"],
        stage=result["stage"],
    )


def tool_set_opportunity_stage(arguments: dict[str, Any]) -> str:
    """Move an opportunity to a new stage, keeping its history intact."""
    process_id = str(arguments.get("opportunityId") or "").strip()
    if not process_id:
        raise ValueError("opportunityId is required")
    result = opp.set_stage(
        process_id,
        str(arguments.get("stage") or ""),
        reason=str(arguments.get("reason") or ""),
        outcome=str(arguments.get("outcome") or ""),
        actor="juno",
    )
    return _ok(
        f"Moved to {opp.STAGES[result['stage']]}.",
        opportunityId=process_id,
        stage=result["stage"],
    )


def tool_add_opportunity_note(arguments: dict[str, Any]) -> str:
    """Record a note, recruiter message, interview detail, or outcome."""
    process_id = str(arguments.get("opportunityId") or "").strip()
    if not process_id:
        raise ValueError("opportunityId is required")
    kind = str(arguments.get("kind") or "note").strip().lower()
    opp.add_note(process_id, str(arguments.get("text") or ""), kind=kind)
    return _ok("Saved to this opportunity's history.", opportunityId=process_id)


def tool_save_application_material(arguments: dict[str, Any]) -> str:
    """Save a resume, cover letter, or application answer for one opportunity."""
    process_id = str(arguments.get("opportunityId") or "").strip()
    if not process_id:
        raise ValueError("opportunityId is required")
    result = opp.save_material(
        process_id,
        kind=str(arguments.get("kind") or "cover_letter").strip().lower(),
        content=str(arguments.get("content") or ""),
        filename=str(arguments.get("filename") or ""),
    )
    return _ok(
        f"Saved as version {result['version']}. Earlier versions are kept.",
        opportunityId=process_id,
        version=result["version"],
    )


def tool_read_my_document(arguments: dict[str, Any]) -> str:
    """Read the text of the user's stored resume or other document."""
    kind = str(arguments.get("kind") or "resume").strip().lower()
    text = document_text(kind=kind)
    if not text:
        return json.dumps(
            {
                "found": False,
                "message": f"No readable {kind} is on file yet. Ask the user to add one, or to paste it.",
            },
            ensure_ascii=False,
        )
    return json.dumps({"found": True, "kind": kind, "text": text}, ensure_ascii=False)


def tool_remember_about_user(arguments: dict[str, Any]) -> str:
    """Store something the user directly told you about themselves."""
    statement = str(arguments.get("statement") or "").strip()
    if not statement:
        raise ValueError("statement is required")
    category = str(arguments.get("category") or "context").strip().lower()
    remember_fact(statement=statement, category=category, confirmed=True)
    return _ok("Noted — this will show up in how I understand you.")


def tool_note_observation(arguments: dict[str, Any]) -> str:
    """Record a pattern you've inferred, for the user to confirm or correct."""
    claim = str(arguments.get("claim") or "").strip()
    if not claim:
        raise ValueError("claim is required")
    domain = str(arguments.get("domain") or "other").strip().lower()
    if domain not in LEARNING_DOMAINS:
        domain = "other"
    try:
        confidence = float(arguments.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))
    initialize_database()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            """
            INSERT INTO learning(
                id, person_id, domain, claim, confidence, review_state,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'unreviewed', ?, ?)
            """,
            (new_id(), DEFAULT_PERSON_ID, domain, claim, confidence, now, now),
        )
    return _ok(
        "Recorded as something I think I'm seeing. It stays a hunch until they confirm it."
    )


def tool_record_progress(arguments: dict[str, Any]) -> str:
    """Acknowledge real progress, including deciding a role isn't worth pursuing."""
    headline = str(arguments.get("headline") or "").strip()
    if not headline:
        raise ValueError("headline is required")
    # Saving a draft or moving a stage already records the progress it represents.
    # Juno reporting it again in the same turn would show the user one action twice.
    if progress_recorded_this_turn():
        return _ok("Already on their progress from what you just did.")
    add_progress_event(
        kind=str(arguments.get("kind") or "insight").strip().lower(),
        headline=headline,
        detail=str(arguments.get("detail") or "").strip() or None,
        process_id=str(arguments.get("opportunityId") or "").strip() or None,
    )
    return _ok("Added to their progress.")


def tool_save_experience(arguments: dict[str, Any]) -> str:
    """Store a role, project, or education item from the user's background."""
    title = str(arguments.get("title") or "").strip()
    organization = str(arguments.get("organization") or "").strip()
    if not title and not organization:
        raise ValueError("title or organization is required")
    skills = arguments.get("skills") or []
    if isinstance(skills, str):
        skills = [item.strip() for item in skills.split(",") if item.strip()]
    initialize_database()
    now = utc_now()
    with transaction() as connection:
        existing = connection.execute(
            """
            SELECT id FROM experience
            WHERE person_id = ? AND status = 'active'
              AND lower(COALESCE(title, '')) = lower(?)
              AND lower(COALESCE(organization, '')) = lower(?)
            LIMIT 1
            """,
            (DEFAULT_PERSON_ID, title, organization),
        ).fetchone()
        if existing is not None:
            return _ok("Already on file, so I left it as it is.")
        connection.execute(
            """
            INSERT INTO experience(
                id, person_id, kind, organization, title, narrative,
                start_date, end_date, skills_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                DEFAULT_PERSON_ID,
                str(arguments.get("kind") or "role").strip().lower(),
                organization or None,
                title or None,
                str(arguments.get("summary") or "").strip() or None,
                str(arguments.get("startDate") or "").strip() or None,
                str(arguments.get("endDate") or "").strip() or None,
                json.dumps([str(item) for item in skills], ensure_ascii=False),
                now,
                now,
            ),
        )
    return _ok("Added to their background.")


STAGE_ENUM = list(opp.STAGES)

TOOLS: dict[str, dict[str, Any]] = {
    "get_opportunities": {
        "description": (
            "List the user's opportunities with stage, your earlier reasoning, and the next action. "
            "Use before answering anything about what they are pursuing or what to focus on."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": STAGE_ENUM,
                    "description": "Optional stage filter. Omit for everything.",
                }
            },
        },
        "handler": tool_get_opportunities,
    },
    "get_opportunity": {
        "description": (
            "Read one opportunity's full stored context: posting, your take, materials, notes, and "
            "stage history. Use before advising on a specific role so you never ask for what you have."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "opportunityId": {"type": "string", "description": "The opportunity id."}
            },
            "required": ["opportunityId"],
        },
        "handler": tool_get_opportunity,
    },
    "save_opportunity": {
        "description": (
            "Add a role the user brought you or that you are recommending, together with your honest "
            "reasoning. Always fill fitSummary, whyItFits, and concerns — the user sees them and they "
            "are how they decide. Use stage 'suggested' when recommending and 'interested' when the "
            "user has said they want it. Calling this again for the same role updates it."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string", "description": "Job title."},
                "company": {"type": "string", "description": "Company or organization name."},
                "jobDescription": {"type": "string", "description": "Full posting text if available."},
                "sourceUrl": {"type": "string", "description": "Where the posting lives."},
                "location": {
                    "type": "object",
                    "description": "Any of city, region, country, remote (boolean), arrangement, text.",
                    "additionalProperties": True,
                },
                "compensation": {
                    "type": "object",
                    "description": "Any of min, max, currency, period, text.",
                    "additionalProperties": True,
                },
                "employmentType": {"type": "string", "description": "Full-time, contract, part-time."},
                "requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key requirements from the posting.",
                },
                "stage": {"type": "string", "enum": STAGE_ENUM},
                "fitSummary": {
                    "type": "string",
                    "description": "One or two candid sentences on the fit, in your own voice.",
                },
                "whyItFits": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concrete reasons tied to this person's experience.",
                },
                "concerns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What genuinely gives you pause. Do not leave empty to be nice.",
                },
                "standsOut": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Notable details worth their attention.",
                },
                "fitScore": {"type": "number", "description": "0 to 1 confidence in the fit."},
                "nextAction": {"type": "string", "description": "One short, unpressured next step."},
                "companyWebsite": {"type": "string"},
            },
            "required": ["role"],
        },
        "handler": tool_save_opportunity,
    },
    "set_opportunity_stage": {
        "description": (
            "Move an opportunity when the user's situation changes: they want to pursue it, they are "
            "applying, they applied, they are interviewing, or it is over. Use 'closed' with a reason "
            "for rejections and for roles they decided against; both are legitimate outcomes."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "opportunityId": {"type": "string"},
                "stage": {"type": "string", "enum": STAGE_ENUM},
                "reason": {"type": "string", "description": "Short, plain reason in the user's terms."},
                "outcome": {
                    "type": "string",
                    "description": "For closed roles: not_a_fit, declined, withdrawn, rejected, or offer_accepted.",
                },
            },
            "required": ["opportunityId", "stage"],
        },
        "handler": tool_set_opportunity_stage,
    },
    "add_opportunity_note": {
        "description": (
            "Save something that happened on one opportunity: recruiter contact, interview details, "
            "how it went, the user's reaction, or a preparation note. This is the opportunity's memory."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "opportunityId": {"type": "string"},
                "text": {"type": "string", "description": "What happened, in plain language."},
                "kind": {
                    "type": "string",
                    "enum": ["note", "email", "call", "interview", "task", "follow_up", "reflection"],
                },
            },
            "required": ["opportunityId", "text"],
        },
        "handler": tool_add_opportunity_note,
    },
    "save_application_material": {
        "description": (
            "Save a tailored resume, cover letter, or application answer for one opportunity. Save "
            "the full final text, not a summary. Each call keeps the previous version. Required "
            "whenever you write one of these — otherwise the draft exists only in the conversation, "
            "and you must not tell the user it is saved."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "opportunityId": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["resume", "cover_letter", "application_answer", "portfolio", "outreach"],
                },
                "content": {"type": "string", "description": "The full text."},
                "filename": {"type": "string"},
            },
            "required": ["opportunityId", "kind", "content"],
        },
        "handler": tool_save_application_material,
    },
    "read_my_document": {
        "description": (
            "Read the text of the user's stored resume or other document. Use this before tailoring "
            "materials or judging fit, instead of asking them to describe their history again."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["resume", "cover_letter", "portfolio", "bio", "transcript"],
                }
            },
        },
        "handler": tool_read_my_document,
    },
    "remember_about_user": {
        "description": (
            "Store one thing the user directly told you about themselves. Use their own framing. "
            "Only for things they stated — for your own inferences use note_observation instead."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string", "description": "One atomic fact in plain language."},
                "category": {
                    "type": "string",
                    "enum": [
                        "direction",
                        "constraint",
                        "skill",
                        "interest",
                        "frustration",
                        "situation",
                        "context",
                    ],
                },
            },
            "required": ["statement"],
        },
        "handler": tool_remember_about_user,
    },
    "note_observation": {
        "description": (
            "Record a pattern you believe you are seeing but the user has not confirmed. It appears "
            "in their profile as something they can confirm or correct, and never as a fact."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string", "description": "The pattern, stated tentatively."},
                "domain": {"type": "string", "enum": list(LEARNING_DOMAINS)},
                "confidence": {"type": "number", "description": "0 to 1."},
            },
            "required": ["claim"],
        },
        "handler": tool_note_observation,
    },
    "record_progress": {
        "description": (
            "Acknowledge something real the user did: improved a resume, explored a new direction, "
            "prepared for an interview, spotted a skill gap, recovered after a rejection, or decided "
            "a role was not worth pursuing. Never use this to nudge, score, or set targets."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "headline": {"type": "string", "description": "Short, warm, past tense."},
                "detail": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["insight", "resume", "prepared", "direction", "recovery", "skill_gap"],
                },
                "opportunityId": {"type": "string", "description": "If tied to one opportunity."},
            },
            "required": ["headline"],
        },
        "handler": tool_record_progress,
    },
    "save_experience": {
        "description": (
            "Store one role, project, or education item from the user's background, normally while "
            "reading their resume. One call per item."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "organization": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["role", "project", "education", "volunteer", "achievement"],
                },
                "summary": {"type": "string", "description": "What they actually did there."},
                "startDate": {"type": "string", "description": "YYYY or YYYY-MM."},
                "endDate": {"type": "string", "description": "YYYY, YYYY-MM, or empty if current."},
                "skills": {"type": "array", "items": {"type": "string"}},
            },
            "required": [],
        },
        "handler": tool_save_experience,
    },
}
