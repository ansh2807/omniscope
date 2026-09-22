"""Run the Creator Intelligence engine's offline multi-creator calibration corpus.

Usage: .venv\\Scripts\\python.exe tools\\calibrate_engine.py
Exit code is non-zero when an accuracy contract fails, making this CI-friendly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine import calibration, pipeline  # noqa: E402
from app.schemas import ContentItem, PlatformAccount, Product, RawProfile  # noqa: E402
from tests import fixtures  # noqa: E402


def _synthetic(name: str, handle: str, titles: list[str], followers: int = 0,
               products: list[Product] | None = None) -> RawProfile:
    account = PlatformAccount(
        platform="youtube", handle=handle, url=f"https://youtube.com/@{handle}",
        display_name=name, followers=followers or None, raw={"verified_via": "seed"})
    for i, title in enumerate(titles):
        account.content.append(ContentItem(
            platform="youtube", title=title, views=(i + 1) * 1700,
            published_at=datetime.now() - timedelta(days=i * 14),
            raw={"sort": "latest"}))
    account.products = products or []
    return RawProfile(seed_url=account.url, seed_platform="youtube", seed_handle=handle,
                      display_name=name, accounts=[account])


def build_corpus():
    factories = [fixtures.sunil_panda, fixtures.chanchal_singh,
                 fixtures.rj_shubham, fixtures.ishaan_arora]
    reports = [pipeline.analyse(factory(), f"cal-{factory.__name__}")
               for factory in factories]
    synthetic = [
        _synthetic("Maya Colours", "mayacolours", [
            "Watercolour portrait tutorial", "Mixing skin tones",
            "Sketchbook tour", "Beginner brush control"], 14_000),
        _synthetic("Dev Byte", "devbyte", [
            "Build an AI agent in Python", "React performance debugging",
            "LLM RAG architecture explained", "Deploy FastAPI on cloud"], 310_000,
            [Product(name="AI Builder Bootcamp", price_inr=7999)]),
        _synthetic("Quiet Signal", "quietsig", [], 0),
        _synthetic("Fit With Arjun", "fitwitharjun", [
            "30 minute home workout", "Protein meal prep",
            "Beginner mobility routine", "Fat loss mistakes"], 88_000),
    ]
    reports.extend(pipeline.analyse(raw, f"cal-synthetic-{i}")
                   for i, raw in enumerate(synthetic, 1))
    return reports


def main() -> int:
    reports = build_corpus()
    result = calibration.evaluate(reports)
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
