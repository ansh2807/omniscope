"""DESK — marketing-needs engine over evidence already collected.

This is the beginner layer. It does not fetch. It does not invent traffic, TAM,
demographics, or follower counts. It maps observed / calculated / modelled
fields onto the questions a marketer actually asks:

  Who do we appear to be? What do we sell? Why believe us? Where do we show
  up? Can someone act? What should we do this week? What can we not know?

Frameworks (4Ps, AIDA, owned/earned/paid, funnel) are templates filled from
payload fields. An empty slot stays UNAVAILABLE.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.omni.llm import narrate_desk

OBS, CALC, MOD, UNA = "observed", "calculated", "modelled", "unavailable"

WEB_CANNOT = (
    "TAM, market share, or category size",
    "Site traffic, rankings, or keyword volume without a licensed search product",
    "Ad spend — ads.txt is a publisher declaration, not a bill",
    "Conversion rate, CAC, LTV, or pipeline",
    "Audience demographics the site did not publish",
    "Whether a competitor is actually winning",
)
CREATOR_CANNOT = (
    "Unique reach, audience overlap, or Stories/Insights totals",
    "Fake-follower percentage from public aggregates",
    "Audience age, gender, income, or city mix unless a source printed it",
    "Campaign impressions, brand lift, or sales attributed to a post",
    "Instagram / X / LinkedIn / Threads / Facebook grids behind a login wall",
    "TAM for the creator's category",
)

GLOSSARY = (
    ("Observed", "Copied from a public page or an official API. We did not infer it."),
    ("Calculated", "Derived from those public numbers — a median, a cadence, a score."),
    ("Modelled", "A labelled score on public fields. Not a platform fact and not a forecast."),
    ("Unavailable", "We did not see it. Empty is not zero, and it is not a reason to invent a number."),
    ("Offer", "A named product, plan or price a buyer can evaluate. A slogan is not an offer."),
    ("Proof", "A review body or printed rating the site published. Star copy in a paragraph is not a rating."),
    ("Demand", "Here: news hits, named rivals, or missing public paths. Not keyword volume."),
    ("Owned / earned / paid", "Site+feed+email / linked socials+news / ads.txt rows. ads.txt is not spend."),
    ("TAM", "Total addressable market. We will not invent one from a homepage."),
)

WEB_NEED_GUIDE = (
    ("identity", "Who you appear to be",
     "The sentence a stranger would use after one look at the homepage."),
    ("offer", "What you sell",
     "A named product or plan. Without this, ads send people nowhere."),
    ("proof", "Why believe you",
     "On-page reviews or a printed rating you can stand behind."),
    ("demand", "Whether anyone is looking",
     "Public substitutes: news, named rivals, missing site paths. Not search volume."),
    ("channel", "Where you already show up",
     "Surfaces the site itself linked — feed, socials, ads.txt, email tool."),
    ("conversion", "Can a stranger act",
     "A form, checkout, demo or pricing path with a named next step."),
    ("trust", "Why a buyer should start",
     "Privacy link, public contact, HTTPS. Not a brand-sentiment score."),
    ("measurement", "Can you learn next week",
     "A sitemap and one analytics fingerprint. They are not traffic."),
)

CREATOR_NEED_GUIDE = (
    ("identity", "Who they appear to be",
     "Published bio, occupation or Wikipedia extract — not a guessed persona."),
    ("delivery", "Whether people actually watch",
     "Recent public views on measured uploads. Subscribers are not views."),
    ("system", "Whether they publish on a rhythm",
     "A measured cadence from dated public items, not a promised calendar."),
    ("offer", "What they sell or attach to",
     "A product, course or link they published. Wikidata works are not SKUs."),
    ("scale", "Public follow totals",
     "Reachability only. Not unique people and not Instagram Insights."),
    ("channel", "Surfaces we could collect",
     "Platforms that returned a public profile. Look-alike handles are forbidden."),
    ("attention", "Public interest off-platform",
     "Wikipedia pageviews if Wikidata already named the article. Not site traffic."),
    ("buy", "Media-buy posture",
     "Prioritize / pilot / hold / pass on public evidence. Not a CPM quote."),
)


class DeskNeed(BaseModel):
    id: str
    title: str
    status: str
    meaning: str
    evidence: str
    next_step: str
    effort: str = "S"


class DeskCell(BaseModel):
    slot: str
    status: str
    fill: str
    note: str = ""


class DeskFramework(BaseModel):
    name: str
    status: str
    cells: list[DeskCell] = Field(default_factory=list)


class DeskPlaybook(BaseModel):
    id: str
    title: str
    status: str
    why: str
    steps: list[str] = Field(default_factory=list)
    cannot: str = ""


class MarketingDesk(BaseModel):
    assessed: bool = True
    kind: str
    one_liner: str
    job: str
    posture: str
    needs: list[DeskNeed] = Field(default_factory=list)
    frameworks: list[DeskFramework] = Field(default_factory=list)
    playbooks: list[DeskPlaybook] = Field(default_factory=list)
    week_plan: list[str] = Field(default_factory=list)
    cannot_know: list[str] = Field(default_factory=list)
    glossary: list[dict[str, str]] = Field(default_factory=list)
    narrative: str = ""
    llm_used: bool = False
    methodology: str = (
        "DESK restates public evidence as a marketing brief. Every cell is "
        "observed, calculated, modelled from printed fields, or unavailable. "
        "An optional language model may restate filled cells as prose when a "
        "key is configured; the brief is complete without it. No invented "
        "traffic, TAM, or private metrics.")


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(key, default if key == keys[-1] else None)
        else:
            cur = getattr(cur, key, default if key == keys[-1] else None)
    return default if cur is None else cur


def _n(seq: Any) -> int:
    return len(seq) if isinstance(seq, (list, tuple, set)) else 0


def _need(nid: str, title: str, status: str, meaning: str, evidence: str,
          next_step: str, effort: str = "S") -> DeskNeed:
    return DeskNeed(id=nid, title=title, status=status, meaning=meaning,
                    evidence=evidence, next_step=next_step, effort=effort)


def _cell(slot: str, status: str, fill: str, note: str = "") -> DeskCell:
    return DeskCell(slot=slot, status=status, fill=fill, note=note)


def _glossary() -> list[dict[str, str]]:
    return [{"term": term, "meaning": meaning} for term, meaning in GLOSSARY]


def _with_narrative(desk: MarketingDesk) -> MarketingDesk:
    text = narrate_desk(desk.model_dump())
    if text:
        desk.narrative = text
        desk.llm_used = True
    return desk


def _playbook(pid: str, title: str, status: str, why: str,
              steps: list[str], cannot: str = "") -> DeskPlaybook:
    return DeskPlaybook(id=pid, title=title, status=status, why=why,
                        steps=steps[:5], cannot=cannot)


def _public_files(payload: Any) -> dict[str, Any]:
    files = _get(payload, "public_intel", "files") or []
    out: dict[str, Any] = {}
    for item in files:
        path = str(_get(item, "path") or "")
        if path:
            out[path] = item
    return out


def _file_present(files: dict[str, Any], *needles: str) -> bool:
    for path, item in files.items():
        if any(n in path for n in needles) and _get(item, "present"):
            return True
    return False


def _security_contacts(files: dict[str, Any]) -> list[str]:
    contacts: list[str] = []
    for path, item in files.items():
        if "security.txt" not in path:
            continue
        for row in _get(item, "contacts") or []:
            text = str(row).strip()
            if text and text not in contacts:
                contacts.append(text)
    return contacts[:8]


def _web_playbooks(*, name: str, has_offer: bool, has_proof: bool,
                   has_feed: bool, has_cta: bool, ads_files: int,
                   llms: bool, security_contacts: list[str],
                   missing_seo: list, has_cik: bool = False,
                   has_cin: bool = False, has_lei: bool = False
                   ) -> list[DeskPlaybook]:
    out: list[DeskPlaybook] = []
    if not has_offer:
        out.append(_playbook(
            "name_offer", "Name one public offer this week", OBS,
            f"{name} has no Product/Offer JSON-LD or pricing page in the sample.",
            ["Pick the one plan a first visit should evaluate.",
             "Put the name and a next step on the homepage and a /pricing or /plans path.",
             "Mark it with Product or Offer schema you can stand behind."],
            "A slogan or category word is not an offer."))
    elif not has_proof:
        out.append(_playbook(
            "attach_proof", "Attach proof to the offer", OBS,
            "A named offer without an on-page review or printed rating asks the buyer to trust a paragraph.",
            ["Collect 3–5 review bodies you can publish on-site.",
             "Add an AggregateRating only if the number is real.",
             "Place the strongest printed rating next to the primary CTA."],
            "Star copy in a sentence is not a rating."))
    if has_feed:
        out.append(_playbook(
            "owned_cadence", "Four weeks on the feed you already advertise", OBS,
            "An RSS/Atom feed is an owned return path. Use it before buying attention.",
            ["Week 1: publish one item that names the offer and the next step.",
             "Week 2: publish one proof item (review, case, or FAQ you already have).",
             "Week 3: publish one item that answers a missing path "
             + ((missing_seo[0] + ".") if missing_seo else "a buyer already asks."),
             "Week 4: re-run Deep Analyze and compare the desk."],
            "A feed is not traffic and not an email list."))
    if ads_files:
        out.append(_playbook(
            "ads_inventory", "ads.txt is inventory, not a media plan", OBS,
            f"{ads_files} ads.txt file(s) were served. That is a publisher declaration.",
            ["If you sell ads, keep DIRECT/RESELLER rows accurate.",
             "If you buy ads, do not read this file as your spend or your paid-social plan.",
             "Do not brief a media buyer from ads.txt alone."],
            "DIRECT/RESELLER is not a bill and not CPM."))
    if llms:
        out.append(_playbook(
            "ai_surface", "You invited AI crawlers — treat it as a surface", OBS,
            "/llms.txt or /ai.txt was served. That is a crawl invitation, not sessions.",
            ["Read the file. It should name the product the way the homepage does.",
             "If the offer or proof on the site changed, update the file the same week.",
             "Do not put Wikipedia pageviews or guessed traffic in it."],
            "An llms.txt hit is not bot traffic and not a ranking."))
    if security_contacts:
        out.append(_playbook(
            "security_contact", "Publish the security contact next to trust", OBS,
            "security.txt listed: " + "; ".join(security_contacts[:2]) + ".",
            ["Keep that Contact: line current (RFC 9116).",
             "Link privacy and this contact from the same footer as the CTA."],
            "A Contact: line is not a SOC 2 badge."))
    if has_cta and not has_offer:
        out.append(_playbook(
            "cta_without_offer", "The button has nowhere to send them", OBS,
            "A form or CTA was observed without a named offer.",
            ["Point the primary CTA at the one plan you will name this week.",
             "Use the same verb on homepage, pricing, and the share card."],
            "A 'Learn more' heading is not a conversion path."))
    if has_cik:
        out.append(_playbook(
            "sec_record", "SEC filings are a public record, not a valuation", OBS,
            f"{name} already had a CIK, so EDGAR submissions were copied.",
            ["Read the latest 10-K/10-Q or equivalent form the pack listed.",
             "Use the printed legal name next to the homepage offer.",
             "Do not brief a buyer with a guessed market cap."],
            "A ticker or SIC code is not a share price."))
    elif has_cin:
        out.append(_playbook(
            "cin_printed", "CIN is printed; MCA text is unavailable", OBS,
            "A CIN matched the MCA pattern. The registry itself is login-walled.",
            ["Keep the printed CIN next to GSTIN if you already publish both.",
             "Do not invent authorised capital or a valuation from the pattern."],
            "A matching CIN string is not a verified incorporation lookup."))
    elif has_lei:
        out.append(_playbook(
            "lei_record", "LEI names the legal entity, not the brand", OBS,
            "A Legal Entity Identifier was already printed or on Wikidata.",
            ["Use the GLEIF legal name when a contract needs the registered party.",
             "Do not treat LEI status as creditworthiness."],
            "GLEIF is not a valuation."))
    return out[:8]


def _creator_playbooks(*, subject: str, has_delivery: bool, has_offer: bool,
                       login_walled: bool, verdict: str) -> list[DeskPlaybook]:
    out: list[DeskPlaybook] = []
    if login_walled and not has_delivery:
        out.append(_playbook(
            "leave_the_wall", "Collect a public surface before you brief a buy", OBS,
            f"{subject} hit a login wall. That is empty, not zero delivery.",
            ["Paste a YouTube, site, or podcast URL they already print.",
             "Re-run Deep Analyze on that URL.",
             "Do not guess a Bluesky or ORCID from Instagram."],
            "A walled grid is not a follower count."))
    if not has_delivery:
        out.append(_playbook(
            "ask_insights", "Price from last-8-post delivery, not follows", OBS,
            "Public view counts were too thin to calculate delivery.",
            ["Ask for a screen-recorded Insights walkthrough of the last 8 posts.",
             "Compare those numbers to any public median in this pack.",
             "Hold the rate until both exist."],
            "Subscribers are not views."))
    elif verdict in {"hold", "pass"}:
        out.append(_playbook(
            "respect_verdict", f"The public scorecard is {verdict}", MOD,
            "Do not override a hold/pass with a follower screenshot.",
            ["If you still want them, ask for Insights and a trackable URL first.",
             "Re-run after those exist."],
            "A modelled verdict is not a platform fact."))
    if not has_offer:
        out.append(_playbook(
            "trackable_url", "Ask for one trackable offer URL", OBS,
            "No product, course, or link stack was published on collected profiles.",
            ["Get one URL they already use for affiliates or products.",
             "Do not treat Wikidata works as SKUs."],
            "Notable works are not a product catalog."))
    return out[:5]


def _week_plan(needs: list[DeskNeed], extra: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for need in needs:
        if need.status == UNA:
            continue
        step = (need.next_step or "").strip()
        if step and step not in out:
            out.append(step)
        if len(out) >= 5:
            return out
    for item in extra or []:
        if item and item not in out:
            out.append(item)
        if len(out) >= 5:
            break
    return out[:5]


def _posture_web(*, overall: float, has_offer: bool, has_proof: bool,
                 has_feed: bool) -> str:
    if overall >= 70 and has_offer and has_proof:
        return "Established public presence — tighten proof and demand, do not rebuild the basics"
    if has_offer or has_feed:
        return "Growing public presence — the offer or publishing system exists; fill the holes"
    return "Early public presence — name the offer and one proof surface before buying ads"


def _posture_creator(*, followers: int, measured: int, verdict: str) -> str:
    if verdict in {"prioritize", "pilot"} and measured >= 4:
        return "Buyable on public delivery evidence — still verify Insights before a rate"
    if followers >= 10_000 or measured >= 4:
        return "Public creator with some measurable surface — treat follower totals as reachability, not reach"
    return "Thin public evidence — do not price from a login-walled profile"


def _web_extra_frameworks(*, payload: Any, has_offer: bool, has_proof: bool,
                          has_cta: bool, has_feed: bool, has_card: bool,
                          socials: list, news_n: int, ads_files: int,
                          email_vendor: list, rival_n: int, missing_seo: list,
                          tagline: str, domain: str) -> list[DeskFramework]:
    faqs = _n(_get(payload, "schema_intel", "faqs") or [])
    langs = list(_get(payload, "locale_intel", "langs") or [])
    seo_slots = _get(payload, "seo_map", "slots") or []
    about_missing = any(str(s).lower() == "about" for s in missing_seo)
    about_present = bool(seo_slots) and not about_missing
    offer_names = []
    for offer in (_get(payload, "product_intel", "ladder")
                  or _get(payload, "products") or [])[:3]:
        if isinstance(offer, dict) and offer.get("name"):
            offer_names.append(str(offer["name"]))
    funnel = DeskFramework(
        name="Funnel (aware → return)",
        status=MOD,
        cells=[
            _cell("Aware", OBS if (has_card or news_n) else UNA,
                  "Share card or news hit observed" if (has_card or news_n)
                  else "No share card and no news hit",
                  "Not impressions."),
            _cell("Consider", OBS if (faqs or has_offer or about_present) else UNA,
                  ("FAQ, named offer, or an about path"
                   if (faqs or has_offer) else
                   "About path present in the sample" if about_present else
                   "No FAQ, offer, or about path"),
                  "A missing About slot is a hole, not a strategy."),
            _cell("Decide", OBS if (has_cta or has_proof) else UNA,
                  "CTA/pricing or printed proof" if (has_cta or has_proof)
                  else "No decision path in the sample",
                  ""),
            _cell("Return", OBS if (has_feed or email_vendor) else UNA,
                  "Feed or email tool observed" if (has_feed or email_vendor)
                  else "No advertised feed or email fingerprint",
                  "A pixel is not a list."),
        ])
    stp = DeskFramework(
        name="STP (segment / target / position)",
        status=MOD,
        cells=[
            _cell("Segment", OBS if langs else UNA,
                  ", ".join(str(x) for x in langs[:6]) or "No html lang / locale tags",
                  "A language tag is not a demographic and not a market."),
            _cell("Target", OBS if (offer_names or tagline) else UNA,
                  ", ".join(offer_names) or tagline or "No named offer or tagline",
                  "We do not invent 'millennials' or a TAM around this."),
            _cell("Position", OBS if tagline else UNA,
                  tagline or "No homepage sentence to hold a position against",
                  (f"{rival_n} official-site rival(s) named in search."
                   if rival_n else "No rival list stored. Absence is not 'category leader'.")),
        ])
    race = DeskFramework(
        name="RACE (reach / act / convert / engage)",
        status=CALC,
        cells=[
            _cell("Reach", OBS if (_n(socials) or news_n or ads_files) else UNA,
                  f"{_n(socials)} linked social(s), {news_n} news, {ads_files} ads.txt",
                  "ads.txt ≠ spend. News hits ≠ circulation."),
            _cell("Act", OBS if has_cta else UNA,
                  "Form, CTA or pricing path" if has_cta else "No action path in sample",
                  ""),
            _cell("Convert", OBS if has_offer else UNA,
                  "Named offer or pricing page" if has_offer else "No public offer",
                  ""),
            _cell("Engage", OBS if (has_feed or email_vendor) else UNA,
                  "Feed or email tool" if (has_feed or email_vendor)
                  else "No return path observed",
                  ""),
        ])
    jtbd = DeskFramework(
        name="Job to be done (from the homepage, not a workshop)",
        status=OBS if tagline else UNA,
        cells=[
            _cell("Job", OBS if tagline else UNA,
                  tagline or "No tagline or H1 job sentence on the sampled homepage",
                  f"Read on {domain}" if domain else "Homepage sentence only."),
        ])
    return [funnel, stp, race, jtbd]


def _creator_extra_frameworks(*, has_scale: bool, has_delivery: bool,
                              has_cadence: bool, has_offer: bool,
                              pillars: list, followers: int,
                              pageviews: dict) -> list[DeskFramework]:
    return [DeskFramework(
        name="Funnel for a creator brief",
        status=MOD,
        cells=[
            _cell("Aware", OBS if (has_scale or pageviews.get("views")) else UNA,
                  (f"{followers:,} public follows"
                   if has_scale else
                   "Wikipedia pageviews only" if pageviews.get("views") else
                   "No public follow total or pageviews"),
                  "Not unique reach."),
            _cell("Consider", OBS if pillars else UNA,
                  ", ".join(pillars) or "No recurring title tokens",
                  "Title tokens, not search demand."),
            _cell("Convert", OBS if has_offer else UNA,
                  "Published offer path" if has_offer else "No trackable offer URL",
                  ""),
            _cell("Return", CALC if has_cadence else UNA,
                  "Measured publishing cadence" if has_cadence
                  else "Cadence unmeasured",
                  ""),
        ])]


# ------------------------------------------------------------------ website
def build_web_desk(payload: Any) -> MarketingDesk:
    name = str(_get(payload, "entity_name") or _get(payload, "domain") or "this site")
    domain = str(_get(payload, "domain") or "")
    tagline = str(_get(payload, "tagline") or "")
    overall = float(_get(payload, "overall_score") or 0)
    products = _get(payload, "product_intel") or {}
    ladder = products.get("ladder") if isinstance(products, dict) else None
    offers = ladder or _get(payload, "products") or []
    reviews = _get(payload, "review_intel") or {}
    ratings = _get(reviews, "ratings") or []
    review_items = _get(reviews, "items") or []
    socials = _get(payload, "socials") or []
    feeds = _get(payload, "feed_intel") or {}
    ads = _get(payload, "ads_intel") or {}
    cards = _get(payload, "card_intel") or {}
    seo_map = _get(payload, "seo_map") or {}
    onpage = _get(payload, "onpage_intel") or {}
    legal = _get(payload, "legal_intel") or {}
    vendors = _get(payload, "vendor_intel") or {}
    news = _get(payload, "news_intel") or {}
    competitors = _get(payload, "competitor_intel") or {}
    contacts = _get(payload, "contacts") or {}
    scores = {str(_get(s, "key")): s for s in (_get(payload, "scores") or [])}
    conv = scores.get("conversion")
    trust = scores.get("trust")
    seo = scores.get("seo")

    has_offer = _n(offers) > 0 or bool(_get(conv, "inputs", "pricing_page"))
    has_proof = _n(ratings) > 0 or _n(review_items) > 0
    has_feed = bool(_get(feeds, "assessed") and (
        _get(feeds, "latest_published") or _n(_get(feeds, "items") or []) > 0))
    has_cta = bool(_get(onpage, "ctas") or _get(onpage, "forms")
                   or _get(conv, "inputs", "pricing_page"))
    has_card = bool(_get(cards, "assessed") and (
        _get(cards, "og_title") or _get(cards, "titles")))
    missing_seo = [s.get("slot") for s in (_get(seo_map, "slots") or [])
                   if isinstance(s, dict) and s.get("status") == "missing"]
    rival_n = _n(_get(competitors, "competitors") or []) if _get(competitors, "assessed") else 0
    news_n = _n(_get(news, "items") or [])
    ads_files = _n(_get(ads, "files") or [])
    email_vendor = [v.get("name") for v in (_get(vendors, "rows") or [])
                    if isinstance(v, dict) and "mail" in (v.get("kind") or "").lower()]
    public_files = _public_files(payload)
    security_contacts = _security_contacts(public_files)
    has_llms = _file_present(public_files, "/llms.txt", "/ai.txt")
    has_humans = _file_present(public_files, "/humans.txt")
    has_security = bool(security_contacts) or _file_present(
        public_files, "security.txt")

    needs = [
        _need(
            "identity", "Who you appear to be",
            OBS if (name or tagline) else UNA,
            "Positioning is the sentence a stranger would use after one look at your homepage.",
            (f"Public name {name}" + (f" — “{tagline[:160]}”" if tagline else "")
             + (f" on {domain}" if domain else "")),
            "Keep the homepage H1 and org name saying the same job in one sentence."
            if tagline else
            "Write one homepage sentence that names the buyer and the job you do.",
            "S"),
        _need(
            "offer", "What you sell",
            OBS if has_offer else UNA,
            "An offer is a named product or plan a buyer can evaluate. A slogan is not an offer.",
            (f"{_n(offers)} public offer/plan row(s) from JSON-LD or visible prices."
             if has_offer else
             "No Product/Offer JSON-LD and no pricing/plans page in the sample."),
            "Publish a pricing or plans page, or mark one product with schema."
            if not has_offer else
            "Name the primary plan on the homepage so a first visit can decide.",
            "M" if not has_offer else "S"),
        _need(
            "proof", "Why believe you",
            OBS if has_proof else UNA,
            "Proof is a review body or printed rating the site itself published. Star copy in a paragraph is not a rating.",
            (f"{_n(ratings)} AggregateRating node(s), {_n(review_items)} Review body(ies)."
             if has_proof else
             "No on-page Review or AggregateRating schema in the sample."),
            "Add 3–5 on-page review bodies or an AggregateRating you can stand behind."
            if not has_proof else
            "Put the strongest printed rating next to the primary CTA.",
            "M"),
        _need(
            "demand", "Whether anyone is looking",
            CALC if (news_n or rival_n or missing_seo) else UNA,
            "Public demand here means search-led news, named rivals, or missing site paths — not keyword volume.",
            (f"{news_n} news hit(s), {rival_n} official-site rival(s), "
             f"{len(missing_seo)} missing SEO slot(s)."
             if (news_n or rival_n or missing_seo) else
             "No news hits, rival list, or SEO-map gaps were stored. Volume is unavailable."),
            "Fill the missing paths first: " + ", ".join(missing_seo[:4]) + "."
            if missing_seo else
            "If you have a Serper key, re-run with competitor discovery to see who else is named.",
            "M"),
        _need(
            "channel", "Where you already show up",
            OBS if (_n(socials) or has_feed or ads_files or email_vendor
                    or has_llms) else UNA,
            "Owned = site + feed + email tool. Earned = linked socials and news. Paid = ads.txt rows, not spend. llms.txt is an AI crawl invitation, not traffic.",
            (f"{_n(socials)} linked social(s), feed "
             f"{'yes' if has_feed else 'no'}, ads.txt files {ads_files}, "
             f"email vendor {', '.join(email_vendor[:2]) or 'none'}"
             + (", llms/ai.txt present" if has_llms else "")
             + (", humans.txt present" if has_humans else "") + "."),
            "Advertise one RSS/Atom feed and link the two socials you actually post on."
            if not (has_feed or _n(socials) >= 2) else
            "Do not buy ads until the owned feed or email path can receive the click.",
            "S"),
        _need(
            "conversion", "Can a stranger act",
            OBS if has_cta else UNA,
            "A conversion path is a form, CTA, checkout fingerprint, or pricing page. A 'Learn more' heading is not a path.",
            ("CTA, form, or pricing page observed on sampled pages."
             if has_cta else
             "No form, priced CTA, or pricing page in the sample."),
            "Add one primary CTA that names the next step (demo, trial, buy, contact)."
            if not has_cta else
            "Make that CTA the same on homepage, pricing, and share card.",
            "S"),
        _need(
            "trust", "Why a buyer should start",
            OBS if (_get(legal, "pages") or _get(contacts, "emails")
                    or _get(trust, "inputs", "privacy_policy")
                    or has_security) else UNA,
            "Trust online starts with a privacy link, a public contact, HTTPS, and a security.txt Contact if they published one. It is not a brand-sentiment score.",
            (f"Privacy/terms pages {_n(_get(legal, 'pages') or [])}, "
             f"public emails {_n(_get(contacts, 'emails') or [])}"
             + (f", security.txt {', '.join(security_contacts[:2])}"
                if security_contacts else "") + "."),
            "Link a privacy policy from the footer of every sampled template."
            if not _get(trust, "inputs", "privacy_policy") else
            "Keep the public email or phone next to the CTA.",
            "S"),
        _need(
            "measurement", "Can you learn next week",
            OBS if (_get(vendors, "rows") or _get(seo, "inputs", "sitemap_xml")) else UNA,
            "A sitemap and an on-page analytics fingerprint are the start of learning. They are not traffic.",
            ("Analytics/marketing fingerprints or a sitemap were observed."
             if (_get(vendors, "rows") or _get(seo, "inputs", "sitemap_xml")) else
             "No sitemap and no marketing-pixel fingerprint in the sample."),
            "Publish sitemap.xml and keep one analytics tool, not five."
            if not _get(seo, "inputs", "sitemap_xml") else
            "Review which pixels fire on pricing — extra pixels are not more insight.",
            "S"),
    ]

    price_fill = ""
    for offer in offers[:3]:
        if isinstance(offer, dict):
            bit = offer.get("name") or "offer"
            if offer.get("price_inr") is not None:
                bit += f" (₹{int(offer['price_inr']):,})"
            price_fill = (price_fill + "; " if price_fill else "") + bit
    four_p = DeskFramework(
        name="4Ps (from the site, not a textbook)",
        status=OBS if (has_offer or tagline) else UNA,
        cells=[
            _cell("Product", OBS if has_offer or tagline else UNA,
                  price_fill or tagline or "No named offer in the sample",
                  "JSON-LD / visible plans only."),
            _cell("Price", OBS if any(isinstance(o, dict) and o.get("price_inr") is not None
                                      for o in offers) else UNA,
                  price_fill or "No visible public price",
                  "A missing price is a strategy, not zero rupees."),
            _cell("Place", OBS if (domain or _n(socials)) else UNA,
                  ", ".join([x for x in [domain] + [
                      str(s.get("platform") or "") for s in socials[:4]
                      if isinstance(s, dict)] if x]) or "Site only",
                  "Surfaces the site linked. Not distribution share."),
            _cell("Promotion", OBS if (has_feed or ads_files or has_card) else UNA,
                  ("Feed, share card, or ads.txt observed"
                   if (has_feed or ads_files or has_card) else
                   "No advertised feed, share card, or ads.txt"),
                  "ads.txt ≠ spend."),
        ])
    aida = DeskFramework(
        name="AIDA (attention → action)",
        status=MOD,
        cells=[
            _cell("Attention", OBS if has_card else UNA,
                  "Open Graph / share card printed" if has_card else "No share card fields",
                  "A card is not a ranking."),
            _cell("Interest", OBS if (_n(_get(payload, "schema_intel", "faqs") or [])
                                      or has_feed) else UNA,
                  "FAQ schema or a first-party feed" if (
                      _n(_get(payload, "schema_intel", "faqs") or []) or has_feed)
                  else "No FAQ schema and no feed",
                  ""),
            _cell("Desire", OBS if has_proof else UNA,
                  "On-page reviews or printed rating" if has_proof else "No printed proof",
                  "Not a sentiment model."),
            _cell("Action", OBS if has_cta else UNA,
                  "CTA / form / pricing path" if has_cta else "No conversion path in sample",
                  ""),
        ])
    oep = DeskFramework(
        name="Owned / earned / paid",
        status=CALC,
        cells=[
            _cell("Owned", OBS if (domain or has_feed or email_vendor) else UNA,
                  f"Site{', feed' if has_feed else ''}{', email tool' if email_vendor else ''}",
                  ""),
            _cell("Earned", OBS if (_n(socials) or news_n) else UNA,
                  f"{_n(socials)} linked social(s), {news_n} news hit(s)",
                  "News hits are search results, not circulation."),
            _cell("Paid", OBS if ads_files else UNA,
                  f"{ads_files} ads.txt file(s)" if ads_files else "No ads.txt in sample",
                  "DIRECT/RESELLER is a declaration, not a media plan."),
        ])

    weak = [n for n in needs if n.status == UNA]
    if not has_offer:
        job = f"Name one public offer for {name} so a first visit can decide."
    elif not has_proof:
        job = f"Attach proof to {name}'s offer before you buy attention."
    elif not has_cta:
        job = f"Give {name} one obvious next step on the homepage."
    elif missing_seo:
        job = f"Close the missing public paths on {name}: {', '.join(missing_seo[:3])}."
    else:
        job = f"Keep {name}'s owned surfaces current and re-measure after you change them."

    one = (
        f"{name} looks like a public web business"
        + (f" — {tagline[:120]}" if tagline else "")
        + f". Score {overall}/100 from six public dimensions. "
        + (f"{len(weak)} basic marketing need(s) still unavailable."
           if weak else "The public basics are present; do not invent demand on top.")
    )
    id_kinds = {str(_get(row, "kind") or "") for row in (
        _get(payload, "identity_intel", "ids") or [])}
    official = _get(payload, "official_ids") or {}
    if isinstance(official, dict):
        id_kinds.update(official.keys())
    for ident in _get(payload, "filings_intel", "identifiers") or []:
        id_kinds.add(str(_get(ident, "kind") or ""))
    return _with_narrative(MarketingDesk(
        kind="web", one_liner=one, job=job,
        posture=_posture_web(overall=overall, has_offer=has_offer,
                             has_proof=has_proof, has_feed=has_feed),
        needs=needs,
        frameworks=[four_p, aida, oep] + _web_extra_frameworks(
            payload=payload, has_offer=has_offer, has_proof=has_proof,
            has_cta=has_cta, has_feed=has_feed, has_card=has_card,
            socials=socials if isinstance(socials, list) else [],
            news_n=news_n, ads_files=ads_files, email_vendor=email_vendor,
            rival_n=rival_n, missing_seo=missing_seo, tagline=tagline,
            domain=domain),
        playbooks=_web_playbooks(
            name=name, has_offer=has_offer, has_proof=has_proof,
            has_feed=has_feed, has_cta=has_cta, ads_files=ads_files,
            llms=has_llms, security_contacts=security_contacts,
            missing_seo=missing_seo,
            has_cik="sec_cik" in id_kinds or "cik" in id_kinds,
            has_cin="cin" in id_kinds,
            has_lei="lei" in id_kinds),
        week_plan=_week_plan(needs, [
            "Download this report before the 24-hour timer.",
            "Re-run Deep Analyze after you change pricing, proof, or the feed.",
        ]),
        cannot_know=list(WEB_CANNOT),
        glossary=_glossary(),
    ))


# ------------------------------------------------------------------ creator
def build_creator_desk(*, name: str, handle: str, overview: Any = None,
                       audience: Any = None, signals: Any = None,
                       content: Any = None, media_buy: Any = None,
                       keyless: dict | None = None,
                       accounts: list | None = None) -> MarketingDesk:
    subject = name or handle or "this creator"
    kl = keyless or {}
    occ = (_get(overview, "credentials") or [])[:3]
    pillars = (_get(overview, "content_pillars") or [])[:4]
    press = _get(overview, "press") or []
    followers = int(_get(signals, "total_audience") or 0)
    primary = str(_get(signals, "primary_platform") or "")
    measured = int(_get(content, "measured_items") or 0)
    median = _get(content, "current_median")
    cadence = _get(content, "cadence_per_month")
    verdict = str(_get(media_buy, "verdict") or "")
    platforms = []
    for acc in accounts or []:
        plat = _get(acc, "platform")
        if plat and plat not in platforms:
            platforms.append(plat)
    login_walled = any(
        _get(acc, "needs_manual") or "login" in " ".join(_get(acc, "errors") or []).lower()
        for acc in (accounts or []))
    wiki = kl.get("wikipedia_title")
    pageviews = kl.get("pageviews") or {}
    orcid = kl.get("orcid")

    has_identity = bool(occ or _get(overview, "positioning") or wiki)
    has_delivery = measured >= 4 and median is not None
    has_cadence = cadence is not None and float(cadence) > 0
    has_offer = bool(_get(overview, "product_stack"))
    has_scale = followers > 0

    needs = [
        _need(
            "identity", "Who they appear to be",
            OBS if has_identity else UNA,
            "A creator's public job is the occupation or bio they published — not an audience persona we invented.",
            (_get(overview, "positioning") or ", ".join(occ) or wiki
             or "No bio, Wikidata occupation, or Wikipedia extract."),
            "Treat the published bio as the brief; do not 'fix' it with guessed demographics.",
            "S"),
        _need(
            "delivery", "Whether the audience actually watches",
            CALC if has_delivery else UNA,
            "Delivery is recent public views on measured uploads. Subscribers are not views.",
            (f"{measured} measured items, median {int(median):,} public views."
             if has_delivery else
             "Not enough dated public view counts. A login wall is not a zero."),
            "Price from a screen-recorded Insights walkthrough, not the headline follow count."
            if not has_delivery else
            "Ask for last-8-post Insights and compare to the public median in this pack.",
            "M"),
        _need(
            "system", "Whether they publish on a rhythm",
            CALC if has_cadence else UNA,
            "A content system is a measured cadence, not a promised calendar.",
            (f"{cadence} public items/month in the observed window."
             if has_cadence else
             "Cadence could not be calculated from dated public items."),
            "Do not brief a weekly series until dated posts exist to measure.",
            "S"),
        _need(
            "offer", "What they sell or attach to",
            OBS if has_offer else UNA,
            "A creator offer is a product, course, or link they published. Notable Wikidata works are not SKUs.",
            (", ".join(_get(overview, "product_stack") or [])
             if has_offer else
             "No product/course/link stack on collected profiles."),
            "If you need an affiliate or product path, ask them to publish one trackable URL.",
            "M"),
        _need(
            "scale", "Public follow totals",
            OBS if has_scale else UNA,
            "Summed public follows are reachability. They are not unique people and not Instagram Insights.",
            (f"{followers:,} summed public follows"
             + (f", heaviest on {primary}" if primary else "") + "."
             if has_scale else
             "No public follower total collected"
             + (" — a login wall is common on Instagram." if login_walled else ".")),
            "Do not invent a follower count. Use YouTube/Wikidata/other public surfaces that printed one.",
            "S"),
        _need(
            "channel", "Surfaces we could collect",
            OBS if platforms else UNA,
            "A channel mix is the platforms that returned a public profile. Guessing Bluesky from Instagram is forbidden.",
            (", ".join(platforms[:8]) if platforms else "Only the seed URL was collected."),
            "Add official URLs they already print (YouTube, site, podcast). Do not probe look-alike handles.",
            "S"),
        _need(
            "attention", "Public interest off-platform",
            OBS if pageviews.get("views") else UNA,
            "Wikipedia pageviews are Wikimedia's count for the article, not site traffic or followers.",
            (f"{int(pageviews['views']):,} Wikipedia pageviews in {pageviews.get('days') or 0} days."
             if pageviews.get("views") else
             "No Wikipedia pageviews stored. That is empty, not zero interest."),
            "Use pageviews as a notability hint only. Do not put them in a media kit as 'traffic'.",
            "S"),
        _need(
            "buy", "Media-buy posture",
            MOD if verdict else UNA,
            "Prioritize / pilot / hold / pass is a modelled scorecard on public evidence, not a platform fact.",
            (f"Media-buy verdict: {verdict}." if verdict else "No media-buy scorecard on this pack."),
            "If the verdict is hold or pass, do not override it with a screenshot of followers.",
            "S"),
    ]

    pillars_fill = ", ".join(pillars) or "No recurring title tokens"
    oep = DeskFramework(
        name="Owned / earned / paid",
        status=CALC,
        cells=[
            _cell("Owned", OBS if (platforms or has_offer) else UNA,
                  ", ".join(platforms[:6]) or "Seed only",
                  "Collected profiles, not a claimed network."),
            _cell("Earned", OBS if (wiki or press or pageviews.get("views")) else UNA,
                  ("Wikipedia / press / pageviews observed"
                   if (wiki or press or pageviews.get("views")) else
                   "No Wikipedia or press row"),
                  "ORCID works are publications, not products."),
            _cell("Paid", UNA, "Creator ad accounts are not public",
                  "Do not infer spend from #ad markers alone."),
        ])
    aida = DeskFramework(
        name="AIDA for a creator brief",
        status=MOD,
        cells=[
            _cell("Attention", OBS if has_scale or pageviews.get("views") else UNA,
                  f"{followers:,} public follows" if has_scale else "Follow totals unavailable",
                  "Not unique reach."),
            _cell("Interest", OBS if pillars else UNA, pillars_fill,
                  "Title tokens, not search demand."),
            _cell("Desire", CALC if has_delivery else UNA,
                  f"Median {int(median):,} views" if has_delivery else "Delivery unmeasured",
                  ""),
            _cell("Action", OBS if has_offer else UNA,
                  "Published offer path" if has_offer else "No trackable offer URL",
                  ""),
        ])

    if login_walled and not has_scale:
        job = f"Collect a non-walled surface for {subject} (YouTube, site, podcast) before you brief a buy."
    elif not has_delivery:
        job = f"Get last-8-post delivery evidence for {subject}; do not price from follows."
    elif verdict in {"hold", "pass"}:
        job = f"Do not force a buy on {subject} — the public scorecard is {verdict}."
    else:
        job = f"Pilot {subject} on the measured platform with one trackable URL."

    one = (
        f"{subject} is a public creator brief"
        + (f" ({', '.join(occ[:2])})" if occ else "")
        + ". "
        + ("Login-walled socials left some counts unavailable. "
           if login_walled else "")
        + ("Wikipedia/ORCID ran on identifiers Wikidata already printed."
           if (wiki or orcid) else "No Wikidata identity was attached.")
    )
    return _with_narrative(MarketingDesk(
        kind="creator", one_liner=one, job=job,
        posture=_posture_creator(followers=followers, measured=measured, verdict=verdict),
        needs=needs,
        frameworks=[oep, aida] + _creator_extra_frameworks(
            has_scale=has_scale, has_delivery=has_delivery,
            has_cadence=has_cadence, has_offer=has_offer, pillars=pillars,
            followers=followers, pageviews=pageviews),
        playbooks=_creator_playbooks(
            subject=subject, has_delivery=has_delivery, has_offer=has_offer,
            login_walled=login_walled, verdict=verdict),
        week_plan=_week_plan(needs, [
            "Download the pack before it is deleted.",
            "If Instagram is walled, paste a YouTube or site URL and re-run.",
        ]),
        cannot_know=list(CREATOR_CANNOT),
        glossary=_glossary(),
    ))
