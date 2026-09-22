"""Combiner: archetype prior + weighted rule contributions -> AudienceModel."""
from __future__ import annotations

import re

from app.engine.inference import benchmarks as B
from app.engine.inference import personas as persona_lib
from app.engine.inference import rules as rule_lib
from app.engine.inference.signals import Signals
from app.schemas import (AudienceModel, ClaimStatus, Distribution, Estimate, Evidence,
                         RawProfile)

PRIOR_WEIGHT = 1.6


def _taxonomy(prior: dict[str, float], buckets: list[str], base_conf: float,
              contribs: list[rule_lib.Contribution], why: str) -> Distribution:
    d = _combine(prior, contribs, buckets, base_conf)
    d.reasoning = (why + " " + d.reasoning).strip()
    return d


def _states(sig, tax, tier) -> Estimate:
    if sig.geo_terms:
        # Only report states that can be resolved from places actually present in the
        # creator's metadata.  Category priors are not creator-specific geography.
        seen, val = set(), []
        for city in sig.geo_terms:
            st = B.CITY_TO_STATE.get(city.lower())
            if st and st not in seen:
                seen.add(st)
                val.append(st)
        why = ("Resolved only from place names found in the creator's public titles, bio "
               "or keywords. This shows content relevance, not a follower-location split.")
        conf = 0.68 if val else 0.0
        status = ClaimStatus.CALCULATED if val else ClaimStatus.UNAVAILABLE
    else:
        val = []
        why = ("No state-level audience analytics or repeated place names were observed. "
               "The engine does not substitute a category-average state list.")
        conf = 0.0
        status = ClaimStatus.UNAVAILABLE
    return Estimate(key="states", value=val, confidence=conf, reasoning=why,
                    status=status, method="public place-name extraction")


def _english(sig, tax) -> Estimate:
    return Estimate(
        key="english_proficiency", value="Not publicly measurable", confidence=0.0,
        status=ClaimStatus.UNAVAILABLE,
        reasoning=("English proficiency is a follower attribute. English words in titles or "
                   "the subject matter do not measure it."),
        method="requires first-party survey or platform analytics")


def _unavailable_dist(reason: str) -> Distribution:
    return Distribution(buckets={}, confidence=0.0, reasoning=reason,
                        status=ClaimStatus.UNAVAILABLE,
                        method="requires first-party audience analytics")


def _parse_split(value) -> dict[str, float]:
    """Parse analyst-supplied ``label:number`` pairs without inventing missing buckets."""
    if isinstance(value, dict):
        pairs = value.items()
    else:
        pairs = []
        for part in re.split(r"[,;\n]+", str(value or "")):
            if ":" not in part:
                continue
            key, raw_value = part.rsplit(":", 1)
            pairs.append((key, raw_value))
    out: dict[str, float] = {}
    for key, raw_value in pairs:
        try:
            number = float(re.sub(r"[^0-9.]", "", str(raw_value)))
        except ValueError:
            continue
        label = str(key).strip().lower().replace("_", " ")
        if label and number >= 0:
            out[label] = number
    return out


def _manual_distribution(raw: RawProfile, key: str) -> Distribution | None:
    for acc in raw.accounts:
        if not acc.raw.get(key):
            continue
        buckets = _parse_split(acc.raw[key])
        if not buckets:
            continue
        return Distribution(
            buckets=buckets, confidence=0.98,
            reasoning=("Creator/analyst-supplied audience analytics. Values are reproduced "
                       "as supplied and are not inferred by the engine."),
            evidence=[Evidence(claim=f"{key} supplied from creator analytics",
                               source_url=acc.url, collected_at=acc.collected_at,
                               note="manual first-party input")],
            status=ClaimStatus.OBSERVED, method="manual first-party analytics",
            sample_size=None)
    return None


