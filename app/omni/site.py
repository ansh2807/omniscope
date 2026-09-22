"""Public site signals: robots.txt, conventional well-known files, HTTP headers.

These are published directives and files, not a security audit or crawl-through
map. Missing files stay missing. We do not invent /admin or hidden inventory.
"""
from __future__ import annotations

from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.engine.http import fetch
from app.omni.ads import ADS_PATHS, AdsRow, AdsVar, parse_ads_txt

PUBLISHED_FILES = (
    "/ads.txt",
    "/app-ads.txt",
    "/humans.txt",
)

SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
)

WELL_KNOWN = (
    "/.well-known/security.txt",
    "/llms.txt",
    "/ai.txt",
    "/.well-known/change-password",
    "/.well-known/gpc.json",
)
FALLBACK_SECURITY = "/security.txt"

FILE_ROLES = {
    "/.well-known/security.txt": "trust",
    "/security.txt": "trust",
    "/llms.txt": "ai",
    "/ai.txt": "ai",
    "/humans.txt": "people",
    "/ads.txt": "ads",
    "/app-ads.txt": "ads",
    "/.well-known/change-password": "privacy",
    "/.well-known/gpc.json": "privacy",
}

SECURITY_FIELDS = (
    "contact", "expires", "encryption", "acknowledgments", "preferred-languages",
    "canonical", "policy", "hiring",
)


class RobotsIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    sitemaps: list[str] = Field(default_factory=list)
    disallow: list[str] = Field(default_factory=list)
    allow: list[str] = Field(default_factory=list)
    user_agents: list[str] = Field(default_factory=list)
    crawl_delay: str = ""
    methodology: str = (
        "Lines are copied from robots.txt. Disallow is a published directive, "
        "not a list of secret pages. Crawl-delay is recorded, not used to "
        "override this engine's own throttle.")


class HeaderIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    present: dict[str, str] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    last_modified: str = ""
    etag: str = ""
    date: str = ""
    cache_control: str = ""
    x_robots_tag: str = ""
    csp_hosts: list[str] = Field(default_factory=list)
    methodology: str = (
        "Security and freshness headers captured on the homepage response we "
        "already fetched. Last-Modified is the header value, not a verified "
        "edit. CSP hosts are policy tokens, not a live load list or vendor "
        "contract. Absence is not a vulnerability score.")


class PublicFile(BaseModel):
    path: str
    present: bool = False
    status: int = 0
    excerpt: str = ""
    contacts: list[str] = Field(default_factory=list)
    role: str = ""
    fields: dict[str, str] = Field(default_factory=dict)
    credits: list[str] = Field(default_factory=list)


class PublicIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    files: list[PublicFile] = Field(default_factory=list)
    hits: list[str] = Field(default_factory=list)
    present_n: int = 0
    ads: list[AdsRow] = Field(default_factory=list)
    ads_vars: list[AdsVar] = Field(default_factory=list)
    inventory: list[dict[str, str]] = Field(default_factory=list)
    methodology: str = (
        "RFC 9116 security.txt (well-known, then /security.txt), /llms.txt, "
        "/ai.txt, /.well-known/change-password, /.well-known/gpc.json, "
        "/ads.txt, /app-ads.txt and /humans.txt. These conventional paths are "
        "checked the same way as robots.txt. Other well-known files are not invented. "
        "Roles are trust / AI-surface / people / ads / privacy. "
        "llms.txt is a crawl invitation, not traffic. "
        "A Contact: line is not a SOC 2 badge.")


def parse_robots(text: str) -> RobotsIntel:
    """Pure parse of a robots.txt body."""
    if not (text or "").strip():
        return RobotsIntel(assessed=False, reason="robots.txt was empty or not served.")
    sitemaps: list[str] = []
    disallow: list[str] = []
    allow: list[str] = []
    agents: list[str] = []
    delay = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent" and value:
            if value not in agents:
                agents.append(value)
        elif key == "disallow" and value:
            if value not in disallow:
                disallow.append(value)
        elif key == "allow" and value:
            if value not in allow:
                allow.append(value)
        elif key == "sitemap" and value:
            if value not in sitemaps:
                sitemaps.append(value)
        elif key == "crawl-delay" and value and not delay:
            delay = value
    return RobotsIntel(
        assessed=True,
        sitemaps=sitemaps[:20],
        disallow=disallow[:40],
        allow=allow[:40],
        user_agents=agents[:12],
        crawl_delay=delay,
    )


def parse_http_date(value: str) -> str:
    """HTTP-date or ISO date → YYYY-MM-DD. Empty when the value is not a date."""
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return ""
    if parsed is None:
        return ""
    return parsed.date().isoformat()


_CSP_SKIP = {
    "'self'", "'none'", "'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'",
    "'strict-dynamic'", "'report-sample'", "'wasm-unsafe-eval'",
    "*", "data:", "blob:", "filesystem:", "mediastream:",
    "https:", "http:", "wss:", "ws:",
}
_CSP_SKIP_DIRECTIVES = {
    "report-uri", "report-to", "sandbox", "upgrade-insecure-requests",
    "block-all-mixed-content",
}


