#!/usr/bin/env python3
"""Generate sample reports from the frozen fixtures — no network required.

    python scripts_demo.py               # four single reports + one cohort report
    python scripts_demo.py sunil_panda   # just one
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.engine import pipeline
from app.engine.render import html as html_render
from app.engine.render.docx_render import render as docx_render
from app.engine.render.docx_render import render_cohort as docx_cohort
from tests import fixtures

out = Path("./data/samples")
out.mkdir(parents=True, exist_ok=True)
names = sys.argv[1:] or list(fixtures.ALL)

payloads = []
for name in names:
    raw = fixtures.ALL[name]()
    p = pipeline.analyse(raw, f"sample-{name}")
    payloads.append(p)
    (out / f"{name}.html").write_text(html_render.render(p), encoding="utf-8")
    docx_render(p, str(out / f"{name}.docx"))
    a, c, f = p.audience, p.content, p.funnel
    age = a.age.as_pct()
    wins = ", ".join(w.phrase for w in (c.catalogue_patterns or c.winning_patterns)[:2]) or "—"
    print(f"{name:16} {a.archetype_label:32} age {max(age, key=age.get):6} "
          f"conf {round(a.overall_confidence*100):>2}%  funnel {f.total:>2}/70  "
          f"wins: {wins}")

if len(payloads) > 1:
    cp = pipeline.analyse_cohort(payloads, uuid.uuid4().hex[:12])
    (out / "cohort.html").write_text(html_render.render_cohort(cp), encoding="utf-8")
    docx_cohort(cp, str(out / "cohort.docx"))
    print(f"\ncohort: {cp.cohort.headline}")
    print(f"        overlap median {cp.cohort.median_overlap}%, peak {cp.cohort.max_overlap}%; "
          f"{cp.cohort.sequential_pairs} sequential / {cp.cohort.competing_pairs} competing pairs")

print(f"\nwritten to {out.resolve()}")
