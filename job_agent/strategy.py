"""Transparent, evidence-thresholded career strategy summaries."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from job_agent.storage import DEFAULT_PERSON_ID, connect, initialize_database

MIN_APPLICATIONS = 3
MIN_ROLE_FAMILY_SAMPLE = 2


def _role_family(title: str) -> str:
    words = [
        word
        for word in re.findall(r"[a-z0-9]+", (title or "").lower())
        if word not in {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "i", "ii", "iii"}
    ]
    return " ".join(words[:3]) or "other"


def strategy_summary(person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    """Compute auditable aggregates without turning sparse data into advice."""
    initialize_database()
    with connect() as connection:
        processes = [
            dict(row)
            for row in connection.execute(
                """
                SELECT p.id, p.current_stage, p.outcome, p.started_at, j.title
                FROM job_process p
                JOIN job j ON j.id = p.job_id
                WHERE p.person_id = ?
                """,
                (person_id,),
            )
        ]
        transitions = [
            dict(row)
            for row in connection.execute(
                """
                SELECT e.id, e.process_id, e.to_stage, e.occurred_at
                FROM job_stage_event e
                JOIN job_process p ON p.id = e.process_id
                WHERE p.person_id = ?
                ORDER BY e.occurred_at
                """,
                (person_id,),
            )
        ]
        materials = [
            dict(row)
            for row in connection.execute(
                """
                SELECT m.id, m.process_id, m.kind, m.version, m.status,
                       p.current_stage, p.outcome
                FROM application_material m
                JOIN job_process p ON p.id = m.process_id
                WHERE p.person_id = ?
                """,
                (person_id,),
            )
        ]
        interview_notes = [
            dict(row)
            for row in connection.execute(
                """
                SELECT i.id, i.process_id, i.summary, i.occurred_at
                FROM job_interaction i
                JOIN job_process p ON p.id = i.process_id
                WHERE p.person_id = ? AND i.kind IN ('interview', 'reflection')
                  AND i.summary IS NOT NULL
                ORDER BY i.occurred_at DESC LIMIT 20
                """,
                (person_id,),
            )
        ]

    reached: dict[str, set[str]] = {}
    for transition in transitions:
        reached.setdefault(str(transition["process_id"]), set()).add(str(transition["to_stage"]))
    applied_ids = {
        process_id
        for process_id, stages in reached.items()
        if stages.intersection({"applied", "screening", "interviewing", "offer"})
    }
    response_ids = {
        process_id
        for process_id, stages in reached.items()
        if stages.intersection({"screening", "interviewing", "offer"})
    }
    interview_ids = {
        process_id
        for process_id, stages in reached.items()
        if stages.intersection({"interviewing", "offer"})
    }
    offer_ids = {process_id for process_id, stages in reached.items() if "offer" in stages}

    families: dict[str, dict[str, Any]] = {}
    process_by_id = {str(item["id"]): item for item in processes}
    for process_id in applied_ids:
        process = process_by_id.get(process_id)
        if not process:
            continue
        family = _role_family(str(process["title"] or ""))
        bucket = families.setdefault(family, {"applications": 0, "responses": 0, "processIds": []})
        bucket["applications"] += 1
        bucket["responses"] += int(process_id in response_ids)
        bucket["processIds"].append(process_id)

    role_families = [
        {
            "roleFamily": family,
            **bucket,
            "responseRate": bucket["responses"] / bucket["applications"],
        }
        for family, bucket in families.items()
        if bucket["applications"] >= MIN_ROLE_FAMILY_SAMPLE
    ]
    role_families.sort(key=lambda item: (-item["responseRate"], -item["applications"], item["roleFamily"]))

    material_outcomes: list[dict[str, Any]] = []
    for material in materials:
        process_id = str(material["process_id"])
        material_outcomes.append(
            {
                "materialId": material["id"],
                "processId": process_id,
                "kind": material["kind"],
                "version": material["version"],
                "status": material["status"],
                "reachedResponse": process_id in response_ids,
                "reachedInterview": process_id in interview_ids,
                "reachedOffer": process_id in offer_ids,
            }
        )

    stage_counts = Counter(str(item["current_stage"]) for item in processes)
    enough = len(applied_ids) >= MIN_APPLICATIONS
    findings: list[dict[str, Any]] = []
    if enough:
        response_rate = len(response_ids) / len(applied_ids)
        findings.append(
            {
                "kind": "response_rate",
                "statement": (
                    f"{len(response_ids)} of {len(applied_ids)} applications reached a recruiter response or later."
                ),
                "value": response_rate,
                "processIds": sorted(applied_ids),
            }
        )
    if len(role_families) >= 2:
        best, worst = role_families[0], role_families[-1]
        if best["responseRate"] - worst["responseRate"] >= 0.25:
            findings.append(
                {
                    "kind": "role_family_difference",
                    "statement": (
                        f"{best['roleFamily']} roles have produced more responses than "
                        f"{worst['roleFamily']} roles in the available sample."
                    ),
                    "roleFamilies": [best, worst],
                }
            )

    return {
        "sample": {
            "opportunities": len(processes),
            "applications": len(applied_ids),
            "responses": len(response_ids),
            "interviews": len(interview_ids),
            "offers": len(offer_ids),
            "enoughForRates": enough,
        },
        "stageCounts": dict(stage_counts),
        "funnel": {
            "applied": len(applied_ids),
            "response": len(response_ids),
            "interview": len(interview_ids),
            "offer": len(offer_ids),
        },
        "roleFamilies": role_families,
        "materialOutcomes": material_outcomes,
        "interviewEvidence": interview_notes,
        "findings": findings,
        "caveat": (
            "These are descriptive local counts, not proof of causation. "
            "No rate is presented until at least three applications exist."
        ),
    }
