"""Conservative, evidence-backed learning for Juno.

Learnings are revisable interpretations, never source facts. New observations
start weak and unreviewed; only the user can confirm them. Cross-opportunity
promotion requires repeated independent evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from job_agent.storage import (
    DEFAULT_PERSON_ID,
    connect,
    initialize_database,
    new_id,
    transaction,
    utc_now,
)

DOMAINS = {"communication", "job_preference", "application", "consistency", "other"}
SCOPES = {"person", "opportunity", "market"}
POLARITIES = {"supports", "contradicts", "neutral"}
REVIEW_VERDICTS = {"confirmed", "edited", "disputed", "rejected", "retired"}

EVIDENCE_LOOKUPS = {
    "profile_fact": "SELECT person_id, NULL AS process_id FROM profile_fact WHERE id = ?",
    "job_process": "SELECT person_id, id AS process_id FROM job_process WHERE id = ?",
    "job_interaction": (
        "SELECT p.person_id, i.process_id FROM job_interaction i "
        "JOIN job_process p ON p.id = i.process_id WHERE i.id = ?"
    ),
    "job_stage_event": (
        "SELECT p.person_id, e.process_id FROM job_stage_event e "
        "JOIN job_process p ON p.id = e.process_id WHERE e.id = ?"
    ),
    "application_material": (
        "SELECT p.person_id, m.process_id FROM application_material m "
        "JOIN job_process p ON p.id = m.process_id WHERE m.id = ?"
    ),
    "progress_event": "SELECT person_id, process_id FROM progress_event WHERE id = ?",
    "message": (
        "SELECT c.person_id, c.job_process_id AS process_id FROM message m "
        "JOIN conversation c ON c.id = m.conversation_id WHERE m.id = ?"
    ),
    "learning": "SELECT person_id, process_id FROM learning WHERE id = ?",
    "preference_signal": (
        "SELECT person_id, NULL AS process_id FROM preference_signal WHERE id = ?"
    ),
    "recommendation_feedback": (
        "SELECT person_id, NULL AS process_id FROM recommendation_feedback WHERE id = ?"
    ),
    "performance_metric": (
        "SELECT p.person_id, m.process_id FROM performance_metric m "
        "LEFT JOIN job_process p ON p.id = m.process_id WHERE m.id = ?"
    ),
}


def _clean_claim(claim: str) -> str:
    clean = " ".join((claim or "").split())
    if not clean:
        raise ValueError("claim is required")
    return clean


def _validate_scope(scope: str, process_id: str | None) -> str:
    normalized = (scope or "person").strip().lower()
    if normalized == "user":
        normalized = "person"
    if normalized not in SCOPES:
        raise ValueError("scope must be person, opportunity, or market")
    if normalized == "opportunity" and not process_id:
        raise ValueError("opportunity-scoped learning requires opportunityId")
    return normalized


def _add_evidence(connection, learning_id: str, evidence: dict[str, Any]) -> bool:
    entity_type = str(evidence.get("entityType") or "").strip()
    entity_id = str(evidence.get("entityId") or "").strip()
    if not entity_type or not entity_id:
        raise ValueError("evidence requires entityType and entityId")
    lookup = EVIDENCE_LOOKUPS.get(entity_type)
    if lookup is None:
        raise ValueError(f"unsupported evidence type: {entity_type}")
    learning = connection.execute(
        "SELECT person_id, process_id FROM learning WHERE id = ?",
        (learning_id,),
    ).fetchone()
    record = connection.execute(lookup, (entity_id,)).fetchone()
    if learning is None or record is None:
        raise ValueError("evidence must reference an existing Clover record")
    if str(record["person_id"] or "") != str(learning["person_id"]):
        raise ValueError("evidence belongs to a different person")
    if (
        learning["process_id"]
        and record["process_id"]
        and str(record["process_id"]) != str(learning["process_id"])
    ):
        raise ValueError("evidence belongs to a different opportunity")
    polarity = str(evidence.get("polarity") or "supports").strip().lower()
    if polarity not in POLARITIES:
        raise ValueError("evidence polarity must be supports, contradicts, or neutral")
    try:
        weight = max(0.0, float(evidence.get("weight", 1)))
    except (TypeError, ValueError):
        weight = 1.0
    now = utc_now()
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO learning_evidence(
            id, learning_id, source_id, entity_type, entity_id, polarity,
            weight, excerpt, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            learning_id,
            str(evidence.get("sourceId") or "").strip() or None,
            entity_type,
            entity_id,
            polarity,
            weight,
            str(evidence.get("excerpt") or "").strip()[:1_000] or None,
            now,
            now,
        ),
    )
    return cursor.rowcount > 0


def _refresh_evidence_state(connection, learning_id: str) -> None:
    row = connection.execute(
        """
        SELECT
            SUM(CASE WHEN polarity = 'supports' THEN 1 ELSE 0 END) AS supports,
            SUM(CASE WHEN polarity = 'contradicts' THEN 1 ELSE 0 END) AS contradictions,
            SUM(CASE WHEN polarity = 'supports' THEN weight ELSE 0 END) AS support_weight,
            SUM(CASE WHEN polarity = 'contradicts' THEN weight ELSE 0 END) AS contradiction_weight,
            MAX(created_at) AS latest
        FROM learning_evidence
        WHERE learning_id = ?
        """,
        (learning_id,),
    ).fetchone()
    supports = int(row["supports"] or 0)
    contradictions = int(row["contradictions"] or 0)
    if supports + contradictions == 0:
        return
    support_weight = float(row["support_weight"] or 0)
    contradiction_weight = float(row["contradiction_weight"] or 0)
    current = connection.execute(
        "SELECT confidence, review_state, lifecycle_state, status FROM learning WHERE id = ?",
        (learning_id,),
    ).fetchone()
    if current is None:
        return
    evidence_score = (support_weight + 1) / (support_weight + contradiction_weight + 2)
    ceiling = 0.98 if current["review_state"] in {"confirmed", "edited"} else 0.79
    confidence = min(ceiling, max(0.05, (float(current["confidence"]) + evidence_score) / 2))
    lifecycle = str(current["lifecycle_state"])
    status = str(current["status"])
    if contradictions > supports:
        lifecycle = "disputed"
        status = "disputed"
    elif (
        lifecycle == "disputed"
        and current["review_state"] != "disputed"
        and supports >= contradictions
    ):
        lifecycle = (
            "confirmed"
            if current["review_state"] in {"confirmed", "edited"}
            else "hypothesis"
        )
        status = "active"
    connection.execute(
        """
        UPDATE learning SET support_count = ?, contradiction_count = ?,
            confidence = ?, lifecycle_state = ?, status = ?,
            last_evidence_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            supports,
            contradictions,
            confidence,
            lifecycle,
            status,
            row["latest"],
            utc_now(),
            learning_id,
        ),
    )


