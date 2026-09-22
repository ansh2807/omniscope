"""DESK — evidence-only marketing brief. Never invent traffic, TAM, or spend."""
from datetime import datetime, timezone

from app.engine.render.html import render_web
from app.omni.desk import build_creator_desk, build_web_desk
from app.omni.webintel import WebIntelPayload


def _web(**extra) -> WebIntelPayload:
    return WebIntelPayload(
        report_id="t" * 12,
        generated_at=datetime.now(timezone.utc),
        entity_name=extra.pop("entity_name", "Bare Co"),
        domain=extra.pop("domain", "bare.example"),
        seed_url=extra.pop("seed_url", "https://bare.example/"),
        **extra,
    )


def _need(desk, nid: str):
    return next(n for n in desk.needs if n.id == nid)


def _cell(desk, framework: str, slot: str):
    fw = next(f for f in desk.frameworks if framework.lower() in f.name.lower())
    return next(c for c in fw.cells if c.slot.lower() == slot.lower())


def test_web_desk_offer_unavailable_without_pricing():
    desk = build_web_desk(_web())
    assert _need(desk, "offer").status == "unavailable"
    assert "json-ld" in _need(desk, "offer").evidence.lower()
    assert desk.kind == "web"
    assert any("TAM" in row for row in desk.cannot_know)


def test_web_desk_ads_txt_is_not_spend():
    desk = build_web_desk(_web(ads_intel={"assessed": True, "files": ["ads.txt"]}))
    paid = _cell(desk, "owned", "Paid")
    assert paid.status == "observed"
    assert "ads.txt" in paid.fill.lower()
    blob = " ".join(desk.cannot_know + [paid.note]).lower()
    assert "spend" in blob
    assert "₹" not in paid.fill
    assert "cpm" not in blob


def test_web_desk_does_not_invent_traffic():
    desk = build_web_desk(_web(tagline="We help teams ship"))
    blob = (desk.one_liner + desk.job + " ".join(n.evidence for n in desk.needs)).lower()
    for banned in ("sessions", "pageviews/month", "keyword volume", "market share"):
        assert banned not in blob
    assert _need(desk, "demand").status == "unavailable"


def test_web_desk_offer_observed_from_jsonld():
    desk = build_web_desk(_web(
        tagline="Analytics for operators",
        products=[{"name": "Pro", "price_inr": 4999}],
        product_intel={"assessed": True, "ladder": [{"name": "Pro", "price_inr": 4999}]},
    ))
    assert _need(desk, "offer").status == "observed"
    price = _cell(desk, "4ps", "Price")
    assert price.status == "observed"
    assert "4,999" in price.fill


def test_creator_desk_login_wall_is_not_zero_followers():
    desk = build_creator_desk(
        name="Ada",
        handle="ada",
        overview={"credentials": [], "product_stack": [], "press": []},
        signals={"total_audience": 0, "primary_platform": ""},
        content={"measured_items": 0, "current_median": None, "cadence_per_month": None},
        media_buy={"verdict": ""},
        keyless={},
        accounts=[{"platform": "instagram", "needs_manual": True,
                   "errors": ["login wall"]}],
    )
    scale = _need(desk, "scale")
    assert scale.status == "unavailable"
    assert "login" in scale.evidence.lower()
    assert "0 follower" not in scale.evidence.lower()
    assert any("Insights" in row for row in desk.cannot_know)


def test_creator_desk_wikidata_works_are_not_product_stack():
    desk = build_creator_desk(
        name="Ada Lovelace",
        handle="ada",
        overview={"credentials": ["mathematician"], "product_stack": [],
                  "press": [], "positioning": ""},
        signals={"total_audience": 0},
        content={"measured_items": 1},
        keyless={"wikipedia_title": "Ada Lovelace", "orcid": "0000-0002-1825-0097",
                 "pageviews": {"views": 12000, "days": 30}},
    )
    assert _need(desk, "offer").status == "unavailable"
    assert "sku" in _need(desk, "offer").meaning.lower()
    attention = _need(desk, "attention")
    assert attention.status == "observed"
    assert "12,000" in attention.evidence
    assert "traffic" in attention.next_step.lower() or "traffic" in attention.meaning.lower()
    blob = " ".join(desk.cannot_know).lower()
    assert "tam" in blob


