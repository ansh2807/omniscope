# Brief coverage matrix

Every requirement from the research brief, mapped to where the engine delivers it and
how. Three honesty levels are used throughout:

* **Measured** — arithmetic over collected public data. No assumptions.
* **Modelled** — inferred, always with a confidence score and printed reasoning.
* **Not obtainable** — behind a login wall or simply not published anywhere. The report
  says so rather than filling the gap.

---

## Output format — the thirteen requested sections

The engine emits **seventeen** sections. Section 5 is the marketing-agency buying desk
requested by commercial clients. Per-platform, brand and growth analysis remain included.

| # | Brief section | Engine section | Status |
|---|---|---|---|
| 1 | Executive Summary | §1 + executive dashboard | Delivered |
| 2 | Creator Overview | §2 | Delivered |
| 3 | Cross-Platform Presence | §3 | Delivered — lists platforms **searched and not found**, not just those found |
| 4 | Audience Intelligence | §4 | Delivered |
| — | **Agency Buying Desk** | **§5** | **Delivered** — quality, demographics, fake-follower anomaly screen, interests, engagement, overlap, lookalikes, contacts, reach, collaborations, influence, insights, brand affinity, historical performance |
| 5 | Content Analysis | §6 | Delivered |
| 6 | Comment & Sentiment Analysis | §7 | Delivered for YouTube; Instagram not obtainable |
| 7 | Competitor Landscape | §8 | Delivered (needs a search key) |
| 8 | SEO & Discoverability | §9 | Delivered (needs a search key) |
| — | Platform Analysis | §10 | Delivered |
| — | Brand Analysis | §11 | Delivered |
| — | Growth Analysis | §12 | Delivered |
| 9 | Marketing Funnel Assessment | §13 | Delivered |
| 10 | Audience Personas | §14 | Delivered — 10–13 per creator |
| 11 | Growth Opportunities | §15 | Delivered |
| 12 | Strategic Recommendations | §16 | Delivered |
| 13 | Appendix, sources, methodology | §17 | Delivered |

---

## Agency buying desk (client-requested diligence metrics)

Implemented in `app/engine/inference/agency_intelligence.py`, wired through `assemble.build`,
rendered in HTML §5 and DOCX §5. Every metric carries status, confidence, formula,
denominator, interpretation, limitations and data-required.

| Client metric | Status contract | Notes |
|---|---|---|
| Audience quality | Modelled proxy or unavailable | Public-signal rubric; never authenticity of people |
| Demographics | Observed when first-party supplied; else modelled/unavailable | Does not invent private splits |
| Fake follower estimates | Anomaly risk range only | **Never** emits a fake-follower percentage from public aggregates |
| Interests | Modelled from content topic shares | Content topics ≠ follower interests |
| Engagement | Calculated from public counts | Likes/comments/views ratios with sample size |
| Audience overlap | Exact overlap unavailable; topic affinity separate | Honest about first-party requirement |
| Lookalike creators | Ranked topic/stage affinity | Explicitly not shared-follower lookalikes |
| Contact details | Observed from creator-owned surfaces only | Press pages cannot supply contacts |
| Estimated reach | Modelled public-view placement band | Not guaranteed impressions |
| Brand collaborations | Observed partnership markers only | Mentions without #ad/sponsored are excluded |
| Influence score | Modelled composite diligence index | Coverage % disclosed |
| Audience insights | Calculated/modelled decision hypotheses | Tied to explicit evidence |
| Brand affinity | Modelled from interests + collabs | Hypothesis, not brand-lift |
| Historical performance | Calculated when dated samples allow | Current vs catalogue medians |

---

## Audience analysis

| Brief item | Status | How |
|---|---|---|
| Age groups | Modelled | Five bands, archetype prior moved by weighted rules |
| Gender split | Modelled | National platform baseline adjusted by subject matter and creator gender |
| Income level | Modelled | Five bands, anchored on the creator's observed price ladder |
| Occupation | Modelled | Eight buckets: school, college, job seeker, fresher, working professional, manager, founder, freelancer/creator |
| Students vs professionals | Modelled | Career-level distribution, five buckets |
| Founders / managers / job seekers | Modelled | Explicit buckets in the occupation split |
| MBA aspirants / engineers | Modelled | Education distribution, six buckets |
| Marketers / creators / freelancers | Modelled | Freelancer-creator bucket; finer splits need first-party data |
| Country | Modelled | India share plus international tail, with reasoning |
| State | Modelled | Cities named in content resolved to states, topped up from the regional cluster |
| Tier 1 / 2 / 3 | Modelled | Three-way split driven by language register and geography lock |
| Top cities | Measured where named, else modelled | Cities the creator names repeatedly are read directly |
| Interests, ranked | Measured | Thirteen-topic lexicon scored across bio, keywords and every title |
| Pain points, goals, dreams, fears | Modelled | Archetype psychographics enriched with the observed price ladder |
| Buying behaviour | Measured + modelled | Real price rungs plus observed transaction counts |
| Lifestyle, motivations, aspirations | Modelled | Archetype-derived |
| Language, personality | Measured + modelled | Personality traits scored from the creator's own corpus |
| Emotional triggers | Modelled | Per-archetype, quoted verbatim in the report |
| Decision-making style | Modelled | Per-archetype |
| Cold / warm / hot | Modelled | Three-way temperature split |
| Fan community, returning, loyal, casual | Modelled | Four-way sophistication split |
| Short form % / long form % / carousel % | Modelled | Six-way consumption split |
| Podcast % / newsletter % / email % / reading % | Modelled | Same split |
| Android / iPhone / Desktop / Tablet | Modelled | Four buckets, anchored to India's device share |
| Primary / secondary / regional language | Measured + modelled | Hindi-marker density measured; regional profile modelled |
| English proficiency | Modelled | Four levels, from delivery register and subject demands |
| Education: school, college, MBA, IIT, IIM, engineers | Modelled | Six-bucket education distribution |
| Career level: student → CXO | Modelled | Five-bucket career distribution |
| Income bands 0–5L to 50L+ | Modelled | Five bands |

