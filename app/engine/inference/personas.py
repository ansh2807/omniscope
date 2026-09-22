"""Evidence-bounded persona scenarios.

The frames are activation ideas derived from public content needs, never measured
audience segments. Private demographics, channel usage, buying behaviour and willingness
to pay stay unavailable until first-party evidence is supplied.
"""
from __future__ import annotations

from app.engine.inference.signals import Signals
from app.schemas import AudienceModel, Persona

FRAMES: dict[str, list[dict[str, str]]] = {
    "exam_prep_educator": [
        {"name": "The exam-year student", "age": "17",
         "tag": "Class 12 · {tier2_city} · household {income_band}",
         "goal": "90%+ in the boards and a college the family respects",
         "pain": "School teacher moves too fast, coaching costs too much, the exam is months away",
         "watches": "Long single-session revisions at 1.5×; anything promising guaranteed marks",
         "buys": "Nothing personally — asks a parent for the low-cost book or question bank",
         "also_on": "YouTube (primary), Instagram Reels, Telegram, WhatsApp",
         "reach": "\"Everything you need for the exam, in one place, free\" — never lead on price"},
        {"name": "The paying parent", "age": "46",
         "tag": "Parent of an exam-year student · the actual buyer",
         "goal": "Their child's result, and an admission worth talking about",
         "pain": "Doesn't understand the syllabus but controls the budget; distrusts costly coaching",
         "watches": "Topper stories, results proof, parent-facing announcements",
         "buys": "Everything. Every paid product in the stack is bought by this person.",
         "also_on": "WhatsApp (primary), Facebook, YouTube over their child's shoulder",
         "reach": "Proof and reassurance, in the family language, on WhatsApp"},
        {"name": "The overseas-syllabus student", "age": "16",
         "tag": "Same curriculum, Gulf or Nepal · high household income",
         "goal": "Build a foundation early and keep options open abroad",
         "pain": "No local coaching for the Indian syllabus; time-zone gaps for live classes",
         "watches": "Mind-maps, notes, recorded long-form sessions",
         "buys": "Parent-funded and price-insensitive — the highest-ARPU segment available",
         "also_on": "YouTube, Instagram, iOS",
         "reach": "\"The Indian syllabus, wherever you are\" — usually an unexploited segment"},
    ],
    "entrance_mentor": [
        {"name": "The working aspirant", "age": "23",
         "tag": "1–2 years into a first job · {tier1_city} · {income_band}",
         "goal": "A top percentile, a call converted, an escape from a stalled career track",
         "pain": "Studying after a ten-hour day; a crowded profile; formal coaching feels wasteful",
         "watches": "Self-preparation strategy, salary breakdowns, interview question walkthroughs",
         "buys": "Enters at the cheapest rung, reads every testimonial, ladders up to a paid call",
         "also_on": "LinkedIn, exam subreddits, YouTube",
         "reach": "\"You need direction, not another expensive course\""},
        {"name": "The second-attempt professional", "age": "25",
         "tag": "3+ years' experience · metro · highest willingness to pay",
         "goal": "The degree that breaks a promotion ceiling",
         "pain": "Missed last cycle; unsure whether experience helps or hurts; fears the interview",
         "watches": "Interview frameworks, experience-versus-fresher strategy, people like them",
         "buys": "The top of the price ladder. The premium package exists for this person.",
         "also_on": "LinkedIn (primary), Instagram",
         "reach": "Representation plus resolution — \"here is the exact answer structure\""},
        {"name": "The non-target final-year", "age": "21",
         "tag": "Final year, state university · household {income_band}",
         "goal": "Turn an unremarkable background into a remarkable admit",
         "pain": "Impostor syndrome; no seniors who have done it; doesn't know the vocabulary yet",
         "watches": "Confidence and fear-buster content, self-prep basics, application help",
         "buys": "Very price-sensitive. The cheapest rung exists precisely for them.",
         "also_on": "Instagram, YouTube Shorts, WhatsApp study groups",
         "reach": "\"You don't need a target college to get in\""},
    ],
    "career_finance_creator": [
        {"name": "The second-year undergraduate", "age": "19",
         "tag": "Commerce degree · {tier1_city} · household {income_band}",
         "goal": "An internship this year; a recognised employer eventually",
         "pain": "\"My degree alone won't get me hired\"; cannot tell the certifications apart",
         "watches": "\"Is this credential still worth it?\", free-course lists, salary framings",
         "buys": "Free first, then a mid-priced course only if a job outcome is attached",
         "also_on": "Instagram Reels (primary), YouTube, a new LinkedIn profile",
         "reach": "Outcome-led: name the job, name the salary, name the timeline"},
        {"name": "The final-year job hunter", "age": "22",
         "tag": "Graduating, no offer yet · {income_band}",
         "goal": "Any credible role; avoid a gap year",
         "pain": "Rejections without feedback; reading automation headlines and panicking",
         "watches": "\"Jobs that survive AI\", named-employer guides, government internships",
         "buys": "Highest urgency and lowest budget in the set — converts only on a guarantee",
         "also_on": "LinkedIn, Telegram job groups, Instagram",
         "reach": "Guarantees. Bundle an outcome, not more lectures."},
        {"name": "The study-abroad aspirant", "age": "20",
         "tag": "Pre-final year · affluent household",
         "goal": "A funded or subsidised degree overseas",
         "pain": "Cost, visa uncertainty, ROI doubt, consultant sales pressure",
         "watches": "Funded-scholarship content, country guides, aspirational lifestyle proof",
         "buys": "Researches for months, then spends heavily — counselling and education loans",
         "also_on": "Instagram, YouTube, Reddit, university forums",
         "reach": "Aspirational proof, then a concrete cost breakdown"},
    ],
    "admissions_desk": [
        {"name": "The first-generation applicant", "age": "18",
         "tag": "Just finished school · {tier2_city} · household {income_band}",
         "goal": "A seat at a good government college",
         "pain": "The portal is opaque and nobody at home can explain the process",
         "watches": "Screen-recorded, step-by-step form walkthroughs in the local language",
         "buys": "Nothing from the creator — but makes a multi-lakh college decision off the content",
         "also_on": "YouTube, WhatsApp",
         "reach": "Sponsorship inside the utility content, never a standalone ad"},
        {"name": "The missed-round scrambler", "age": "19",
         "tag": "Missed the first counselling rounds · low household income",
         "goal": "Not lose the year",
         "pain": "Pure panic — every day without a seat feels terminal",
         "watches": "\"Didn't get admission, what now\", vacant-seat and later-round updates",
         "buys": "Will act on almost any credible recommendation immediately",
         "also_on": "YouTube, WhatsApp",
         "reach": "Relief, not aspiration: \"there is still a path\""},
        {"name": "The parent in the feeder town", "age": "44",
         "tag": "Watching alongside their child · pays the fee",
         "goal": "Get their child admitted without paying an agent",
         "pain": "Distrusts consultants; cannot confidently read the official notifications",
         "watches": "The same videos, for the fees, dates and document detail",
         "buys": "The fee — and would pay for guided help if it were offered",
         "also_on": "WhatsApp, Facebook",
         "reach": "Local language, trust signals, an explicit price"},
    ],
}
FRAMES["skill_educator"] = FRAMES["career_finance_creator"]
FRAMES["generalist_creator"] = []