def test_creator_desk_delivery_needs_measured_views():
    desk = build_creator_desk(
        name="Chan",
        handle="chan",
        signals={"total_audience": 80_000, "primary_platform": "youtube"},
        content={"measured_items": 8, "current_median": 12_500,
                 "cadence_per_month": 4.0},
        media_buy={"verdict": "pilot"},
        accounts=[{"platform": "youtube", "needs_manual": False, "errors": []}],
    )
    assert _need(desk, "delivery").status == "calculated"
    assert _need(desk, "scale").status == "observed"
    assert _need(desk, "buy").status == "modelled"
    assert "pilot" in desk.job.lower() or "pilot" in desk.posture.lower()


def test_web_report_renders_desk_section():
    html = render_web(_web(
        tagline="Decisions from product data",
        content={"pages_sampled": 1, "total_words": 120, "latest_dated_content": None},
        seo={"robots_txt": False, "sitemap_xml": False, "sitemap_url_count": 0,
             "structured_data_types": []},
        scores=[], overall_score=12,
        unavailable=[{"item": "Traffic", "why": "first-party analytics"}],
    ))
    assert "Marketing desk" in html
    assert "Eight basic marketing needs" in html
    assert "Will not be invented" in html
    assert "TAM" in html


def test_desk_hub_and_api_are_public():
    from fastapi.testclient import TestClient

    from app import main
    client = TestClient(main.app)
    page = client.get("/desk")
    assert page.status_code == 200
    assert b"Basic marketing needs" in page.content
    assert b"Who you appear to be" in page.content
    assert b"Playbooks" in page.content
    assert client.get("/api/v1/desk").status_code == 200
    index = client.get("/api/v1")
    assert "GET /api/v1/desk" in index.json()["endpoints"]


def test_web_desk_playbook_from_ads_txt_is_not_spend():
    desk = build_web_desk(_web(ads_intel={"assessed": True, "files": ["ads.txt"]}))
    ads = next(p for p in desk.playbooks if p.id == "ads_inventory")
    assert ads.status == "observed"
    assert "cpm" in ads.cannot.lower() or "spend" in (ads.cannot + ads.why + " ".join(ads.steps)).lower()
    assert "media plan" in ads.title.lower() or "inventory" in ads.title.lower()


def test_web_desk_llms_txt_is_not_traffic():
    desk = build_web_desk(_web(public_intel={
        "assessed": True,
        "files": [{"path": "/llms.txt", "present": True, "excerpt": "# Acme"}],
    }))
    ai = next(p for p in desk.playbooks if p.id == "ai_surface")
    blob = (ai.why + ai.cannot + " ".join(ai.steps)).lower()
    assert "invitation" in blob or "crawl" in blob
    assert "traffic" in blob
    assert _need(desk, "channel").status == "observed"


def test_web_desk_security_txt_is_trust_not_soc2():
    desk = build_web_desk(_web(public_intel={
        "assessed": True,
        "files": [{"path": "/.well-known/security.txt", "present": True,
                   "contacts": ["mailto:security@bare.example"]}],
    }))
    assert _need(desk, "trust").status == "observed"
    assert "security@bare.example" in _need(desk, "trust").evidence
    sec = next(p for p in desk.playbooks if p.id == "security_contact")
    assert "soc 2" in sec.cannot.lower()


def test_creator_desk_playbook_does_not_guess_handles():
    desk = build_creator_desk(
        name="Ada",
        handle="ada",
        accounts=[{"platform": "instagram", "needs_manual": True,
                   "errors": ["login wall"]}],
    )
    leave = next(p for p in desk.playbooks if p.id == "leave_the_wall")
    blob = " ".join(leave.steps).lower()
    assert "bluesky" in blob or "orcid" in blob
    assert "guess" in blob


def test_compare_desk_does_not_pick_a_winner():
    from app.omni.compare import compare_payloads

    left = {
        "entity_name": "Acme", "domain": "acme.example", "overall_score": 40,
        "tagline": "Ops software",
        "products": [{"name": "Acme Pro", "price_inr": 1000}],
    }
    right = {
        "entity_name": "Bare", "domain": "bare.example", "overall_score": 12,
    }
    intel = compare_payloads(left, right)
    assert intel.assessed is True
    assert intel.desk_rows
    offer = next(r for r in intel.desk_rows if r.field == "What you sell")
    assert offer.note == "left_only"
    assert "winner" not in intel.verdict.lower()
    assert all(r.note != "winner" for r in intel.desk_rows)
    assert "offer" in intel.left_job.lower() or "offer" in intel.right_job.lower()