---

## Platform analysis — every requested attribute

Produced per platform in §9. Follower quality, engagement quality, community strength,
posting frequency, brand positioning, content categories, tone, visual style,
storytelling style, hooks, CTA, hashtags, SEO, community loyalty, virality potential —
all present. Posting frequency, hooks, CTAs, hashtags and virality are **measured** from
collected content; the rest are graded with stated evidence.

Where a platform is login-walled, the row is marked `WALLED` and says what is missing.

---

## Content analysis

| Brief item | Status |
|---|---|
| Categorise every post | Measured — topic classification across all collected items |
| Topics, posting schedule, frequency | Measured |
| Average engagement | Public like/view/count ratios where available; reach-normalised engagement and audience quality require first-party analytics |
| Best / worst performing | Measured |
| Historical view dispersion | Measured — best-to-median multiple, Gini and top-fifth share; not a forecast of virality |
| Most educational / emotional | Measured by proxy — tone classification |
| Most commented | Measured where comment counts are exposed |
| Most shared / most saved | **Not obtainable** — no platform exposes these publicly |
| Most controversial | **Not obtainable reliably** without representative audience text and a defined controversy classifier |

Beyond the brief, the engine also computes: matched-date title-pattern lift, historical
catalogue lift, public series view-count change, promo-versus-organic delivery gap,
percentiles, IQR, MAD, Gini, Lorenz curve, breakout rate, title construction, Cliff's
delta, publishing gaps, burstiness and measured seasonality. Each calculation states its
sample and the confounders it does not control.

---

## Comments analysis

| Brief item | Status |
|---|---|
| Analyse thousands of public comments | **Delivered for YouTube when available** — up to 16 recent/high-view videos and up to 200 relevance/time-ranked comments per video via the official API; browser fallback is smaller |
| Common questions | Measured — extracted and clustered into six themes |
| Pain points, repeated requests | Measured |
| Emotions, sentiment (pos/neu/neg) | Calculated by auditable lexicon, with Wilson intervals and verbatim examples; ranking and sampling bias are disclosed |
| Buying intent, confusion, frustration | Measured — separate categories with examples |
| Community behaviour, inside jokes | Measured — recurring phrases the audience uses that the creator does not |
| Audience vocabulary | Measured — frequency-ranked |
| **Instagram comments** | **Not obtainable.** Login-walled. YouTube comments are never substituted for them. |

Needs **either** `YOUTUBE_API_KEY` **or** the browser tier (`ENABLE-BROWSER.bat`). With
neither, the section says exactly why it is empty rather than modelling sentiment.

---

## Competitor, SEO, brand, growth

| Brief item | Status |
|---|---|
| Identify similar creators, rank them | Delivered — topic-driven discovery, not name matching |
| Compare followers | Measured — live collection |
| Engagement, growth comparison | Partial — needs per-competitor collection depth |
| Audience overlap | **Unavailable** without privacy-safe matched first-party data; lexical topic affinity is reported separately and never renamed as audience overlap |
| Brand positioning, strengths, weaknesses | Internal public-evidence rubric and explicit scale/infrastructure indices; buyer perception, lift and brand safety remain unmeasured |
| Google rankings, organic visibility | Measured — page-one ownership share |
| Brand keywords | Measured — declared channel keywords |
| Search demand, intent, related searches | Modelled — intent clusters with commercial value |
| Trending topics | Partial — related searches are measured keylessly from live autocomplete |
| Related searches | **Measured, keyless** — live autocomplete completions |
| Podcast appearances | **Measured, keyless** — Apple Podcasts Search API |
| Notability / Wikipedia | **Measured, keyless** — MediaWiki API |
| Personal brand, authority, trust, expertise | Modelled — five scored pillars with evidence |
| Brand perception, personality, voice | Modelled — traits and three voice axes |
| Funnels, lead magnets, courses, community | Measured — from real product pages |
| Monetisation, products, offers | Measured |
| Partnerships, sponsors | Partial — inferred from promotional content patterns |
| Growth trend | Measured — median views per item by quarter |
| Content / audience / brand evolution | Measured — three-era comparison |
| Future opportunities, missed opportunities, bottlenecks | Delivered — each tied to a specific observation |