def _published_format(raw: RawProfile) -> Distribution:
    items = raw.all_content()
    if not items:
        return _unavailable_dist("No public content items were collected to classify format.")
    counts = {"long_form": 0.0, "short_form": 0.0, "static": 0.0, "live": 0.0}
    for item in items:
        if item.kind in ("post", "carousel"):
            counts["static"] += 1
        elif item.kind == "live":
            counts["live"] += 1
        elif item.kind in ("short", "reel") or (
                item.duration_seconds is not None and item.duration_seconds <= 180):
            counts["short_form"] += 1
        else:
            counts["long_form"] += 1
    counts = {k: v for k, v in counts.items() if v}
    return Distribution(
        buckets=counts, confidence=0.92,
        reasoning=(f"Distribution of the {len(items)} public items the engine collected. This is "
                   "the creator's published output mix, not the audience's total media diet."),
        status=ClaimStatus.CALCULATED, method="classified public content items",
        sample_size=len(items))


def _combine(prior: dict[str, float], contribs: list[rule_lib.Contribution],
             buckets: list[str], base_conf: float) -> Distribution:
    acc = {b: prior.get(b, 0.0) * PRIOR_WEIGHT for b in buckets}
    total_w = PRIOR_WEIGHT
    conf = base_conf
    reasons: list[str] = []
    evidence: list[Evidence] = []

    for c in contribs:
        for b in buckets:
            acc[b] += c.buckets.get(b, 0.0) * c.weight
        total_w += c.weight
        conf = conf + (c.confidence - conf) * min(0.55, c.weight / 4.0)
        reasons.append(c.reasoning)
        evidence.append(Evidence(claim=c.reasoning, note=c.rule_id))

    s = sum(acc.values()) or 1.0
    return Distribution(
        buckets={b: acc[b] / s for b in buckets},
        confidence=round(min(0.92, max(0.30, conf)), 2),
        reasoning=" ".join(reasons) or "Modelled from category priors only.",
        evidence=evidence,
        status=ClaimStatus.MODELLED,
        method="archetype prior updated by content-stage rules",
    )


def run(sig: Signals, raw: RawProfile) -> AudienceModel:
    arch = B.ARCHETYPES.get(sig.archetype, B.ARCHETYPES["generalist_creator"])
    tax = B.ARCHETYPE_TAXONOMY.get(sig.archetype,
                                   B.ARCHETYPE_TAXONOMY["generalist_creator"])

    by_dim: dict[str, list[rule_lib.Contribution]] = {}
    fired: list[str] = []
    for r in rule_lib.RULES:
        res = r.fn(sig)
        if not res:
            continue
        for c in (res if isinstance(res, list) else [res]):
            if c.dimension != "age":
                # Public creator metadata can constrain life stage, but it cannot turn
                # platform/category priors into creator-specific gender, income, device,
                # geography or buyer-temperature percentages.
                continue
            by_dim.setdefault(c.dimension, []).append(c)
            fired.append(c.rule_id or r.id)

    base = arch["confidence"]
    manual_age = _manual_distribution(raw, "audience_age")
    if manual_age:
        age = manual_age
    elif sig.archetype == "generalist_creator" or sig.topic_distinct_terms < 2:
        age = _unavailable_dist(
            "No stable content-stage classification was supported by at least two distinct "
            "boundary-matched topic terms. Age is withheld.")
    else:
        age = _combine(arch["age"], by_dim.get("age", []), B.AGE_BUCKETS, base)
    gender = (_manual_distribution(raw, "audience_gender") or
              _unavailable_dist("Gender is private platform analytics. Creator category, "
                                "platform baselines and creator gender are not valid substitutes."))
    tier = _unavailable_dist("Follower city-tier distribution was not observed. Place names in "
                             "content describe subject relevance, not follower residence.")
    income = _unavailable_dist("Audience income is not public. Product price measures the offer, "
                               "not the income of followers who did or did not buy it.")
    device = _unavailable_dist("Device mix is private platform analytics; national Android/iOS "
                               "averages are not creator-specific evidence.")
    fmt = _published_format(raw)
    temp = _unavailable_dist("Cold/warm/hot audience shares require first-party behaviour or CRM "
                             "data. Public follower and rating counts cannot produce this split.")

    model = AudienceModel(
        archetype=sig.archetype,
        archetype_label=arch["label"],
        one_liner=_one_liner(sig, arch, age),
        age=age, gender=gender, city_tier=tier, income=income,
        device=device, format_mix=fmt, temperature=temp,
        occupation=None, education_mix=None, career_mix=None,
        sophistication=None, consumption=None,
        seasonality={},
        signals_fired=sorted(set(fired)),
    )

    model.country_split = _country(sig)
    model.top_cities = _manual_cities(raw) or _cities(sig, tier)
    model.education = _education(sig, arch)
    model.career_stage = _career(sig, arch, age)
    model.language = _language(sig)
    model.states = _states(sig, tax, tier)
    model.english_proficiency = _english(sig, tax)
    model.regional_language = Estimate(
        key="regional_language", value="Not publicly measurable", confidence=0.0,
        status=ClaimStatus.UNAVAILABLE,
        reasoning=("A creator's topic geography does not establish which regional languages "
                   "their followers speak."), method="requires first-party analytics")
    model.interests = _interests(sig)
    model.psychographics = (_psychographics(sig, arch)
                             if sig.archetype != "generalist_creator" else {})
    model.vocabulary = _vocabulary(sig)
    model.behaviours = _behaviours(sig)
    model.personas = persona_lib.build(sig, model)
    model.activation = _activation(sig, arch, model)
    model.unavailable = _unavailable(raw)

    for fn in rule_lib.CALLOUT_RULES:
        co = fn(sig)
        if co:
            model.callouts.append({"kind": co.kind, "title": co.title,
                                   "body": co.body, "rule_id": co.rule_id})

    dims = [d for d in (age, gender, tier, income, device, temp)
            if d.status != ClaimStatus.UNAVAILABLE]
    model.overall_confidence = round(sum(d.confidence for d in dims) / len(dims), 2) if dims else 0.0
    return model


