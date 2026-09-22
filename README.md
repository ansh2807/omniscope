<p align="center">
  <img src="assets/hero.svg" alt="Omniscope" width="100%">
</p>

<h1 align="center">Omniscope</h1>

<p align="center">
  <b>Marketing Intelligence OS.</b> Drop a creator link, a website, a company name or a keyword into one box —<br>
  Omniscope routes it to the right engines and returns an evidence-backed intelligence report, on your own infrastructure.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/self--hosted-10b981?style=for-the-badge&logo=serverfault&logoColor=black" alt="self-hosted">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Playwright-2EAD33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker">
</p>

---

## 🛰️ What it does

**Drop anything. Get intelligence.** One input box routes to the right engines and returns an evidence-backed report — no black-box vendor between the input and the output. Two engines ship today:

- **Creator intelligence** — a full 17-section diligence pack for any creator.
- **Web intelligence** — for any domain or company: bounded compliant crawl, entity extraction, technology detection, SEO/structure signals, live social discovery, and six scored dimensions **that print their formulas**.

## 🧭 Product surfaces

| Surface | What it does |
|---|---|
| **Workspace** `/` | Deep-analyze anything — creator packs, cohorts, website intelligence |
| **Discover** `/discover` | Niche creator search across Instagram, YouTube, TikTok, LinkedIn, X |
| **Shortlists** `/shortlists` | Campaign rosters with pipeline stages |
| **Library** `/library` | Filter/sort reports by kind, media-buy verdict, fit and confidence |
| **Entities** `/entities` | Intelligence-graph subjects — watch + re-analyze |
| **Alerts** `/alerts` | Score / tech / social changes on watched entities |
| **Report** `/r/{slug}` | Shareable creator diligence pack or website intelligence report |

## 💡 Why it's different

- **Discovery + full diligence** — search leads straight into a 17-section report, not a thin profile card.
- **Honest audience quality** — quality and fake-follower screens show **formulas, denominators and coverage**; private facts are never fabricated.
- **Media-buy decision layer** — every report ends in a weighted `prioritize / pilot / hold / pass` scorecard with reasons, risks and next steps.
- **Evidence-first** — every signal is traced to a public source; nothing is invented to fill a gap.

## 🚀 Quick start

```bash
cp .env.example .env
pip install -r requirements.txt
python -m playwright install chromium
python cli.py            # or: docker compose up --build
```

See **[QUICKSTART.md](QUICKSTART.md)** and **[HOSTING.md](HOSTING.md)** for full setup, and **[LEGAL.md](LEGAL.md)** for the compliance model.

## 🏗️ Stack

**FastAPI** application · **Playwright** for bounded, compliant public collection · a discovery/inference engine that scores dimensions and prints their formulas · **DOCX / HTML** report rendering · Docker + Compose for self-hosting.

## 🔐 Ethics & privacy

- Collection is **bounded and compliant** — public evidence only, rate-limited, with sources recorded. Nothing behind a login wall is scraped, and private facts are never fabricated.
- `.env`, `data/`, and all collected/validation datasets are git-ignored — no third-party personal data ships in this repo. Examples in the code use a neutral placeholder handle.

---

<p align="center"><sub>Full-diligence creator & web intelligence you can run yourself — instead of renting a black box.</sub></p>
