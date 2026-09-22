# OMNISCOPE spec map — where we stand

Honest status of the master build prompt against this tree as of **8.23.0**.
“Shipped” means a working path with UI + API + tests + provenance — not the
Bloomberg/Palantir vision, and never a fabricated metric.

This file is the standing record. Update it when a slice ships or when a
section is proven blocked. Do not mark a section complete because the nav
exists.

## Completable vs blocked

**First slices for milestones 1–8 are done.** What is left is either:

1. another official/public source we have not wired yet, or
2. something that needs a licensed provider, OCR, LLM, Redis/OpenSearch/Neo4j,
   or a login — and must stay `UNAVAILABLE` until that exists.

**Will not be faked from this tree:** document OCR / scanned PPTX-XLSX layout,
keyword-demand SEO quadrants, TAM/share, trained narrative/review classifiers,
Redis queues, OpenSearch, a graph database, LLM agents, live award deadlines
unless the official page printed a date, Instagram / X / LinkedIn / Threads /
Facebook grids behind login, unofficial X embed tokens, guessing Bluesky /
Mastodon / GitHub / SoundCloud / Pinterest / Hacker News / ORCID from an
Instagram handle.

## Section status

| Spec | Intent | Status | Where |
|---|---|---|---|
| §1 Universal input | Drop anything | Shipped: creator / website / keyword / post | `input_resolver.py`, `media.py` |
| §2 Modular architecture | Independent engines | Logical modules in `app/omni` + `app/engine`; one process | — |
| §3 Production requirements | logging, retries, cache, tenancy | Partial: HTTP cache/retries/SSRF, tenancy, tests. Reports TTL 24h + download. No Redis queue, no Alembic | `http.py`, `commercial/`, `housekeeping.py` |
| §4–5 Provider layer | adapters + registry | Protocols + ensemble adapters + health registry | `app/providers/`, `registry.py` |
| §6 ATLAS crawler | frontier, JS render, budgets | Same-host crawl; sitemap-index children; lastmod-ordered other URLs; Playwright Chromium in the prod image | `webintel.py`, `collectors/browser.py` |
| §7 PULSE social | platform adapters | Creator engine + Reddit/TikTok/podcast/Bluesky/Mastodon/GitHub/SoundCloud/Pinterest/Hacker News/YouTube Atom + Wikidata biography + official ORCID / MusicBrainz / Wikipedia pageview / Spotify oEmbed hydration + more official IDs already on Wikidata (CIK, LEI, VIAF, LCCN, GND, IMDb, ISIN, Companies House, OpenCorporates — never guessed from Instagram) + Wikimedia portrait + official-site RSS + Telegram t.me/s + Wikipedia sections + Apple Podcasts review RSS. Threads/Facebook/LinkedIn/X/Instagram grids stay login-walled | `collectors/`, `media.py`, `wikidata_identity.py`, `public_records.py`, `feeds.py`, `keyless.py` |
| §8 Content DNA | hooks, formats, CTAs | H1/CTA + feeds + on-page + locale + share cards + vendor hosts + document links | `content_dna.py`, `cards.py`, `vendors.py`, `links.py` |
| §9 Virality | relative performance | Creator content engine only | `inference/content.py` |
| §10 Audience | observable clusters | Creator audience model; no fabricated demographics | `inference/` |
| §11 Web intelligence | scored website | Shipped + cards + links + CSP + sameAs + AggregateRating + opening hours + HowTo tools + schema prints + well-known inventory + official filings when an ID already exists | `webintel.py`, `schema_intel.py`, `claims.py`, `reviews.py`, `site.py`, `filings.py` |
| §12 Search intelligence | normalize/dedupe | Ensemble search + merge. Needs a search key; degrades honestly | `discovery/search.py` |
| §13 News / Narrative Radar | narratives, timelines | Search hits + article hydrate + HN Algolia for sites; first-party feeds separate. No trained narrative classifier | `news.py`, `feeds.py`, `open_sources.py` |
| §14 Competitors | battlefield | Official-site rivals + stored-report compare | `competitors.py`, `compare.py` |
| §15 Product battlecard | offers/pricing | JSON-LD offers + visible ₹ + terms + sku/gtin + printed AggregateOffer / OfferCatalog | `products.py`, `schema_intel.py` |
| §16 Review intelligence | theme clusters | On-page Review bodies + printed AggregateRating. Body star copy ignored | `reviews.py` |
| §17 SEO | opportunity map | Present/thin/missing + canonical mismatches + locale + robots. Demand quadrants unavailable | `seo_map.py`, `indexability.py` |
| §18 Market intelligence | market maps | Search-led official sites | `market.py` |
| §19 Trend / SIGNAL | velocity classes | Snapshot score series | `trends.py` |
| §20–21 Awards | discovery + matching | Catalog + on-site mentions + official-page dates. No invented deadlines | `awards.py`, `award_dates.py` |
| §22 Documents | PDF/OCR | Digital PDF/DOCX/TXT/CSV/HTML upload, no OCR. Same-host .pdf hrefs listed, not fetched. PPTX/XLSX not extracted | `documents.py`, `onpage.py` |
| §23 Entity resolution | same entity across sources | Domain + handle + GSTIN/CIN/LEI merge. rel=me, sameAs, ORCID listed, never merge keys. Name never merges | `resolve.py`, `mentions.py`, `claims.py` |
| §24–25 Graph + evidence | temporal graph | Snapshots, evidence, timeline (news + feeds), tenant graph in SQL | `timeline.py`, `graphmap.py` |
| §26 ORACLE | predictions with limits | Snapshot delta + freshness. Not a forecast model | `oracle.py` |
| §27 AI reasoning agents | multi-agent critique | Deterministic critic from measured fields. Optional desk prose when a key exists; DESK is the fallback | `reason.py`, `llm.py`, `desk.py` |
| DESK | beginner marketing brief | Eight needs + frameworks + evidence-gated playbooks. Compare lists need status, never a winner. llms.txt ≠ traffic. ads.txt ≠ spend. Optional LLM restates filled cells only | `app/omni/desk.py`, `/desk`, `/compare`, `llm.py` |
| §28–29 NEXUS + Deep Analyze | planner | Shipped | `nexus.py`, `/` |
| §30 Intelligence report | full sections | Creator + web packs; JSON; coverage; unmeasured; CSV. Deleted after 24 hours | `export.py`, `/coverage`, `housekeeping.py` |
| §31 Proactive | watch + alerts | Homepage + feed diffs; new websites are watched after Deep Analyze. Overnight interval is env, default off in tests. No threat score | `watch.py`, `digest.py` |
| §32 Frontend nav | research-grade OS | Full OS nav is public; Overview is the hub index | `base.html`, `/overview` |
| §33 Visual intelligence | timelines, maps, clusters | Report charts + hub tables. No network-graph product | report templates, hubs |
| §34 Security | SSRF, tenancy, RBAC | HTTP SSRF + recorded security headers + CSP host tokens. Not a CVE score | `http.py`, `site.py`, `legal.py` |
| §35 Databases | PG + Redis + OS + graph | SQLite/Postgres only | assumption §51.2 |
| §36 Events | event-driven | In-process bus | `events.py` |
| §37 Observability | traces, dashboards | Structured logs + provider health counters. No distributed tracing stack | `registry.py` |
| §38 Cost control | usage + model routing | HTTP cache + crawl budgets. Optional LLM is skipped without a key | `http.py`, `llm.py` |
| §39 Model routing | cheap/fast vs premium | Optional OpenAI chat when a key exists; DESK is the deterministic fallback | `llm.py`, `desk.py` |
| §40 Multi-tenancy | orgs, roles, quotas | Org + API keys + public email-only flow. Signup closed | `commercial/` |
| §41 API-first | versioned API | `/api/v1` + OpenAPI + CSV of stored tables | `main.py` |
| §42 Plugin architecture | installable engines | Python packages under `app/omni` + `app/engine`. Not a plugin loader | — |
| §43 Testing | unit / integration / security | `tests/` including accuracy contract and SSRF | `tests/` |
| §44 Development strategy | vertical slices | Followed. Do not start 100 engines at once | this file |
| §45 Repository structure | monorepo apps/engines | Mapped onto `app/`. Second deployable service does not exist | assumption §51.1 |
| §46 Open-source first | evaluate before reinventing | See `DEPENDENCIES.md` | `DEPENDENCIES.md` |
| §47 Data governance | retention, correction | Reports deleted after 24 hours. Source timestamps on fetch | `housekeeping.py`, `http.py` |
| §48 No fake intelligence | absolute | Tested | `test_accuracy_contract.py`, `test_omniscope.py` |
| §49 Differentiation | universal + evidence | Product principle in force. Not Bloomberg-scale | `docs/OMNISCOPE.md` |
| §50 First implementation | architecture then slice | Done in 4.x–8.x | this repo |
| §51 Agent behaviour | no fake adapters | In force | `AGENTS.md` |
| §52 Definition of done | UI+API+tests+provenance | Used per slice, not per vision sentence | — |
| §53 Final vision | one coherent OS | Direction. Not a ship checklist | — |

## Live product constraints (not in the spec)

- Public site: full product, free, no account. Email optional. Reports kept 24 hours
- DESK is the first section of website and creator reports; `/desk` explains the eight needs
- Compare shows desk need status side by side and does not declare a winner
- Conventional public files now include `/ai.txt`, `/.well-known/change-password`, `/.well-known/gpc.json`; `/well-known` is the trust/AI inventory hub
- Official filings: SEC / GLEIF only when a CIK or LEI already exists; CIN is printed, MCA text stays unavailable; no valuation
- New websites are watched after Deep Analyze; overnight sweep is `WATCH_INTERVAL_MINUTES` (720 in prod)
- Optional `OPENAI_API_KEY` restates filled DESK cells; invented numbers are rejected; no key = deterministic desk
- Production image installs Playwright Chromium
- SMTP sends HTML+attachments when host/from are set; 587 uses STARTTLS; download from the job page if unset
- Instagram datacenter login-wall is common; Wikidata / Wikipedia / official
  keyless APIs are the mitigation
- Do not start a second Caddy on the droplet
