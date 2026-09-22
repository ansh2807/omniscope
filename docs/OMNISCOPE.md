# OMNISCOPE — Universal Marketing Intelligence Operating System

**Architecture document.** How the existing Creator Intelligence Engine (v3.5.0) evolves
into OMNISCOPE, what is reused, what is new, and the milestone plan.

The product principle is unchanged from the creator engine and is inherited everywhere:

> **DROP ANYTHING. GET INTELLIGENCE.** Every claim is `OBSERVED`, `CALCULATED`,
> `MODELLED` (with confidence and printed reasoning) or `UNAVAILABLE`. Nothing private
> is fabricated. Every figure carries source, timestamp and method.

---

## 1. What already exists and is reused as-is

The creator engine is a working vertical slice of the OMNISCOPE spec. Mapping:

| OMNISCOPE spec concept | Existing implementation | Status |
|---|---|---|
| Compliant fetch layer (SSRF guard, robots, throttle, cache) | `app/engine/http.py` | Reused unchanged |
| Browser renderer (logged-out, no evasion) | `app/engine/collectors/browser.py` | Reused unchanged |
| Social engine (PULSE) | `app/engine/collectors/` — YouTube, Instagram, X, LinkedIn, Telegram, Topmate, Linktree, app stores | Reused; becomes one NEXUS engine |
| Identity expansion / entity linking | `app/omni/resolve.py` + `graph.py` aliases/links; creator corroboration stays in `discovery/corroborate.py` | First slice shipped |
| Evidence contract | `app/schemas.py` — `Evidence`, `ClaimStatus`, provenance on every account | Reused; extended by `app/omni/evidence.py` |
| Audience/content/comment intelligence | `app/engine/inference/` | Reused inside the creator engine |
| Report render + design system | `app/engine/render/`, `_style.html.j2` | Reused; new web-report template added |
| Jobs, share links, library, multi-tenancy, billing | `app/main.py`, `app/commercial/` | Reused unchanged |
| Anti-hallucination tests | `tests/test_accuracy_contract.py` and friends | Must stay green |

## 2. What is new — the `app/omni/` layer

```
                         any input
                             │
              app/omni/input_resolver.py        ← universal classification
                             │
                  app/omni/nexus.py             ← analysis planner
                     │               │
        creator plan │               │ website / company plan
                     ▼               ▼
        app/engine/pipeline.py   app/omni/webintel.py   ← NEW engine
        (existing, untouched)        │
                     │               │  crawl (http.py) · tech detect · SEO signals
                     │               │  socials via sameAs/links → existing collectors
                     ▼               ▼
                  ReportPayload   WebIntelPayload
                     │               │
                  existing render  web_report.html.j2 (same design system)
```

### 2.1 `input_resolver.py` — universal input

Classifies anything pasted into one of:

| Kind | Examples | Routed to |
|---|---|---|
| `creator` | `@handle`, instagram.com/…, youtube.com/@…, topmate.io/… | existing creator pipeline |
| `website` | `acme.com`, `https://acme.com/pricing`, any non-social URL | web intelligence engine |
| `keyword` | free text: `"crm software india"`, a company name | search-led entity discovery (needs a search provider; degrades honestly) |

The existing `app/engine/resolver.py` stays authoritative for social-platform URL
parsing; the universal resolver wraps it.

### 2.2 `nexus.py` — analysis planner

Given a classified input, NEXUS emits a `Plan` — the ordered engine list with reasons —
and executes it. It never runs every engine blindly: an Instagram profile does not get a
product-page crawl; a B2B domain does not get an audience-persona pass. Each plan step
reports progress through the same `Job.stage/progress` fields the UI already renders.

### 2.3 `webintel.py` — Web Intelligence engine (ATLAS, first slice)

Given a domain:

1. **Crawl** — homepage + sitemap/robots discovery (urlset or same-host sitemap-index
   children, max 3) + relevant same-host pages, all through the compliant `http.py`
   fetcher (SSRF-guarded, robots-respecting, cached), bounded by `WEBSITE_MAX_PAGES`.
2. **Extract** — metadata, Open Graph, JSON-LD entities (Organization/Product/Person),
   headings, canonical/robots/sitemap presence, contact surfaces, social links.
3. **Detect technologies** — publicly observable fingerprints only (generator meta,
   analytics/pixel scripts, framework markers, commerce platforms). No probing beyond
   pages already fetched.
4. **Discover the entity** — org name, logo, socials from `sameAs` + footer links; the
   discovered social accounts are collected by the *existing* platform collectors, so a
   company report includes live follower counts with the same provenance rules.
5. **First-party feeds** — RSS/Atom URLs the homepage advertised (same-host only).
   Item dates come from feed fields. No advertised feed → UNAVAILABLE, not an empty blog.
6. **Score** — Website Intelligence Score across dimensions (technical, SEO, content,
   brand, conversion, trust). Every dimension prints its formula, inputs and what was
   *not* measured. No PageSpeed-style lab metrics are invented; performance and
   accessibility are reported only from observable static signals and are labelled as
   such.
7. **Evidence** — every page fetched becomes an evidence record: URL, SHA-256,
   fetched-at, what was read from it. Stored in the report payload.

