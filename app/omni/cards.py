"""Published share cards and app-banner tags (spec §8, §11).

Open Graph, Twitter card and smart-banner meta are copied. twitter:site is a
printed handle, not followers. An app-id is not an App Store scrape or
install count.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.engine.collectors.web import _meta

OG_KEYS = ("og:type", "og:title", "og:image", "og:site_name")
TWITTER_KEYS = ("twitter:card", "twitter:title", "twitter:site", "twitter:image")
BANNERS = (
    ("apple-itunes-app", "ios"),
    ("google-play-app", "android"),
    ("al:ios:app_store_id", "ios"),
    ("al:android:package", "android"),
)


class BannerRow(BaseModel):
    kind: str
    value: str


class CardIntel(BaseModel):
    assessed: bool = False
    reason: str = ""
    og_type: str = ""
    og_title: str = ""
    og_image: str = ""
    twitter_card: str = ""
    twitter_site: str = ""
    twitter_title: str = ""
    banners: list[BannerRow] = Field(default_factory=list)
    methodology: str = (
        "Fields are copied from og:* / twitter:* and smart-banner meta on "
        "sampled pages. twitter:site is not a follower count. An app banner "
        "id is not store ranking or installs.")


def analyse_cards(raw_html: list[tuple[str, str]]) -> CardIntel:
    """Pure over already-fetched HTML."""
    if not raw_html:
        return CardIntel(assessed=False, reason="No pages were sampled.")
    og_type = og_title = og_image = ""
    tw_card = tw_site = tw_title = ""
    banners: list[BannerRow] = []
    seen_banner: set[tuple[str, str]] = set()
    for _url, html in raw_html:
        html = html or ""
        og_type = og_type or (_meta(html, "og:type") or "")
        og_title = og_title or (_meta(html, "og:title") or "")
        og_image = og_image or (_meta(html, "og:image") or "")
        tw_card = tw_card or (_meta(html, "twitter:card") or "")
        tw_site = tw_site or (_meta(html, "twitter:site") or "")
        tw_title = tw_title or (_meta(html, "twitter:title") or "")
        for name, kind in BANNERS:
            value = (_meta(html, name) or "").strip()
            if not value:
                continue
            key = (kind, value[:80].lower())
            if key in seen_banner:
                continue
            seen_banner.add(key)
            banners.append(BannerRow(kind=kind, value=value[:80]))
    if not any((og_type, og_title, og_image, tw_card, tw_site, tw_title, banners)):
        return CardIntel(
            assessed=True,
            reason="No Open Graph, Twitter card or app-banner meta on sampled pages.",
        )
    return CardIntel(
        assessed=True,
        og_type=og_type[:40],
        og_title=og_title[:160],
        og_image=og_image[:240],
        twitter_card=tw_card[:40],
        twitter_site=tw_site[:40],
        twitter_title=tw_title[:160],
        banners=banners[:8],
    )