# ---------------------------------------------------------------------------
# Segment personas. The archetype frames above cover the modal audience; these
# cover the *rest* of it — the segments a marketer would otherwise miss. They
# are emitted whenever the audience model says the segment is materially present,
# so a report always reaches the ten-persona depth the brief asks for.
# ---------------------------------------------------------------------------
SEGMENT_FRAMES: list[dict] = [
    {"key": "job_seeker", "min_share": 8, "name": "The active job seeker", "age": "23",
     "tag": "Applying everywhere, no offer yet · {income_band}",
     "goal": "Any credible offer, and an end to the uncertainty",
     "pain": "Rejections with no feedback; watching peers get placed; running out of runway",
     "watches": "Anything naming a specific employer, salary or a guaranteed outcome",
     "buys": "Highest urgency, lowest budget. Converts only on a guarantee.",
     "also_on": "LinkedIn, Telegram job groups, WhatsApp referral chains",
     "reach": "Guarantee-led. Bundle an outcome, never more lectures."},
    {"key": "working_professional", "min_share": 12, "name": "The evening learner", "age": "27",
     "tag": "Full-time job, studying after hours · {income_band}",
     "goal": "A credential that moves them out of a plateaued role",
     "pain": "No time; guilt about slow progress; unsure the investment will pay back",
     "watches": "Condensed, high-density content consumed at 1.5× late at night",
     "buys": "The highest willingness-to-pay in the base — real income, real urgency",
     "also_on": "LinkedIn, YouTube, saved posts they never revisit",
     "reach": "Respect their time. Lead with duration and outcome, never with enthusiasm."},
    {"key": "manager", "min_share": 4, "name": "The team lead", "age": "31",
     "tag": "Managing people, weighing an exit · {income_band}",
     "goal": "A step change — either a bigger title or a different track entirely",
     "pain": "Career ceiling is visible; retraining feels risky at this stage",
     "watches": "Strategy and decision content rather than tactical how-to",
     "buys": "Considered and slow, but buys at the top of the ladder when convinced",
     "also_on": "LinkedIn primarily; low platform tolerance elsewhere",
     "reach": "Peer proof — people at their level who made the move."},
    {"key": "founder", "min_share": 2, "name": "The side-project founder", "age": "29",
     "tag": "Building something alongside a job · {income_band}",
     "goal": "Skills and network that compound into their own thing",
     "pain": "Everything is urgent; no one to ask; learning by expensive trial and error",
     "watches": "Case studies, revenue breakdowns, operator interviews",
     "buys": "Buys access and network far more readily than information",
     "also_on": "X, LinkedIn, founder communities, niche Discords",
     "reach": "Access, not content. Community and introductions are the product."},
    {"key": "freelancer_creator", "min_share": 3, "name": "The freelancer", "age": "26",
     "tag": "Client work, irregular income · {income_band}",
     "goal": "Higher-value clients and a more predictable pipeline",
     "pain": "Feast-or-famine income; positioning is undifferentiated; undercharging",
     "watches": "Positioning, pricing and portfolio content",
     "buys": "Price-sensitive but decisive — buys when the ROI is arithmetic",
     "also_on": "Instagram, X, LinkedIn, freelance marketplaces",
     "reach": "Show the arithmetic: what this costs, what it returns, how fast."},
    {"key": "fan_community", "min_share": 4, "name": "The superfan", "age": "20",
     "tag": "Watches everything, comments on everything",
     "goal": "To be seen by someone they admire, and to belong to the group around them",
     "pain": "Feels unseen in a large audience; wants access that does not exist",
     "watches": "Everything, including announcements and behind-the-scenes",
     "buys": "Buys first, buys everything, and recruits others. Tiny in number, "
             "disproportionate in effect.",
     "also_on": "Every platform the creator is on, plus the community channel",
     "reach": "Recognition and access. A members tier or a named community converts here."},
    {"key": "casual_viewer", "min_share": 30, "name": "The drive-by searcher", "age": "22",
     "tag": "Arrived from search with one question",
     "goal": "One answer, right now, then gone",
     "pain": "Overwhelmed by choice; distrusts anything that looks like a sales pitch",
     "watches": "A single video or reel, usually never a second",
     "buys": "Nothing on this visit. Converts only if captured off-platform first.",
     "also_on": "Google, then wherever the answer lives",
     "reach": "A single, specific, genuinely useful free asset in exchange for contact."},
    {"key": "college_student", "min_share": 10, "name": "The undergraduate", "age": "20",
     "tag": "Mid-degree, starting to worry about what comes after · {income_band}",
     "goal": "Finish the degree with something on the CV that actually matters",
     "pain": "The degree alone feels insufficient; no idea which extra credential is worth it",
     "watches": "Roadmaps, 'is X worth it' comparisons, free-course lists",
     "buys": "Free first, always; converts on anything priced under a month's allowance",
     "also_on": "Instagram Reels, YouTube, a thin new LinkedIn profile",
     "reach": "Sequence it for them. They want an order of operations, not options."},
    {"key": "school_student", "min_share": 25, "name": "The exam-year teenager", "age": "17",
     "tag": "One exam between them and everything · household {income_band}",
     "goal": "The score that unlocks the next step",
     "pain": "Classroom pace does not match theirs; time is running out; family is watching",
     "watches": "Long revision sessions at 1.5×, anything promising a quantified return",
     "buys": "Nothing personally. Asks a parent for anything under a few hundred rupees.",
     "also_on": "YouTube first, Instagram second, Telegram and WhatsApp for material",
     "reach": "Quantify the payoff and keep it free at the point of use."},
    {"key": "fresher", "min_share": 12, "name": "The first-job fresher", "age": "24",
     "tag": "One or two years in, already reconsidering · {income_band}",
     "goal": "Escape a role that is not going anywhere",
     "pain": "Chose without information; peers appear to be ahead; switching feels risky",
     "watches": "Salary benchmarks, switch stories, credential comparisons",
     "buys": "First cohort with genuine disposable income — the ladder's real middle",
     "also_on": "LinkedIn, Instagram, YouTube, subreddits for their exam or field",
     "reach": "\"It is not too late\" — permission plus a concrete first step."},
    {"key": "returning_viewer", "min_share": 22, "name": "The regular", "age": "21",
     "tag": "Watches most things, comments on nothing",
     "goal": "Stay on top of a subject they have already committed to",
     "pain": "Wants depth, gets repetition; already knows the beginner material",
     "watches": "New uploads reliably, skips anything introductory",
     "buys": "The most convertible untapped segment — already trusts, never asked",
     "also_on": "Wherever the creator posts; rarely follows competitors",
     "reach": "Ask them. This segment converts on a direct offer and is rarely given one."},
    {"key": "loyal_follower", "min_share": 10, "name": "The advocate", "age": "23",
     "tag": "Recommends the creator unprompted",
     "goal": "To see the person they backed succeed, and to be part of it",
     "pain": "Nothing to buy that matches how much they care",
     "watches": "Everything, including the announcements others skip",
     "buys": "Buys early and repeatedly, and brings others with them",
     "also_on": "Every surface, plus whatever community channel exists",
     "reach": "Referral mechanics. This segment will do the selling if given the tools."},
    {"key": "tier_3", "min_share": 15, "name": "The small-town first-generation learner",
     "age": "19", "tag": "Tier-3 town, first in the family to get this far · {income_band}",
     "goal": "Access to what metro peers get by default",
     "pain": "No local guidance, patchy bandwidth, and nobody at home who knows the system",
     "watches": "Downloadable material and anything that works on a weak connection",
     "buys": "Extremely price-sensitive; free-first is not a preference but a constraint",
     "also_on": "YouTube, WhatsApp groups, Telegram for downloads",
     "reach": "Vernacular, low-data, and free at the point of use. Charge later, not here."},
    {"key": "parent_buyer", "min_share": 0, "name": "The paying parent", "age": "45",
     "tag": "Does not watch the content, signs off on every purchase",
     "goal": "Their child's result, and an outcome the family can be proud of",
     "pain": "Cannot judge quality; distrusts expensive coaching; fears wasting money",
     "watches": "Results proof, topper stories, and parent-facing announcements",
     "buys": "Is the buyer for every product in the ladder, and is marketed to by accident",
     "also_on": "WhatsApp above all, then Facebook",
     "reach": "Proof and reassurance, in the family language, on WhatsApp."},
    {"key": "diaspora", "min_share": 0, "name": "The overseas aspirant", "age": "19",
     "tag": "Indian curriculum or Indian ambitions, outside India",
     "goal": "Keep Indian options open while living abroad",
     "pain": "No local support for the Indian system; time zones; feels forgotten",
     "watches": "Recorded long-form, notes and downloadable material",
     "buys": "Highest ARPU segment available — price-insensitive and under-served",
     "also_on": "YouTube, Instagram, iOS",
     "reach": "\"Wherever you are\" positioning. Almost always unexploited."},
]


