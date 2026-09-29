"""CV / résumé text extraction and deterministic structured parsing.

Every extracted fact carries an ``evidence`` snippet (the source line) so downstream agents
and human reviewers can verify it — facts are never invented.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass, field
from datetime import date

from app.ai.taxonomy import LANGUAGES, matchers
from app.core.logging import EMAIL_PATTERN

SUPPORTED_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/markdown": "txt",
}


class DocumentParseError(Exception):
    pass


def extract_text(data: bytes, content_type: str) -> str:
    kind = SUPPORTED_TYPES.get(content_type)
    if kind == "pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise DocumentParseError("Encrypted PDFs are not accepted")
            if len(reader.pages) > 50:
                raise DocumentParseError("PDF has too many pages")
            return "\n".join((page.extract_text() or "") for page in reader.pages)
        except PdfReadError as exc:
            raise DocumentParseError("Unreadable PDF") from exc
    if kind == "docx":
        import zipfile

        from docx import Document

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                total = sum(i.file_size for i in zf.infolist())
                if total > 50 * 1024 * 1024:
                    raise DocumentParseError("DOCX expands beyond safe limits")
            doc = Document(io.BytesIO(data))
        except (zipfile.BadZipFile, KeyError, ValueError) as exc:
            raise DocumentParseError("Unreadable DOCX") from exc
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text for c in row.cells))
        return "\n".join(parts)
    if kind == "txt":
        return data.decode("utf-8", errors="replace")
    raise DocumentParseError(f"Unsupported content type {content_type}")


@dataclass
class ExtractedSkill:
    name: str
    category: str
    evidence: str
    mentions: int = 1
    years: float | None = None


@dataclass
class ExperienceEntry:
    title: str | None
    company: str | None
    start: str | None
    end: str | None
    months: int
    evidence: str


@dataclass
class EducationEntry:
    degree: str
    field: str | None
    institution: str | None
    evidence: str


@dataclass
class ParsedCV:
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = field(default_factory=list)
    headline: str | None = None
    skills: list[ExtractedSkill] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    total_years_experience: float | None = None
    stated_years_experience: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


EMAIL_RE = re.compile(EMAIL_PATTERN)
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?)\d{3,4}[\s.-]?\d{3,4}")
URL_RE = re.compile(r"(https?://[^\s,;]+|(?:www\.)?linkedin\.com/in/[^\s,;]+|github\.com/[^\s,;]+)", re.I)
MONTHS = {
    m: i
    for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)
}
DATE_TOKEN = r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?(?:\d{1,2}/)?(?:19|20)\d{2}"
RANGE_RE = re.compile(
    rf"(?P<start>{DATE_TOKEN})\s*(?:-|–|—|to|until)\s*(?P<end>{DATE_TOKEN}|present|current|now|today|date)",
    re.I,
)
STATED_YEARS_RE = re.compile(
    r"(\d{1,2})\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:professional\s+|industry\s+|relevant\s+)?experience", re.I
)
DEGREE_RE = re.compile(
    r"\b(ph\.?d|doctorate|m\.?sc|m\.?s\.?|master(?:'s)?|mba|m\.?eng|b\.?sc|b\.?s\.?|b\.?a\.?|bachelor(?:'s)?|b\.?eng|"
    r"b\.?tech|diploma|associate(?:'s)? degree|hnd|national diploma)\b(?:\s+(?:of|in)\s+(?P<field>[A-Za-z &]+))?",
    re.I,
)
CERT_RE = re.compile(
    r"\b(AWS Certified [A-Za-z -]+|CKA|CKAD|CISSP|CISM|CEH|PMP|PRINCE2|CPA|ACCA|CFA|CIPD|SHRM-CP|SHRM-SCP|"
    r"Azure (?:Administrator|Developer|Solutions Architect)[A-Za-z -]*|Google Cloud [A-Za-z -]+|"
    r"Scrum Master|CSM|ITIL)\b"
)
TITLE_HINT = re.compile(
    r"\b(engineer|developer|manager|analyst|designer|scientist|architect|consultant|lead|director|specialist|"
    r"administrator|officer|coordinator|recruiter|accountant|associate|intern|head of|vp)\b",
    re.I,
)
INSTITUTION_RE = re.compile(
    r"(?:[A-Z][\w&.'-]*\s+){0,4}(?:University|College|Institute|School|Polytechnic|Academy)"
    r"(?:\s+of\s+(?:[A-Z][\w&.'-]*\s?){1,4})?"
)
SECTION_HEADERS = re.compile(
    r"^\s*(experience|work experience|employment|education|skills|projects|certifications|"
    r"languages|summary|profile)\s*:?\s*$",
    re.I,
)


def _parse_date(token: str, *, today: date) -> date | None:
    t = token.strip().lower()
    if t in {"present", "current", "now", "today", "date"}:
        return today
    year_m = re.search(r"(19|20)\d{2}", t)
    if not year_m:
        return None
    year = int(year_m.group(0))
    month = 1
    mon_m = re.match(r"([a-z]{3})", t)
    if mon_m and mon_m.group(1) in MONTHS:
        month = MONTHS[mon_m.group(1)]
    else:
        num_m = re.match(r"(\d{1,2})/", t)
        if num_m and 1 <= int(num_m.group(1)) <= 12:
            month = int(num_m.group(1))
    return date(year, month, 1)


def _months_between(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + (b.month - a.month) + 1)


def _merge_intervals(intervals: list[tuple[date, date]]) -> int:
    """Total months across possibly overlapping employment periods (overlaps counted once)."""
    if not intervals:
        return 0
    intervals.sort()
    total = 0
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += _months_between(cur_s, cur_e)
            cur_s, cur_e = s, e
    total += _months_between(cur_s, cur_e)
    return total


def parse_cv(text: str, *, today: date | None = None) -> ParsedCV:
    today = today or date.today()
    lines = [ln.strip() for ln in text.splitlines()]
    non_empty = [ln for ln in lines if ln]
    result = ParsedCV()

    if m := EMAIL_RE.search(text):
        result.email = m.group(0).lower()
    for m in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 9 <= len(digits) <= 15 and not RANGE_RE.search(m.group(0)):
            result.phone = m.group(0).strip()
            break
    result.links = sorted({u.rstrip(").") for u in URL_RE.findall(text)})

    # Name: first short line with 2-4 capitalised words and no digits/@.
    for ln in non_empty[:6]:
        words = ln.split()
        looks_like_name = 2 <= len(words) <= 4 and all(w[:1].isupper() for w in words)
        if (
            looks_like_name
            and not re.search(r"[\d@|:/]", ln)
            and not SECTION_HEADERS.match(ln)
            and not TITLE_HINT.search(ln)
        ):
            result.full_name = ln
            break
    for ln in non_empty[:8]:
        if TITLE_HINT.search(ln) and len(ln) < 120 and ln != result.full_name and "@" not in ln:
            result.headline = ln
            break
    for ln in non_empty[:10]:
        if m := re.match(r"^(?:location|address|based in)\s*:?\s*(.+)$", ln, re.I):
            result.location = m.group(1).strip()[:200]
            break

    # Skills with evidence.
    lowered_lines = [(ln, ln.lower()) for ln in non_empty]
    for matcher in matchers():
        hits = [ln for ln, _low in lowered_lines if matcher.pattern.search(ln)]
        if hits:
            result.skills.append(
                ExtractedSkill(matcher.canonical, matcher.category, evidence=hits[0][:240], mentions=len(hits))
            )

    # Experience ranges.
    intervals: list[tuple[date, date]] = []
    section = None
    for idx, ln in enumerate(non_empty):
        if header := SECTION_HEADERS.match(ln):
            section = header.group(1).lower()
            continue
        if section in {"education", "certifications", "languages"} or DEGREE_RE.search(ln) or CERT_RE.search(ln):
            continue
        for m in RANGE_RE.finditer(ln):
            start = _parse_date(m.group("start"), today=today)
            end = _parse_date(m.group("end"), today=today)
            if not start or not end or end < start or start > today:
                continue
            context = ln
            title_line = None
            for probe in (
                ln,
                non_empty[idx - 1] if idx > 0 else "",
                non_empty[idx + 1] if idx + 1 < len(non_empty) else "",
            ):
                if probe and TITLE_HINT.search(probe):
                    title_line = probe
                    break
            title, company = None, None
            if title_line:
                cleaned = RANGE_RE.sub("", title_line).strip(" ,|-–—()")
                parts = re.split(r"\s+(?:at|@)\s+|\s*[|,–—-]\s*", cleaned, maxsplit=1)
                title = parts[0].strip()[:160] or None
                company = parts[1].strip()[:160] if len(parts) > 1 and parts[1].strip() else None
            months = _months_between(start, end)
            intervals.append((start, end))
            result.experience.append(
                ExperienceEntry(title, company, start.isoformat(), end.isoformat(), months, evidence=context[:240])
            )
    if intervals:
        result.total_years_experience = round(_merge_intervals(intervals) / 12, 1)
    if m := STATED_YEARS_RE.search(text):
        result.stated_years_experience = float(m.group(1))

    for ln in non_empty:
        for m in DEGREE_RE.finditer(ln):
            fld = re.split(r"\s{2,}|,|\b(?:at|from)\b", (m.group("field") or ""))[0].strip() or None
            inst = None
            if im := INSTITUTION_RE.search(ln):
                inst = im.group(0).strip(" ,|-")
            result.education.append(EducationEntry(m.group(1), fld, inst, evidence=ln[:240]))
            break
    result.certifications = sorted({m.group(0).strip() for m in CERT_RE.finditer(text)})
    result.languages = sorted({lang for lang in LANGUAGES if re.search(rf"\b{lang}\b", text)})
    return result
