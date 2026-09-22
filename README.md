<picture>
  <source media="(prefers-reduced-motion: reduce)" srcset="assets/brand/cover.png">
  <img src="assets/brand/cover.gif" alt="Omniscope — original animated project artwork by Ansh Kalra" width="1200">
</picture>

# Omniscope

**Creator and website intelligence with evidence attached.** Explore public signals, compare opportunities, and turn source-backed findings into reports you can inspect.

[Quick start](#quick-start) · [Setup guide](QUICKSTART.md) · [Hosting](HOSTING.md) · [Collection policy](LEGAL.md)

<sub>Python · FastAPI · Playwright · DOCX · Docker</sub>

---

## What it does

**Drop anything. Get intelligence.** One input box routes to the right engines and returns an evidence-backed report — no black-box vendor between the input and the output. Two engines ship today:

- **Creator intelligence** — a full 17-section diligence pack for any creator.
- **Web intelligence** — for any domain or company: bounded compliant crawl, entity extraction, technology detection, SEO/structure signals, live social discovery, and six scored dimensions **that print their formulas**.

## Product surfaces

| Surface | What it does |
|---|---|
| **Workspace** `/` | Deep-analyze anything — creator packs, cohorts, website intelligence |
| **Discover** `/discover` | Niche creator search across Instagram, YouTube, TikTok, LinkedIn, X |
| **Shortlists** `/shortlists` | Campaign rosters with pipeline stages |
| **Library** `/library` | Filter/sort reports by kind, media-buy verdict, fit and confidence |
| **Entities** `/entities` | Intelligence-graph subjects — watch + re-analyze |
| **Alerts** `/alerts` | Score / tech / social changes on watched entities |
| **Report** `/r/{slug}` | Shareable creator diligence pack or website intelligence report |

## Why it's different

- **Discovery + full diligence** — search leads straight into a 17-section report, not a thin profile card.
- **Honest audience quality** — quality and fake-follower screens show **formulas, denominators and coverage**; private facts are never fabricated.
- **Media-buy decision layer** — every report ends in a weighted `prioritize / pilot / hold / pass` scorecard with reasons, risks and next steps.
- **Evidence-first** — every signal is traced to a public source; nothing is invented to fill a gap.

## Quick start

```bash
cp .env.example .env
pip install -r requirements.txt
python -m playwright install chromium
python cli.py            # or: docker compose up --build
```

See **[QUICKSTART.md](QUICKSTART.md)** and **[HOSTING.md](HOSTING.md)** for full setup, and **[LEGAL.md](LEGAL.md)** for the compliance model.

## Stack

**FastAPI** application · **Playwright** for bounded, compliant public collection · a discovery/inference engine that scores dimensions and prints their formulas · **DOCX / HTML** report rendering · Docker + Compose for self-hosting.

## Ethics & privacy

- Collection is **bounded and compliant** — public evidence only, rate-limited, with sources recorded. Nothing behind a login wall is scraped, and private facts are never fabricated.
- `.env`, `data/`, and all collected/validation datasets are git-ignored — no third-party personal data ships in this repo. Examples in the code use a neutral placeholder handle.

---

**Built by [Ansh Kalra / DRAG](https://github.com/ansh2807).** Explore the [project collection](https://github.com/ansh2807#selected-work).

<sub>[View the still cover](assets/brand/cover.png) · [Artwork source](https://github.com/ansh2807/ansh2807/blob/main/tools/generate_brand.py)</sub>
