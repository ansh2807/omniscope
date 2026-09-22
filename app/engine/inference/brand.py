"""Brand analysis and SWOT.

Scores authority, trust and expertise from public-evidence inputs: credentials stated
in bios, third-party search results, verification badges, sampled outcome language,
public offer prices, and consistency of positioning across surfaces. The rubric does not
measure buyer perception, paid volume, campaign safety or commercial performance.

The SWOT is generated from the same evidence rather than written by hand, so it moves
when the underlying facts move.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

CREDENTIAL_PATTERNS = [
    (r"\biim\s+(?:ahmedabad|bangalore|calcutta|lucknow|kozhikode|indore)\b",
     "IIM affiliation stated in bio", 3),
    (r"\biit\s+(?:delhi|bombay|madras|kanpur|kharagpur|roorkee|guwahati)\b",
     "IIT affiliation stated in bio", 3),
    (r"\bcfa\s+(?:charterholder|charter holder)\b|\bchartered financial analyst\b",
     "CFA charterholder stated in bio", 3),
    (r"\bfrm\s+(?:certified|charterholder|charter holder)\b",
     "FRM credential stated in bio", 3),
    (r"\bchartered accountant\b", "Chartered Accountant stated in bio", 3),
    (r"\bacca\s+(?:member|qualified|affiliate)\b", "ACCA credential stated in bio", 2),
    (r"\bcpa\s+(?:licensed|qualified|certified)\b", "CPA credential stated in bio", 2),
    (r"\bmba\b", "MBA stated in bio", 2), (r"\bph\.?d\.?\b", "PhD stated in bio", 3),
    (r"\bex[- ](google|amazon|microsoft|mckinsey|bcg|deloitte|pwc|kpmg|ey)\b",
     "Ex-brand-name employer", 3),
    (r"\b(?:worked at|ex[- ])(?:big ?4|deloitte|pwc|kpmg|ey)\b",
     "Big 4 experience stated in bio", 2),
    (r"\bsebi[- ]registered\b", "SEBI registration stated in bio", 3),
]
PRESS_PATTERNS = [
    ("tedx", "TEDx", 3), ("josh talks", "Josh Talks", 2), ("yourstory", "YourStory", 2),
    ("humans of bombay", "Humans of Bombay", 2), ("forbes", "Forbes", 4),
    ("linkedin top voice", "LinkedIn Top Voice", 3),
    ("hindustan times", "Hindustan Times", 2), ("times of india", "Times of India", 2),
    ("economic times", "Economic Times", 3), ("shark tank", "Shark Tank", 4),
]
VOICE_AXES = {
    "Formal ↔ Casual": (["therefore", "furthermore", "kindly", "regards", "sir/madam"],
                        ["guys", "bhaiya", "yaar", "let's", "honestly", "tbh", "no cap"]),
    "Instructional ↔ Inspirational": (["step", "how to", "guide", "syllabus", "chapter",
                                       "formula", "process"],
                                      ["dream", "believe", "journey", "story", "mindset",
                                       "motivat", "struggle"]),
    "Cautious ↔ Bold": (["may", "might", "generally", "usually", "consider", "depends"],
                        ["guarantee", "fixed", "never", "always", "must", "only way",
                         "truth"]),
}


@dataclass
class Pillar:
    name: str
    score: int          # 0-10
    grade: str
    evidence: list[str] = field(default_factory=list)
    why: str = ""


@dataclass
class BrandAnalysis:
    pillars: list[Pillar] = field(default_factory=list)
    total: int = 0
    archetype_label: str = ""
    perception: str = ""
    personality: list[dict] = field(default_factory=list)
    voice: list[dict] = field(default_factory=list)
    promise: str = ""
    proof: list[str] = field(default_factory=list)
    consistency: str = ""
    swot: dict[str, list[str]] = field(default_factory=dict)
    position_x: float = 5.0     # public scale index (0-10)
    position_y: float = 5.0     # commercial-infrastructure evidence (0-10)
    position_note: str = ""


def _grade(v: int) -> str:
    return ("very strong" if v >= 9 else "strong" if v >= 7 else
            "moderate" if v >= 5 else "weak" if v >= 3 else "very weak")


def analyse(raw, sig, funnel, seo, content, comments) -> BrandAnalysis:
    ba = BrandAnalysis()
    corpus = sig.corpus
    credential_corpus = sig.bio_text

    # ------------------------------------------------------------- expertise
    creds, cred_pts = [], 0
    for rx, label, pts in CREDENTIAL_PATTERNS:
        if re.search(rx, credential_corpus, re.I):
            creds.append(label)
            cred_pts += pts
    verified_creds = list(creds)
    depth = 1 if len(sig.topic_rank) <= 4 and sig.topic_rank else 0
    publishing = 2 if content and content.measured_items >= 20 else 1 if content and \
        content.measured_items >= 8 else 0
    if publishing:
        creds.append(f"{content.measured_items} public content items analysed on the subject")
    exp_score = min(10, cred_pts + depth + publishing)
    ba.pillars.append(Pillar(
        "Expertise", exp_score, _grade(exp_score), creds,
        why=("Credentials are counted only when stated in a public bio; video topics and "
             "keywords are never treated as the creator's qualifications." if cred_pts else
             "No verifiable credential stated in any public bio. Expertise rests on the "
             "content alone, which is harder for a brand to due-diligence.")))

    # ------------------------------------------------------------- authority
    press, press_pts = [], 0
    for claimed in sig.press_signals:
        label = f"Claimed in bio: {claimed}"
        if label not in press:
            press.append(label)
            press_pts += 1
    for h in raw.search_hits[:40]:
        blob = f"{h.title} {h.snippet}".lower()
        for term, label, pts in PRESS_PATTERNS:
            if term in blob and label not in press:
                press.append(label)
                press_pts += pts
    auth = min(10, press_pts + (2 if sig.verified else 0)
               + (2 if sig.total_audience > 500_000 else 1 if sig.total_audience > 50_000 else 0))
    ba.pillars.append(Pillar(
        "Authority", auth, _grade(auth), press,
        why=("Independent search-result evidence scores more heavily than self-published "
             "speaker claims; verification and public reach are scored separately."
             if press or sig.verified else
             "No third-party press, stage or verification found. Authority is "
             "self-asserted, which is materially weaker in a due-diligence review.")))

    # ----------------------------------------------------------------- trust
    trust_ev, trust_pts = [], 0
    if sig.verified:
        trust_ev.append("Platform-verified account")
        trust_pts += 3
    ratings = (funnel.social_proof.get("ratings") if funnel else None) or 0
    if ratings:
        trust_ev.append(f"{ratings} public ratings (payment status not assumed)")
        trust_pts += 4 if ratings >= 25 else 2
    if funnel and funnel.social_proof.get("score"):
        trust_ev.append(f"{funnel.social_proof['score']}/5 average rating")
        trust_pts += 1
    if comments and comments.available:
        if comments.sentiment.get("positive", 0) >= 70:
            trust_ev.append(f"{comments.sentiment['positive']}% of {comments.sample_size:,} "
                            f"sampled public comments match positive lexicon markers")
            trust_pts += 2
        if comments.outcome_reports:
            trust_ev.append(f"{len(comments.outcome_reports)} unprompted audience reports "
                            f"of a concrete outcome")
            trust_pts += 2
    trust = min(10, trust_pts)
    ba.pillars.append(Pillar(
        "Trust", trust, _grade(trust), trust_ev,
        why=("Several public trust-rubric inputs were observed; buyer trust, brand lift and "
             "campaign safety still require direct evidence." if trust >= 6 else
             "Few public trust-rubric inputs were found. This identifies diligence questions, "
             "not a verdict on buyer trust or recommended deal structure.")))

    # ---------------------------------------------------------- distinctness
    distinct_ev, d_pts = [], 0
    if sig.geo_scope in ("city", "regional"):
        distinct_ev.append(f"Content repeatedly references a specific geography "
                           f"({', '.join(sig.geo_terms[:2])})")
        d_pts += 3
    if sig.curriculum_locked:
        distinct_ev.append("Content repeatedly serves a specific curriculum")
        d_pts += 3
    if content and content.catalogue_patterns:
        distinct_ev.append(f'Uses a recurring sampled title signature: '
                           f'"{content.catalogue_patterns[0].phrase}"')
        d_pts += 2
    if seo and seo.assessed and seo.collision_risk == "low":
        distinct_ev.append("Creator-controlled/platform properties are prominent in branded search")
        d_pts += 2
    elif seo and seo.assessed and seo.collision_risk == "severe":
        distinct_ev.append("Name collides with several unrelated entities in search")
        d_pts -= 1
    dis = max(0, min(10, d_pts + 2))
    ba.pillars.append(Pillar(
        "Distinctiveness", dis, _grade(dis), distinct_ev,
        why=("The public corpus contains several repeated positioning markers. Whether they "
             "are distinctive to buyers or hard to copy was not measured." if dis >= 6 else
             "Few distinctive public positioning markers were observed. Buyer perception and "
             "competitor substitutability were not measured.")))

    # ------------------------------------------------------------ consistency
    bios = [(a.display_name or "", a.bio) for a in raw.accounts if a.bio]
    if len(bios) >= 2:
        subject_tokens = set(re.findall(r"[a-z]{3,}", (raw.display_name or "").lower()))
        identity_matches = sum(
            1 for display, _ in bios
            if subject_tokens and subject_tokens & set(re.findall(r"[a-z]{3,}", display.lower())))
        cross_links = sum(1 for a in raw.accounts if a.external_links)
        cons = min(10, 4 + identity_matches + min(2, cross_links))
        ba.consistency = (
            f"Identity/name alignment was found on {identity_matches} of {len(bios)} bio-bearing "
            f"surfaces; {cross_links} surfaces publish cross-links. Bio wording is not expected "
            "to be identical across platforms, so lexical overlap is not used as an identity test.")
    else:
        cons = 5
        ba.consistency = ("Only one public bio was found, so cross-surface consistency "
                          "could not be measured.")
    ba.pillars.append(Pillar("Consistency", cons, _grade(cons), [], why=ba.consistency))

    ba.total = sum(p.score for p in ba.pillars)

    # ------------------------------------------------------- voice and tone
    for axis, (left, right) in VOICE_AXES.items():
        l = sum(corpus.count(t) for t in left)
        r = sum(corpus.count(t) for t in right)
        if l + r == 0:
            continue
        pos = round(r / (l + r) * 100)
        ba.voice.append({"axis": axis, "position": pos,
                         "reads": axis.split(" ↔ ")[1 if pos >= 55 else 0]})

    traits = []
    for label, terms in [
        ("Reassuring", ["don't worry", "easy", "simple", "step by step", "anyone can"]),
        ("Urgent", ["last date", "today", "hurry", "deadline", "now", "limited"]),
        ("Aspirational", ["lakh", "lpa", "package", "dream", "abroad", "topper", "rank"]),
        ("Blunt", ["truth", "reality", "no nonsense", "honest", "stop", "waste"]),
        ("Generous", ["free", "download", "no cost", "sharing", "resources"]),
        ("Credential-led", ["iim", "iit", "cfa", "frm", "tedx", "big 4"]),
    ]:
        hits = sum(corpus.count(t) for t in terms)
        if hits:
            traits.append({"trait": label, "hits": hits})
    total_traits = sum(t["hits"] for t in traits) or 1
    traits.sort(key=lambda d: -d["hits"])
    ba.personality = [{"trait": t["trait"], "share": round(t["hits"] / total_traits * 100)}
                      for t in traits[:5]]

    # ------------------------------------------------------ promise and proof
    top_pillar = max(ba.pillars, key=lambda p: p.score)
    ba.promise = _promise(sig, funnel)
    if verified_creds:
        ba.proof.append("Credentials stated in public bios: " + ", ".join(verified_creds))
    if press:
        ba.proof.append("Third-party stage: " + ", ".join(press))
    if ratings:
        ba.proof.append(f"{ratings} public ratings; paid transaction count unavailable")
    if content and content.top_views:
        ba.proof.append(f"A public content item with {content.top_views:,} views (not unique reach)")
    if comments and comments.outcome_reports:
        ba.proof.append("Unprompted audience reports of concrete outcomes in the comments")
    if not ba.proof:
        ba.proof.append("No externally verifiable proof point found in the collected sample.")

    ba.perception = (
        f"Strongest as {top_pillar.name.lower()} ({top_pillar.score}/10); weakest as "
        f"{min(ba.pillars, key=lambda p: p.score).name.lower()}. "
        "These are internal public-evidence rubric scores, not measured buyer perception, "
        "brand lift, safety or campaign performance.")

    # ----------------------------------------------------------- positioning
    aud = sig.total_audience or 1
    ba.position_x = max(0.5, min(9.5, (math.log10(max(aud, 1)) - 3) / 4 * 9))
    transact = 1.0
    if funnel:
        transact += min(3.0, len(funnel.rungs) * .6)
        transact += 1.5 if funnel.routing_surfaces else 0
        transact += 1.5 if funnel.permissioned_channels else 0
        transact += 1.5 if funnel.owned_audience else 0
    ba.position_y = max(0.5, min(9.5, transact))
    ba.position_note = (
        f"Public-scale index {ba.position_x:.1f}/10 from log10 summed public follows; "
        f"commercial-infrastructure index {ba.position_y:.1f}/10 from observed offers, "
        "routing and permissioned/owned channels. Neither axis measures audience quality, "
        "conversion or brand position in buyers' minds.")

    ba.swot = _swot(sig, funnel, seo, content, comments, ba)
    return ba


def _promise(sig, funnel) -> str:
    arch = {
        "exam_prep_educator": "\"I will get you the marks.\"",
        "entrance_mentor": "\"I will turn your attempt into an admit.\"",
        "career_finance_creator": "\"I will make you employable.\"",
        "admissions_desk": "\"I will not let you miss the deadline.\"",
        "skill_educator": "\"I will make you employable in a new skill.\"",
        "generalist_creator": "No single implicit promise is legible from the public content.",
    }.get(sig.archetype, "")
    arch = "Inferred messaging promise from recurring public content framing: " + arch
    if funnel and funnel.price_max:
        arch += f" A public offer is listed up to ₹{int(funnel.price_max):,}; sales are unavailable."
    return arch


def _swot(sig, funnel, seo, content, comments, ba) -> dict[str, list[str]]:
    S, W, O, T = [], [], [], []

    if sig.verified:
        S.append("A platform verification badge was observed; identity and campaign claims "
                 "still require normal diligence.")
    if sig.press_signals:
        S.append("Public bios contain speaking/stage claims: " +
                 ", ".join(sig.press_signals) +
                 ". Treat as self-published unless the appendix cites an independent source.")
    if funnel and funnel.social_proof.get("ratings", 0) >= 25:
        S.append(f"{funnel.social_proof['ratings']} public ratings — strong social proof, "
                 f"without assuming each rating is a paid transaction.")
    if content and content.catalogue_patterns:
        S.append(f'"{content.catalogue_patterns[0].phrase}" appears in a measured title '
                 f'pattern; its association with views is not causal.')
    if sig.curriculum_locked:
        S.append("The observed content is curriculum-locked, which defines a precise content "
                 "use case; follower composition remains private.")
    if sig.total_audience > 300_000:
        S.append(f"{sig.total_audience:,} summed public follows indicate distribution scale, "
                 "with cross-platform duplication and unique reach unknown.")
    if comments and comments.available and comments.sentiment.get("positive", 0) >= 70:
        S.append(f"{comments.sentiment['positive']}% positive comment sentiment across "
                 f"{comments.sample_size:,} public comments.")

    if funnel and not funnel.owned_audience:
        W.append("No verified first-party audience list was observed. Public websites, "
                 "storefronts and messaging links are routing surfaces, not proof of a "
                 "portable email or CRM audience.")
    if content and content.sub_to_view is not None and content.sub_to_view < 0.02:
        W.append(f"Median current-sample views equal {content.sub_to_view*100:.2f}% of the "
                 f"public subscriber count. This ratio does not identify unique viewers, "
                 f"subscriber reach or follower activity.")
    if len(sig.followers) > 1 and sig.platform_skew > 0.85:
        weak = [p for p in sig.followers if p != sig.primary_platform]
        W.append(f"{round(sig.platform_skew*100)}% of summed public follows are on "
                 f"{sig.primary_platform}; {weak[0]} has the smaller public count. Unique "
                 "people, reach and duplication are unknown.")
    if seo and seo.assessed and seo.collision_risk == "severe":
        W.append("Severe name collision in search — several unrelated entities outrank "
                 "or crowd the creator's own name.")
    if funnel and funnel.spread and funnel.spread < 3:
        W.append("Observed public prices are tightly clustered; whether buyers want a lower "
                 "trial or higher tier was not measured.")
    if content and content.series_attrition and content.series_attrition > 0.5:
        W.append(f"Public view counts fell {round(content.series_attrition*100)}% from the first "
                 f"to final sampled series part. This is not unique-viewer retention.")
    if not any(p.name == "Expertise" and p.score >= 5 for p in ba.pillars):
        W.append("No verifiable credential stated publicly.")

    if seo and seo.assessed and seo.intent_clusters:
        top = seo.intent_clusters[0]
        O.append(f"\"{top['cluster']}\" is a topic/intent cluster in the collected content. "
                 f"Search volume is unavailable; validate demand before investing in it.")
    if comments and comments.available and comments.question_themes:
        q = comments.question_themes[0]
        O.append(f"{q.share}% of classified questions in the collected comment sample cluster "
                 f"on \"{q.label.lower()}\". Test whether it represents broader demand.")
    if comments and comments.available:
        intent = next((b for b in comments.buckets if b.label == "Buying intent"), None)
        if intent and intent.share >= 5:
            O.append(f"{intent.share}% of the collected comment sample mentions price, "
                     f"enrolment or links. Conversion and whether an offer answered it are unknown.")
    if sig.archetype in ("exam_prep_educator", "admissions_desk"):
        O.append("The content need is tied to an annual exam/admission transition. Test a "
                 "bridge product for the following stage rather than assuming cohort retention.")
    if content and content.promo_gap and content.promo_gap > 0.5:
        O.append("In the collected sample, promotional titles are associated with lower views. "
                 "Test integrated placements; the title association is not causal proof.")
    if funnel and funnel.price_max and funnel.price_max < 2000:
        O.append("The public offer ceiling is below ₹2,000. Test willingness to pay before "
                 "adding a higher tier; public pricing does not reveal demand.")

    T.append("Category hypothesis to monitor: paid platforms may compete for the same topic "
             "attention; no ad-spend comparison was collected in this report.")
    if sig.archetype in ("exam_prep_educator", "admissions_desk", "entrance_mentor"):
        T.append("Total dependence on exam and admission calendars set by third parties.")
        T.append("Regulatory tightening on coaching and edtech advertising claims.")
    if content and content.decay_ratio and content.decay_ratio < 0.15:
        T.append("Recent dated-sample lifetime views are below the older dated-sample median. "
                 "Exposure age differs, so this is not a measured reach decline and the cause "
                 "cannot be assigned.")
    if content and content.promo_gap and content.promo_gap > 0.4:
        T.append("Promotional titles have lower views in the collected sample. Treat this as "
                 "an association to test, not measured audience ad-blindness.")
    T.append("Category hypothesis to monitor: generative content may increase competition in "
             "free educational topics; this report did not measure that market effect.")

    return {"strengths": S[:7], "weaknesses": W[:7],
            "opportunities": O[:7], "threats": T[:6]}