# ------------------------------------------------------------------ narrative
def _one_liner(sig: Signals, arch: dict, age: Distribution) -> str:
    if age.status == ClaimStatus.UNAVAILABLE:
        return ("Public content did not support a stable content-stage audience taxonomy; "
                "life stage and follower geography remain unavailable. Private demographic "
                "and purchasing data are not inferred.")
    pct = age.as_pct()
    modal = max(pct, key=pct.get) if pct else "not measured"
    geo = (f"content repeatedly references {sig.geo_terms[0]}"
           if sig.geo_terms else "follower geography unavailable")
    return (f"{arch['one_liner']} — likely life-stage {modal} from content relevance; "
            f"{geo}. Private demographic and purchasing data are not inferred.")


def _country(sig: Signals) -> list[Estimate]:
    if sig.geo_scope == "city":
        value, why = "India-focused; local catchment named in content", (
            "Repeated Indian institution and place names establish content relevance. They do "
            "not reveal follower-country percentages.")
        conf = 0.82
    elif sig.geo_scope == "global":
        value, why = "India-origin content with international topics", (
            "Study-abroad and overseas-opportunity titles establish topic scope, not the "
            "residence of viewers.")
        conf = 0.66
    elif any(t in sig.topic_scores for t in (
            "board_exams", "commerce_subjects", "entrance_cat", "entrance_gov",
            "cuet_admissions", "school_science")):
        value, why = "India-focused", (
            "The public subject matter is tied to Indian institutions, exams or careers. "
            "Follower-country percentages remain private.")
        conf = 0.68
    else:
        return [Estimate(
            key="market_relevance", value="Follower country unavailable", confidence=0.0,
            reasoning=("No first-party country analytics or repeated place/institution evidence "
                       "was observed. The engine does not infer geography from locale defaults."),
            status=ClaimStatus.UNAVAILABLE,
            method="requires first-party audience analytics")]
    return [Estimate(key="market_relevance", value=value, confidence=conf, reasoning=why,
                     status=ClaimStatus.CALCULATED,
                     method="public topic and place-name classification")]


def _manual_cities(raw: RawProfile) -> Estimate | None:
    for acc in raw.accounts:
        value = acc.raw.get("audience_cities")
        if not value:
            continue
        if isinstance(value, list):
            cities = [str(v).strip() for v in value if str(v).strip()]
        else:
            cities = [v.strip() for v in re.split(r"[,;\n]+", str(value)) if v.strip()]
        if cities:
            return Estimate(
                key="top_cities", value=cities, confidence=0.98,
                reasoning=("Creator/analyst-supplied audience analytics, reproduced as "
                           "provided and not inferred by the engine."),
                evidence=[Evidence(claim="Top audience cities supplied from creator analytics",
                                   source_url=acc.url, collected_at=acc.collected_at,
                                   note="manual first-party input")],
                status=ClaimStatus.OBSERVED, method="manual first-party analytics")
    return None


