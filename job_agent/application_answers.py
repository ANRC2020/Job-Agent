"""Fast, grounded answers for common application fields."""

from __future__ import annotations

import re
from typing import Any

from job_agent.storage import DEFAULT_PERSON_ID, connect, initialize_database, transaction, utc_now

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
URL = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


def answer_key(label: str, field_type: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", (label or "").casefold()).strip()
    return f"{field_type.casefold()}:{normalized}"


def _identity_kind(label: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", " ", (label or "").casefold()).strip()
    if re.search(r"\b(first|given) name\b", clean):
        return "first_name"
    if re.search(r"\b(last|family|surname) name\b", clean):
        return "last_name"
    if re.search(r"\b(full|legal) name\b|^name$", clean):
        return "full_name"
    if re.search(r"\be ?mail(?: address)?\b", clean):
        return "email"
    if re.search(r"\b(phone|mobile|telephone)(?: number)?\b", clean):
        return "phone"
    if "linkedin" in clean:
        return "linkedin"
    if "github" in clean:
        return "github"
    if re.search(r"\b(portfolio|personal website|website url)\b", clean):
        return "website"
    return ""


def _profile_values(person_id: str) -> dict[str, str]:
    initialize_database()
    with connect() as connection:
        person = connection.execute(
            "SELECT display_name, preferred_name, email FROM person_profile WHERE id = ?",
            (person_id,),
        ).fetchone()
        document = connection.execute(
            """
            SELECT text_content FROM person_document
            WHERE person_id = ? AND kind = 'resume' AND status = 'active'
            ORDER BY version DESC, updated_at DESC LIMIT 1
            """,
            (person_id,),
        ).fetchone()
    text = str((document["text_content"] if document else "") or "")
    full_name = str((person["display_name"] if person else "") or "").strip()
    preferred = str((person["preferred_name"] if person else "") or "").strip()
    if len(full_name.split()) < 2:
        for raw_line in text.splitlines()[:15]:
            line = re.sub(r"\s+", " ", raw_line).strip()
            words = line.split()
            if (
                2 <= len(words) <= 5
                and len(line) <= 80
                and (not preferred or preferred.casefold() in line.casefold())
                and not re.search(r"[@:/\d]", line)
            ):
                full_name = line
                break
    parts = full_name.split()
    urls = [item.rstrip(".,;") for item in URL.findall(text)]
    email = str((person["email"] if person else "") or "").strip()
    if not email:
        match = EMAIL.search(text)
        email = match.group(0) if match else ""
    phone = PHONE.search(text)
    return {
        "full_name": full_name or preferred,
        "first_name": parts[0] if parts else preferred,
        "last_name": parts[-1] if len(parts) > 1 else "",
        "email": email,
        "phone": phone.group(0) if phone else "",
        "linkedin": next((item for item in urls if "linkedin.com/" in item.casefold()), ""),
        "github": next((item for item in urls if "github.com/" in item.casefold()), ""),
        "website": next(
            (
                item
                for item in urls
                if "linkedin.com/" not in item.casefold()
                and "github.com/" not in item.casefold()
            ),
            "",
        ),
    }


def quick_answers(
    fields: list[dict[str, Any]],
    person_id: str = DEFAULT_PERSON_ID,
) -> list[dict[str, Any]]:
    values = _profile_values(person_id)
    cached = cached_answers(fields, person_id)
    by_field = {item["fieldId"]: item for item in cached}
    for field in fields:
        field_id = str(field.get("fieldId") or "")
        if not field_id or field_id in by_field or str(field.get("currentValue") or "").strip():
            continue
        kind = _identity_kind(str(field.get("label") or field.get("name") or ""))
        value = values.get(kind, "")
        if value:
            by_field[field_id] = {
                "fieldId": field_id,
                "value": value,
                "source": "profile",
                "confidence": 1.0,
                "rationale": f"Verified {kind.replace('_', ' ')} from your Clover profile.",
            }
    return list(by_field.values())


def cached_answers(
    fields: list[dict[str, Any]],
    person_id: str = DEFAULT_PERSON_ID,
) -> list[dict[str, Any]]:
    if not fields:
        return []
    keys = [answer_key(str(item.get("label") or ""), str(item.get("type") or "text")) for item in fields]
    placeholders = ",".join("?" for _ in keys)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT answer_key, value, source, confidence
            FROM application_answer
            WHERE person_id = ? AND status = 'active' AND answer_key IN ({placeholders})
            """,
            (person_id, *keys),
        ).fetchall()
    by_key = {str(row["answer_key"]): dict(row) for row in rows}
    answers = []
    for field, key in zip(fields, keys):
        row = by_key.get(key)
        if row is None:
            continue
        value = str(row["value"] or "")
        options = [str(item) for item in field.get("options") or []]
        if options and value.casefold() not in {item.casefold() for item in options}:
            continue
        answers.append(
            {
                "fieldId": str(field.get("fieldId") or ""),
                "value": value,
                "source": str(row["source"] or "memory"),
                "confidence": float(row["confidence"] or 0),
                "rationale": "Reused a verified answer from an earlier application.",
            }
        )
    return answers


def remember_answers(
    fields: list[dict[str, Any]],
    suggestions: list[dict[str, Any]],
    person_id: str = DEFAULT_PERSON_ID,
) -> None:
    by_id = {str(item.get("fieldId") or ""): item for item in fields}
    now = utc_now()
    for suggestion in suggestions:
        field = by_id.get(str(suggestion.get("fieldId") or ""))
        source = str(suggestion.get("source") or "")
        confidence = float(suggestion.get("confidence") or 0)
        if (
            field is None
            or not _identity_kind(str(field.get("label") or field.get("name") or ""))
            or source not in {"resume", "memory"}
            or confidence < 0.9
        ):
            continue
        key = answer_key(str(field.get("label") or ""), str(field.get("type") or "text"))
        value = str(suggestion.get("value") or "").strip()
        if not value:
            continue
        with transaction() as connection:
            connection.execute(
                """
                INSERT INTO application_answer(
                    person_id, answer_key, field_label, field_type, value,
                    source, confidence, use_count, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?)
                ON CONFLICT(person_id, answer_key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    confidence = MAX(application_answer.confidence, excluded.confidence),
                    use_count = application_answer.use_count + 1,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    person_id,
                    key,
                    str(field.get("label") or "")[:300],
                    str(field.get("type") or "text")[:40],
                    value[:4000],
                    source,
                    confidence,
                    now,
                    now,
                ),
            )
