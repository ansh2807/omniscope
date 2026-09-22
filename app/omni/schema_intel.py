"""JSON-LD inventory and printed structured entities (spec §11, §15).

Types, FAQ answers, job postings, events and NAP come from schema the pages
already serve. JobPosting count is not hiring volume. Event dates are schema
dates. hreflang is copied from link[rel=alternate] on the same host.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, Field
from selectolax.parser import HTMLParser

from app.engine.collectors.web import _jsonld

FEATURED = (
    "Organization", "LocalBusiness", "OnlineBusiness", "Corporation",
    "Person", "JobPosting", "Event", "FAQPage", "Question",
    "BreadcrumbList", "Article", "BlogPosting", "NewsArticle", "WebSite",
    "VideoObject", "HowTo", "SoftwareApplication", "MobileApplication",
    "Course", "EducationalOccupationalProgram",
    "ContactPoint", "ItemList",
    "OfferCatalog", "AggregateOffer",
    "WebPage", "AboutPage", "ContactPage", "SpeakableSpecification",
    "Review", "AggregateRating", "OpeningHoursSpecification",
)
PAGE_TYPES = {
    "WebPage", "AboutPage", "ContactPage", "CollectionPage",
    "ItemPage", "FAQPage", "ProfilePage", "SearchResultsPage",
}
ORG_TYPES = {"Organization", "LocalBusiness", "OnlineBusiness", "Corporation"}


class SchemaItem(BaseModel):
    type: str
    name: str = ""
    extra: str = ""
    url: str = ""


class FaqItem(BaseModel):
    question: str
    answer: str = ""
    url: str = ""


class JobItem(BaseModel):
    title: str
    location: str = ""
    date_posted: str = ""
    valid_through: str = ""
    employment: str = ""
    salary: str = ""
    url: str = ""


class EventItem(BaseModel):
    name: str
    start: str = ""
    end: str = ""
    location: str = ""
    offer: str = ""
    url: str = ""


class NapCard(BaseModel):
    name: str = ""
    telephone: str = ""
    email: str = ""
    address: str = ""
    founding_date: str = ""
    hours: str = ""
    geo: str = ""
    url: str = ""


class ArticleItem(BaseModel):
    title: str
    published: str = ""
    modified: str = ""
    url: str = ""


class CourseItem(BaseModel):
    name: str
    kind: str = "course"
    provider: str = ""
    code: str = ""
    start: str = ""
    credential: str = ""
    url: str = ""


class BreadcrumbTrail(BaseModel):
    path: str
    url: str = ""


class PersonCard(BaseModel):
    name: str
    job_title: str = ""
    url: str = ""


class VideoItem(BaseModel):
    title: str
    uploaded: str = ""
    url: str = ""


class HowToItem(BaseModel):
    name: str
    steps: int = 0
    tools: list[str] = Field(default_factory=list)
    supplies: list[str] = Field(default_factory=list)
    total_time: str = ""
    url: str = ""


class SearchAction(BaseModel):
    target: str
    url: str = ""


class AppItem(BaseModel):
    name: str
    kind: str = "software"
    os: str = ""
    url: str = ""


class ServingCard(BaseModel):
    area: str = ""
    payments: str = ""
    price_range: str = ""
    languages: str = ""
    employees: str = ""
    also_known: list[str] = Field(default_factory=list)
    url: str = ""


class ContactPointItem(BaseModel):
    contact_type: str = ""
    telephone: str = ""
    email: str = ""
    area: str = ""
    languages: str = ""
    url: str = ""


class ItemListCard(BaseModel):
    name: str = ""
    entries: list[str] = Field(default_factory=list)
    number_of_items: str = ""
    url: str = ""


class AggregateOfferRow(BaseModel):
    name: str = ""
    low: str = ""
    high: str = ""
    currency: str = ""
    offer_count: str = ""
    url: str = ""


class OfferCatalogRow(BaseModel):
    name: str = ""
    items: list[str] = Field(default_factory=list)
    url: str = ""


class SpeakableRow(BaseModel):
    name: str = ""
    selectors: list[str] = Field(default_factory=list)
    url: str = ""


class WebPageCard(BaseModel):
    name: str = ""
    kind: str = "WebPage"
    last_reviewed: str = ""
    reviewed_by: str = ""
    specialty: str = ""
    significant_links: list[str] = Field(default_factory=list)
    url: str = ""


class HoursRow(BaseModel):
    name: str = ""
    day: str = ""
    opens: str = ""
    closes: str = ""
    valid_from: str = ""
    valid_through: str = ""
    url: str = ""


class Hreflang(BaseModel):
    lang: str
    url: str


class SchemaIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    types: dict[str, int] = Field(default_factory=dict)
    items: list[SchemaItem] = Field(default_factory=list)
    faqs: list[FaqItem] = Field(default_factory=list)
    jobs: list[JobItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    nap: NapCard | None = None
    hreflang: list[Hreflang] = Field(default_factory=list)
    articles: list[ArticleItem] = Field(default_factory=list)
    breadcrumbs: list[BreadcrumbTrail] = Field(default_factory=list)
    people: list[PersonCard] = Field(default_factory=list)
    videos: list[VideoItem] = Field(default_factory=list)
    howtos: list[HowToItem] = Field(default_factory=list)
    search_actions: list[SearchAction] = Field(default_factory=list)
    serving: ServingCard | None = None
    apps: list[AppItem] = Field(default_factory=list)
    courses: list[CourseItem] = Field(default_factory=list)
    contact_points: list[ContactPointItem] = Field(default_factory=list)
    item_lists: list[ItemListCard] = Field(default_factory=list)
    aggregate_offers: list[AggregateOfferRow] = Field(default_factory=list)
    offer_catalogs: list[OfferCatalogRow] = Field(default_factory=list)
    speakable: list[SpeakableRow] = Field(default_factory=list)
    web_pages: list[WebPageCard] = Field(default_factory=list)
    hours: list[HoursRow] = Field(default_factory=list)
    methodology: str = (
        "JSON-LD on sampled pages plus same-host hreflang links. FAQ/job/event/"
        "article/breadcrumb/person/video/HowTo/serving/app/course/contactPoint/"
        "ItemList/AggregateOffer/OfferCatalog/speakable/WebPage/hours rows copy "
        "printed fields only. dateModified and lastReviewed are printed fields, "
        "not verified edits. Speakable selectors are not a featured-snippet "
        "rank. significantLink URLs are listed, not fetched. Course count is "
        "not enrollment. A ContactPoint is not a verified helpdesk. ItemList "
        "length is not inventory. An AggregateOffer range is not a market "
        "price. OfferCatalog names are not a complete catalog. Opening hours "
        "are printed slots, not an open-now verdict. HowTo tools and supplies "
        "are printed names, not a shopping list. totalTime is a printed "
        "duration, not a completion forecast. operatingSystem is a "
        "schema field, not an app-store scrape. numberOfEmployees is a printed "
        "string, not a headcount. alternateName is never a merge key.")


def _type_names(entity: dict) -> list[str]:
    raw = entity.get("@type")
    if isinstance(raw, str):
        return [raw.split("/")[-1]]
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            names.append(item.split("/")[-1])
    return names


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _textish(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "name", "addressLocality", "streetAddress",
                    "addressCountry", "addressRegion"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        addr = value.get("address")
        if addr is not None and addr is not value:
            return _textish(addr)
    return ""


def _field(entity: dict, *keys: str) -> str:
    for key in keys:
        text = _textish(entity.get(key))
        if text:
            return text[:160]
    return ""


def _address_line(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()[:200]
    if not isinstance(value, dict):
        return ""
    parts = [value.get(k) for k in (
        "streetAddress", "addressLocality", "addressRegion",
        "postalCode", "addressCountry")]
    return ", ".join(str(p).strip() for p in parts if isinstance(p, str) and p.strip())[:200]


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def extract_faqs(entities: list[dict], page_url: str) -> list[FaqItem]:
    """Pure. FAQPage.mainEntity and standalone Question nodes."""
    out: list[FaqItem] = []
    seen: set[str] = set()

    def add(question: str, answer: str) -> None:
        question = question.strip()
        if not question or question.lower() in seen:
            return
        seen.add(question.lower())
        out.append(FaqItem(question=question[:240], answer=answer.strip()[:400],
                           url=page_url))

    for entity in entities:
        types = set(_type_names(entity))
        questions = []
        if "FAQPage" in types:
            questions = [q for q in _as_list(entity.get("mainEntity")) if isinstance(q, dict)]
        elif "Question" in types:
            questions = [entity]
        for node in questions:
            question = _textish(node.get("name") or node.get("text"))
            accepted = node.get("acceptedAnswer")
            answer = ""
            if isinstance(accepted, dict):
                answer = _textish(accepted.get("text") or accepted.get("name"))
            elif isinstance(accepted, str):
                answer = accepted.strip()
            add(question, answer)
    return out[:20]


def extract_jobs(entities: list[dict], page_url: str) -> list[JobItem]:
    out: list[JobItem] = []
    seen: set[str] = set()
    for entity in entities:
        if "JobPosting" not in _type_names(entity):
            continue
        title = _field(entity, "title", "name")
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        loc = entity.get("jobLocation")
        location = _address_line(loc.get("address") if isinstance(loc, dict) else None)
        if not location:
            location = _textish(loc)
        out.append(JobItem(
            title=title[:160],
            location=location[:160],
            date_posted=_field(entity, "datePosted")[:10],
            valid_through=_field(entity, "validThrough")[:10],
            employment=_field(entity, "employmentType")[:40],
            salary=_salary(entity),
            url=_field(entity, "url") or page_url,
        ))
    return out[:20]


def extract_events(entities: list[dict], page_url: str) -> list[EventItem]:
    out: list[EventItem] = []
    seen: set[str] = set()
    for entity in entities:
        if "Event" not in _type_names(entity):
            continue
        name = _field(entity, "name")
        start = _field(entity, "startDate")
        key = f"{name}|{start}"
        if not name or key.lower() in seen:
            continue
        seen.add(key.lower())
        loc = entity.get("location")
        location = _address_line(loc.get("address") if isinstance(loc, dict) else None)
        if not location:
            location = _textish(loc)
        out.append(EventItem(
            name=name[:160],
            start=start[:16],
            end=_field(entity, "endDate")[:16],
            location=location[:160],
            offer=_event_offer(entity),
            url=_field(entity, "url") or page_url,
        ))
    return out[:20]


def _salary(entity: dict) -> str:
    """Printed baseSalary fields only. Not a compensation survey."""
    raw = entity.get("baseSalary")
    if raw is None:
        return ""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)[:40]
    if isinstance(raw, str):
        return raw.strip()[:80]
    if not isinstance(raw, dict):
        return ""
    currency = _textish(raw.get("currency") or raw.get("priceCurrency"))
    unit = _textish(raw.get("unitText"))
    value = raw.get("value")
    if isinstance(value, dict):
        low = value.get("minValue")
        high = value.get("maxValue")
        single = value.get("value")
        unit = unit or _textish(value.get("unitText"))
        parts: list[str] = []
        if low is not None and str(low).strip() != "":
            parts.append(str(low).strip())
        if high is not None and str(high).strip() != "":
            parts.append(str(high).strip())
        if not parts and single is not None:
            parts.append(str(single).strip())
        span = "-".join(parts)
        return " ".join(x for x in (span, currency, unit) if x)[:80]
    if value is not None and str(value).strip() != "":
        return " ".join(x for x in (str(value).strip(), currency, unit) if x)[:80]
    return " ".join(x for x in (currency, unit) if x)[:80]


def _event_offer(entity: dict) -> str:
    """Printed Event.offers price + currency. Not a ticket-demand model."""
    offers = entity.get("offers")
    for offer in _as_list(offers):
        if not isinstance(offer, dict):
            continue
        price = offer.get("price")
        if price is None:
            price = offer.get("lowPrice")
        if price is None or str(price).strip() == "":
            continue
        currency = _textish(offer.get("priceCurrency"))
        return " ".join(x for x in (str(price).strip(), currency) if x)[:60]
    return ""


def _hours(entity: dict) -> str:
    raw = entity.get("openingHours") or entity.get("openingHoursSpecification")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:160]
    bits: list[str] = []
    for spec in _as_list(raw):
        if isinstance(spec, str) and spec.strip():
            bits.append(spec.strip())
        elif isinstance(spec, dict):
            day = _textish(spec.get("dayOfWeek"))
            opens = _textish(spec.get("opens"))
            closes = _textish(spec.get("closes"))
            if day or opens:
                bits.append(" ".join(x for x in (day, opens, closes) if x))
        if len(bits) >= 4:
            break
    return "; ".join(bits)[:200]


def _geo(entity: dict) -> str:
    geo = entity.get("geo")
    if isinstance(geo, dict):
        lat, lng = geo.get("latitude"), geo.get("longitude")
        if lat is not None and lng is not None:
            return f"{lat},{lng}"
    lat, lng = entity.get("latitude"), entity.get("longitude")
    if lat is not None and lng is not None:
        return f"{lat},{lng}"
    return ""


def extract_nap(entities: list[dict], page_url: str) -> NapCard | None:
    """First Organization/LocalBusiness that printed a contact surface."""
    for entity in entities:
        if not (set(_type_names(entity)) & ORG_TYPES):
            continue
        card = NapCard(
            name=_field(entity, "name"),
            telephone=_field(entity, "telephone"),
            email=_field(entity, "email"),
            address=_address_line(entity.get("address")) or _field(entity, "address"),
            founding_date=_field(entity, "foundingDate")[:10],
            hours=_hours(entity),
            geo=_geo(entity),
            url=_field(entity, "url") or page_url,
        )
        if (card.telephone or card.address or card.email or card.founding_date
                or card.hours or card.geo):
            return card
    return None


def extract_contact_points(entities: list[dict], page_url: str) -> list[ContactPointItem]:
    """Organization.contactPoint and standalone ContactPoint. Not a helpdesk."""
    out: list[ContactPointItem] = []
    seen: set[tuple[str, str, str]] = set()

    def add(node: dict) -> None:
        if not isinstance(node, dict):
            return
        types = set(_type_names(node))
        if types and "ContactPoint" not in types and not (
                node.get("telephone") or node.get("email") or node.get("contactType")):
            return
        contact_type = _field(node, "contactType")[:80]
        telephone = _field(node, "telephone")[:80]
        email = _field(node, "email")[:80]
        if not (contact_type or telephone or email):
            return
        key = (contact_type.lower(), telephone, email.lower())
        if key in seen:
            return
        seen.add(key)
        out.append(ContactPointItem(
            contact_type=contact_type,
            telephone=telephone,
            email=email,
            area=_join_field(node, "areaServed")[:80],
            languages=_join_field(node, "availableLanguage")[:80],
            url=_field(node, "url") or page_url,
        ))

    for entity in entities:
        if "ContactPoint" in _type_names(entity):
            add(entity)
        for node in _as_list(entity.get("contactPoint")):
            if isinstance(node, dict):
                add(node)
    return out[:12]


def _list_entry_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    name = _textish(value.get("name") or value.get("headline"))
    if name:
        return name
    item = value.get("item")
    if isinstance(item, dict):
        return _textish(item.get("name") or item.get("headline") or item)
    return _textish(item)


def extract_item_lists(entities: list[dict], page_url: str) -> list[ItemListCard]:
    """ItemList names only. BreadcrumbList is out of scope here. Not inventory."""
    out: list[ItemListCard] = []
    seen: set[str] = set()
    for entity in entities:
        types = set(_type_names(entity))
        if "ItemList" not in types or "BreadcrumbList" in types:
            continue
        name = _field(entity, "name")
        entries: list[str] = []
        for raw in _as_list(entity.get("itemListElement")):
            entry = _list_entry_name(raw)[:80]
            if entry and entry.lower() not in {e.lower() for e in entries}:
                entries.append(entry)
            if len(entries) >= 12:
                break
        raw_n = entity.get("numberOfItems")
        if isinstance(raw_n, bool):
            printed_n = ""
        elif isinstance(raw_n, (int, float)):
            printed_n = str(int(raw_n))[:20]
        else:
            printed_n = _field(entity, "numberOfItems")[:20]
        if not name and not entries and not printed_n:
            continue
        key = (name or "itemlist").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ItemListCard(
            name=(name or "ItemList")[:160],
            entries=entries[:12],
            number_of_items=printed_n,
            url=_field(entity, "url") or page_url,
        ))
    return out[:8]


def _printed_amount(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)[:40]
    if isinstance(value, float):
        return (str(int(value)) if value.is_integer() else str(value))[:40]
    return _textish(value)[:40]


def _offer_item_name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    name = _textish(value.get("name") or value.get("headline"))
    if name:
        return name
    offered = value.get("itemOffered") or value.get("item")
    if isinstance(offered, dict):
        return _textish(offered.get("name") or offered.get("headline"))
    return _textish(offered)


def extract_aggregate_offers(entities: list[dict], page_url: str) -> list[AggregateOfferRow]:
    """AggregateOffer low/high/count. Not a market price or inventory."""
    out: list[AggregateOfferRow] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(node: dict, parent_name: str = "") -> None:
        if not isinstance(node, dict):
            return
        if "AggregateOffer" not in _type_names(node):
            return
        low = _printed_amount(node.get("lowPrice"))
        high = _printed_amount(node.get("highPrice"))
        count = _printed_amount(node.get("offerCount"))
        currency = _field(node, "priceCurrency")[:16]
        name = _field(node, "name") or parent_name
        if not (low or high or count):
            return
        key = (name.lower(), low, high, count)
        if key in seen:
            return
        seen.add(key)
        out.append(AggregateOfferRow(
            name=name[:160],
            low=low,
            high=high,
            currency=currency,
            offer_count=count,
            url=_field(node, "url") or page_url,
        ))

    for entity in entities:
        if "AggregateOffer" in _type_names(entity):
            add(entity)
        parent = _field(entity, "name")
        for node in _as_list(entity.get("offers")):
            if isinstance(node, dict):
                add(node, parent)
    return out[:12]


def extract_offer_catalogs(entities: list[dict], page_url: str) -> list[OfferCatalogRow]:
    """OfferCatalog item names. Not a complete catalog or SKU ladder."""
    out: list[OfferCatalogRow] = []
    seen: set[str] = set()

    def add(node: dict) -> None:
        if not isinstance(node, dict):
            return
        types = set(_type_names(node))
        if types and "OfferCatalog" not in types:
            return
        name = _field(node, "name")
        items: list[str] = []
        for raw in _as_list(node.get("itemListElement")) + _as_list(node.get("itemOffered")):
            entry = _offer_item_name(raw)[:80]
            if entry and entry.lower() not in {i.lower() for i in items}:
                items.append(entry)
            if len(items) >= 12:
                break
        if not name and not items:
            return
        key = (name or "offercatalog").lower()
        if key in seen:
            return
        seen.add(key)
        out.append(OfferCatalogRow(
            name=(name or "OfferCatalog")[:160],
            items=items[:12],
            url=_field(node, "url") or page_url,
        ))

    for entity in entities:
        if "OfferCatalog" in _type_names(entity):
            add(entity)
        for node in _as_list(entity.get("hasOfferCatalog")):
            if isinstance(node, dict):
                add(node)
    return out[:8]


def _speakable_selectors(node: dict) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in ("cssSelector", "xpath"):
        for item in _as_list(node.get(key)):
            text = _textish(item)
            if not text:
                continue
            token = f"{key}:{text[:80]}"
            if token.lower() in seen:
                continue
            seen.add(token.lower())
            out.append(token)
    return out[:8]


def extract_speakable(entities: list[dict], page_url: str) -> list[SpeakableRow]:
    """SpeakableSpecification selectors. Not a featured-snippet or voice rank."""
    out: list[SpeakableRow] = []
    seen: set[tuple[str, str]] = set()

    def add(node: dict, parent_name: str = "") -> None:
        if not isinstance(node, dict):
            return
        types = set(_type_names(node))
        if types and "SpeakableSpecification" not in types:
            return
        selectors = _speakable_selectors(node)
        name = _field(node, "name") or parent_name
        if not selectors and not name:
            return
        key = (name.lower(), "|".join(selectors).lower())
        if key in seen:
            return
        seen.add(key)
        out.append(SpeakableRow(
            name=name[:160],
            selectors=selectors,
            url=_field(node, "url") or page_url,
        ))

    for entity in entities:
        parent = _field(entity, "name", "headline")
        if "SpeakableSpecification" in _type_names(entity):
            add(entity, parent)
        for node in _as_list(entity.get("speakable")):
            if isinstance(node, dict):
                add(node, parent)
            elif isinstance(node, str) and node.strip():
                token = f"cssSelector:{node.strip()[:80]}"
                key = (parent.lower(), token.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(SpeakableRow(
                    name=parent[:160], selectors=[token], url=page_url))
    return out[:8]


def _reviewed_by(entity: dict) -> str:
    raw = entity.get("reviewedBy")
    if isinstance(raw, dict):
        return _textish(raw.get("name") or raw)[:80]
    return _textish(raw)[:80]


def extract_web_pages(entities: list[dict], page_url: str) -> list[WebPageCard]:
    """WebPage lastReviewed / significantLink. Dates are printed, links not fetched."""
    out: list[WebPageCard] = []
    seen: set[str] = set()
    for entity in entities:
        types = set(_type_names(entity))
        if not (types & PAGE_TYPES):
            continue
        kind = next((name for name in (
            "AboutPage", "ContactPage", "CollectionPage", "ItemPage",
            "FAQPage", "ProfilePage", "SearchResultsPage", "WebPage")
            if name in types), "WebPage")
        last_reviewed = _field(entity, "lastReviewed")[:10]
        reviewed_by = _reviewed_by(entity)
        specialty = _field(entity, "specialty")[:80]
        links: list[str] = []
        for raw in _as_list(entity.get("significantLink")):
            href = _textish(raw) if not isinstance(raw, dict) else _textish(
                raw.get("url") or raw.get("@id") or raw)
            if not href:
                continue
            absolute = urljoin(page_url, href).split("#")[0]
            if not absolute.startswith("http"):
                continue
            if absolute not in links:
                links.append(absolute[:240])
            if len(links) >= 8:
                break
        if not (last_reviewed or reviewed_by or specialty or links):
            continue
        name = _field(entity, "name", "headline") or kind
        key = f"{kind}:{name.lower()}:{last_reviewed}"
        if key in seen:
            continue
        seen.add(key)
        out.append(WebPageCard(
            name=name[:160],
            kind=kind,
            last_reviewed=last_reviewed,
            reviewed_by=reviewed_by,
            specialty=specialty,
            significant_links=links[:8],
            url=_field(entity, "url") or page_url,
        ))
    return out[:8]


def _day_name(value: Any) -> str:
    text = _textish(value)
    if text.startswith("http") and "schema.org" in text.lower():
        text = text.rstrip("/").split("/")[-1]
    return text[:40]


def extract_hours(entities: list[dict], page_url: str) -> list[HoursRow]:
    """OpeningHoursSpecification day/opens/closes. Not an open-now verdict."""
    out: list[HoursRow] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(node: dict, parent_name: str) -> None:
        if not isinstance(node, dict):
            return
        opens = _textish(node.get("opens"))[:16]
        closes = _textish(node.get("closes"))[:16]
        valid_from = _field(node, "validFrom")[:10]
        valid_through = _field(node, "validThrough")[:10]
        days = [_day_name(item) for item in _as_list(node.get("dayOfWeek"))]
        days = [d for d in days if d] or ([""] if (opens or closes) else [])
        name = _field(node, "name") or parent_name
        for day in days:
            if not (day or opens or closes):
                continue
            key = (name.lower(), day.lower(), opens, closes)
            if key in seen:
                continue
            seen.add(key)
            out.append(HoursRow(
                name=name[:160],
                day=day,
                opens=opens,
                closes=closes,
                valid_from=valid_from,
                valid_through=valid_through,
                url=_field(node, "url") or page_url,
            ))

    for entity in entities:
        parent = _field(entity, "name")
        types = set(_type_names(entity))
        if "OpeningHoursSpecification" in types:
            add(entity, parent)
        if types & ORG_TYPES or "Place" in types:
            for node in _as_list(entity.get("openingHoursSpecification")):
                if isinstance(node, dict):
                    add(node, parent)
    return out[:14]


def _join_field(entity: dict, *keys: str) -> str:
    bits: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for item in _as_list(entity.get(key)):
            text = _textish(item)
            if not text:
                continue
            if text.startswith("http") and "schema.org" in text:
                text = text.split("/")[-1]
            low = text.lower()
            if low in seen:
                continue
            seen.add(low)
            bits.append(text[:80])
        if bits:
            break
    return ", ".join(bits)[:200]


def _employees(entity: dict) -> str:
    raw = entity.get("numberOfEmployees")
    if isinstance(raw, (int, float)):
        return str(int(raw))[:40]
    if isinstance(raw, dict):
        val = raw.get("value") or raw.get("minValue")
        if val is not None:
            return str(val)[:40]
    return _textish(raw)[:40]


def extract_serving(entities: list[dict], page_url: str) -> ServingCard | None:
    """Organization serving/payment/language prints. Not a market map."""
    for entity in entities:
        if not (set(_type_names(entity)) & ORG_TYPES):
            continue
        aliases: list[str] = []
        seen: set[str] = set()
        for item in _as_list(entity.get("alternateName")):
            name = _textish(item)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                aliases.append(name[:80])
        card = ServingCard(
            area=_join_field(entity, "areaServed", "serviceArea"),
            payments=_join_field(entity, "paymentAccepted", "currenciesAccepted"),
            price_range=_field(entity, "priceRange")[:40],
            languages=_join_field(entity, "availableLanguage", "knowsLanguage"),
            employees=_employees(entity),
            also_known=aliases[:8],
            url=_field(entity, "url") or page_url,
        )
        if (card.area or card.payments or card.price_range or card.languages
                or card.employees or card.also_known):
            return card
    return None


def extract_articles(entities: list[dict], page_url: str) -> list[ArticleItem]:
    out: list[ArticleItem] = []
    seen: set[str] = set()
    for entity in entities:
        types = set(_type_names(entity))
        if not (types & {"Article", "BlogPosting", "NewsArticle"}):
            continue
        title = _field(entity, "headline", "name")
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append(ArticleItem(
            title=title[:200],
            published=_field(entity, "datePublished")[:10],
            modified=_field(entity, "dateModified")[:10],
            url=_field(entity, "url") or page_url,
        ))
    return out[:15]


def _provider(entity: dict) -> str:
    raw = entity.get("provider") or entity.get("organizer")
    if isinstance(raw, dict):
        return _textish(raw.get("name") or raw)[:160]
    return _textish(raw)[:160]


def _course_start(entity: dict) -> str:
    start = _field(entity, "startDate")[:10]
    if start:
        return start
    for inst in _as_list(entity.get("hasCourseInstance")):
        if isinstance(inst, dict):
            day = _field(inst, "startDate")[:10]
            if day:
                return day
    return ""


def extract_courses(entities: list[dict], page_url: str) -> list[CourseItem]:
    """Course / EducationalOccupationalProgram prints. Not enrollment volume."""
    out: list[CourseItem] = []
    seen: set[str] = set()
    for entity in entities:
        names = set(_type_names(entity))
        if "EducationalOccupationalProgram" in names:
            kind = "program"
        elif "Course" in names:
            kind = "course"
        else:
            continue
        name = _field(entity, "name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(CourseItem(
            name=name[:200],
            kind=kind,
            provider=_provider(entity),
            code=_field(entity, "courseCode")[:40],
            start=_course_start(entity),
            credential=_field(entity, "educationalCredentialAwarded")[:80],
            url=_field(entity, "url") or page_url,
        ))
    return out[:15]


def extract_breadcrumbs(entities: list[dict], page_url: str) -> list[BreadcrumbTrail]:
    out: list[BreadcrumbTrail] = []
    for entity in entities:
        if "BreadcrumbList" not in _type_names(entity):
            continue
        names: list[str] = []
        crumbs = _as_list(entity.get("itemListElement"))
        crumbs = sorted(
            (c for c in crumbs if isinstance(c, dict)),
            key=lambda c: int(c.get("position") or 0) if str(c.get("position") or "").isdigit() else 0)
        for crumb in crumbs:
            item = crumb.get("item")
            name = _textish(crumb.get("name")) or _textish(item)
            if name:
                names.append(name[:80])
        if names:
            out.append(BreadcrumbTrail(path=" › ".join(names), url=page_url))
    return out[:8]


def extract_people(entities: list[dict], page_url: str) -> list[PersonCard]:
    out: list[PersonCard] = []
    seen: set[str] = set()
    for entity in entities:
        if "Person" not in _type_names(entity):
            continue
        name = _field(entity, "name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(PersonCard(
            name=name[:160],
            job_title=_field(entity, "jobTitle")[:80],
            url=_field(entity, "url") or page_url,
        ))
    return out[:20]


def extract_videos(entities: list[dict], page_url: str) -> list[VideoItem]:
    out: list[VideoItem] = []
    seen: set[str] = set()
    for entity in entities:
        if "VideoObject" not in _type_names(entity):
            continue
        title = _field(entity, "name", "headline")
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append(VideoItem(
            title=title[:200],
            uploaded=_field(entity, "uploadDate", "datePublished")[:10],
            url=_field(entity, "embedUrl", "contentUrl", "url") or page_url,
        ))
    return out[:15]


def _step_count(entity: dict) -> int:
    steps = entity.get("step") or entity.get("howToStep") or entity.get("itemListElement")
    n = 0
    for item in _as_list(steps):
        if isinstance(item, dict) or (isinstance(item, str) and item.strip()):
            n += 1
    return n


def _named_list(entity: dict, *keys: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for key in keys:
        for item in _as_list(entity.get(key)):
            if isinstance(item, dict):
                text = _textish(item.get("name") or item)
            else:
                text = _textish(item)
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            out.append(text[:80])
            if len(out) >= 8:
                return out
    return out


def extract_howtos(entities: list[dict], page_url: str) -> list[HowToItem]:
    """HowTo steps plus printed tools/supplies/time. Not a shopping list."""
    out: list[HowToItem] = []
    seen: set[str] = set()
    for entity in entities:
        if "HowTo" not in _type_names(entity):
            continue
        name = _field(entity, "name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(HowToItem(
            name=name[:200],
            steps=_step_count(entity),
            tools=_named_list(entity, "tool", "tools"),
            supplies=_named_list(entity, "supply", "supplies"),
            total_time=_field(entity, "totalTime", "performTime", "prepTime")[:40],
            url=_field(entity, "url") or page_url,
        ))
    return out[:10]


def extract_apps(entities: list[dict], page_url: str) -> list[AppItem]:
    """SoftwareApplication / MobileApplication name + OS. Not an app-store scrape."""
    out: list[AppItem] = []
    seen: set[str] = set()
    for entity in entities:
        names = set(_type_names(entity))
        if "MobileApplication" in names:
            kind = "mobile"
        elif "SoftwareApplication" in names:
            kind = "software"
        else:
            continue
        name = _field(entity, "name")
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(AppItem(
            name=name[:200],
            kind=kind,
            os=_field(entity, "operatingSystem")[:80],
            url=_field(entity, "url") or page_url,
        ))
    return out[:12]


def extract_search_actions(entities: list[dict], page_url: str) -> list[SearchAction]:
    out: list[SearchAction] = []
    seen: set[str] = set()

    def add(action: dict) -> None:
        if "SearchAction" not in _type_names(action):
            return
        target = action.get("target")
        if isinstance(target, dict):
            template = _textish(target.get("urlTemplate")) or _textish(target)
        else:
            template = _textish(target)
        if not template or template.lower() in seen:
            return
        seen.add(template.lower())
        out.append(SearchAction(target=template[:240], url=page_url))

    for entity in entities:
        if "SearchAction" in _type_names(entity):
            add(entity)
        for action in _as_list(entity.get("potentialAction")):
            if isinstance(action, dict):
                add(action)
    return out[:8]


def discover_hreflang(page_url: str, html: str) -> list[Hreflang]:
    """Same-host alternate language URLs the page advertised. Pure."""
    host = _host(page_url)
    if not host or not html:
        return []
    tree = HTMLParser(html)
    out: list[Hreflang] = []
    seen: set[tuple[str, str]] = set()
    for node in tree.css("link[hreflang]"):
        rel = (node.attributes.get("rel") or "").lower()
        if rel and "alternate" not in rel:
            continue
        lang = (node.attributes.get("hreflang") or "").strip().lower()
        href = (node.attributes.get("href") or "").strip()
        if not lang or not href or lang == "x-default":
            continue
        absolute = urljoin(page_url, href).split("#")[0]
        if _host(absolute) != host:
            continue
        key = (lang, absolute)
        if key in seen:
            continue
        seen.add(key)
        out.append(Hreflang(lang=lang[:16], url=absolute))
    return out[:20]


def analyse_schema(raw_html: list[tuple[str, str]]) -> SchemaIntel:
    """Pure over already-fetched HTML."""
    counts: dict[str, int] = {}
    items: list[SchemaItem] = []
    faqs: list[FaqItem] = []
    jobs: list[JobItem] = []
    events: list[EventItem] = []
    articles: list[ArticleItem] = []
    breadcrumbs: list[BreadcrumbTrail] = []
    people: list[PersonCard] = []
    videos: list[VideoItem] = []
    howtos: list[HowToItem] = []
    search_actions: list[SearchAction] = []
    apps: list[AppItem] = []
    courses: list[CourseItem] = []
    contact_points: list[ContactPointItem] = []
    item_lists: list[ItemListCard] = []
    aggregate_offers: list[AggregateOfferRow] = []
    offer_catalogs: list[OfferCatalogRow] = []
    speakable: list[SpeakableRow] = []
    web_pages: list[WebPageCard] = []
    hours: list[HoursRow] = []
    nap: NapCard | None = None
    serving: ServingCard | None = None
    langs: list[Hreflang] = []
    seen_item: set[tuple[str, str]] = set()
    seen_lang: set[tuple[str, str]] = set()
    for page_url, html in raw_html:
        entities = [e for e in _jsonld(html or "") if isinstance(e, dict)]
        for entity in entities:
            for name in _type_names(entity):
                counts[name] = counts.get(name, 0) + 1
                if name not in FEATURED:
                    continue
                title = _field(entity, "name", "headline", "title")
                extra = _field(
                    entity, "foundingDate", "startDate", "endDate",
                    "datePublished", "dateModified", "lastReviewed",
                    "validThrough", "address", "jobLocation")
                key = (name, title or page_url)
                if key in seen_item:
                    continue
                seen_item.add(key)
                items.append(SchemaItem(
                    type=name, name=title, extra=extra, url=page_url))
        faqs.extend(extract_faqs(entities, page_url))
        jobs.extend(extract_jobs(entities, page_url))
        events.extend(extract_events(entities, page_url))
        articles.extend(extract_articles(entities, page_url))
        breadcrumbs.extend(extract_breadcrumbs(entities, page_url))
        people.extend(extract_people(entities, page_url))
        videos.extend(extract_videos(entities, page_url))
        howtos.extend(extract_howtos(entities, page_url))
        search_actions.extend(extract_search_actions(entities, page_url))
        apps.extend(extract_apps(entities, page_url))
        courses.extend(extract_courses(entities, page_url))
        contact_points.extend(extract_contact_points(entities, page_url))
        item_lists.extend(extract_item_lists(entities, page_url))
        aggregate_offers.extend(extract_aggregate_offers(entities, page_url))
        offer_catalogs.extend(extract_offer_catalogs(entities, page_url))
        speakable.extend(extract_speakable(entities, page_url))
        web_pages.extend(extract_web_pages(entities, page_url))
        hours.extend(extract_hours(entities, page_url))
        if nap is None:
            nap = extract_nap(entities, page_url)
        if serving is None:
            serving = extract_serving(entities, page_url)
        for row in discover_hreflang(page_url, html or ""):
            key = (row.lang, row.url)
            if key in seen_lang:
                continue
            seen_lang.add(key)
            langs.append(row)
    faqs = _unique_question(faqs)[:20]
    jobs = _unique_title(jobs)[:20]
    events = events[:20]
    articles = _unique_article(articles)[:15]
    breadcrumbs = _unique_trail(breadcrumbs)[:8]
    if not counts and not langs:
        return SchemaIntel(
            assessed=False,
            reason="No JSON-LD entities on sampled pages.",
        )
    return SchemaIntel(
        assessed=True,
        types=dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        items=items[:30],
        faqs=faqs,
        jobs=jobs,
        events=events,
        nap=nap,
        serving=serving,
        hreflang=langs[:20],
        articles=articles[:15],
        breadcrumbs=breadcrumbs[:8],
        people=_unique_person(people)[:20],
        videos=_unique_video(videos)[:15],
        howtos=_unique_howto(howtos)[:10],
        search_actions=_unique_search(search_actions)[:8],
        apps=_unique_app(apps)[:12],
        courses=_unique_course(courses)[:15],
        contact_points=_unique_contact(contact_points)[:12],
        item_lists=_unique_item_list(item_lists)[:8],
        aggregate_offers=_unique_aggregate(aggregate_offers)[:12],
        offer_catalogs=_unique_catalog(offer_catalogs)[:8],
        speakable=_unique_speakable(speakable)[:8],
        web_pages=_unique_web_page(web_pages)[:8],
        hours=_unique_hours(hours)[:14],
    )


def _unique_question(rows: list[FaqItem]) -> list[FaqItem]:
    seen: set[str] = set()
    out: list[FaqItem] = []
    for row in rows:
        key = row.question.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_title(rows: list[JobItem]) -> list[JobItem]:
    seen: set[str] = set()
    out: list[JobItem] = []
    for row in rows:
        key = row.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_article(rows: list[ArticleItem]) -> list[ArticleItem]:
    seen: set[str] = set()
    out: list[ArticleItem] = []
    for row in rows:
        key = row.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_trail(rows: list[BreadcrumbTrail]) -> list[BreadcrumbTrail]:
    seen: set[str] = set()
    out: list[BreadcrumbTrail] = []
    for row in rows:
        key = row.path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_person(rows: list[PersonCard]) -> list[PersonCard]:
    seen: set[str] = set()
    out: list[PersonCard] = []
    for row in rows:
        key = row.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_video(rows: list[VideoItem]) -> list[VideoItem]:
    seen: set[str] = set()
    out: list[VideoItem] = []
    for row in rows:
        key = row.title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_howto(rows: list[HowToItem]) -> list[HowToItem]:
    seen: set[str] = set()
    out: list[HowToItem] = []
    for row in rows:
        key = row.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_search(rows: list[SearchAction]) -> list[SearchAction]:
    seen: set[str] = set()
    out: list[SearchAction] = []
    for row in rows:
        key = row.target.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_app(rows: list[AppItem]) -> list[AppItem]:
    seen: set[str] = set()
    out: list[AppItem] = []
    for row in rows:
        key = f"{row.kind}:{row.name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_course(rows: list[CourseItem]) -> list[CourseItem]:
    seen: set[str] = set()
    out: list[CourseItem] = []
    for row in rows:
        key = f"{row.kind}:{row.name.lower()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_contact(rows: list[ContactPointItem]) -> list[ContactPointItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[ContactPointItem] = []
    for row in rows:
        key = (row.contact_type.lower(), row.telephone, row.email.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_item_list(rows: list[ItemListCard]) -> list[ItemListCard]:
    seen: set[str] = set()
    out: list[ItemListCard] = []
    for row in rows:
        key = row.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_aggregate(rows: list[AggregateOfferRow]) -> list[AggregateOfferRow]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[AggregateOfferRow] = []
    for row in rows:
        key = (row.name.lower(), row.low, row.high, row.offer_count)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_catalog(rows: list[OfferCatalogRow]) -> list[OfferCatalogRow]:
    seen: set[str] = set()
    out: list[OfferCatalogRow] = []
    for row in rows:
        key = row.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_speakable(rows: list[SpeakableRow]) -> list[SpeakableRow]:
    seen: set[tuple[str, str]] = set()
    out: list[SpeakableRow] = []
    for row in rows:
        key = (row.name.lower(), "|".join(row.selectors).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_web_page(rows: list[WebPageCard]) -> list[WebPageCard]:
    seen: set[str] = set()
    out: list[WebPageCard] = []
    for row in rows:
        key = f"{row.kind}:{row.name.lower()}:{row.last_reviewed}"
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _unique_hours(rows: list[HoursRow]) -> list[HoursRow]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[HoursRow] = []
    for row in rows:
        key = (row.name.lower(), row.day.lower(), row.opens, row.closes)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def type_names(intel: dict[str, Any] | None) -> set[str]:
    data = intel or {}
    return {str(k) for k in (data.get("types") or {}) if k}