def _cities(sig: Signals, tier: Distribution) -> Estimate:
    if sig.geo_terms:
        cities = sig.geo_terms[:8]
        why = ("Cities named in the creator's public titles, bio or keywords. These are "
               "content geographies, not a follower-location ranking.")
        conf = 0.70 if sig.geo_scope in ("city", "regional") else 0.55
        status = ClaimStatus.CALCULATED
    else:
        cities = []
        why = ("No creator-supplied city analytics were provided and no repeated place names "
               "were found. The engine does not invent a standard city list.")
        conf = 0.0
        status = ClaimStatus.UNAVAILABLE
    return Estimate(key="top_cities", value=cities, confidence=conf, reasoning=why,
                    status=status, method="public place-name extraction")


def _education(sig: Signals, arch: dict) -> Estimate:
    if sig.archetype == "generalist_creator":
        return Estimate(
            key="education", value="Unavailable", confidence=0.0,
            reasoning=("The collected content did not support a stable education-stage "
                       "classification. A generic creator prior is not audience evidence."),
            status=ClaimStatus.UNAVAILABLE,
            method="requires first-party analytics or a supported content-stage taxonomy")
    m = {
        "exam_prep_educator": "Content is most relevant to school students in the named class/stream; exact follower mix is unavailable",
        "admissions_desk": "Content is most relevant to school-leavers and undergraduate entrants; exact follower mix is unavailable",
        "entrance_mentor": "Content is most relevant to graduates, final-year students and early-career applicants; exact follower mix is unavailable",
        "career_finance_creator": "Content is most relevant to commerce students and early-career finance aspirants; exact follower mix is unavailable",
        "skill_educator": "Mixed graduate and working population; degree is largely irrelevant to the purchase",
        "generalist_creator": "Mixed; no single dominant educational profile",
    }[sig.archetype]
    return Estimate(key="education", value=m, confidence=max(0.35, arch["confidence"] - 0.16),
                    reasoning=("Read from the subject matter, since the content itself is only "
                               "useful to people at a specific educational stage. This is a "
                               "relevance hypothesis, not a measured demographic split."),
                    status=ClaimStatus.MODELLED,
                    method="content-stage relevance")


def _career(sig: Signals, arch: dict, age: Distribution) -> Estimate:
    if sig.archetype == "generalist_creator":
        return Estimate(
            key="career_stage", value="Unavailable", confidence=0.0,
            reasoning=("The collected content did not support a stable career-stage "
                       "classification. Career stage is therefore withheld."),
            status=ClaimStatus.UNAVAILABLE,
            method="requires first-party analytics or a supported content-stage taxonomy")
    m = {
        "exam_prep_educator": "School-stage learner; parents may influence purchases",
        "admissions_desk": "School-leaver or new undergraduate at an active admissions decision",
        "entrance_mentor": "Final-year student, fresher or early-career applicant",
        "career_finance_creator": "Student, fresher or early-career professional exploring finance careers",
        "skill_educator": "Student or working professional seeking a practical skill",
        "generalist_creator": "Mixed",
    }[sig.archetype]
    return Estimate(key="career_stage", value=m, confidence=max(0.35, arch["confidence"] - 0.20),
                    reasoning=("Derived from who the public content is useful to. Exact career-"
                               "stage shares require first-party analytics or survey data."),
                    status=ClaimStatus.MODELLED, method="content-stage relevance")


def _language(sig: Signals) -> Estimate:
    m = {
        "hindi": ("Hindi primary, regional language secondary, English confined to titles and "
                  "on-screen text"),
        "hinglish": "Hinglish primary, English in titles and thumbnails",
        "english": "English primary, with Hindi in spoken asides",
    }[sig.language]
    if sig.language_measured:
        why = ("Classified from Hindi/Hinglish markers in public titles, bio and keywords. "
               "This describes written metadata only; spoken delivery was not transcribed.")
        conf = 0.72
        status = ClaimStatus.CALCULATED
    else:
        m = "Spoken language unavailable; public metadata is predominantly English"
        why = ("English titles are common search metadata and do not establish spoken delivery. "
               "The engine needs a transcript or analyst observation to classify it.")
        conf = 0.0
        status = ClaimStatus.UNAVAILABLE
    return Estimate(key="language", value=m, confidence=conf, reasoning=why,
                    status=status, method="public metadata language markers")


