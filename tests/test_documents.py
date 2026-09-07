from __future__ import annotations

import base64
import os
import tempfile
import unittest
import zipfile
import zlib
from io import BytesIO
from unittest.mock import patch

from job_agent.documents import (
    document_text,
    extract_text,
    refresh_pdf_extractions,
    save_document,
    save_document_base64,
    save_pasted_text,
)
from job_agent.person import profile_overview
from job_agent.storage import connect, initialize_database

RESUME_TEXT = (
    "Sam Rivera\n"
    "Support lead at Northwind, 2019 to 2024.\n"
    "Built the onboarding documentation and ran a team of six.\n"
    "Skills: Zendesk, SQL, technical writing.\n"
)


def build_docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return buffer.getvalue()


def build_pdf(lines: list[str]) -> bytes:
    operators = "BT\n" + "".join(f"({line}) Tj T*\n" for line in lines) + "ET"
    compressed = zlib.compress(operators.encode("latin-1"))
    return b"%PDF-1.4\n4 0 obj\n<< /Length 1 >>\nstream\n" + compressed + b"\nendstream\nendobj\n%%EOF"


class DocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"JOB_AGENT_DATA_DIR": self.temp_dir.name})
        self.env.start()
        initialize_database()

    def tearDown(self) -> None:
        self.env.stop()
        self.temp_dir.cleanup()

    def test_plain_text_is_read_directly(self) -> None:
        self.assertIn("Northwind", extract_text("resume.txt", RESUME_TEXT.encode("utf-8")))

    def test_word_documents_keep_their_paragraphs(self) -> None:
        text = extract_text("resume.docx", build_docx(["Sam Rivera", "Support lead at Northwind"]))

        self.assertIn("Sam Rivera", text)
        self.assertIn("Support lead at Northwind", text)

    def test_word_entities_are_decoded(self) -> None:
        self.assertIn(
            "Research & Development",
            extract_text("resume.docx", build_docx(["Research &amp; Development"])),
        )

    def test_pdf_text_is_pulled_out_of_compressed_streams(self) -> None:
        text = extract_text("resume.pdf", build_pdf(["Sam Rivera", "Support lead at Northwind"]))

        self.assertIn("Sam Rivera", text)
        self.assertIn("Northwind", text)

    def test_existing_pdf_text_is_reextracted_after_parser_upgrade(self) -> None:
        save_document(
            filename="resume.pdf",
            data=build_pdf(RESUME_TEXT.splitlines()),
        )
        with connect() as connection:
            connection.execute(
                "UPDATE person_document SET text_content = 'garbled old extraction'"
            )
            connection.commit()

        self.assertEqual(1, refresh_pdf_extractions())
        self.assertIn("Northwind", document_text())

    def test_unreadable_files_are_saved_with_an_honest_message(self) -> None:
        result = save_document(filename="scan.pdf", data=b"%PDF-1.4 not really a pdf")

        self.assertFalse(result["readable"])
        self.assertIn("couldn't pull clean text", result["message"])
        self.assertIn("paste the contents", result["message"])

    def test_a_readable_resume_is_stored_and_offered_to_juno(self) -> None:
        result = save_document(filename="resume.txt", data=RESUME_TEXT.encode("utf-8"))

        self.assertTrue(result["readable"])
        self.assertIn("Northwind", document_text())
        self.assertEqual(["resume.txt"], [doc["filename"] for doc in profile_overview()["documents"]])

    def test_replacing_a_resume_supersedes_the_previous_one(self) -> None:
        save_document(filename="old.txt", data=RESUME_TEXT.encode("utf-8"))
        second = save_document(filename="new.txt", data=(RESUME_TEXT + "Now also: Python.").encode("utf-8"))

        active = [doc["filename"] for doc in profile_overview()["documents"]]

        self.assertEqual(2, second["version"])
        self.assertEqual(["new.txt"], active)
        self.assertIn("Python", document_text())

    def test_uploading_the_same_file_twice_does_not_duplicate_it(self) -> None:
        save_document(filename="resume.txt", data=RESUME_TEXT.encode("utf-8"))
        save_document(filename="resume.txt", data=RESUME_TEXT.encode("utf-8"))

        self.assertEqual(1, len(profile_overview()["documents"]))

    def test_base64_uploads_from_the_window_are_accepted(self) -> None:
        encoded = base64.b64encode(RESUME_TEXT.encode("utf-8")).decode("ascii")
        result = save_document_base64(filename="resume.txt", content=f"data:text/plain;base64,{encoded}")

        self.assertTrue(result["readable"])

    def test_pasted_text_is_accepted_when_there_is_no_file(self) -> None:
        result = save_pasted_text(text=RESUME_TEXT)

        self.assertTrue(result["readable"])
        self.assertIn("Northwind", document_text())

    def test_a_scrap_of_text_is_turned_down_kindly(self) -> None:
        with self.assertRaises(ValueError) as caught:
            save_pasted_text(text="I did support")

        self.assertIn("a bit short", str(caught.exception))

    def test_oversized_files_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            save_document(filename="huge.txt", data=b"x" * (11 * 1024 * 1024))

    def test_no_resume_reads_as_empty_rather_than_failing(self) -> None:
        self.assertEqual("", document_text())


if __name__ == "__main__":
    unittest.main()