### 2.4 `registry.py` — provider registry

A typed registry over every data source the platform can use: name, category,
capabilities, auth mode, configured/keyless/off status, cost notes and fallback order.
In-memory health counters (success/error/latency) recorded by the fetch layer feed the
Diagnostics page. The Settings UI already lets users add their own keys; the registry
makes source selection explicit instead of scattered `if settings.x` checks.

### 2.5 `evidence.py` — evidence records

A small, general evidence-log builder used by the web engine now and other engines
later. Records live inside `Report.payload_json` (same storage and deletion path as
today, so retention/erasure keep working). A dedicated evidence table and the
intelligence graph move to Milestone 6 — the payload keeps a stable shape so migration
is additive.

## 3. Storage

No schema break. `Report.kind` gains the value `"web"` (existing values: `single`,
`cohort`). Jobs, tenancy, quotas, retention and deletion are unchanged. The graph
database, OpenSearch and a queue service from the spec are deliberately deferred; all
access goes through interfaces so they can be introduced without rewrites.

## 4. Security posture (inherited, not weakened)

`http.py` already enforces: public-IP-only DNS resolution (SSRF/rebinding guard),
manual redirect re-validation, robots.txt, per-host delay, global concurrency cap,
logged-out browser with no CAPTCHA/bot evasion. The web engine adds **no** new fetch
path — every request goes through the same client. Uploaded-document processing is out
of scope until the Document Intelligence milestone and will be sandboxed when built.

## 5. Milestones

| # | Milestone | Contents | Status |
|---|---|---|---|
| 1 | Universal input → web analysis → report | `app/omni/`, web report, rebrand | Done |
| 2 | Social intelligence | already shipped as the creator engine | Done (pre-existing) |
| 3 | Competitor intelligence | company rivals via search (`app/omni/competitors.py`) | First slice shipped |
| 4 | Product intelligence | JSON-LD offers → public pricing battlecard | First slice shipped |
| 5 | Award intelligence | curated catalog + on-site mentions (`app/omni/awards.py`) | First slice shipped |
| 6 | Intelligence graph | `Entity` + `EvidenceItem` tables, `/entities` | First slice shipped |
| 7 | Predictive intelligence | ORACLE: snapshot delta + content freshness | First slice shipped |
| 8 | Proactive monitoring | watch flag, change alerts on re-analyze | First slice shipped |

Product OS shell (v8.23.0): DESK beginner brief (eight marketing needs +
frameworks + playbooks gated on observed surfaces; compare does not pick a
winner), scored website engine, ads.txt, claims (including
printed sameAs), share cards, vendor hosts, document links, CSP host tokens,
printed job/event/course/ContactPoint/ItemList/AggregateOffer/OfferCatalog/
speakable/WebPage lastReviewed/opening-hours/HowTo-tool fields, printed
AggregateRating, hubs. Creator reports also copy advertised official-site
RSS/Atom items, Telegram t.me/s preview messages, Wikipedia article sections,
Wikidata nominations / events / memberships / positions / residences /
birthplaces / pseudonyms / official names / ORCID / significant events, a
Wikimedia portrait, Apple Podcasts customer reviews, Mastodon, GitHub (stars
are not views), SoundCloud oEmbed (plays are not copied), Pinterest oEmbed
(pins are not followers), and Hacker News public user records (karma is not
followers). When Wikidata already printed an ORCID, MusicBrainz artist ID,
Wikipedia title or Spotify artist URL, official public APIs are fetched:
ORCID affiliations and work titles, Wikimedia pageviews, MusicBrainz name
and homepage, Spotify oEmbed title. Pageviews are not traffic or followers.
ORCID works are not a product stack. MusicBrainz country is not a current
base. Spotify title is not monthly listeners. None of those networks are
guessed from Instagram. Birthplace is not a current base. A pseudonym is
not a guessed display name. Residence is not citizenship. A Wikidata office
is not an audience job. Reports expire
after 24 hours and must be downloaded. The public site is the full OS, free,
with no account. Optional desk prose runs only when an API key exists; the
desk is complete without it. Still not OCR, demand SEO, TAM, or invented
valuations. Full section map: `docs/SPEC-MAP.md`.

## 6. Assumptions made (per spec §51)

1. **Evolve, don't rewrite.** The spec's monorepo layout is logically mapped onto the
   existing `app/` package: `app/omni/` = orchestrator + engines’ shared core,
   `app/engine/` = social/creator engine, `app/commercial/` = tenancy/billing. A
   physical `apps/…` split is justified only when a second deployable service exists.
2. **SQLite/Postgres only for now.** Graph DB, OpenSearch and Redis queues are behind
   interfaces, introduced when a milestone actually needs them.
3. **Optional LLM, deterministic fallback.** DESK and the critic stay complete
   without a key. When `OPENAI_API_KEY` is set, prose restates filled cells only
   and any number not already on the desk is rejected.
4. **DOCX for web reports is deferred**; HTML ships first (share links + print styles).
5. **Keyword inputs need a search provider**; without one the platform says exactly
   that instead of guessing (same posture as the SEO module today).

Full section-by-section status against the master build prompt: `docs/SPEC-MAP.md`.
Open-source / API choices: `docs/DEPENDENCIES.md`.