def _interests(sig: Signals) -> list[dict]:
    pretty = {
        "board_exams": "Board exam preparation and revision",
        "commerce_subjects": "Commerce subjects (accountancy, economics, business studies)",
        "entrance_cat": "MBA entrance exams and B-school admissions",
        "entrance_gov": "Government service examinations",
        "cuet_admissions": "University admissions, merit lists and counselling",
        "finance_certifications": "Finance certifications (CFA, FRM, ACCA, CPA, CMA)",
        "careers_jobs": "Careers, jobs, internships and placement",
        "study_abroad": "Studying abroad and scholarships",
        "entrepreneurship": "Entrepreneurship and side income",
        "investing": "Investing and markets",
        "ai_tech": "AI and technology skills",
        "productivity": "Productivity, habits and motivation",
        "school_science": "School science stream and engineering/medical entrances",
        "creative_arts": "Creative arts, visual technique and process",
        "fitness_wellness": "Fitness, movement, nutrition and wellbeing",
        "beauty_style": "Beauty, skincare, fashion and styling",
        "food_cooking": "Food, recipes and cooking",
        "gaming": "Gaming, streams and competitive play",
        "travel": "Travel planning, destinations and experiences",
        "entertainment": "Entertainment, humour and personality-led content",
    }
    out = []
    for i, (topic, score) in enumerate(sig.topic_rank[:10], start=1):
        out.append({
            "rank": i,
            "topic": pretty.get(topic, topic.replace("_", " ").title()),
            "share": round(score * 100),
            "key": topic,
        })
    return out


def _psychographics(sig: Signals, arch: dict) -> dict[str, str]:
    base = {
        "exam_prep_educator": {
            "pain": "\"I can't follow this subject from my school teacher and the exam is close.\"",
            "emotion": "Exam fear compounded by overwhelm, and family expectation underneath it",
            "goal": "A high enough score to secure the next step",
            "fear": "Failing, and having to explain it",
            "buying": "Consumes only free content personally; converts on low-ticket items a parent pays for",
            "decision": "Trust-and-repeat — picks one teacher and stays for the whole academic year",
            "trigger": "A guaranteed, quantified return: \"this chapter is worth 15 marks\"",
        },
        "admissions_desk": {
            "pain": "\"The portal is confusing, nobody at home can explain it, and I might miss a deadline.\"",
            "emotion": "Urgency and confusion, escalating to panic in the later rounds",
            "goal": "A seat, preferably at a good government institution",
            "fear": "Losing the year",
            "buying": "Buys nothing from the creator, but makes a multi-lakh decision off the content",
            "decision": "Speed-driven — whoever explains the notification first wins",
            "trigger": "\"Last date is today.\"",
        },
        "entrance_mentor": {
            "pain": "\"I don't know if I'm good enough, and formal coaching costs more than I want to risk.\"",
            "emotion": "Anxiety layered over impostor syndrome",
            "goal": "Convert an attempt into an admit, and a salary step-change behind it",
            "fear": "Wasting a year; being rejected at the interview after clearing the exam",
            "buying": "Highly considered — researches the mentor, reads every testimonial, buys in steps",
            "decision": "Evidence-seeking; social proof is decisive",
            "trigger": "\"Someone like me did it.\"",
        },
        "career_finance_creator": {
            "pain": "\"My degree alone won't get me hired and I can't tell the certifications apart.\"",
            "emotion": "FOMO braided with aspiration",
            "goal": "A high-paying, ideally global career",
            "fear": "Buying a useless course; graduating with no offer; being automated out",
            "buying": "Free first, always; then mid-ticket only if a job outcome is attached",
            "decision": "Authority-following — credentials and brand names close the decision",
            "trigger": "\"You are already behind.\"",
        },
        "skill_educator": {
            "pain": "\"My current skills are going stale faster than I can refresh them.\"",
            "emotion": "Low-grade professional anxiety",
            "goal": "Stay employable and raise earning power",
            "fear": "Obsolescence",
            "buying": "Comparison-shops; wants a portfolio outcome, not a certificate",
            "decision": "Peer-proof driven",
            "trigger": "\"Here is what this skill pays.\"",
        },
    }.get(sig.archetype, {
        "pain": "Not enough signal in public content to characterise reliably",
        "emotion": "Mixed", "goal": "Mixed", "fear": "Mixed",
        "buying": "Mixed", "decision": "Mixed", "trigger": "Mixed",
    })
    # Public content can suggest a problem space, but it cannot reveal how followers buy,
    # what closes a decision, or whether a creative trigger works.
    base["buying"] = ("Purchase behaviour and willingness to pay are unavailable without "
                      "first-party transactions or tracked tests.")
    base["decision"] = ("Decision criteria are unavailable; treat authority, peer proof and "
                        "price as separate hypotheses to test.")
    base["trigger"] = f"Creative framing idea to test, not an observed response: {base['trigger']}"
    if sig.price_max and sig.price_min:
        base["buying"] += (f" Separately observed: the public offer ladder runs "
                           f"₹{int(sig.price_min):,} to ₹{int(sig.price_max):,}; no sales "
                           "volume was observed.")
    return {k: f"Hypothesis from content need: {v}" for k, v in base.items()}


