"""Polite HTTP layer.

Three non-negotiables baked in, because this ships to customers:
  1. robots.txt is honoured for every generic web fetch (RESPECT_ROBOTS must stay true).
  2. Per-host delay + global concurrency cap, so we never hammer anyone.
  3. On-disk response cache, so re-running a report doesn't re-hit the source.

What this module deliberately does NOT do: solve CAPTCHAs, rotate proxies to evade
rate limits, or carry credentials past a login wall. If a page needs auth, we record
`needs_manual` and ask a human. That is the whole compliance posture of the product.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time
import urllib.robotparser as robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.config import settings

_host_locks: dict[str, asyncio.Lock] = {}
_host_last_hit: dict[str, float] = {}
_robots_cache: dict[str, robotparser.RobotFileParser | None] = {}
_semaphore: asyncio.Semaphore | None = None
_MAX_REDIRECTS = 5
_BLOCKED_HOST_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrency)
    return _semaphore


@dataclass
class Fetched:
    url: str
    status: int
    text: str
    from_cache: bool = False
    blocked_by_robots: bool = False
    error: str | None = None
    final_url: str | None = None
    headers: dict[str, str] | None = None
    fetched_at: str | None = None
    content_sha256: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and bool(self.text)


def _address_is_public(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_global


async def validate_public_url(url: str) -> str:
    """Reject local/private destinations before any network or cache access.

    Every resolved address must be globally routable.  Rejecting the whole hostname when
    even one answer is private prevents dual-stack and mixed-answer bypasses.  Redirects
    are validated independently by ``_request`` below.
    """
    try:
        parts = urlparse(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if parts.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are allowed")
    if not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("URL must contain a public host and no embedded credentials")
    host = parts.hostname.rstrip(".").lower()
    if (host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES)):
        raise ValueError("local network destinations are not allowed")

    literal = None
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        pass
    if literal is not None:
        if not literal.is_global:
            raise ValueError("private, reserved and local IP addresses are not allowed")
        return url

    try:
        answers = await asyncio.to_thread(
            socket.getaddrinfo, host, port or (443 if parts.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("host did not resolve to a public address") from exc
    addresses = {row[4][0] for row in answers if row and row[4]}
    if not addresses or any(not _address_is_public(address) for address in addresses):
        raise ValueError("host resolves to a private, reserved or local address")
    return url


async def _request(client: httpx.AsyncClient, url: str, *, method: str = "GET",
                   headers: dict[str, str] | None = None,
                   json_body: dict | None = None) -> httpx.Response:
    """Send a request while validating the initial URL and every redirect hop."""
    current, current_method = url, method.upper()
    for hop in range(_MAX_REDIRECTS + 1):
        await validate_public_url(current)
        if current_method == "POST":
            response = await client.post(current, headers=headers, json=json_body)
        else:
            response = await client.get(current, headers=headers)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("location")
        if not location:
            return response
        if hop >= _MAX_REDIRECTS:
            raise ValueError("too many redirects")
        current = urljoin(str(response.url), location)
        if response.status_code == 303 or (response.status_code in {301, 302}
                                           and current_method == "POST"):
            current_method = "GET"
            json_body = None
    raise ValueError("too many redirects")


def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    return Path(settings.cache_dir) / f"{h}.json"


def _read_cache(url: str) -> Fetched | None:
    p = _cache_path(url)
    if not p.exists():
        return None
    age_hours = (time.time() - p.stat().st_mtime) / 3600
    if age_hours > settings.cache_ttl_hours:
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return Fetched(url=url, status=d["status"], text=d["text"], from_cache=True,
                       final_url=d.get("final_url") or url, headers=d.get("headers") or {},
                       fetched_at=d.get("fetched_at"),
                       content_sha256=d.get("content_sha256") or
                       hashlib.sha256(d["text"].encode()).hexdigest())
    except Exception:
        return None


def _write_cache(url: str, status: int, text: str, *, final_url: str,
                 headers: dict[str, str], fetched_at: str) -> None:
    try:
        _cache_path(url).write_text(
            json.dumps({"status": status, "text": text, "final_url": final_url,
                        "headers": headers, "fetched_at": fetched_at,
                        "content_sha256": hashlib.sha256(text.encode()).hexdigest()}),
            encoding="utf-8"
        )
    except Exception:
        pass


async def _robots_allows(url: str) -> bool:
    if not settings.respect_robots:
        return True
    parts = urlparse(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots_cache:
        rp = robotparser.RobotFileParser()
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=False,
                                         trust_env=False) as c:
                r = await _request(c, f"{base}/robots.txt",
                                   headers={"User-Agent": settings.user_agent})
            if r.status_code == 200:
                rp.parse(r.text.splitlines())
            else:
                rp = None  # no robots.txt published -> allowed
        except Exception:
            rp = None
        _robots_cache[base] = rp
    rp = _robots_cache[base]
    if rp is None:
        return True
    try:
        return rp.can_fetch(settings.user_agent, url)
    except Exception:
        return True


async def _throttle(host: str) -> None:
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        last = _host_last_hit.get(host, 0.0)
        wait = settings.per_host_delay - (time.monotonic() - last)
        if wait > 0:
            await asyncio.sleep(wait)
        _host_last_hit[host] = time.monotonic()


async def fetch(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    use_cache: bool = True,
    check_robots: bool = True,
    method: str = "GET",
    json_body: dict | None = None,
) -> Fetched:
    try:
        await validate_public_url(url)
    except ValueError as exc:
        return Fetched(url=url, status=0, text="", error=f"unsafe URL: {exc}")

    if use_cache and method == "GET":
        cached = _read_cache(url)
        if cached:
            return cached

    if check_robots and not await _robots_allows(url):
        return Fetched(url=url, status=0, text="", blocked_by_robots=True,
                       error="disallowed by robots.txt")

    host = urlparse(url).netloc
    hdrs = {
        "User-Agent": settings.user_agent,
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    hdrs.update(headers or {})

    async with _sem():
        await _throttle(host)
        try:
            async with httpx.AsyncClient(
                timeout=settings.request_timeout, follow_redirects=False,
                trust_env=False,
            ) as client:
                r = await _request(client, url, method=method, headers=hdrs,
                                   json_body=json_body)
            text = r.text
            captured = datetime.now(timezone.utc).isoformat()
            public_headers = {k.lower(): v for k, v in r.headers.items()
                              if k.lower() in {
                                  "content-type", "last-modified", "etag", "date",
                                  "strict-transport-security", "content-security-policy",
                                  "x-content-type-options", "x-frame-options",
                                  "referrer-policy", "permissions-policy",
                                  "content-language", "cache-control",
                                  "x-robots-tag", "link",
                              }}
            if r.status_code == 200 and method == "GET" and use_cache:
                _write_cache(url, r.status_code, text, final_url=str(r.url),
                             headers=public_headers, fetched_at=captured)
            return Fetched(url=url, status=r.status_code, text=text,
                           final_url=str(r.url), headers=public_headers,
                           fetched_at=captured,
                           content_sha256=hashlib.sha256(text.encode()).hexdigest())
        except Exception as exc:  # noqa: BLE001
            return Fetched(url=url, status=0, text="", error=f"{type(exc).__name__}: {exc}")
