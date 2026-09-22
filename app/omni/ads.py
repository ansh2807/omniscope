"""ads.txt / app-ads.txt records the origin published (spec §11).

IAB rows are copied. DIRECT/RESELLER is a declaration, not spend, not a live
Ads account, and not proof inventory is sold. An HTML error page is not a file.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

ADS_PATHS = ("/ads.txt", "/app-ads.txt")
RELATION = {"direct", "reseller"}


class AdsRow(BaseModel):
    path: str
    exchange: str
    publisher: str
    relationship: str
    authority: str = ""


class AdsVar(BaseModel):
    path: str
    key: str
    value: str


class AdsIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    rows: list[AdsRow] = Field(default_factory=list)
    vars: list[AdsVar] = Field(default_factory=list)
    exchanges: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    methodology: str = (
        "Records are copied from ads.txt and app-ads.txt on this origin. "
        "DIRECT/RESELLER is a published declaration, not ad spend or a "
        "verified Google Ads account. Missing files are empty, not "
        "'they do not advertise'.")


def _looks_html(text: str) -> bool:
    head = (text or "")[:300].lower()
    return "<html" in head or "<!doctype" in head


def parse_ads_txt(text: str, path: str = "/ads.txt") -> tuple[list[AdsRow], list[AdsVar]]:
    """Pure parse of an IAB ads.txt body."""
    if not (text or "").strip() or _looks_html(text):
        return [], []
    rows: list[AdsRow] = []
    variables: list[AdsVar] = []
    seen_row: set[tuple[str, str, str, str]] = set()
    seen_var: set[tuple[str, str]] = set()
    for raw in text.splitlines()[:200]:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "=" in line and "," not in line:
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key and value and (key, value.lower()) not in seen_var:
                seen_var.add((key, value.lower()))
                variables.append(AdsVar(path=path, key=key[:40], value=value[:160]))
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        exchange, publisher, rel = parts[0].lower(), parts[1], parts[2].lower()
        if rel not in RELATION:
            continue
        if "." not in exchange or " " in exchange or " " in publisher:
            continue
        if not publisher or len(publisher) > 80:
            continue
        key = (path, exchange, publisher.lower(), rel)
        if key in seen_row:
            continue
        seen_row.add(key)
        authority = parts[3] if len(parts) > 3 else ""
        rows.append(AdsRow(
            path=path,
            exchange=exchange[:80],
            publisher=publisher[:80],
            relationship=rel.upper(),
            authority=authority[:80],
        ))
        if len(rows) >= 40:
            break
    return rows, variables


def summarise(rows: list[AdsRow], variables: list[AdsVar],
              files: list[str]) -> AdsIntel:
    """Pure. files are paths that were actually served."""
    served = [p for p in files if p in ADS_PATHS]
    if not served and not rows:
        return AdsIntel(
            assessed=True,
            reason="No ads.txt or app-ads.txt was served on this origin.",
        )
    if served and not rows:
        return AdsIntel(
            assessed=True,
            files=served,
            reason="ads.txt was served but contained no IAB records.",
        )
    exchanges: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if row.exchange not in seen:
            seen.add(row.exchange)
            exchanges.append(row.exchange)
    return AdsIntel(
        assessed=True,
        rows=rows[:40],
        vars=variables[:20],
        exchanges=exchanges[:20],
        files=served,
    )
