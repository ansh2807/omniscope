"""Search-operator templates — the 'dorking' layer.

These are ordinary Google/Bing search operators run through a licensed search API.
Nothing here probes for vulnerabilities or exposed credentials; the queries only look
for a person's *own published* public footprint across platforms and press.

Each template declares what it is trying to find, so the expander can label the
provenance of anything it discovers.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dork:
    id: str
    purpose: str
    template: str
    weight: float = 1.0   # how strongly a hit implies identity match


PLATFORM_DORKS: list[Dork] = [
    Dork("ig",        "Instagram account",      'site:instagram.com "{name}" OR "{handle}"'),
    Dork("yt",        "YouTube channel",        'site:youtube.com "{name}" OR "{handle}"'),
    Dork("li",        "LinkedIn profile",       'site:linkedin.com/in "{name}"'),
    Dork("x",         "X / Twitter",            '(site:x.com OR site:twitter.com) "{name}" OR "{handle}"'),
    Dork("threads",   "Threads",                'site:threads.net "{handle}"'),
    Dork("fb",        "Facebook page",          'site:facebook.com "{name}"'),
    Dork("tg",        "Telegram channel",       'site:t.me "{name}" OR "{handle}"'),
    Dork("bio",       "Link-in-bio page",       '(site:linktr.ee OR site:topmate.io OR site:superprofile.bio OR site:beacons.ai OR site:bio.link) "{handle}" OR "{name}"'),
    Dork("app",       "Mobile app",             '(site:apps.apple.com OR site:play.google.com) "{name}"'),
    Dork("substack",  "Newsletter",             '(site:substack.com OR site:beehiiv.com OR site:medium.com) "{name}"'),
    Dork("spotify",   "Podcast",                '(site:open.spotify.com OR site:podcasts.apple.com) "{name}"'),
    Dork("github",    "Code presence",          'site:github.com "{name}"', 0.5),
]

FOOTPRINT_DORKS: list[Dork] = [
    Dork("exact",     "Exact identity footprint", '"{name}" "{handle}"'),
    Dork("site",      "Own website",            '"{name}" (official OR website OR "about me") -site:instagram.com -site:youtube.com'),
    Dork("sameas",    "Cross-linked identity",   '"{handle}" ("official website" OR "social links" OR "follow me")'),
    Dork("press",     "News & press mentions",   '"{name}" (interview OR profile OR "in conversation" OR featured)'),
    Dork("news",      "Independent news record", '"{name}" (site:indiatoday.in OR site:forbes.com OR site:entrepreneur.com OR site:thebetterindia.com OR site:yourstory.com)'),
    Dork("talks",     "Stage & conference",     '"{name}" (tedx OR "josh talks" OR summit OR conference OR "keynote" OR "guest speaker")'),
    Dork("podcast",   "Podcast appearances",    '"{name}" (podcast OR "episode with" OR "on the show")'),
    Dork("publication", "Authored publications", '"{name}" (author OR paper OR publication OR research OR book)'),
    Dork("credential", "Credential corroboration", '"{name}" (university OR college OR alumnus OR certification OR faculty OR institute)'),
    Dork("company",   "Company / venture",      '"{name}" (founder OR "co-founder" OR CEO) (startup OR company OR crunchbase OR tracxn)'),
    Dork("registry",  "Corporate records",       '"{name}" (director OR company OR LLP) (site:mca.gov.in OR site:tofler.in OR site:zaubacorp.com)'),
    Dork("pricing",   "Products & pricing",     '"{name}" (course OR workshop OR mentorship OR consultation) ₹'),
    Dork("offers",    "Offer catalogue",         '("{name}" OR "{handle}") (buy OR enroll OR book OR pricing OR fees)'),
    Dork("sponsor",   "Brand campaign evidence", '"{name}" (sponsored OR partnership OR collaboration OR campaign OR ambassador)'),
    Dork("reviews",   "Third-party reviews",    '"{name}" (review OR testimonial OR "worth it")'),
    Dork("complaints", "Risk and complaint triage", '("{name}" OR "{handle}") (complaint OR scam OR fraud OR refund OR misleading)', 0.6),
    Dork("community", "Community discussion",   '"{name}" (site:reddit.com OR site:quora.com)'),
    Dork("edu",       "Education platforms",    '"{name}" (site:unacademy.com OR site:udemy.com OR site:coursera.org OR site:shiksha.com)'),
    Dork("rank",      "Creator rankings",       '"{handle}" (site:socialblade.com OR site:hypeauditor.com OR site:favikon.com OR site:starngage.com)', 0.7),
]

AUDIENCE_DORKS: list[Dork] = [
    Dork("aud_q",     "Audience questions",     '"{name}" (how OR "is it worth" OR fees OR "vs")'),
    Dork("aud_forum", "Forum sentiment",        '("{name}" OR "{handle}") (experience OR "anyone tried" OR honest)'),
    Dork("aud_outcome", "Audience outcome language", '("{name}" OR "{handle}") (helped OR learned OR result OR outcome OR success)'),
]

ALL_DORKS = PLATFORM_DORKS + FOOTPRINT_DORKS + AUDIENCE_DORKS


def build(dorks: list[Dork], *, name: str, handle: str) -> list[tuple[Dork, str]]:
    out = []
    for d in dorks:
        try:
            q = d.template.format(name=name or handle, handle=handle or name)
        except (KeyError, IndexError):
            continue
        out.append((d, q))
    return out
