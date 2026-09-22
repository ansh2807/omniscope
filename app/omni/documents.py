"""Document intelligence (spec §22) — text extraction, no OCR in this slice.

Supported: digital PDF, DOCX, TXT, CSV, HTML. Scanned PDFs return
INSUFFICIENT EVIDENCE. Award catalog matching reuses the awards engine.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.omni.awards import CATALOG

ALLOWED_SUFFIX = {".pdf", ".docx", ".txt", ".csv", ".html", ".htm"}
MAX_BYTES = 8 * 1024 * 1024
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b",
    re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


class DocumentIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    filename: str = ""
    media_type: str = ""
    chars: int = 0
    excerpt: str = ""
    dates: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    award_hits: list[str] = Field(default_factory=list)
    methodology: str = (
        "Text is extracted from the uploaded digital file. Scanned pages are "
        "not OCRed in this slice. Award names are catalog matches, not a claim "
        "the document proves a win.")


def sniff_suffix(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def extract_text(path: Path, suffix: str) -> str:
    """Read bytes already written to disk. Never follows the original filename."""
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:40])
    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    raw = path.read_bytes()
    if raw[:2] == b"PK" and suffix not in {".docx"}:
        raise ValueError("archive uploads are not accepted")
    return raw.decode("utf-8", errors="replace")


def analyse_text(text: str, *, filename: str, media_type: str) -> DocumentIntel:
    cleaned = (text or "").strip()
    if not cleaned:
        return DocumentIntel(
            assessed=False, filename=filename, media_type=media_type,
            reason="No extractable text. If this is a scan, OCR is not enabled.")
    lower = cleaned.lower()
    awards = [a.name for a in CATALOG if any(alias in lower for alias in a.aliases)]
    dates = list(dict.fromkeys(DATE_RE.findall(cleaned)))[:20]
    emails = list(dict.fromkeys(EMAIL_RE.findall(cleaned)))[:20]
    return DocumentIntel(
        assessed=True,
        filename=filename,
        media_type=media_type,
        chars=len(cleaned),
        excerpt=cleaned[:600],
        dates=dates,
        emails=emails,
        award_hits=awards,
    )