def _vocabulary(sig: Signals) -> list[str]:
    words: list[str] = []
    corpus = sig.corpus.lower()

    def observed(term: str) -> bool:
        return bool(re.search(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)", corpus))

    for topic, _ in sig.topic_rank[:4]:
        # Topic lexicons supply candidates; only phrases actually present in the
        # collected bios/titles/keywords may be shown as observed vocabulary.
        words += [w for w in B.VOCAB_LEXICON.get(topic, []) if observed(w)]
    for phrase in ("one shot", "worth it", "marks", "roadmap", "strategy", "guarantee"):
        if observed(phrase) and phrase not in words:
            words.append(phrase)
    seen, out = set(), []
    for w in words:
        if w.lower() in seen:
            continue
        seen.add(w.lower())
        out.append(w)
    return out[:16]


def _behaviours(sig: Signals) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if sig.sub_to_view is not None:
        out.append({"label": "Median views / subscribers",
                    "value": f"{sig.sub_to_view * 100:.2f}%",
                    "note": ("Ratio of current-sample median public views to the current public "
                             "subscriber count. It is not unique reach, subscriber reach or a "
                             "pricing/conversion measure.")})
    if sig.recent_median_views and sig.top_views:
        out.append({"label": "Catalogue vs current",
                    "value": f"top {sig.top_views:,} views · recent median {sig.recent_median_views:,}",
                    "note": ("Describes collected lifetime-view totals only. Older items have "
                             "had more exposure time, so this is not a growth or decay measure.")})
    if sig.median_duration:
        mins = sig.median_duration // 60
        out.append({"label": "Median content length", "value": f"{mins} min {sig.median_duration % 60}s",
                    "note": "Read directly from published durations."})
    if sig.capture_channels:
        out.append({"label": "Routing / contact surfaces", "value": ", ".join(sig.capture_channels),
                    "note": ("Observed public destinations. A link page or storefront does not "
                             "by itself prove a permissioned or owned audience.")})
    if sig.proven_transactions:
        out.append({"label": "Public rating count", "value": f"{sig.proven_transactions} ratings",
                    "note": ("Observed social proof. The engine does not convert ratings into sales, "
                             "buyers or revenue without transaction data.")})
    if sig.platform_skew and len(sig.followers) > 1:
        out.append({"label": "Platform concentration",
                    "value": f"{round(sig.platform_skew * 100)}% of summed public follows on "
                             f"{sig.primary_platform}",
                    "note": ("Share of summed public account counts, not unique people; the same "
                             "person may follow on multiple platforms.")})
    return out


def _activation(sig: Signals, arch: dict, model: AudienceModel) -> list[dict[str, str]]:
    brand = (
        f"The largest collected public account is {sig.primary_platform or 'not established'}. "
        "Before buying, request first-party unique reach, geography, age, audience overlap and "
        "prior campaign outcomes for the intended placement window. Public views and follows "
        "are diligence inputs, not guaranteed delivery or conversion.")

    topics = ", ".join(t.replace("_", " ") for t, _ in sig.topic_rank[:3]) or "the observed topics"
    product = (
        f"Public content indicates a problem space around {topics}. Treat that as discovery input, "
        "not demand: run interviews, a tracked landing page and a priced offer test before "
        "building. Audience income, willingness to pay, buyer identity and sales volume are "
        "unavailable.")
    if sig.price_min and sig.price_max:
        product += (f" The observed public offer range is ₹{int(sig.price_min):,}–"
                    f"₹{int(sig.price_max):,}; no purchase count was observed.")

    creator = []
    if len(sig.followers) > 1 and sig.platform_skew > 0.85:
        weak = [p for p in sig.followers if p != sig.primary_platform]
        creator.append(f"The {weak[0]} account is much smaller by public follows; test its current "
                       "content reach and audience fit before allocating more resources.")
    creator.append("Verify whether an email or CRM-backed list exists; public links do not establish one.")
    if sig.series_attrition and sig.series_attrition > 0.5:
        creator.append("A measured series lost views across parts; test a consolidated version "
                       "against the next comparable series before changing the format.")
    if not creator:
        creator.append("Run a controlled content-format test; public history alone does not show causality.")

    return [
        {"who": "A brand buying media", "do": brand},
        {"who": "Building a product for this audience", "do": product},
        {"who": "Advising the creator", "do": " ".join(creator)},
    ]


def _unavailable(raw: RawProfile) -> list[dict[str, str]]:
    platforms = {a.platform for a in raw.accounts}
    ig = next((a for a in raw.accounts if a.platform == "instagram"), None)
    x_acc = next((a for a in raw.accounts if a.platform == "x"), None)
    li_acc = next((a for a in raw.accounts if a.platform == "linkedin"), None)

    out = [
        {"data": "Audience age, gender, city and income breakdowns",
         "why": ("These are private first-party analytics on every major platform. "
                 "Public bios and post titles can support a modelled life-stage band only "
                 "when content-stage evidence is strong — never a substitute for Insights."),
         "how": "Creator media kit, platform Insights export, or the analyst paste-form."},
        {"data": "Follower growth history",
         "why": "No public historical snapshot is available.",
         "how": "A paid analytics subscription with time-series data."},
    ]
    if ig is not None:
        out.insert(0, {
            "data": "Instagram post-level views, likes, saves and comments",
            "why": "Login-walled. Not obtainable by any external tool.",
            "how": "Creator-supplied Insights export, or the analyst paste-form in this tool.",
        })
    else:
        out.append({
            "data": "Instagram profile and post metrics",
            "why": "No Instagram account was collected for this subject.",
            "how": "Paste an Instagram profile URL as a seed, or ensure the handle is discoverable.",
        })
    if x_acc is not None:
        if not x_acc.content:
            out.append({
                "data": "X post-level engagement (views, likes, replies, reposts)",
                "why": "Full timeline metrics are not exposed to logged-out collectors.",
                "how": "X Analytics export from the creator, or a licensed firehose provider.",
            })
        if x_acc.followers is None:
            out.append({
                "data": "X follower count",
                "why": "Public syndication/HTML did not return a count for this handle.",
                "how": "Re-run with the browser tier on, or paste the count from the profile header.",
            })
    else:
        out.append({
            "data": "X (Twitter) profile",
            "why": "No X account was collected for this subject.",
            "how": "Paste https://x.com/{handle} as a seed or cohort line.",
        })
    if li_acc is not None:
        out.append({
            "data": "LinkedIn follower count and post engagement",
            "why": "LinkedIn authentication wall — only public meta tags are readable logged out.",
            "how": "Paste follower count / headline from a logged-in session, or Sales Navigator.",
        })
    elif "linkedin" not in platforms:
        out.append({
            "data": "LinkedIn profile",
            "why": "No LinkedIn account was collected (search hits stay gated to avoid stranger attribution).",
            "how": "Paste https://www.linkedin.com/in/{handle} as a seed when it is the subject's own URL.",
        })
    out.append({"data": "Revenue, enrolments and session volumes",
                "why": "Private commercial data.",
                "how": "Direct disclosure under NDA."})
    return out
