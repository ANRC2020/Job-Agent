"""Secure, ephemeral bridge for the Clover Chromium companion."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from job_agent import opportunities
from job_agent.chat import complete
from job_agent.context import build_turn_context
from job_agent.storage import (
    DEFAULT_PERSON_ID,
    ensure_thread,
    initialize_database,
    new_id,
    transaction,
    utc_now,
)

PAIRING_TTL_MINUTES = 10
MAX_EXTENSION_BODY_BYTES = 512_000
MAX_PAGE_TEXT_CHARS = 30_000
MAX_FIELDS = 80
MAX_FIELD_VALUE_CHARS = 4_000
READ_ONLY_EXTENSION_TOOLS = ("get_opportunity", "read_my_document", "search_memory")

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
}
SENSITIVE_FIELD_PATTERN = re.compile(
    r"\b(password|passcode|credit|debit|card number|cvv|cvc|bank|routing|"
    r"social security|ssn|national id|government id|passport|driver.?s license|"
    r"race|ethnicity|gender|sex|sexual orientation|disability|veteran|religion|"
    r"date of birth|birth date|medical|health)\b",
    re.IGNORECASE,
)
BLOCKED_FIELD_TYPES = {"password", "hidden", "file", "submit", "reset", "button", "image"}

_rate_lock = threading.Lock()
_rate_events: dict[str, deque[float]] = defaultdict(deque)


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def check_rate_limit(key: str, *, limit: int = 20, window_seconds: int = 60) -> None:
    now = time.monotonic()
    with _rate_lock:
        events = _rate_events[key]
        while events and events[0] <= now - window_seconds:
            events.popleft()
        if len(events) >= limit:
            raise ValueError("Too many extension requests. Wait a moment and try again.")
        events.append(now)


def create_pairing_code(person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    """Create a short-lived code that Clover shows once in Settings."""
    initialize_database()
    code = f"{secrets.randbelow(100_000_000):08d}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=PAIRING_TTL_MINUTES)
    with transaction() as connection:
        connection.execute(
            """
            UPDATE extension_pairing_code
            SET used_at = COALESCE(used_at, ?), updated_at = ?
            WHERE person_id = ? AND used_at IS NULL
            """,
            (now.isoformat(), now.isoformat(), person_id),
        )
        connection.execute(
            """
            INSERT INTO extension_pairing_code(
                id, person_id, code_hash, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                person_id,
                _hash_secret(code),
                expires.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return {"code": code, "expiresAt": expires.isoformat()}


def pair_extension(
    code: str,
    *,
    extension_name: str = "Clover Browser Companion",
    extension_id: str = "",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    check_rate_limit("pair", limit=10, window_seconds=60)
    clean = re.sub(r"\D", "", code or "")
    if len(clean) != 8:
        raise ValueError("Enter the eight-digit code shown in Clover Settings.")
    now = utc_now()
    token = secrets.token_urlsafe(32)
    with transaction() as connection:
        row = connection.execute(
            """
            SELECT id FROM extension_pairing_code
            WHERE person_id = ? AND code_hash = ?
              AND used_at IS NULL AND expires_at > ?
            """,
            (person_id, _hash_secret(clean), now),
        ).fetchone()
        if row is None:
            raise ValueError("That pairing code is invalid or has expired.")
        connection.execute(
            "UPDATE extension_pairing_code SET used_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
        token_id = new_id()
        connection.execute(
            """
            INSERT INTO extension_token(
                id, person_id, extension_name, extension_id, token_hash,
                created_at, last_used_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token_id,
                person_id,
                (extension_name or "Clover Browser Companion").strip()[:120],
                (extension_id or "").strip()[:160] or None,
                _hash_secret(token),
                now,
                now,
                now,
            ),
        )
    return {"token": token, "connectionId": token_id}


def authenticate(authorization: str) -> dict[str, str]:
    initialize_database()
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise PermissionError("Pair the browser companion with Clover first.")
    token_hash = _hash_secret(token.strip())
    now = utc_now()
    with transaction() as connection:
        row = connection.execute(
            """
            SELECT id, person_id, extension_name
            FROM extension_token
            WHERE token_hash = ? AND revoked_at IS NULL
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            raise PermissionError("This browser companion connection is no longer valid.")
        connection.execute(
            "UPDATE extension_token SET last_used_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
    check_rate_limit(f"token:{row['id']}", limit=30, window_seconds=60)
    return {
        "id": str(row["id"]),
        "personId": str(row["person_id"]),
        "name": str(row["extension_name"]),
    }


def list_connections(person_id: str = DEFAULT_PERSON_ID) -> list[dict[str, Any]]:
    initialize_database()
    with transaction() as connection:
        rows = connection.execute(
            """
            SELECT id, extension_name, extension_id, created_at, last_used_at
            FROM extension_token
            WHERE person_id = ? AND revoked_at IS NULL
            ORDER BY COALESCE(last_used_at, created_at) DESC
            """,
            (person_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_connection(connection_id: str, person_id: str = DEFAULT_PERSON_ID) -> None:
    now = utc_now()
    with transaction() as connection:
        cursor = connection.execute(
            """
            UPDATE extension_token SET revoked_at = ?, updated_at = ?
            WHERE id = ? AND person_id = ? AND revoked_at IS NULL
            """,
            (now, now, connection_id, person_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("That browser connection is already gone.")


def normalize_url(url: str) -> str:
    clean = (url or "").strip()
    parsed = urlsplit(clean)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("The active page does not have a usable web address.")
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), ""))


def _safe_field(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    field_id = str(raw.get("fieldId") or "").strip()[:160]
    label = " ".join(str(raw.get("label") or "").split())[:300]
    field_type = str(raw.get("type") or "text").strip().lower()[:40]
    name = str(raw.get("name") or "").strip()[:240]
    combined = f"{label} {name}"
    if (
        not field_id
        or field_type in BLOCKED_FIELD_TYPES
        or SENSITIVE_FIELD_PATTERN.search(combined)
        or bool(raw.get("sensitive"))
    ):
        return None
    try:
        maximum = int(raw.get("maxLength") or 0)
    except (TypeError, ValueError):
        maximum = 0
    return {
        "fieldId": field_id,
        "label": label or name or "Unlabeled field",
        "name": name,
        "type": field_type,
        "required": bool(raw.get("required")),
        "maxLength": max(0, min(maximum, MAX_FIELD_VALUE_CHARS)),
        "currentValue": str(raw.get("currentValue") or "")[:MAX_FIELD_VALUE_CHARS],
        "options": [
            str(option)[:120]
            for option in (raw.get("options") or [])[:30]
            if str(option).strip()
        ],
    }


def sanitize_page(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Page context must be an object.")
    fields = []
    for item in (raw.get("fields") or [])[:MAX_FIELDS]:
        field = _safe_field(item)
        if field is not None:
            fields.append(field)
    return {
        "url": normalize_url(str(raw.get("url") or "")),
        "title": " ".join(str(raw.get("title") or "").split())[:500],
        "company": " ".join(str(raw.get("company") or "").split())[:300],
        "postingText": str(raw.get("postingText") or "")[:MAX_PAGE_TEXT_CHARS],
        "fields": fields,
        "capturedAt": str(raw.get("capturedAt") or "")[:80],
    }


def resolve_page(raw_page: Any, person_id: str = DEFAULT_PERSON_ID) -> dict[str, Any]:
    page = sanitize_page(raw_page)
    match = opportunities.find_process_by_source_url(page["url"], person_id=person_id)
    if match is None:
        for item in opportunities.list_opportunities(person_id)["opportunities"]:
            try:
                candidate = normalize_url(str(item.get("sourceUrl") or ""))
            except ValueError:
                continue
            if candidate == page["url"]:
                match = item
                break
    return {"page": page, "matched": match is not None, "opportunity": match}


def _page_context(
    page: dict[str, Any],
    *,
    person_id: str,
    opportunity_id: str | None,
    task: str,
) -> tuple[str, str]:
    thread_id = (
        opportunities.thread_id(opportunity_id, person_id=person_id)
        if opportunity_id
        else ensure_thread(kind="juno", title="Juno", person_id=person_id)
    )
    context = build_turn_context(
        person_id=person_id,
        conversation_id=thread_id,
        process_id=opportunity_id,
        task=task,
        ephemeral={"browserPage": page},
    )
    return thread_id, context


def analyze_page(
    raw_page: Any,
    *,
    question: str = "",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    resolved = resolve_page(raw_page, person_id)
    opportunity = resolved["opportunity"] or {}
    opportunity_id = str(opportunity.get("id") or "") or None
    task = (question or "").strip() or (
        "Assess this job page candidly. Explain the strongest fit, the main concern, "
        "and one useful next step. Do not claim the job is saved."
    )
    _, context = _page_context(
        resolved["page"],
        person_id=person_id,
        opportunity_id=opportunity_id,
        task=task,
    )
    result = complete(
        [{"role": "user", "content": task}],
        context=context,
        tool_names=READ_ONLY_EXTENSION_TOOLS,
        opportunity_id=opportunity_id,
    )
    return {
        "content": result["content"],
        "matchedOpportunityId": opportunity_id,
        "page": {
            "url": resolved["page"]["url"],
            "title": resolved["page"]["title"],
            "company": resolved["page"]["company"],
            "fieldCount": len(resolved["page"]["fields"]),
        },
    }


def _parse_object(text: str) -> dict[str, Any]:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        finish = clean.rfind("}")
        if start < 0 or finish <= start:
            raise ValueError("Juno did not return structured field answers.") from None
        try:
            parsed = json.loads(clean[start : finish + 1])
        except json.JSONDecodeError as exc:
            raise ValueError("Juno did not return valid structured field answers.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Juno did not return a field-answer object.")
    return parsed


def suggest_fields(
    raw_page: Any,
    *,
    instructions: str = "",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    resolved = resolve_page(raw_page, person_id)
    page = resolved["page"]
    empty_fields = [
        field for field in page["fields"] if not field["currentValue"].strip()
    ][:50]
    if not empty_fields:
        return {"suggestions": [], "skipped": "No safe empty fields were found."}
    opportunity = resolved["opportunity"] or {}
    opportunity_id = str(opportunity.get("id") or "") or None
    field_contract = [
        {
            "fieldId": field["fieldId"],
            "label": field["label"],
            "type": field["type"],
            "required": field["required"],
            "maxLength": field["maxLength"],
            "options": field["options"],
        }
        for field in empty_fields
    ]
    task = (
        "Generate application-form answers grounded only in the resume, confirmed memories, "
        "confirmed learnings, and this page. Never invent credentials or protected-trait answers. "
        "Return JSON only with this shape: "
        '{"fields":[{"fieldId":"exact id","value":"answer","rationale":"brief basis",'
        '"source":"resume|memory|opportunity|inferred","confidence":0.0}]}. '
        f"Allowed fields: {json.dumps(field_contract, ensure_ascii=False)}. "
        f"Additional user instructions: {(instructions or '').strip()[:1000]}"
    )
    _, context = _page_context(
        page,
        person_id=person_id,
        opportunity_id=opportunity_id,
        task="Generate safe application field answers",
    )
    result = complete(
        [{"role": "user", "content": task}],
        context=context,
        tool_names=READ_ONLY_EXTENSION_TOOLS,
        opportunity_id=opportunity_id,
    )
    parsed = _parse_object(result["content"])
    by_id = {field["fieldId"]: field for field in empty_fields}
    suggestions = []
    seen = set()
    for raw in parsed.get("fields") or []:
        if not isinstance(raw, dict):
            continue
        field_id = str(raw.get("fieldId") or "")
        field = by_id.get(field_id)
        if field is None or field_id in seen:
            continue
        value = str(raw.get("value") or "").strip()
        maximum = field["maxLength"]
        if maximum:
            value = value[:maximum]
        else:
            value = value[:MAX_FIELD_VALUE_CHARS]
        if field["type"] == "select" and field["options"]:
            selected = next(
                (option for option in field["options"] if option.casefold() == value.casefold()),
                None,
            )
            if selected is None:
                continue
            value = selected
        if not value:
            continue
        try:
            confidence = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        source = str(raw.get("source") or "inferred").lower()
        if source not in {"resume", "memory", "opportunity", "inferred"}:
            source = "inferred"
        suggestions.append(
            {
                "fieldId": field_id,
                "value": value,
                "rationale": str(raw.get("rationale") or "")[:500],
                "source": source,
                "confidence": confidence,
            }
        )
        seen.add(field_id)
    return {"suggestions": suggestions, "matchedOpportunityId": opportunity_id}


def save_page_opportunity(
    raw_page: Any,
    *,
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    page = sanitize_page(raw_page)
    existing = resolve_page(page, person_id)["opportunity"]
    if existing is not None:
        return {**existing, "created": False}
    return opportunities.save_opportunity(
        title=page["title"] or "Untitled opportunity",
        company=page["company"],
        description=page["postingText"],
        source_url=page["url"],
        stage="interested",
        person_id=person_id,
    )
