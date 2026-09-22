# OMNISCOPE — agent notes

Product: universal marketing intelligence. Drop a creator, website, company or
keyword; get an evidence-backed report. Claims stay observed, calculated,
modelled, or unavailable.

Architecture and roadmap: `docs/OMNISCOPE.md`.

## Stack
- FastAPI + SQLModel (SQLite by default), Jinja templates, vanilla CSS.
- Creator engine: `app/engine/` (pipeline, collectors, inference, discovery).
- OMNISCOPE layer: `app/omni/` — input resolver, NEXUS planner, webintel,
  product battlecards, company competitors, evidence log, provider registry,
  DESK marketing-needs engine (`app/omni/desk.py`), official filings
  (`app/omni/filings.py`), optional LLM (`app/omni/llm.py`).
- Report renderers: `app/engine/render/html.py`, `docx_render.py`,
  `web_report.html.j2`.
- Agency desk: `app/engine/inference/agency_intelligence.py`,
  `media_buy.py`.

## Design system
- App shell: `app/templates/base.html` (Outfit + IBM Plex Mono, single accent
  `#3dd68c`, dark `#0a0c0f`). Soft shapes language: pill nav, soft radii (24/18/14),
  ambient mesh + dot-grid pattern, grain, staggered rise motion, tinted shadows.
  Product UI — no AI-purple gradients.
- Report theme: `app/engine/render/templates/_style.html.j2` (same tokens).
- Keep claim chips: `obs` / `est` / `una`. Never invent private metrics.

## Tests
- `tests/` — run with `python -m pytest tests -q` from project root (conftest adds root).
- Full suite green as of v4.1.0 (includes `tests/test_omniscope.py`).

## Skills used
- Installed via `npx skills add Leonxlnx/taste-skill`.
- Applied `redesign-existing-projects`, `design-taste-frontend`, `high-end-visual-design`
  to the app shell and report styling (typography, single-accent palette, double-bezel
  restraint, focus/transition states, bento layout on workspace).
