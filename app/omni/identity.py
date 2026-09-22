"""Printed business identifiers from sampled pages (spec §11, §23).

GSTIN is kept only when the 15-character string passes the published checksum.
CIN is format-only. taxID / vatID / leiCode come from Organization schema
fields, not from guessing in body text. Nothing is checked against a
government registry — a matching string is not a verified incorporation.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.engine.collectors.web import _jsonld, _text

GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9])\b")
GSTIN_EXACT = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]$")
CIN_RE = re.compile(r"\b([UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6})\b")
CIN_EXACT = re.compile(r"^[UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")
CIK_LABELED = re.compile(r"\bCIK[:\s#]*(\d{1,10})\b", re.I)
GSTN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ORG_TYPES = {"Organization", "LocalBusiness", "OnlineBusiness", "Corporation"}


class PrintedId(BaseModel):
    kind: str
    value: str
    source: str
    url: str = ""


class IdentityIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    ids: list[PrintedId] = Field(default_factory=list)
    logo_url: str = ""
    methodology: str = (
        "GSTIN rows pass the official check digit. CIN matches the MCA pattern "
        "only. A CIK is kept only when the page printed the word CIK next to "
        "the digits. Schema tax/VAT/LEI fields are copied as printed. Registry "
        "lookups live on filings_intel and run only when an identifier already "
        "exists. Absence is empty, not 'unregistered'.")


def gstin_check_digit(body14: str) -> str:
    """Check character for the first 14 GSTIN characters."""
    factor = 2
    total = 0
    for ch in body14[::-1]:
        code = GSTN_CHARS.index(ch)
        digit = factor * code
        factor = 1 if factor == 2 else 2
        digit = (digit // 36) + (digit % 36)
        total += digit
    return GSTN_CHARS[(36 - (total % 36)) % 36]


def cin_valid(value: str) -> bool:
    """MCA CIN pattern only. Does not query the registry."""
    return bool(CIN_EXACT.match((value or "").strip().upper().replace(" ", "")))


def gstin_valid(value: str) -> bool:
    """Format plus check digit. Does not query the GST portal."""
    text = (value or "").strip().upper()
    if len(text) != 15 or text[13] != "Z":
        return False
    if not GSTIN_EXACT.match(text):
        return False
    try:
        return text[14] == gstin_check_digit(text[:14])
    except ValueError:
        return False


def _type_names(entity: dict) -> list[str]:
    raw = entity.get("@type")
    if isinstance(raw, str):
        return [raw.split("/")[-1]]
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            names.append(item.split("/")[-1])
    return names


def _textish(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("url", "contentUrl", "@id", "name"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def _logo(entity: dict) -> str:
    raw = _textish(entity.get("logo"))
    if raw.startswith("http"):
        return raw.split("#")[0]
    return ""


def extract_schema_ids(entities: list[dict], page_url: str) -> tuple[list[PrintedId], str]:
    """taxID / vatID / leiCode / duns and logo from Organization nodes."""
    ids: list[PrintedId] = []
    logo = ""
    for entity in entities:
        if not (set(_type_names(entity)) & ORG_TYPES):
            continue
        if not logo:
            logo = _logo(entity)
        for field, kind in (
                ("taxID", "tax_id"), ("vatID", "vat_id"),
                ("leiCode", "lei"), ("duns", "duns")):
            value = _textish(entity.get(field))
            if not value:
                continue
            if kind == "tax_id" and gstin_valid(value):
                ids.append(PrintedId(kind="gstin", value=value.upper(),
                                     source="schema", url=page_url))
            else:
                ids.append(PrintedId(kind=kind, value=value[:40],
                                     source="schema", url=page_url))
    return ids, logo


def extract_text_ids(html: str, page_url: str) -> list[PrintedId]:
    """GSTIN (checksum) and CIN (pattern) in visible text."""
    blob = _text(html or "")
    out: list[PrintedId] = []
    for match in GSTIN_RE.finditer(blob.upper()):
        value = match.group(1)
        if gstin_valid(value):
            out.append(PrintedId(kind="gstin", value=value,
                                 source="text", url=page_url))
    for match in CIN_RE.finditer(blob.upper()):
        out.append(PrintedId(kind="cin", value=match.group(1),
                             source="text", url=page_url))
    for match in CIK_LABELED.finditer(blob):
        digits = re.sub(r"\D", "", match.group(1))
        if digits:
            out.append(PrintedId(kind="sec_cik", value=digits.zfill(10),
                                 source="text", url=page_url))
    return out


def analyse_identity(raw_html: list[tuple[str, str]]) -> IdentityIntel:
    """Pure over already-fetched HTML."""
    ids: list[PrintedId] = []
    seen: set[tuple[str, str]] = set()
    logo = ""
    for url, html in raw_html or []:
        entities = [e for e in _jsonld(html or "") if isinstance(e, dict)]
        schema_ids, schema_logo = extract_schema_ids(entities, url)
        if schema_logo and not logo:
            logo = schema_logo
        for row in schema_ids + extract_text_ids(html or "", url):
            key = (row.kind, row.value)
            if key in seen:
                continue
            seen.add(key)
            ids.append(row)
    if logo and ("logo", logo) not in seen:
        ids.append(PrintedId(kind="logo", value=logo, source="schema"))
    if not ids:
        return IdentityIntel(
            assessed=False,
            reason="No GSTIN, CIN or Organization tax/VAT/LEI/logo was printed on sampled pages.",
        )
    return IdentityIntel(assessed=True, ids=ids[:20], logo_url=logo)
