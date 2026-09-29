from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest
from docx import Document

from app.ai.cv_parser import DocumentParseError, extract_text, parse_cv
from app.core.errors import UnsafeContent, ValidationFailed
from app.domain.enums import ScanStatus
from app.services.files import EICAR, safe_filename, scan_bytes, validate_upload
from tests.factories import SENIOR_CV


def test_parse_cv_extracts_facts_with_evidence() -> None:
    p = parse_cv(SENIOR_CV, today=date(2026, 9, 1))
    assert p.full_name == "Jane Doe"
    assert p.email == "jane.doe@example.com"
    assert p.location == "Cape Town, South Africa"
    names = {s.name for s in p.skills}
    assert {"Python", "PostgreSQL", "Kafka", "Docker", "Kubernetes", "AWS", "FastAPI", "Django", "React"} <= names
    assert all(s.evidence for s in p.skills)
    assert p.total_years_experience == pytest.approx(11.5, abs=0.2)  # 2015-03 → 2026-09, education excluded
    assert p.stated_years_experience == 8
    assert p.experience[0].title == "Senior Software Engineer" and p.experience[0].company == "Acme Corp"
    assert p.education[0].degree == "BSc" and p.education[0].institution == "University of Cape Town"
    assert p.certifications == ["AWS Certified Solutions Architect"]
    assert p.languages == ["Afrikaans", "English"]


def test_overlapping_jobs_not_double_counted() -> None:
    text = "Engineer at A  Jan 2020 - Dec 2021\nConsultant at B  Jun 2020 - Jun 2021\n"
    assert parse_cv(text, today=date(2026, 1, 1)).total_years_experience == 2.0


def test_skill_matching_avoids_false_positives() -> None:
    names = {
        s.name for s in parse_cv("I love going to the gym and reading R.L. Stine books", today=date.today()).skills
    }
    assert "Go" not in names and "R" not in names


def _docx(text: str, macro: bool = False) -> bytes:
    buf = io.BytesIO()
    d = Document()
    d.add_paragraph(text)
    d.save(buf)
    if not macro:
        return buf.getvalue()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("word/vbaProject.bin", b"evil")
    return out.getvalue()


def test_docx_extraction() -> None:
    data = _docx("Python and Kubernetes engineer")
    ctype, name = validate_upload(
        data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "../../etc/cv.docx"
    )
    assert name == "cv.docx"
    assert "Kubernetes" in extract_text(data, ctype)


@pytest.mark.parametrize(
    ("data", "ctype", "name", "err"),
    [
        (b"%PDF-1.4 /JavaScript (app.alert(1))", "application/pdf", "cv.pdf", UnsafeContent),
        (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\xff\xff", "application/pdf", "cv.pdf", UnsafeContent),
        (b"plain text", "text/plain", "cv.exe", UnsafeContent),
        (b"%PDF-1.4 ok", "application/pdf", "cv.txt", UnsafeContent),
        (b"", "text/plain", "cv.txt", ValidationFailed),
    ],
)
def test_upload_rejections(data: bytes, ctype: str, name: str, err: type[Exception]) -> None:
    with pytest.raises(err):
        validate_upload(data, ctype, name)


def test_macro_docx_rejected() -> None:
    with pytest.raises(UnsafeContent, match="macros"):
        validate_upload(
            _docx("x", macro=True), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "cv.docx"
        )


def test_eicar_detected_and_names_sanitized() -> None:
    assert scan_bytes(b"hello " + EICAR).status == ScanStatus.INFECTED
    assert scan_bytes(b"clean").status == ScanStatus.CLEAN
    assert safe_filename('..\\..\\a<b>"c.pdf') == "a_b__c.pdf"


def test_corrupt_pdf_raises_parse_error() -> None:
    with pytest.raises(DocumentParseError):
        extract_text(b"%PDF-1.4 garbage", "application/pdf")