---

## Visualisations

| Requested | Status |
|---|---|
| Executive Dashboard | Delivered — §1 |
| Audience Heatmaps | Delivered — age × city tier bubble grid |
| Interest Maps | Delivered — ranked topic bars |
| Persona Cards | Delivered — 10–13 per creator |
| Marketing Funnel | Delivered — staged funnel diagram |
| Content Matrix | Delivered — length against views, log scale |
| Platform Comparison | Delivered |
| Engagement Charts | Delivered |
| SWOT Analysis | Delivered — four-quadrant grid |
| Brand Positioning Map | Delivered — reach against transactionality |
| Growth Timeline | Delivered — median views per quarter |
| Competitor Matrix | Delivered — audience against topical overlap |

Charts render only where the collected evidence supports the measure; private demographics,
overlap and sparse time-series trends remain explicitly unavailable.

---

## What is genuinely impossible, and why

These are not gaps in the engine. No external tool can obtain them.

| Data | Why | The only real route |
|---|---|---|
| Instagram post views, likes, saves, shares, comments | Login wall on all logged-out access | Creator's Insights export, or the analyst paste-form built into this tool |
| Instagram audience demographics | Private creator-only analytics | Media kit or Insights screenshot |
| Follower growth history | No platform publishes historical snapshots | Paid analytics subscription with time series, or start recording from today |
| "Most saved" / "most shared" | No platform exposes these publicly on any surface | Creator's own analytics |
| LinkedIn followers and post engagement | Authentication wall | Logged-in session or Sales Navigator |
| Revenue, enrolments, session volumes | Private commercial data | Disclosure under NDA |
| Google Trends search volume | Requires a Trends data source | Add a Trends API adapter |

The engine records each of these as `UNAVAILABLE` with the reason and the route to
getting it. It never models them and presents the result as fact.

---

## Collection tiers — what needs a key and what does not

Each source is tried in order, cheapest and most reliable first. The report prints which
tier produced each figure in the Cross-Platform Presence table.

| Source | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|
| Podcast appearances | **Apple Podcasts Search API — keyless** | — | — |
| Notability, official links | **Wikipedia/Wikidata API — keyless** | — | — |
| Related searches, search intent | **Autocomplete endpoint — keyless** | — | — |
| Other platforms (YouTube, Telegram, Threads, Topmate, Linktree) | **Handle probing — keyless, identity-verified** | Search API | — |
| YouTube channel + views | Official Data API (free key) | **Browser render, no key** — includes the Popular sort | Plain HTTP parse, Latest only |
| YouTube comments | Official Data API (free key) | **Browser render, no key** | — |
| Instagram profile header | Commercial provider (optional) | **Browser render, no key** | Plain HTTP meta tags |
| Instagram post metrics | — | — | **Analyst paste-form. Nothing else works.** |
| Topmate / Linktree / websites | Plain HTTP | — | — |
| Search, competitors, SEO | Licensed search API | — | — |

**The browser tier removes the API-key requirement for everything except search.** Run
`ENABLE-BROWSER.bat` once and the engine reads Instagram and YouTube the same way a
person does: open the page, let it render, read what is on screen. Logged out, no
credentials, no CAPTCHA bypass.

## Checking your setup

The app has a **Diagnostics** page that tests each tier live against a real public page.
Run it before concluding anything is broken — it distinguishes "no internet", "browser not
installed", "search key missing" and "platform served a sign-in wall", which need
completely different fixes.

## What improves the report most, in order

1. **The browser tier** — `ENABLE-BROWSER.bat`, one click, no account, no key. Unlocks
   Instagram follower data, YouTube all-time top performers and the entire comment
   analysis section. Biggest single upgrade.
2. **`SEARCH_PROVIDER` + key** — now needed for a genuinely narrow set of things:
   competitor discovery, page-one search ownership, and press and news mentions. Podcast
   appearances, Wikipedia notability, related searches and cross-platform discovery are
   all keyless. Serper's free tier is 2,500 queries, roughly 250 reports.
3. **`YOUTUBE_API_KEY`** — free, 10,000 units/day. Not required once the browser tier is
   on, but gives exact view counts and real publish dates instead of rounded figures and
   relative dates, which improves the seasonality and growth analysis.
4. **The analyst paste-form** — thirty seconds of a human's time converts the Instagram
   post-level dimensions from modelled to observed. Nothing automated can do this.
