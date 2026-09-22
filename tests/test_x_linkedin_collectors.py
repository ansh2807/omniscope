"""X and LinkedIn collectors — pasted URLs must collect like IG/YT seeds."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.engine.collectors import linkedin as li
from app.engine.collectors import x as x_col
from app.engine.inference import engine as infer
from app.engine.pipeline import _collect_one
from app.engine.resolver import resolve
from app.schemas import PlatformAccount, RawProfile


class _Resp:
    def __init__(self, text: str = "", status: int = 200, ok: bool | None = None):
        self.text = text
        self.status = status
        self.ok = (status == 200 and bool(text)) if ok is None else ok


def test_resolver_accepts_x_and_linkedin_seeds():
    x = resolve("https://x.com/OpenAI")
    assert x.platform == "x" and x.handle.lower() == "openai"
    tw = resolve("https://twitter.com/OpenAI")
    assert tw.platform == "x"
    li_r = resolve("https://www.linkedin.com/in/satyanadella/")
    assert li_r.platform == "linkedin" and "satyanadella" in li_r.handle.lower()


def test_x_collector_uses_syndication_json():
    payload = [{
        "screen_name": "OpenAI",
        "name": "OpenAI",
        "description": "AI research and deployment",
        "followers_count": 2_400_000,
        "friends_count": 12,
        "statuses_count": 5_000,
        "verified": True,
    }]

    async def fake_fetch(url, **kw):
        if "syndication.twimg.com" in url:
            return _Resp(json.dumps(payload))
        return _Resp("", status=404)

    with patch("app.engine.collectors.x.fetch", new=AsyncMock(side_effect=fake_fetch)):
        acc = asyncio.run(x_col.collect("OpenAI"))

    assert acc.platform == "x"
    assert acc.handle == "OpenAI"
    assert acc.followers == 2_400_000
    assert acc.following == 12
    assert acc.display_name == "OpenAI"
    assert "AI research" in (acc.bio or "")
    assert acc.raw.get("source") == "syndication_followbutton"
    assert not any("authentication wall" in e.lower() for e in acc.errors)


def test_linkedin_collector_reads_public_meta():
    html = """
    <html><head>
      <meta property="og:title" content="Jane Creator - AI educator | LinkedIn"/>
      <meta property="og:description" content="12K followers on LinkedIn. Helping operators ship."/>
    </head><body></body></html>
    """

    async def fake_fetch(url, **kw):
        return _Resp(html)

    with patch("app.engine.collectors.linkedin.fetch", new=AsyncMock(side_effect=fake_fetch)):
        with patch("app.engine.collectors.browser.enabled", return_value=False):
            acc = asyncio.run(li.collect("jane-creator"))

    assert acc.platform == "linkedin"
    assert acc.display_name == "Jane Creator"
    assert acc.followers == 12_000
    assert "operators" in (acc.bio or "").lower() or "AI educator" in (acc.bio or "")
    assert acc.needs_manual is True  # engagement stays walled


def test_pipeline_collect_one_routes_x_and_linkedin():
    x_acc = PlatformAccount(
        platform="x", handle="demo", url="https://x.com/demo",
        followers=1000, raw={"source": "syndication_followbutton"})
    li_acc = PlatformAccount(
        platform="linkedin", handle="demo-person",
        url="https://www.linkedin.com/in/demo-person/",
        display_name="Demo Person", raw={"source": "public_profile_meta"})

    with patch("app.engine.pipeline.x_col.collect",
               new=AsyncMock(return_value=x_acc)) as xc:
        out = asyncio.run(_collect_one("x", "https://x.com/demo"))
        assert out is x_acc
        xc.assert_awaited()

    with patch("app.engine.pipeline.li.collect",
               new=AsyncMock(return_value=li_acc)) as lc:
        out = asyncio.run(_collect_one(
            "linkedin", "https://www.linkedin.com/in/demo-person/"))
        assert out is li_acc
        lc.assert_awaited()


def test_x_probe_confirms_matching_handle():
    from app.engine.discovery import probe as pr

    payload = [{
        "screen_name": "democreator",
        "name": "Demo Creator",
        "description": "host",
        "followers_count": 9_000_000,
    }]

    async def fake_fetch(url, **kw):
        if "syndication" in url:
            return _Resp(json.dumps(payload))
        return _Resp("", status=404)

    with patch("app.engine.discovery.probe.fetch", new=AsyncMock(side_effect=fake_fetch)):
        res = asyncio.run(pr.run("democreator", display_name="Demo Creator",
                                 known={"youtube", "telegram", "threads",
                                        "topmate", "linktree", "superprofile"}))

    assert any(h.platform == "x" and h.confirmed for h in res.hits)
    hit = next(h for h in res.hits if h.platform == "x")
    assert hit.followers_hint == 9_000_000


def test_audience_unavailable_lists_collected_x_and_linkedin_honestly():
    raw = RawProfile(
        seed_url="https://x.com/demo", seed_platform="x", seed_handle="demo",
        accounts=[
            PlatformAccount(platform="x", handle="demo", url="https://x.com/demo",
                            followers=10_000, bio="finance tips India",
                            raw={"source": "syndication_followbutton"}),
            PlatformAccount(platform="linkedin", handle="demo",
                            url="https://linkedin.com/in/demo",
                            display_name="Demo", needs_manual=True,
                            raw={"source": "public_profile_meta"}),
        ],
    )
    from app.engine.inference.signals import extract
    model = infer.run(extract(raw), raw)
    blob = " ".join(f"{u['data']} {u['why']}" for u in model.unavailable).lower()
    assert "x post-level" in blob or "x (twitter)" in blob or "engagement" in blob
    assert "linkedin" in blob
    # Should not claim LinkedIn is missing when we have the account.
    assert "no linkedin account was collected" not in blob
