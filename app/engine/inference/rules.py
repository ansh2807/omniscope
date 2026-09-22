"""The rule engine — this is the product's actual IP.

A rule looks at the Signals and, if it fires, contributes a weighted opinion about one
audience dimension, together with the reasoning and evidence that justify it. The
combiner in engine.py blends every contribution against the archetype prior.

Design constraints deliberately imposed:
  * a rule may never invent a number without stating the observation behind it
  * weight  = how much this rule should move the posterior
  * conf    = how much this rule should raise our confidence in the result
  * every rule returns a `reasoning` string that is printed verbatim in the report

Adding a rule is the normal way to make the engine smarter. Keep them small and
independently defensible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.engine.inference import benchmarks as B
from app.engine.inference.signals import Signals


@dataclass
class Contribution:
    dimension: str                  # age | gender | tier | income | device | format | temperature
    buckets: dict[str, float]
    weight: float
    confidence: float
    reasoning: str
    rule_id: str = ""


@dataclass
class Callout:
    kind: str                       # insight | risk | opportunity | correction
    title: str
    body: str
    rule_id: str = ""


@dataclass
class Rule:
    id: str
    fn: Callable[[Signals], list[Contribution] | Contribution | None]
    about: str = ""


RULES: list[Rule] = []
CALLOUT_RULES: list[Callable[[Signals], Callout | None]] = []


def rule(rid: str, about: str = ""):
    def deco(fn):
        RULES.append(Rule(rid, fn, about))
        return fn
    return deco


def callout(fn):
    CALLOUT_RULES.append(fn)
    return fn


def _c(dim, buckets, weight, conf, why, rid=""):
    return Contribution(dim, buckets, weight, conf, why, rid)


# ============================================================== AGE
@rule("age.curriculum_lock", "School-syllabus content pins the audience to a school cohort")
def r_age_curriculum(s: Signals):
    if not s.curriculum_locked or s.archetype != "exam_prep_educator":
        return None
    return _c("age", {"15-17": 0.38, "18-20": 0.41, "21-24": 0.15, "25-30": 0.05, "31+": 0.01},
              weight=3.0, conf=0.82,
              why=("Content is a fixed school syllabus. Nobody outside the Class 11–12 cohort "
                   "has a reason to watch a multi-hour chapter revision, so the audience is "
                   "age-locked by the content itself."),
              rid="age.curriculum_lock")


@rule("age.admissions_window", "Admission-counselling content pins the audience to school-leavers")
def r_age_admissions(s: Signals):
    if s.archetype != "admissions_desk":
        return None
    return _c("age", {"15-17": 0.19, "18-20": 0.58, "21-24": 0.19, "25-30": 0.03, "31+": 0.01},
              weight=3.0, conf=0.85,
              why=("Merit lists, counselling rounds and admission-form walkthroughs are only "
                   "useful in the weeks between finishing school and taking a university seat."),
              rid="age.admissions_window")


@rule("age.entrance_workex", "Work-experience and gap-year products imply post-graduate ages")
def r_age_workex(s: Signals):
    terms = ("work ex", "work-ex", "gap year", "fresher", "experienced", "profile building")
    if not any(t in s.corpus for t in terms):
        return None
    return _c("age", {"15-17": 0.01, "18-20": 0.10, "21-24": 0.45, "25-30": 0.34, "31+": 0.10},
              weight=1.6, conf=0.68,
              why=("The creator sells products that address gap years, work-experience strategy "
                   "and fresher-versus-experienced positioning — all of which only make sense to "
                   "someone who has finished or is finishing a degree."),
              rid="age.entrance_workex")


@rule("age.first_year_content", "'After class 12' and first-year-internship content skews younger")
def r_age_firstyear(s: Signals):
    terms = ("after class 12", "after 12th", "1st year", "first year", "college student",
             "b.com vs", "bba vs")
    if not any(t in s.corpus for t in terms):
        return None
    return _c("age", {"15-17": 0.06, "18-20": 0.30, "21-24": 0.40, "25-30": 0.20, "31+": 0.04},
              weight=1.4, conf=0.64,
              why=("Titles target students choosing a degree or hunting a first internship, "
                   "which places the bulk of the audience in the undergraduate years."),
              rid="age.first_year_content")


# ============================================================== GENDER
@rule("gender.baseline", "Start from India's platform gender split")
def r_gender_base(s: Signals):
    return _c("gender", {"male": B.INDIA_IG_GENDER["male"], "female": B.INDIA_IG_GENDER["female"]},
              weight=1.0, conf=0.45,
              why=("India's Instagram user base is roughly 67% male / 33% female "
                   "(DataReportal, 2026). Every gender estimate starts from that baseline and "
                   "is adjusted by subject matter."),
              rid="gender.baseline")


@rule("gender.subject_skew", "Finance and technical subjects skew male; school subjects do not")
def r_gender_subject(s: Signals):
    fin = s.topic_scores.get("finance_certifications", 0) + s.topic_scores.get("investing", 0)
    school = s.topic_scores.get("board_exams", 0) + s.topic_scores.get("commerce_subjects", 0)
    if fin > 0.25:
        return _c("gender", {"male": 0.70, "female": 0.30}, 1.5, 0.60,
                  ("Finance-career and certification content reliably skews male, pushing this "
                   "audience slightly above the national baseline."),
                  "gender.subject_skew")
    if school > 0.30:
        return _c("gender", {"male": 0.54, "female": 0.46}, 1.5, 0.52,
                  ("School commerce and humanities streams enrol close to gender parity, which "
                   "offsets the platform's national male skew."),
                  "gender.subject_skew")
    return None


@rule("gender.female_creator", "A visible female creator lifts female audience share")
def r_gender_creator(s: Signals):
    fem = ("she ", " her ", "ms.", "mrs.", "woman", "women", "garba", "daughter")
    blob = (" ".join(s.testimonial_themes) + " " + s.bio_text + " " + " ".join(s.titles)).lower()
    hits = sum(blob.count(t) for t in fem)
    if hits < 4:
        return None
    return _c("gender", {"male": 0.58, "female": 0.42}, 1.4, 0.52,
              ("Evidence across the creator's own content and third-party testimonials indicates "
               "a female creator. In male-dominated categories this reliably pulls female "
               "audience share well above the platform baseline."),
              "gender.female_creator")


# ============================================================== CITY TIER
@rule("tier.language_register", "Hindi and Hinglish delivery extends reach beyond metros")
def r_tier_language(s: Signals):
    if s.language == "hindi":
        return _c("tier", {"tier_1": 0.30, "tier_2": 0.45, "tier_3": 0.25}, 1.8, 0.58,
                  ("Delivery is primarily in Hindi. That is the single strongest indicator of a "
                   "tier-2 and tier-3 weighted audience in the Indian creator market."),
                  "tier.language_register")
    if s.language == "hinglish":
        return _c("tier", {"tier_1": 0.42, "tier_2": 0.38, "tier_3": 0.20}, 1.3, 0.54,
                  ("Hinglish delivery broadens reach past the metros without losing the "
                   "English-medium, metro-coded segment."),
                  "tier.language_register")
    return _c("tier", {"tier_1": 0.55, "tier_2": 0.32, "tier_3": 0.13}, 1.2, 0.55,
              ("English-first delivery concentrates the audience in metros and large tier-2 "
               "cities, where the English-medium graduate base sits."),
              "tier.language_register")


@rule("tier.city_lock", "Single-city subject matter collapses the geography")
def r_tier_citylock(s: Signals):
    if s.geo_scope != "city":
        return None
    return _c("tier", {"tier_1": 0.34, "tier_2": 0.44, "tier_3": 0.22}, 2.2, 0.62,
              (f"Content is anchored to one city ({', '.join(s.geo_terms[:2]) or 'a single metro'}) "
               "and its immediate feeder towns. The tier mix follows that catchment rather than "
               "any national pattern."),
              "tier.city_lock")


# ============================================================== INCOME
@rule("income.price_ladder", "What the creator charges reveals what the audience can pay")
def r_income_price(s: Signals):
    if not s.price_max:
        return None
    if s.price_max >= 5000:
        return _c("income", {"0-5L": 0.29, "5-10L": 0.34, "10-20L": 0.27, "20-50L": 0.08, "50L+": 0.02},
                  1.8, 0.52,
                  (f"The creator successfully sells at up to ₹{int(s.price_max):,}. A price point "
                   "that high only clears against an employed adult or a committed parent budget, "
                   "which lifts the whole income distribution."),
                  "income.price_ladder")
    if s.price_max <= 1500:
        return _c("income", {"0-5L": 0.50, "5-10L": 0.30, "10-20L": 0.14, "20-50L": 0.05, "50L+": 0.01},
                  1.6, 0.50,
                  (f"The product ceiling is ₹{int(s.price_max):,}. Pricing that low is a direct "
                   "read on a price-sensitive, largely student audience."),
                  "income.price_ladder")
    return _c("income", {"0-5L": 0.42, "5-10L": 0.31, "10-20L": 0.19, "20-50L": 0.06, "50L+": 0.02},
              1.4, 0.48,
              (f"Products cluster between ₹{int(s.price_min or 0):,} and ₹{int(s.price_max):,}, "
               "a mid-market band consistent with students and early-career buyers."),
              "income.price_ladder")


@rule("income.free_first", "A free-first content model implies a low-budget audience")
def r_income_free(s: Signals):
    if s.corpus.count("free") < 4:
        return None
    return _c("income", {"0-5L": 0.47, "5-10L": 0.29, "10-20L": 0.17, "20-50L": 0.06, "50L+": 0.01},
              1.3, 0.48,
              ("The word 'free' recurs heavily across titles and bios. Creators lead with free "
               "when their audience has no money of its own — usually students, or children "
               "whose parents hold the budget."),
              "income.free_first")


# ============================================================== DEVICE
@rule("device.india_baseline", "Android share, adjusted for audience affluence")
def r_device(s: Signals):
    tier1_lean = s.language == "english"
    if tier1_lean:
        buckets = {"android": 0.86, "ios": 0.11, "desktop_tablet": 0.03}
        why = ("India runs 93–95% Android. This audience skews metro and affluent, which lifts "
               "iOS share several points above the national average.")
    elif s.language == "hindi":
        buckets = {"android": 0.95, "ios": 0.03, "desktop_tablet": 0.02}
        why = ("A Hindi-first, tier-2/3 weighted audience sits at or above India's already very "
               "high Android share.")
    else:
        buckets = {"android": 0.90, "ios": 0.07, "desktop_tablet": 0.03}
        why = "Sits close to the national Android/iOS split, with a small metro iOS tail."
    return _c("device", buckets, 1.5, 0.55, why, "device.india_baseline")


# ============================================================== FORMAT
@rule("format.observed_durations", "Actual published durations beat any assumption")
def r_format_durations(s: Signals):
    if s.long_form_share is None:
        return None
    lf = s.long_form_share
    buckets = {
        "short_form": max(0.05, 0.80 - lf * 0.75),
        "long_form": min(0.75, lf * 0.85 + 0.05),
        "carousel_static": 0.10,
        "text_chat": 0.07,
    }
    return _c("format", buckets, 2.4, 0.66,
              (f"{round(lf * 100)}% of the creator's measured video output runs over ten minutes. "
               "Format consumption is modelled from what they actually publish rather than from "
               "category assumptions."),
              "format.observed_durations")


# ============================================================== TEMPERATURE
@rule("temp.proven_buyers", "Public ratings do not establish audience temperature")
def r_temp_buyers(s: Signals):
    # Public ratings are social proof, not transaction records or evidence of an audience's
    # cold/warm/hot composition.
    return None


@rule("temp.attention_efficiency", "Views delivered per subscriber measures real engagement")
def r_temp_efficiency(s: Signals):
    if s.sub_to_view is None:
        return None
    r = s.sub_to_view
    if r >= 0.05:
        return _c("temperature", {"cold": 0.32, "warm": 0.44, "hot": 0.24}, 1.8, 0.58,
                  (f"Median recent public views equal {r * 100:.1f}% of the current subscriber "
                   "count. This does not identify unique viewers or subscriber reach, so it "
                   "cannot establish audience temperature."),
                  "temp.attention_efficiency")
    if r <= 0.01:
        return _c("temperature", {"cold": 0.72, "warm": 0.20, "hot": 0.08}, 1.8, 0.58,
                  (f"Median recent public views equal {r * 100:.2f}% of the current subscriber "
                   "count. This does not identify unique viewers or subscriber reach, so it "
                   "cannot establish whether the following is dormant."),
                  "temp.attention_efficiency")
    return None


# ============================================================== CALLOUTS
@callout
def co_view_decay(s: Signals):
    if s.decay_ratio is None or s.top_views is None or s.recent_median_views is None:
        return None
    subs = s.followers.get("youtube") or 0
    # Meaningless below a real subscriber base, and not a finding when the audience
    # that does exist is watching. Both gates matter.
    if subs < 5_000 or s.sub_to_view is None or s.sub_to_view > 0.03:
        return None
    if s.decay_ratio > 0.15:
        return None
    return Callout(
        "risk", "Recent lifetime-view totals are below older sampled uploads",
        (f"The median of recent dated uploads is {s.recent_median_views:,}, or "
         f"{s.decay_ratio * 100:.1f}% of the older dated-sample median. Older uploads have had "
         f"more time to accumulate views, so this ratio is descriptive—not a growth or decay "
         f"rate. The all-time top is "
         f"{s.top_views:,}, but the engine does not use that outlier as the decline baseline. Against "
         f"{s.followers.get('youtube', 0):,} subscribers that is a "
         f"{(s.sub_to_view or 0) * 100:.2f}% median-view-to-subscriber ratio, not unique "
         "subscriber reach. Request first-party recent reach before using it commercially."),
        "co.view_decay")


@callout
def co_platform_skew(s: Signals):
    if len(s.followers) < 2 or s.platform_skew < 0.85:
        return None
    weak = {p: n for p, n in s.followers.items() if p != s.primary_platform}
    if not weak:
        return None
    second, n2 = max(weak.items(), key=lambda kv: kv[1])
    n1 = s.followers[s.primary_platform]
    if n2 == 0:
        return None
    return Callout(
        "opportunity", f"Summed public follows are {n1 // max(n2, 1)}:1 skewed toward {s.primary_platform}",
        (f"{s.primary_platform.title()} contributes {n1:,} of {s.total_audience:,} summed public "
         "account follows (not unique people), "
         f"against {n2:,} on {second}. This establishes public distribution concentration, "
         "not platform quality or incremental reach. Validate current unique reach, audience "
         "fit and cost per outcome on both surfaces before changing resourcing."),
        "co.platform_skew")


@callout
def co_series_attrition(s: Signals):
    if s.series_attrition is None or s.series_attrition < 0.5:
        return None
    return Callout(
        "insight", "Later numbered parts carry lower sampled lifetime views",
        (f"Across the creator's collected numbered series, public lifetime view counts fall "
         f"{s.series_attrition * 100:.0f}% from part one to the last part. This does not "
         "measure the same viewers returning or prove that numbering caused the decline. Test "
         "a consolidated version against a comparable series before changing the format."),
        "co.series_attrition")


@callout
def co_price_ladder(s: Signals):
    if not s.price_points or len(s.price_points) < 3:
        return None
    lo, hi = int(min(s.price_points)), int(max(s.price_points))
    if hi / max(lo, 1) < 5:
        return None
    return Callout(
        "insight", "A public price ladder is already in place",
        (f"Products span ₹{lo:,} to ₹{hi:,} across {len(s.price_points)} observed SKUs. A spread "
         "that wide establishes multiple public offer levels. Buyer movement between levels, "
         "willingness to pay and conversion volume remain unavailable."),
        "co.price_ladder")


@callout
def co_no_owned_audience(s: Signals):
    if any(c in s.capture_channels for c in ("telegram", "whatsapp")):
        return None
    return Callout(
        "risk", "No permissioned contact channel observed",
        ("No public email list, Telegram or WhatsApp channel was found. A website, link page "
         "or storefront routes traffic but does not prove a contactable audience. Confirm CRM "
         "or list ownership directly before treating reach as reusable."),
        "co.no_owned_audience")


@callout
def co_seasonality(s: Signals):
    # Category calendars are useful hypotheses, not creator-specific audience measurements.
    # Measured seasonality is reconciled later from a sufficiently complete dated series.
    return None


@callout
def co_credentials(s: Signals):
    if len(s.press_signals) < 2 and not s.verified:
        return None
    bits = []
    if s.verified:
        bits.append("a verified account")
    if s.press_signals:
        bits.append(", ".join(sorted(set(s.press_signals))))
    return Callout(
        "insight", "Public identity and credential signals are available",
        (f"Public surfaces state {' plus '.join(bits)}. Verification is observed; speaking "
         "claims remain self-published unless an independent result is collected. These are "
         "diligence inputs, not proof of conversion."),
        "co.credentials")


@callout
def co_dormant_seed(s: Signals):
    seed_p = None
    for p, n in s.followers.items():
        if n and n < 5000 and s.total_audience > n * 5:
            seed_p = p
            break
    if not seed_p:
        return None
    return Callout(
        "correction", f"The {seed_p} account is not the largest public following",
        (f"The {seed_p} presence holds {s.followers[seed_p]:,} followers against "
         f"{s.total_audience:,} summed public follows. Analysing this creator through that "
         f"handle alone would omit the much larger {s.primary_platform} account; unique people "
         f"and cross-platform duplication remain unknown."),
        "co.dormant_seed")