def parse_csp_hosts(policy: str, origin: str = "") -> list[str]:
    """Host-like tokens from a Content-Security-Policy value. Not a live inventory."""
    origin = (origin or "").lower().removeprefix("www.")
    hosts: list[str] = []
    seen: set[str] = set()
    for directive in (policy or "").split(";"):
        parts = directive.strip().split()
        if not parts:
            continue
        if parts[0].lower() in _CSP_SKIP_DIRECTIVES:
            continue
        for token in parts[1:]:
            token = token.strip()
            if not token:
                continue
            lowered = token.lower()
            if lowered in _CSP_SKIP or lowered.startswith("'"):
                continue
            if lowered.startswith("nonce-") or lowered.startswith("sha256-") or lowered.startswith("sha384-") or lowered.startswith("sha512-"):
                continue
            host = ""
            if "://" in token:
                host = urlparse(token).netloc.lower()
            elif "." in token or token.startswith("*."):
                host = token.lower().split("/", 1)[0]
            host = host.removeprefix("*.").removeprefix("www.").split(":")[0]
            if not host or host == origin or "." not in host:
                continue
            if host not in seen:
                seen.add(host)
                hosts.append(host[:80])
    return hosts[:30]


def from_headers(headers: dict[str, str] | None, origin: str = "") -> HeaderIntel:
    """Pure: homepage response headers → security + recorded freshness fields."""
    raw = {k.lower(): v for k, v in (headers or {}).items() if v}
    present = {name: raw[name][:180] for name in SECURITY_HEADERS if name in raw}
    missing = [name for name in SECURITY_HEADERS if name not in present]
    return HeaderIntel(
        assessed=True,
        present=present,
        missing=missing,
        last_modified=raw.get("last-modified", "")[:80],
        etag=raw.get("etag", "")[:80],
        date=raw.get("date", "")[:80],
        cache_control=raw.get("cache-control", "")[:80],
        x_robots_tag=raw.get("x-robots-tag", "")[:80],
        csp_hosts=parse_csp_hosts(raw.get("content-security-policy", ""), origin),
    )


def parse_security_txt(text: str) -> tuple[list[str], dict[str, str]]:
    """RFC 9116 fields. Contact lines are listed; other keys are copied once."""
    contacts: list[str] = []
    fields: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not value:
            continue
        if key == "contact":
            if value not in contacts:
                contacts.append(value[:160])
            continue
        if key in SECURITY_FIELDS and key not in fields:
            fields[key] = value[:180]
    return contacts[:8], fields


def parse_humans_txt(text: str) -> list[str]:
    """First credit lines. Comments stay out. Not a headcount."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line not in out:
            out.append(line[:120])
        if len(out) >= 8:
            break
    return out


def _security_contacts(text: str) -> list[str]:
    contacts, _fields = parse_security_txt(text)
    return contacts


def file_role(path: str) -> str:
    return FILE_ROLES.get(path, "")


def inventory_from_files(files: list[PublicFile]) -> list[dict[str, str]]:
    """Trust / AI / people / ads / privacy rows. Absence stays absent."""
    rows: list[dict[str, str]] = []
    for item in files:
        role = item.role or file_role(item.path)
        if not role:
            continue
        note = ""
        if role == "ai":
            note = "Crawl invitation, not traffic."
        elif role == "trust" and item.contacts:
            note = "Contact listed. Not a SOC 2 badge."
        elif role == "ads":
            note = "Publisher declaration, not spend."
        elif role == "people":
            note = "Credits as printed. Not a headcount."
        elif role == "privacy":
            note = "Published privacy signal, not a compliance score."
        rows.append({
            "path": item.path,
            "role": role,
            "present": "yes" if item.present else "no",
            "status": str(item.status or 0),
            "note": note,
        })
    return rows


def _public_file(path: str, page) -> PublicFile:
    contacts: list[str] = []
    fields: dict[str, str] = {}
    credits: list[str] = []
    if page.ok and "security.txt" in path:
        contacts, fields = parse_security_txt(page.text)
    if page.ok and path.endswith("humans.txt"):
        credits = parse_humans_txt(page.text)
    return PublicFile(
        path=path,
        present=bool(page.ok),
        status=page.status,
        excerpt=(page.text or "")[:240] if page.ok else "",
        contacts=contacts,
        role=file_role(path),
        fields=fields,
        credits=credits,
    )


async def collect_public_files(base: str) -> PublicIntel:
    """Fetch conventional public-file locations on this origin only."""
    files: list[PublicFile] = []
    for path in WELL_KNOWN:
        page = await fetch(f"{base}{path}", check_robots=False)
        files.append(_public_file(path, page))
        if path == "/.well-known/security.txt" and not page.ok:
            fallback = await fetch(f"{base}{FALLBACK_SECURITY}", check_robots=False)
            files.append(_public_file(FALLBACK_SECURITY, fallback))
    ads: list[AdsRow] = []
    ads_vars: list[AdsVar] = []
    for path in PUBLISHED_FILES:
        page = await fetch(f"{base}{path}", check_robots=False)
        files.append(_public_file(path, page))
        if page.ok and path in ADS_PATHS:
            rows, variables = parse_ads_txt(page.text, path)
            ads.extend(rows)
            ads_vars.extend(variables)
    present_n = sum(1 for f in files if f.present)
    return PublicIntel(
        assessed=True,
        files=files,
        hits=[f.path for f in files if f.present],
        present_n=present_n,
        ads=ads[:40],
        ads_vars=ads_vars[:20],
        inventory=inventory_from_files(files),
        reason="" if present_n else "No conventional public files were served.",
    )
