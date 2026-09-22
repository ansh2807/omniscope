#!/usr/bin/env python3
"""Command line entry point.

    python cli.py https://www.instagram.com/handle/ --out ./out
    python cli.py @handle --no-dorks --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.engine import pipeline
from app.engine.render import html as html_render
from app.engine.render.docx_render import render as docx_render
from app.engine.render.docx_render import render_cohort as docx_cohort


async def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate a creator audience report. Pass several links for a cohort "
                    "report with comparison, overlap and lifecycle analysis.")
    ap.add_argument("url", nargs="+", help="one or more creator URLs or @handles")
    ap.add_argument("--out", default="./data/reports", help="output directory")
    ap.add_argument("--no-dorks", action="store_true", help="skip the search/discovery layer")
    ap.add_argument("--json", action="store_true", help="also write the raw payload as JSON")
    ap.add_argument("--manual", help="path to a JSON file of Instagram manual fields")
    ap.add_argument("--competitors", action="store_true",
                    help="run competitor discovery (costs extra search queries)")
    args = ap.parse_args()
    seeds = args.url

    def progress(stage: str, pct: int) -> None:
        print(f"  [{pct:3d}%] {stage}", file=sys.stderr)

    manual = json.loads(Path(args.manual).read_text()) if args.manual else None
    payloads = []
    raws = []
    for i, seed in enumerate(seeds):
        print(f"Collecting [{i+1}/{len(seeds)}] {seed}", file=sys.stderr)
        raw = await pipeline.collect(seed, run_dorks=not args.no_dorks, progress=progress)
        if manual:
            from app.engine.collectors.instagram import merge_manual
            for acc in raw.accounts:
                if acc.platform == "instagram":
                    merge_manual(acc, manual)
        raws.append(raw)
        comps = await pipeline.find_competitors(raw) if args.competitors else None
        payloads.append(pipeline.analyse(raw, uuid.uuid4().hex[:12], competitors=comps))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if len(payloads) == 1:
        payload = payloads[0]
        stem = (payload.subject_handle or "report").strip("@").replace("/", "-")
        (out / f"{stem}.html").write_text(html_render.render(payload), encoding="utf-8")
        docx_render(payload, str(out / f"{stem}.docx"))
        if args.json:
            (out / f"{stem}.json").write_text(payload.model_dump_json(indent=2),
                                              encoding="utf-8")
        print(f"\n  subject     {payload.subject_name}", file=sys.stderr)
        print(f"  archetype   {payload.audience.archetype_label}", file=sys.stderr)
        print(f"  confidence  {round(payload.audience.overall_confidence*100)}%", file=sys.stderr)
        print(f"  surfaces    {len(raws[0].accounts)}", file=sys.stderr)
        print(f"  signals     {len(payload.audience.signals_fired)}", file=sys.stderr)
    else:
        cp = pipeline.analyse_cohort(payloads, uuid.uuid4().hex[:12])
        stem = "cohort-" + "-".join(
            (p.subject_handle or "x").strip("@")[:12] for p in payloads[:3])
        (out / f"{stem}.html").write_text(html_render.render_cohort(cp), encoding="utf-8")
        docx_cohort(cp, str(out / f"{stem}.docx"))
        if args.json:
            (out / f"{stem}.json").write_text(cp.model_dump_json(indent=2), encoding="utf-8")
        print(f"\n  cohort      {len(payloads)} creators", file=sys.stderr)
        print(f"  headline    {cp.cohort.headline}", file=sys.stderr)
        print(f"  overlap     median {cp.cohort.median_overlap}%, "
              f"peak {cp.cohort.max_overlap}%", file=sys.stderr)
    print(f"\n  written to {out.resolve()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
