"""Provider registry — every data source OMNISCOPE can draw on, in one place.

The registry answers three questions the spec demands an explicit answer to:
  1. Which providers exist, what can each one do, and what does it cost?
  2. Which are usable *right now* on this instance (key present, browser installed)?
  3. How healthy has each one been in this process (success rate, latency)?

Health counters are in-memory per process: enough for the Diagnostics page and for
fallback decisions, without inventing a metrics stack before one is needed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import settings

STATUS_ACTIVE = "active"        # configured and usable now
STATUS_KEYLESS = "keyless"      # usable now, needs no key at all
STATUS_OFF = "off"              # exists, not configured on this instance


@dataclass
class ProviderHealth:
    ok: int = 0
    errors: int = 0
    total_ms: float = 0.0
    last_error: str = ""
    last_used_at: float | None = None

    @property
    def calls(self) -> int:
        return self.ok + self.errors

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0


_health: dict[str, ProviderHealth] = {}


def record(provider: str, ok: bool, elapsed_ms: float = 0.0, error: str = "") -> None:
    h = _health.setdefault(provider, ProviderHealth())
    if ok:
        h.ok += 1
    else:
        h.errors += 1
        h.last_error = error[:200]
    h.total_ms += elapsed_ms
    h.last_used_at = time.time()


def health(provider: str) -> ProviderHealth:
    return _health.setdefault(provider, ProviderHealth())


@dataclass
class ProviderSpec:
    name: str
    category: str                 # search | social | web | video | enrichment | news
    capabilities: list[str]
    auth: str                     # none | api_key | browser
    status: str                   # active | keyless | off
    cost: str = "free"
    fallbacks: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def health(self) -> ProviderHealth:
        return health(self.name)


def registry() -> list[ProviderSpec]:
    """The current provider catalogue, computed from live settings."""
    from app.engine.collectors import browser as br

    search_on = settings.search_provider not in ("", "none")
    return [
        ProviderSpec(
            name="http", category="web", auth="none", status=STATUS_KEYLESS,
            capabilities=["fetch_page", "crawl_site", "structured_data", "robots"],
            notes="Robots-respecting, SSRF-guarded, throttled, cached. Every other "
                  "provider's HTTP traffic goes through it."),
        ProviderSpec(
            name="browser", category="web", auth="browser",
            status=STATUS_ACTIVE if br.enabled() else STATUS_OFF,
            capabilities=["render_page", "instagram_header", "youtube_popular",
                          "youtube_comments"],
            fallbacks=["http"],
            notes="Logged-out Playwright rendering. Removes the API-key requirement "
                  "for Instagram and YouTube."),
        ProviderSpec(
            name="youtube_api", category="video", auth="api_key",
            status=STATUS_ACTIVE if settings.youtube_api_key else STATUS_OFF,
            capabilities=["get_channel", "get_videos", "get_comments"],
            cost="free, 10k units/day", fallbacks=["browser", "http"],
            notes="Exact counts and real publish dates when configured."),
        ProviderSpec(
            name="serper", category="search", auth="api_key",
            status=STATUS_ACTIVE if (search_on and settings.serper_api_key) else STATUS_OFF,
            capabilities=["search", "news"], cost="2,500 free queries",
            fallbacks=["brave", "google_cse"]),
        ProviderSpec(
            name="brave", category="search", auth="api_key",
            status=STATUS_ACTIVE if (search_on and settings.brave_api_key) else STATUS_OFF,
            capabilities=["search", "news"], fallbacks=["serper", "google_cse"]),
        ProviderSpec(
            name="google_cse", category="search", auth="api_key",
            status=STATUS_ACTIVE if (search_on and settings.google_cse_key
                                     and settings.google_cse_cx) else STATUS_OFF,
            capabilities=["search"], fallbacks=["serper", "brave"]),
        ProviderSpec(
            name="apple_podcasts", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["podcast_appearances"],
            notes="Official iTunes Search API."),
        ProviderSpec(
            name="wikipedia", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["notability", "official_links"],
            notes="MediaWiki / Wikidata APIs."),
        ProviderSpec(
            name="autocomplete", category="search", auth="none",
            status=STATUS_KEYLESS, capabilities=["related_searches", "search_intent"],
            notes="Public suggest endpoint. Query associations, not volume."),
        ProviderSpec(
            name="ig_provider", category="social", auth="api_key",
            status=STATUS_ACTIVE if settings.ig_provider not in ("", "none") else STATUS_OFF,
            capabilities=["instagram_profile"], cost="commercial",
            fallbacks=["browser", "http"],
            notes="Optional licensed Instagram data vendor."),
        ProviderSpec(
            name="itunes_lookup", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["get_app"],
            notes="Official App Store lookup API."),
        ProviderSpec(
            name="archive_org", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["wayback_snapshots"],
            notes="Internet Archive CDX + availability. Capture times, not founding."),
        ProviderSpec(
            name="hackernews", category="news", auth="none",
            status=STATUS_KEYLESS, capabilities=["story_search"],
            notes="HN official search (Algolia). Fallback when licensed news is empty."),
        ProviderSpec(
            name="domainsdb", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["related_domains"],
            notes="domainsdb.info registered-name search. Shared label ≠ same owner."),
        ProviderSpec(
            name="datamuse", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["related_words"],
            notes="Means-like associations. Not search volume."),
        ProviderSpec(
            name="nominatim", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["geocode_printed_address"],
            notes="OpenStreetMap Nominatim. Only runs on a printed street address."),
        ProviderSpec(
            name="rest_countries", category="enrichment", auth="none",
            status=STATUS_KEYLESS, capabilities=["cctld_country"],
            notes="Country record for a country-code TLD only."),
    ]


def usable(category: str | None = None) -> list[ProviderSpec]:
    """Providers usable right now, primary-first (active before keyless)."""
    rows = [p for p in registry() if p.status != STATUS_OFF
            and (category is None or p.category == category)]
    return sorted(rows, key=lambda p: 0 if p.status == STATUS_ACTIVE else 1)
