"""Cross-source identity and claim corroboration.

This is deliberately deterministic and inspectable. The engine does not call a result
"verified" because it looks plausible: every account and claim receives a score from
named evidence, contradictions are recorded, and weak discovered surfaces are withheld.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.schemas import PlatformAccount, RawProfile

SOCIAL_HOSTS = {
    "instagram.com", "youtube.com", "youtu.be", "linkedin.com", "x.com",
    "twitter.com", "threads.net", "facebook.com", "t.me", "linktr.ee",
    "topmate.io", "superprofile.bio", "beacons.ai", "bio.link", "medium.com",
}
GENERIC = {"official", "creator", "educator", "mentor", "coach", "founder",
           "speaker", "channel", "profile", "india", "website", "page"}


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _tokens(*values: str | None) -> set[str]:
    blob = " ".join(v or "" for v in values).lower()
    return {x for x in re.split(r"[^a-z0-9]+", blob)
            if len(x) > 2 and x not in GENERIC}


def _url(url: str) -> str:
    try:
        p = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in
                 {"gclid", "fbclid", "ref", "ref_src", "source"}]
        return urlunsplit((p.scheme.lower(), p.netloc.lower().replace("www.", ""),
                           p.path.rstrip("/") or "/", urlencode(query), ""))
    except Exception:
        return url.rstrip("/").lower()


def _source_tier(account: PlatformAccount) -> tuple[str, float]:
    route = account.raw.get("verified_via") or account.raw.get("source") or "public_page"
    if route in {"seed", "official_api", "youtube_data_api", "itunes_lookup_api"}:
        return "official / supplied seed", 0.98
    if route in {"owned_link", "link_in_bio"}:
        return "creator-owned link graph", 0.94
    if route == "probe":
        return "verified public handle probe", 0.84
    if route == "search+content":
        return "search and collected-page agreement", 0.82
    if route == "search_identity":
        return "search-indexed direct profile", 0.76
    if route in {"public_profile", "public_channel_preview", "public_web"}:
        return "public first-party surface", 0.78
    return "public surface", 0.62


def _logistic(evidence: list[tuple[float, str]], penalties: list[tuple[float, str]]) -> float:
    """Combine independent evidence in log-odds space; cap correlated certainty."""
    odds = -1.75
    for weight, _ in evidence:
        odds += weight
    for weight, _ in penalties:
        odds -= weight
    return round(max(0.01, min(0.99, 1 / (1 + math.exp(-odds)))), 3)


def _account_audit(raw: RawProfile, account: PlatformAccount) -> dict:
    evidence: list[tuple[float, str]] = []
    penalties: list[tuple[float, str]] = []
    route = account.raw.get("verified_via", "")
    canonical = _url(account.url)
    is_seed = canonical == _url(raw.seed_url)
    tier, tier_weight = _source_tier(account)
    seed_handle = _norm(raw.seed_handle)
    account_handle = _norm(account.handle)

    seed_surfaces = [a for a in raw.accounts if _url(a.url) == _url(raw.seed_url)]
    seed_blob = _norm(" ".join(
        [raw.display_name or "", raw.seed_handle or ""] +
        [f"{a.display_name or ''} {a.bio or ''} {' '.join(a.external_links)}"
         for a in seed_surfaces]))
    page_blob = _norm(f"{account.display_name or ''} {account.bio or ''} "
                      f"{' '.join(account.external_links)}")
    seed_mentions_account = bool(account_handle and len(account_handle) >= 5 and
                                 account_handle in seed_blob)
    account_mentions_seed = bool(seed_handle and seed_handle in page_blob)
    mutual_mention = seed_mentions_account and account_mentions_seed
    derivative = bool(seed_handle and account_handle.startswith(seed_handle) and
                      account_handle != seed_handle and
                      account_handle[len(seed_handle):] in {
                          "clips", "shorts", "podcast", "official", "show", "tv"})

    parts = urlsplit(account.url)
    host = parts.netloc.lower().replace("www.", "")
    path = parts.path.lower().rstrip("/")
    vendor_junk = ((host == "linktr.ee" and
                    (path in {"", "/", "/marketplace"} or path.startswith("/blog/"))) or
                   (host in {"beacons.ai", "bio.link"} and path in {"", "/"}))
    host_identity = bool(seed_handle and seed_handle in _norm(host))

    if is_seed or route == "seed":
        role = "primary"
        evidence.append((6.0, "user-supplied seed surface"))
    elif vendor_junk:
        role = "platform_navigation"
        penalties.append((5.0, "platform editorial/navigation URL, not a creator surface"))
    elif route == "search_identity":
        role = "primary" if seed_handle and account_handle == seed_handle else "indexed_profile"
        evidence.append((2.5, "direct indexed profile strongly matches the subject identity"))
    elif seed_handle and account_handle == seed_handle:
        role = ("owned_property" if account.platform in {
            "website", "topmate", "superprofile", "linktree", "appstore", "playstore"
        } else "primary")
        evidence.append((1.55, "exact cross-platform handle match"))
    elif mutual_mention:
        role = "associated_brand"
        evidence.append((2.1, "mutual handle mention links this associated brand to the subject"))
    elif derivative and account_mentions_seed:
        role = "secondary_channel"
        evidence.append((1.4, "derivative handle and page identity indicate a secondary channel"))
    elif route == "owned_link":
        role = "owned_property"
    elif account.platform == "website" and host_identity:
        role = "owned_property"
        evidence.append((1.1, "domain matches the subject handle"))
    elif account.platform == "website":
        role = "independent_evidence"
    else:
        role = "candidate"

    if route == "owned_link":
        evidence.append((3.3, "linked from a creator-controlled surface"))
    if route == "probe":
        evidence.append((1.8, "public handle probe passed"))
    if route == "search+content":
        evidence.append((1.65, "search and page identity evidence agree"))
    if route == "search_identity":
        evidence.append((0.65, "high-confidence search URL, title and snippet agreement"))
    if seed_handle and account_handle and account_handle != seed_handle and not (
            mutual_mention or derivative):
        penalties.append((0.25, "handle differs from seed; requires other evidence"))

    subject_tokens = _tokens(raw.display_name, raw.seed_handle)
    page_tokens = _tokens(account.display_name, account.bio)
    overlap = len(subject_tokens & page_tokens) / max(1, len(subject_tokens))
    if overlap >= 0.99 and len(subject_tokens) >= 2:
        evidence.append((1.45, "full display-name token agreement"))
    elif overlap >= 0.5:
        evidence.append((0.72, f"partial display-name agreement ({overlap:.0%})"))
    elif account.display_name and subject_tokens and role not in {
            "associated_brand", "independent_evidence"}:
        penalties.append((0.85, "display name does not corroborate the subject"))

    inbound = []
    for source in raw.accounts:
        if source is account:
            continue
        if any(_url(link) == canonical for link in source.external_links):
            inbound.append(source.platform)
    if inbound:
        evidence.append((2.4, "cross-linked by " + ", ".join(sorted(set(inbound)))))

    search_rows = [h for h in raw.search_hits if _url(h.url) == canonical]
    if search_rows:
        providers = {p for h in search_rows for p in h.providers}
        search_score = max((h.identity_score or 0.0) for h in search_rows)
        if search_score >= 0.68:
            evidence.append((0.8 + min(0.45, .15 * len(providers)),
                             f"search identity score {search_score:.0%} across "
                             f"{len(providers) or 1} provider(s)"))

    if account.raw.get("verified_via") == "rejected":
        penalties.append((4.0, "failed collection-time identity gate"))
    if account.errors and not (account.display_name or account.bio or account.content):
        penalties.append((0.45, "surface yielded no readable identity content"))

    score = _logistic(evidence, penalties)
    if role == "independent_evidence":
        status = "evidence_only"
    elif role == "platform_navigation":
        status = "withheld"
    elif role == "candidate":
        status = "review" if score >= 0.55 else "withheld"
    else:
        status = "accepted" if score >= 0.75 else "review" if score >= 0.55 else "withheld"
    return {
        "platform": account.platform, "url": account.url,
        "handle": account.handle or "", "display_name": account.display_name or "",
        "score": score, "status": status, "role": role,
        "analysis_eligible": status == "accepted" and role not in {
            "independent_evidence", "platform_navigation", "candidate"},
        "source_tier": tier, "source_weight": tier_weight,
        "signals": [x[1] for x in evidence], "conflicts": [x[1] for x in penalties],
        "verified_via": route or "not recorded", "is_seed": is_seed,
    }


def _claim(key: str, value, status: str, confidence: float, sources: list[str],
           method: str, conflict: str = "") -> dict:
    return {"key": key, "value": value, "status": status,
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "sources": list(dict.fromkeys(sources)), "method": method,
            "conflict": conflict}


def _claim_ledger(raw: RawProfile, accounts: list[dict]) -> tuple[list[dict], list[dict]]:
    claims: list[dict] = []
    conflicts: list[dict] = []
    strong = [a for a in accounts if a["status"] == "accepted" and a["role"] == "primary"]
    identity_sources = [a["url"] for a in strong]
    if len(strong) >= 2:
        claims.append(_claim("subject_identity", raw.display_name or raw.seed_handle,
                             "corroborated", min(0.99, sum(a["score"] for a in strong) / len(strong)),
                             identity_sources, "agreement across accepted public surfaces"))
    elif strong:
        claims.append(_claim("subject_identity", raw.display_name or raw.seed_handle,
                             "observed_single_source", strong[0]["score"], identity_sources,
                             "one accepted public surface; no independent account corroboration"))
    else:
        claims.append(_claim("subject_identity", "withheld", "withheld", 0.0, [],
                             "no surface passed the identity threshold"))

    # Platform counts are observed at a point in time, not treated as unique people.
    audit_by_url = {_url(a["url"]): a for a in accounts}
    by_platform_handle: dict[tuple[str, str], list[PlatformAccount]] = defaultdict(list)
    for account in raw.accounts:
        audit_row = audit_by_url.get(_url(account.url), {})
        if account.followers is not None and audit_row.get("status") == "accepted":
            by_platform_handle[(account.platform, _norm(account.handle) or _url(account.url))].append(account)
    for (platform, handle_key), rows in by_platform_handle.items():
        vals = [a.followers for a in rows if a.followers is not None]
        sources = [a.url for a in rows]
        relation = audit_by_url.get(_url(rows[0].url), {}).get("role", "primary")
        conflict = ""
        status = "observed_single_source" if len(vals) == 1 else "corroborated"
        conf = 0.90 if len(vals) == 1 else 0.96
        if len(vals) > 1 and min(vals) and (max(vals) - min(vals)) / min(vals) > 0.15:
            conflict = f"public counts disagree by more than 15%: {min(vals):,} to {max(vals):,}"
            status, conf = "conflicted", 0.25
            conflicts.append({"type": "follower_count", "claim": f"{platform}_followers",
                              "detail": conflict, "sources": sources})
        suffix = "" if relation == "primary" else f": @{rows[0].handle or handle_key} ({relation})"
        claims.append(_claim(f"{platform}_followers{suffix}", vals[-1], status, conf, sources,
                             "public platform count captured at collection time", conflict))

    # The same normalised offer with divergent live prices is an explicit conflict.
    products: dict[str, list[tuple[PlatformAccount, object]]] = defaultdict(list)
    for account in raw.accounts:
        audit_row = audit_by_url.get(_url(account.url), {})
        if audit_row.get("status") != "accepted" or audit_row.get("role") in {
                "candidate", "independent_evidence", "platform_navigation"}:
            continue
        for product in account.products:
            name = " ".join(sorted(_tokens(product.name))) or _norm(product.name)
            if name:
                products[name].append((account, product))
    for name, rows in products.items():
        prices = [p.price_inr for _, p in rows if p.price_inr is not None]
        label = rows[0][1].name
        sources = [(p.url or a.url) for a, p in rows]
        conflict = ""
        status = "observed_single_source" if len(rows) == 1 else "corroborated"
        conf = 0.88 if len(rows) == 1 else 0.94
        value = prices[-1] if prices else "price unavailable"
        if len(prices) > 1 and min(prices) and (max(prices) - min(prices)) / min(prices) > 0.10:
            conflict = f"public prices disagree by more than 10%: INR {min(prices):,.0f} to {max(prices):,.0f}"
            status, conf, value = "conflicted", 0.25, "withheld"
            conflicts.append({"type": "product_price", "claim": label,
                              "detail": conflict, "sources": sources})
        claims.append(_claim(f"offer: {label}", value, status, conf, sources,
                             "public offer card or structured Product/Offer data", conflict))

    return claims, conflicts


def audit(raw: RawProfile) -> dict:
    accounts = [_account_audit(raw, account) for account in raw.accounts]
    claims, conflicts = _claim_ledger(raw, accounts)

    # Multiple accepted identities on one platform are never silently merged.
    accepted_by_platform: dict[str, list[dict]] = defaultdict(list)
    for row in accounts:
        if row["status"] == "accepted" and row["role"] == "primary":
            accepted_by_platform[row["platform"]].append(row)
    for platform, rows in accepted_by_platform.items():
        identities = {_norm(x["display_name"]) for x in rows if x["display_name"]}
        if len(rows) > 1 and len(identities) > 1:
            detail = f"{len(rows)} accepted {platform} surfaces carry different display identities"
            conflicts.append({"type": "identity_collision", "claim": platform,
                              "detail": detail, "sources": [x["url"] for x in rows]})
            for row in rows:
                row["status"] = "conflicted"
                row["conflicts"].append(detail)

    identity_collisions = [x for x in conflicts if x["type"] == "identity_collision"]
    if identity_collisions:
        for claim in claims:
            if claim["key"] == "subject_identity":
                claim.update({"value": "withheld", "status": "conflicted",
                              "confidence": 0.0,
                              "conflict": "; ".join(x["detail"] for x in identity_collisions)})

    accepted = [x for x in accounts if x["status"] == "accepted"]
    primary = [x for x in accepted if x["role"] == "primary"]
    identity_score = round(sum(x["score"] for x in primary) / len(primary), 3) if primary else 0.0
    identity_status = ("corroborated" if len(primary) >= 2 and not any(
        x["type"] == "identity_collision" for x in conflicts)
        else "single-source" if primary else "insufficient")

    account_hosts = {urlsplit(_url(a.url)).netloc for a in raw.accounts}
    independent = sorted({urlsplit(_url(h.url)).netloc for h in raw.search_hits
                          if urlsplit(_url(h.url)).netloc not in account_hosts
                          and not any(urlsplit(_url(h.url)).netloc.endswith(s) for s in SOCIAL_HOSTS)})
    claim_counts = dict(Counter(c["status"] for c in claims))
    now = datetime.now(timezone.utc)
    ages = []
    for a in raw.accounts:
        dt = a.collected_at.replace(tzinfo=timezone.utc) if a.collected_at.tzinfo is None else a.collected_at
        ages.append(max(0, (now - dt).total_seconds() / 3600))
    return {
        "identity_status": identity_status, "identity_score": identity_score,
        "accounts": accounts, "accepted_accounts": len(accepted),
        "primary_accounts": len(primary),
        "related_accounts": sum(x["role"] in {
                                    "associated_brand", "secondary_channel", "owned_property",
                                    "indexed_profile"
                                }
                                and x["status"] == "accepted" for x in accounts),
        "withheld_accounts": (sum(x["status"] != "accepted" for x in accounts)
                              + len(raw.rejected)),
        "claims": claims, "claim_counts": claim_counts, "conflicts": conflicts,
        "independent_sources": independent, "independent_source_count": len(independent),
        "query_count": len({q for h in raw.search_hits for q in (h.matched_queries or [h.query_id]) if q}),
        "provider_count": len({p for h in raw.search_hits for p in h.providers}),
        "freshness_hours": round(max(ages), 1) if ages else None,
        "policy": "Contradictory or low-confidence facts are withheld; audience size never proves identity.",
    }


def enforce(raw: RawProfile) -> dict:
    """Separate analytical surfaces, visible candidates and independent evidence."""
    report = audit(raw)
    rows = {_url(x["url"]): x for x in report["accounts"]}
    kept: list[PlatformAccount] = []
    for account in raw.accounts:
        row = rows.get(_url(account.url), {})
        protected = row.get("is_seed") or account.raw.get("verified_via") == "seed"
        if row.get("role") in {"independent_evidence", "platform_navigation"}:
            # Press/citation pages remain in search evidence; they are not creator accounts.
            continue
        if not protected and row.get("status") in {"withheld", "conflicted"}:
            raw.rejected.append({
                "platform": account.platform, "url": account.url,
                "reason": ("Withheld by cross-source identity audit: "
                           + "; ".join(row.get("conflicts") or [
                               f"identity score {row.get('score', 0):.0%} below threshold"])),
            })
            continue
        account.raw["identity_score"] = row.get("score", 0.0)
        account.raw["identity_signals"] = row.get("signals", [])
        account.raw["identity_role"] = row.get("role", "candidate")
        account.raw["identity_status"] = row.get("status", "review")
        account.raw["analysis_eligible"] = bool(row.get("analysis_eligible"))
        kept.append(account)
    raw.accounts = kept
    accepted_urls = {_url(a.url) for a in kept}
    seen_rejected: set[tuple[str, str]] = set()
    rejected = []
    for item in raw.rejected:
        key = (item.get("platform", ""), _url(item.get("url", "")))
        if key[1] in accepted_urls or key in seen_rejected:
            continue
        seen_rejected.add(key)
        rejected.append(item)
    raw.rejected = rejected
    raw.verification = audit(raw)
    return raw.verification
