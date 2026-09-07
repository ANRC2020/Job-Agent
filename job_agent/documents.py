"""Taking in a resume so the user never has to retype their history.

Text extraction is dependency-free and best-effort. When a file can't be read,
that is reported plainly so Juno can ask for a paste instead of failing silently.
"""

from __future__ import annotations

import base64
import hashlib
import re
import zipfile
import zlib
from io import BytesIO
from typing import Any

from job_agent.storage import (
    DEFAULT_PERSON_ID,
    add_progress_event,
    connect,
    documents_dir,
    initialize_database,
    new_id,
    transaction,
    utc_now,
)

MAX_BYTES = 10 * 1024 * 1024
MIN_USEFUL_CHARS = 120

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rtf", ".csv"}


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _from_docx(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        names = [name for name in ("word/document.xml", "word/document2.xml") if name in archive.namelist()]
        if not names:
            return ""
        xml = archive.read(names[0]).decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        xml = xml.replace(entity, char)
    return _clean(xml)


_PDF_ESCAPES = {
    "n": "\n",
    "r": "\n",
    "t": "\t",
    "b": "",
    "f": "",
    "(": "(",
    ")": ")",
    "\\": "\\",
}


def _pdf_literal(raw: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            nxt = raw[index + 1]
            if nxt in _PDF_ESCAPES:
                out.append(_PDF_ESCAPES[nxt])
                index += 2
                continue
            if nxt.isdigit():
                octal = raw[index + 1 : index + 4]
                match = re.match(r"[0-7]{1,3}", octal)
                if match:
                    out.append(chr(int(match.group(0), 8)))
                    index += 1 + len(match.group(0))
                    continue
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _pdf_text_from_stream(content: str) -> str:
    lines: list[str] = []
    current: list[str] = []
    token = re.compile(
        r"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]+>|\bT[Jj]\b|\bT[Dd]\b|\bT\*\b|\bET\b|\bTf\b"
    )
    for match in token.finditer(content):
        text = match.group(0)
        if text.startswith("("):
            current.append(_pdf_literal(text[1:-1]))
        elif text.startswith("<"):
            hex_digits = re.sub(r"\s+", "", text[1:-1])
            if len(hex_digits) % 2 == 0:
                try:
                    decoded = bytes.fromhex(hex_digits).decode("utf-16-be", errors="replace")
                except ValueError:
                    decoded = ""
                current.append(decoded)
        elif text in {"TD", "Td", "T*", "ET"}:
            if current:
                lines.append("".join(current))
                current = []
    if current:
        lines.append("".join(current))
    return "\n".join(line for line in lines if line.strip())


def _from_pdf(data: bytes) -> str:
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n?(.*?)endstream", data, re.DOTALL):
        raw = match.group(1)
        try:
            decoded = zlib.decompress(raw)
        except zlib.error:
            try:
                decoded = zlib.decompressobj().decompress(raw)
            except zlib.error:
                decoded = raw
        text = decoded.decode("latin-1", errors="replace")
        if "Tj" not in text and "TJ" not in text:
            continue
        extracted = _pdf_text_from_stream(text)
        if extracted:
            chunks.append(extracted)
    return _clean("\n".join(chunks))


def extract_text(filename: str, data: bytes) -> str:
    lowered = filename.lower()
    suffix = lowered[lowered.rfind(".") :] if "." in lowered else ""
    try:
        if suffix == ".docx":
            return _from_docx(data)
        if suffix == ".pdf":
            return _from_pdf(data)
        if suffix in TEXT_SUFFIXES or not suffix:
            return _clean(data.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - extraction is best-effort by design
        return ""
    # Unknown extension: try plain text and let the caller judge the result.
    decoded = _clean(data.decode("utf-8", errors="replace"))
    printable = sum(1 for char in decoded if char.isprintable() or char in "\n\t")
    return decoded if decoded and printable / max(1, len(decoded)) > 0.9 else ""


def save_document(
    *,
    filename: str,
    data: bytes,
    kind: str = "resume",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    """Store a document locally and keep whatever text we could read from it."""
    initialize_database()
    if not data:
        raise ValueError("That file came through empty.")
    if len(data) > MAX_BYTES:
        raise ValueError("That file is larger than 10 MB — try exporting a smaller version.")
    safe_name = (filename or "document").strip().replace("/", "_").replace("\\", "_") or "document"
    digest = hashlib.sha256(data).hexdigest()
    text = extract_text(safe_name, data)
    readable = len(text) >= MIN_USEFUL_CHARS

    target_dir = documents_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = target_dir / f"{digest[:16]}-{safe_name}"
    stored.write_bytes(data)

    now = utc_now()
    with transaction() as connection:
        existing = connection.execute(
            "SELECT id, version FROM person_document WHERE person_id = ? AND kind = ? AND sha256 = ?",
            (person_id, kind, digest),
        ).fetchone()
        if existing is not None:
            document_id = str(existing["id"])
            version = int(existing["version"])
            connection.execute(
                "UPDATE person_document SET status = 'active', updated_at = ? WHERE id = ?",
                (now, document_id),
            )
        else:
            version_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM person_document WHERE person_id = ? AND kind = ?",
                (person_id, kind),
            ).fetchone()
            version = int(version_row["version"]) + 1
            connection.execute(
                """
                UPDATE person_document SET status = 'superseded', updated_at = ?
                WHERE person_id = ? AND kind = ? AND status = 'active'
                """,
                (now, person_id, kind),
            )
            document_id = new_id()
            connection.execute(
                """
                INSERT INTO person_document(
                    id, person_id, kind, filename, storage_uri, text_content,
                    sha256, version, mime_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    person_id,
                    kind,
                    safe_name,
                    str(stored),
                    text or None,
                    digest,
                    version,
                    None,
                    now,
                    now,
                ),
            )

    if readable:
        add_progress_event(
            kind="resume",
            headline="Gave Juno your background",
            detail=safe_name,
            person_id=person_id,
        )
    return {
        "id": document_id,
        "filename": safe_name,
        "kind": kind,
        "version": version,
        "readable": readable,
        "characters": len(text),
        "message": (
            f"Got it — I've read {safe_name} and I'll use it from here on."
            if readable
            else (
                f"I saved {safe_name}, but I couldn't pull clean text out of it. "
                "If you paste the contents into our conversation I'll take it from there."
            )
        ),
    }


def save_document_base64(
    *,
    filename: str,
    content: str,
    kind: str = "resume",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    payload = content.split(",", 1)[-1] if content.startswith("data:") else content
    try:
        data = base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("That file couldn't be read.") from exc
    return save_document(filename=filename, data=data, kind=kind, person_id=person_id)


def save_pasted_text(
    *,
    text: str,
    filename: str = "pasted-resume.txt",
    kind: str = "resume",
    person_id: str = DEFAULT_PERSON_ID,
) -> dict[str, Any]:
    clean = (text or "").strip()
    if len(clean) < 40:
        raise ValueError("That's a bit short for Juno to work from — a few more lines would help.")
    return save_document(
        filename=filename,
        data=clean.encode("utf-8"),
        kind=kind,
        person_id=person_id,
    )


def document_text(
    *,
    kind: str = "resume",
    person_id: str = DEFAULT_PERSON_ID,
    limit: int = 20_000,
) -> str:
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT filename, text_content FROM person_document
            WHERE person_id = ? AND kind = ? AND status = 'active'
            ORDER BY version DESC LIMIT 1
            """,
            (person_id, kind),
        ).fetchone()
    if row is None:
        return ""
    text = str(row["text_content"] or "")
    return text[:limit]