def record_hypothesis(
    *,
    claim: str,
    domain: str = "other",
    confidence: float = 0.35,
    scope: str = "person",
    process_id: str | None = None,
    evidence: list[dict[str, Any]] | None = None,
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    """Create or reinforce one unreviewed interpretation."""
    initialize_database()
    clean = _clean_claim(claim)
    normalized_domain = domain if domain in DOMAINS else "other"
    normalized_scope = _validate_scope(scope, process_id)
    bounded_confidence = min(0.6, max(0.05, float(confidence)))
    now = utc_now()
    created = False
    with transaction() as connection:
        existing = connection.execute(
            """
            SELECT id FROM learning
            WHERE person_id = ? AND domain = ? AND scope = ?
              AND COALESCE(process_id, '') = COALESCE(?, '')
              AND lower(trim(claim)) = lower(trim(?))
              AND status IN ('active', 'disputed')
            ORDER BY created_at LIMIT 1
            """,
            (person_id, normalized_domain, normalized_scope, process_id, clean),
        ).fetchone()
        if existing is None:
            learning_id = new_id()
            connection.execute(
                """
                INSERT INTO learning(
                    id, person_id, domain, scope, process_id, claim, confidence,
                    review_state, lifecycle_state, decay_policy, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unreviewed', 'hypothesis', 'standard', ?, ?)
                """,
                (
                    learning_id,
                    person_id,
                    normalized_domain,
                    normalized_scope,
                    process_id,
                    clean,
                    bounded_confidence,
                    now,
                    now,
                ),
            )
            created = True
        else:
            learning_id = str(existing["id"])
        for item in evidence or []:
            _add_evidence(connection, learning_id, item)
        _refresh_evidence_state(connection, learning_id)
        _promote_repeated_pattern(connection, learning_id, person_id)
    return {"id": learning_id, "created": created}


def _promote_repeated_pattern(connection, learning_id: str, person_id: str) -> None:
    source = connection.execute(
        "SELECT domain, claim, scope FROM learning WHERE id = ?",
        (learning_id,),
    ).fetchone()
    if source is None or source["scope"] != "opportunity":
        return
    matches = connection.execute(
        """
        SELECT id, process_id FROM learning
        WHERE person_id = ? AND domain = ? AND scope = 'opportunity'
          AND lower(trim(claim)) = lower(trim(?))
          AND status = 'active' AND support_count > 0
        GROUP BY process_id
        """,
        (person_id, source["domain"], source["claim"]),
    ).fetchall()
    if len({row["process_id"] for row in matches if row["process_id"]}) < 2:
        return
    parent = connection.execute(
        """
        SELECT id FROM learning
        WHERE person_id = ? AND domain = ? AND scope = 'person'
          AND lower(trim(claim)) = lower(trim(?))
          AND status IN ('active', 'disputed')
        LIMIT 1
        """,
        (person_id, source["domain"], source["claim"]),
    ).fetchone()
    now = utc_now()
    if parent is None:
        parent_id = new_id()
        connection.execute(
            """
            INSERT INTO learning(
                id, person_id, domain, scope, claim, confidence, review_state,
                lifecycle_state, decay_policy, created_at, updated_at
            ) VALUES (?, ?, ?, 'person', ?, 0.55, 'unreviewed', 'pattern', 'slow', ?, ?)
            """,
            (parent_id, person_id, source["domain"], source["claim"], now, now),
        )
    else:
        parent_id = str(parent["id"])
    for match in matches:
        _add_evidence(
            connection,
            parent_id,
            {
                "entityType": "learning",
                "entityId": str(match["id"]),
                "polarity": "supports",
                "weight": 1,
                "excerpt": f"Observed in opportunity {match['process_id']}",
            },
        )
    _refresh_evidence_state(connection, parent_id)
    connection.execute(
        "UPDATE learning SET lifecycle_state = 'pattern', updated_at = ? WHERE id = ?",
        (utc_now(), parent_id),
    )


def review_learning(
    learning_id: str,
    verdict: str,
    *,
    edited_claim: str = "",
    note: str = "",
    person_id: str = DEFAULT_PERSON_ID,
) -> None:
    """Apply an explicit user review; model callers cannot invoke this implicitly."""
    normalized = (verdict or "").strip().lower()
    if normalized not in REVIEW_VERDICTS:
        raise ValueError("verdict must be confirmed, edited, disputed, rejected, or retired")
    claim = _clean_claim(edited_claim) if normalized == "edited" else None
    review_state = "rejected" if normalized == "retired" else normalized
    lifecycle = {
        "confirmed": "confirmed",
        "edited": "confirmed",
        "disputed": "disputed",
        "rejected": "retired",
        "retired": "retired",
    }[normalized]
    status = "archived" if normalized in {"rejected", "retired"} else (
        "disputed" if normalized == "disputed" else "active"
    )
    with transaction() as connection:
        cursor = connection.execute(
            """
            UPDATE learning SET
                claim = COALESCE(?, claim),
                review_state = ?,
                lifecycle_state = ?,
                status = ?,
                reviewed_at = ?,
                review_note = ?,
                updated_at = ?
            WHERE id = ? AND person_id = ?
            """,
            (
                claim,
                review_state,
                lifecycle,
                status,
                utc_now(),
                (note or "").strip() or None,
                utc_now(),
                learning_id,
                person_id,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError("Juno no longer has that observation.")


def learning_detail(learning_id: str, person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any] | None:
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM learning WHERE id = ? AND person_id = ?",
            (learning_id, person_id),
        ).fetchone()
        if row is None:
            return None
        evidence = [
            dict(item)
            for item in connection.execute(
                """
                SELECT id, entity_type, entity_id, polarity, weight, excerpt, created_at
                FROM learning_evidence WHERE learning_id = ?
                ORDER BY created_at DESC
                """,
                (learning_id,),
            )
        ]
    result = dict(row)
    result["evidence"] = evidence
    return result


def apply_decay(person_id: str = DEFAULT_PERSON_ID, now: datetime | None = None) -> int:
    """Reduce stale, unreviewed confidence; confirmed user beliefs do not decay."""
    current_time = now or datetime.now(timezone.utc)
    changed = 0
    rates = {"none": 1.0, "slow": 0.98, "standard": 0.94, "fast": 0.85}
    with transaction() as connection:
        rows = connection.execute(
            """
            SELECT id, confidence, decay_policy, lifecycle_state,
                   COALESCE(last_decayed_at, last_evidence_at, updated_at) AS anchor
            FROM learning
            WHERE person_id = ? AND status = 'active'
              AND review_state = 'unreviewed'
            """,
            (person_id,),
        ).fetchall()
        for row in rows:
            try:
                anchor = datetime.fromisoformat(str(row["anchor"]))
                if anchor.tzinfo is None:
                    anchor = anchor.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            periods = max(0, (current_time - anchor).days // 30)
            if periods == 0:
                continue
            confidence = float(row["confidence"]) * rates.get(str(row["decay_policy"]), 0.94) ** periods
            status = "archived" if confidence < 0.15 else "active"
            lifecycle = "retired" if status == "archived" else str(row["lifecycle_state"])
            connection.execute(
                """
                UPDATE learning SET confidence = ?, status = ?, lifecycle_state = ?,
                    last_decayed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    confidence,
                    status,
                    lifecycle,
                    current_time.isoformat(),
                    utc_now(),
                    row["id"],
                ),
            )
            changed += 1
    return changed
