"""Fast, grounded answers for common application fields."""

from __future__ import annotations

import re
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from job_agent.documents import document_file
from job_agent.storage import DEFAULT_PERSON_ID, connect, initialize_database, transaction, utc_now

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
URL = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
BARE_PROFILE_URL = re.compile(
    r"\b(?:www\.)?(?:linkedin\.com/in|github\.com)/[A-Z0-9._~/%+-]+",
    re.IGNORECASE,
)


def _resume_link_annotations(person_id: str) -> list[str]:
    try:
        document = document_file(kind="resume", person_id=person_id)
        if document is None or not str(document["filename"]).casefold().endswith(".pdf"):
            return []
        links: list[str] = []
        for page in PdfReader(BytesIO(document["data"])).pages:
            for annotation_ref in page.get("/Annots") or []:
                annotation = annotation_ref.get_object()
                action = annotation.get("/A")
                uri = str(action.get("/URI") or "") if action else ""
                if uri.startswith(("http://", "https://")):
                    links.append(uri)
        return links
    except Exception:  # noqa: BLE001 - annotations are optional resume metadata
        return []


def answer_key(label: str, field_type: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", (label or "").casefold()).strip()
    return f"{field_type.casefold()}:{normalized}"


def _answer_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (label or "").casefold()).strip()


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
    if re.search(r"\b(portfolio|personal website|website url)\b|^website$", clean):
        return "website"
    if re.search(r"\b(school|university|college)\b", clean):
        return "education_school"
    if re.search(r"\bdegree\b", clean):
        return "education_degree"
    if re.search(r"\b(discipline|major|field of study)\b", clean):
        return "education_discipline"
    if re.search(r"\b(end date year|graduation year)\b", clean):
        return "education_end_year"
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
    urls.extend(
        link
        for link in _resume_link_annotations(person_id)
        if link not in urls
    )
    urls.extend(
        f"https://{item.rstrip('.,;')}"
        for item in BARE_PROFILE_URL.findall(text)
        if not any(item.casefold() in existing.casefold() for existing in urls)
    )
    email = str((person["email"] if person else "") or "").strip()
    if not email:
        match = EMAIL.search(text)
        email = match.group(0) if match else ""
    phone = PHONE.search(text)
    values = {
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
    education_match = re.search(
        r"(?:^|\n)EDUCATION\s*\n(?P<school>[^\n]+)\n"
        r"(?:[●•\-]\s*)?(?P<degree>[^\n]+)",
        text,
        re.IGNORECASE,
    )
    if education_match:
        school_line = education_match.group("school").strip()
        degree_line = education_match.group("degree").strip()
        school = re.split(
            r"\s+(?=(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{4}\b)",
            school_line,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        degree_parts = re.split(r"\s+in\s+", degree_line, maxsplit=1, flags=re.IGNORECASE)
        discipline = (
            re.split(r"\s+GPA\s*:", degree_parts[1], maxsplit=1, flags=re.IGNORECASE)[0].strip()
            if len(degree_parts) == 2
            else ""
        )
        years = re.findall(r"\b(?:19|20)\d{2}\b", school_line)
        values.update(
            {
                "education_school": school,
                "education_degree": degree_parts[0].strip(),
                "education_discipline": discipline,
                "education_end_year": years[-1] if years else "",
            }
        )
    return values


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
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT answer_key, field_label, value, source, confidence
            FROM application_answer
            WHERE person_id = ? AND status = 'active'
            """,
            (person_id,),
        ).fetchall()
    by_key = {str(row["answer_key"]): dict(row) for row in rows}
    by_label = {_answer_label(str(row["field_label"] or "")): dict(row) for row in rows}
    answers = []
    for field, key in zip(fields, keys):
        row = by_key.get(key) or by_label.get(_answer_label(str(field.get("label") or "")))
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


NON_REUSABLE_USER_ANSWER = re.compile(
    r"\b(why (?:do|are|would)|this (?:job|role|company|position)|"
    r"cover letter|tell us|describe (?:a|an|your)|additional information)\b",
    re.IGNORECASE,
)


def remember_user_answers(
    fields: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    person_id: str = DEFAULT_PERSON_ID,
) -> None:
    """Remember explicit, reusable application facts supplied by the person."""
    by_id = {str(item.get("fieldId") or ""): item for item in fields}
    now = utc_now()
    for answer in answers:
        field = by_id.get(str(answer.get("fieldId") or ""))
        value = str(answer.get("value") or "").strip()
        label = str((field or {}).get("label") or "").strip()
        if (
            field is None
            or not value
            or len(value) > 500
            or NON_REUSABLE_USER_ANSWER.search(label)
        ):
            continue
        key = answer_key(label, str(field.get("type") or "text"))
        with transaction() as connection:
            connection.execute(
                """
                INSERT INTO application_answer(
                    person_id, answer_key, field_label, field_type, value,
                    source, confidence, use_count, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'user', 1.0, 1, 'active', ?, ?)
                ON CONFLICT(person_id, answer_key) DO UPDATE SET
                    value = excluded.value,
                    source = 'user',
                    confidence = 1.0,
                    use_count = application_answer.use_count + 1,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    person_id,
                    key,
                    label[:300],
                    str(field.get("type") or "text")[:40],
                    value,
                    now,
                    now,
                ),
            )
