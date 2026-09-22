"""Official filings — SEC EDGAR and GLEIF only when an identifier already exists.

CIN is recorded as printed. MCA Master Data is login/captcha-walled, so filing
text stays UNAVAILABLE. Valuation, market cap, share price and headcount are
never copied or invented.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.engine.http import fetch

CIK_RE = re.compile(r"^\d{1,10}$")
LEI_RE = re.compile(r"^[A-Z0-9]{20}$")
_VALUATION = re.compile(
    r"(market.?cap|valuation|share.?price|enterprise.?value|marketvalue)",
    re.I,
)


class FilingId(BaseModel):
    kind: str
    value: str
    source: str
    url: str = ""


class RecentFiling(BaseModel):
    form: str
    filed: str = ""
    accession: str = ""
    url: str = ""


class FilingRecord(BaseModel):
    kind: str
    identifier: str
    source: str
    name: str = ""
    status: str = ""
    detail: str = ""
    official_url: str = ""
    filings: list[RecentFiling] = Field(default_factory=list)
    reason: str = ""


class FilingsIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    identifiers: list[FilingId] = Field(default_factory=list)
    records: list[FilingRecord] = Field(default_factory=list)
    methodology: str = (
        "SEC submissions JSON runs only when a CIK was already printed or on "
        "Wikidata (P5531). GLEIF runs only when an LEI was already printed or "
        "on Wikidata (P1278). CIN is pattern-only; MCA filing text is "
        "unavailable without an official public API. Valuation is never stored."
    )


def cik_normalize(value: str) -> str:
    """Digits only, padded to 10. Empty when the string is not a CIK."""
    text = re.sub(r"\D", "", (value or "").strip())
    if not text or not CIK_RE.fullmatch(text):
        return ""
    return text.zfill(10)


def lei_normalize(value: str) -> str:
    text = re.sub(r"\s+", "", (value or "").strip().upper())
    return text if LEI_RE.fullmatch(text) else ""


def _sec_headers() -> dict[str, str]:
    contact = settings.smtp_from or "noreply@localhost"
    return {
        "User-Agent": (
            f"{settings.app_name}/{settings.app_version} "
            f"({settings.public_base_url}; {contact})"
        ),
        "Accept": "application/json",
    }


def _drop_valuation(payload: Any) -> Any:
    """Strip keys that look like a price or valuation before we copy fields."""
    if isinstance(payload, dict):
        return {
            key: _drop_valuation(val)
            for key, val in payload.items()
            if not _VALUATION.search(str(key))
        }
    if isinstance(payload, list):
        return [_drop_valuation(item) for item in payload]
    return payload


def parse_sec_submissions(payload: dict, cik: str) -> FilingRecord | None:
    """Copy name, SIC, tickers, exchanges, recent forms. No market cap."""
    body = _drop_valuation(payload if isinstance(payload, dict) else {})
    if not isinstance(body, dict):
        return None
    name = str(body.get("name") or "").strip()
    sic = str(body.get("sic") or "").strip()
    sic_desc = str(body.get("sicDescription") or "").strip()
    tickers = [str(t) for t in (body.get("tickers") or []) if t][:8]
    exchanges = [str(x) for x in (body.get("exchanges") or []) if x][:8]
    detail_parts = []
    if sic:
        detail_parts.append(f"SIC {sic}" + (f" {sic_desc}" if sic_desc else ""))
    if tickers:
        detail_parts.append("tickers " + ", ".join(tickers))
    if exchanges:
        detail_parts.append("exchanges " + ", ".join(exchanges))
    recent = ((body.get("filings") or {}) if isinstance(body.get("filings"), dict)
              else {})
    recent = recent.get("recent") if isinstance(recent, dict) else {}
    forms = list(recent.get("form") or []) if isinstance(recent, dict) else []
    dates = list(recent.get("filingDate") or []) if isinstance(recent, dict) else []
    accs = list(recent.get("accessionNumber") or []) if isinstance(recent, dict) else []
    docs = list(recent.get("primaryDocument") or []) if isinstance(recent, dict) else []
    cik_int = str(int(cik)) if cik.isdigit() else cik.lstrip("0") or "0"
    rows: list[RecentFiling] = []
    for i, form in enumerate(forms[:12]):
        form_s = str(form or "").strip()
        if not form_s:
            continue
        filed = str(dates[i] if i < len(dates) else "")[:10]
        accession = str(accs[i] if i < len(accs) else "")
        doc = str(docs[i] if i < len(docs) else "")
        acc_path = accession.replace("-", "")
        url = ""
        if acc_path and doc:
            url = (f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
                   f"{acc_path}/{doc}")
        rows.append(RecentFiling(form=form_s[:20], filed=filed,
                                 accession=accession[:24], url=url))
    if not (name or rows or detail_parts):
        return None
    return FilingRecord(
        kind="sec",
        identifier=cik,
        source="sec_edgar",
        name=name[:160],
        status="observed",
        detail="; ".join(detail_parts)[:240],
        official_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
        filings=rows,
    )


def parse_gleif(payload: dict, lei: str) -> FilingRecord | None:
    """Legal name, status, HQ. Not a valuation or credit score."""
    body = _drop_valuation(payload if isinstance(payload, dict) else {})
    data = body.get("data") if isinstance(body, dict) else None
    attrs = data.get("attributes") if isinstance(data, dict) else None
    if not isinstance(attrs, dict):
        return None
    entity = attrs.get("entity") if isinstance(attrs.get("entity"), dict) else {}
    legal = entity.get("legalName") if isinstance(entity.get("legalName"), dict) else {}
    name = str(legal.get("name") or "").strip()
    status = str(entity.get("status") or "").strip()
    address = entity.get("legalAddress") if isinstance(entity.get("legalAddress"), dict) else {}
    city = str(address.get("city") or "").strip()
    country = str(address.get("country") or "").strip()
    hq = ", ".join(part for part in (city, country) if part)
    jurisdiction = str(entity.get("jurisdiction") or "").strip()
    detail_parts = []
    if hq:
        detail_parts.append(hq)
    if jurisdiction:
        detail_parts.append(f"jurisdiction {jurisdiction}")
    if not (name or status or detail_parts):
        return None
    return FilingRecord(
        kind="gleif",
        identifier=lei,
        source="gleif",
        name=name[:160],
        status=status[:40] or "observed",
        detail="; ".join(detail_parts)[:240],
        official_url=f"https://search.gleif.org/#/record/{lei}",
    )


def identifiers_from(printed: list[Any], official: dict[str, str] | None = None
                     ) -> list[FilingId]:
    """CIK / LEI / CIN already present. No guessed numbers."""
    out: list[FilingId] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: str, source: str, url: str = "") -> None:
        key = (kind, value)
        if not value or key in seen:
            return
        seen.add(key)
        out.append(FilingId(kind=kind, value=value, source=source, url=url[:200]))

    for row in printed or []:
        if isinstance(row, dict):
            kind = str(row.get("kind") or "")
            value = str(row.get("value") or "")
            source = str(row.get("source") or "printed")
            url = str(row.get("url") or "")
        else:
            kind = str(getattr(row, "kind", "") or "")
            value = str(getattr(row, "value", "") or "")
            source = str(getattr(row, "source", "") or "printed")
            url = str(getattr(row, "url", "") or "")
        if kind in {"sec_cik", "cik"}:
            add("sec_cik", cik_normalize(value), source, url)
        elif kind == "lei":
            add("lei", lei_normalize(value), source, url)
        elif kind == "cin":
            add("cin", value.strip().upper(), source, url)
    for kind, value in (official or {}).items():
        if kind in {"sec_cik", "cik"}:
            add("sec_cik", cik_normalize(value), "wikidata")
        elif kind == "lei":
            add("lei", lei_normalize(value), "wikidata")
        elif kind == "cin":
            add("cin", str(value).strip().upper(), "wikidata")
    return out


async def collect_filings(printed: list[Any] | None = None,
                          official: dict[str, str] | None = None) -> FilingsIntel:
    """Fetch official records only for identifiers we already have."""
    ids = identifiers_from(printed or [], official)
    if not ids:
        return FilingsIntel(
            assessed=False,
            reason="No CIK, LEI or CIN was already printed or on Wikidata.",
        )
    records: list[FilingRecord] = []
    for ident in ids:
        if ident.kind == "sec_cik":
            url = f"https://data.sec.gov/submissions/CIK{ident.value}.json"
            page = await fetch(url, check_robots=False, headers=_sec_headers(),
                               use_cache=True)
            if page.ok:
                try:
                    packed = json.loads(page.text)
                except json.JSONDecodeError:
                    packed = {}
                parsed = parse_sec_submissions(packed, ident.value)
                if parsed:
                    records.append(parsed)
                else:
                    records.append(FilingRecord(
                        kind="sec", identifier=ident.value, source="sec_edgar",
                        status="unavailable",
                        reason="SEC returned a body we could not copy."))
            else:
                records.append(FilingRecord(
                    kind="sec", identifier=ident.value, source="sec_edgar",
                    status="unavailable",
                    official_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ident.value}",
                    reason="SEC submissions JSON was not served."))
        elif ident.kind == "lei":
            url = f"https://api.gleif.org/api/v1/lei-records/{ident.value}"
            page = await fetch(url, check_robots=False, use_cache=True)
            if page.ok:
                try:
                    packed = json.loads(page.text)
                except json.JSONDecodeError:
                    packed = {}
                parsed = parse_gleif(packed, ident.value)
                if parsed:
                    records.append(parsed)
                else:
                    records.append(FilingRecord(
                        kind="gleif", identifier=ident.value, source="gleif",
                        status="unavailable",
                        reason="GLEIF returned a body we could not copy."))
            else:
                records.append(FilingRecord(
                    kind="gleif", identifier=ident.value, source="gleif",
                    status="unavailable",
                    official_url=f"https://search.gleif.org/#/record/{ident.value}",
                    reason="GLEIF record was not served."))
        elif ident.kind == "cin":
            records.append(FilingRecord(
                kind="mca", identifier=ident.value, source=ident.source,
                status="unavailable",
                reason=("CIN is recorded as printed. MCA Master Data is "
                        "login/captcha-walled. Filing text and valuation "
                        "are unavailable."),
            ))
    return FilingsIntel(assessed=True, identifiers=ids, records=records)