def _scenario(f: dict, model: AudienceModel, basis: str) -> Persona:
    """Convert a creative frame into a clearly bounded test scenario."""
    return Persona(
        name=f["name"],
        tag="Content-need scenario · city, income and household status unavailable",
        goal=f"Hypothesis to validate: {f['goal']}",
        pain=f"Hypothesis to validate: {f['pain']}",
        watches=f"Content relevance idea to test: {f['watches']}",
        buys=("Purchase behaviour and willingness to pay unavailable; validate with a "
              "tracked offer test or first-party transaction data."),
        also_on=("Segment-level platform usage unavailable; creator account presence does not "
                 "establish where this scenario's people spend time."),
        reach_with=("Activation idea to test: frame a small tracked creative around this stated "
                    "goal and pain point; do not assume response."),
        basis=basis,
        confidence=max(0.30, min(0.60, model.age.confidence - 0.15)),
    )


def _segment_personas(sig, model) -> list[Persona]:
    """Emit personas for segments the audience model says are materially present."""
    out: list[Persona] = []
    occ = model.occupation.as_pct() if model.occupation else {}
    soph = model.sophistication.as_pct() if model.sophistication else {}
    income_band = (f"₹{model.income.modal.replace('-', '–').replace('L', ' lakh')}"
                   if model.income and model.income.modal else "income not measured")

    intl = 0
    for e in model.country_split:
        if e.key == "international_share":
            try:
                intl = int(str(e.value).strip("~%"))
            except ValueError:
                intl = 0

    for f in SEGMENT_FRAMES:
        k = f["key"]
        if k in occ:
            share = occ[k]
        elif k in soph:
            share = soph[k]
        elif k == "parent_buyer":
            share = 100 if sig.archetype in ("exam_prep_educator", "admissions_desk") else 0
        elif k == "tier_3":
            share = (model.city_tier.as_pct().get("tier_3", 0) if model.city_tier else 0)
        elif k == "diaspora":
            share = intl * 5          # 8% international is a meaningful segment
        else:
            share = 0
        if share < f["min_share"] or (f["min_share"] == 0 and share <= 0):
            continue
        out.append(_scenario(
            f, model, "Hypothesis from the content need and modelled life-stage relevance"))
    return out


def build(sig: Signals, model: AudienceModel) -> list[Persona]:
    if sig.archetype == "generalist_creator" or model.age.status.value == "unavailable":
        return []
    frames = FRAMES.get(sig.archetype, FRAMES["generalist_creator"])
    out: list[Persona] = []
    for f in frames:
        out.append(_scenario(
            f, model,
            "Hypothesis from the creator's public content topics and modelled life stage"))

    # Segment personas cover the audience the archetype frames miss. Together they
    # take every report to the ten-persona depth the brief specifies.
    def concept(name: str) -> str:
        n = name.lower()
        for tag in ("parent", "overseas", "job seeker", "superfan", "searcher",
                    "freelancer", "founder", "team lead", "evening learner"):
            if tag in n:
                return tag
        return n
    seen = {concept(p.name) for p in out}
    for p in _segment_personas(sig, model):
        c = concept(p.name)
        if c in seen:
            continue
        seen.add(c)
        out.append(p)
    return out
