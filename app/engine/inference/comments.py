"""Comment analysis.

Turns raw public comments into the things the brief asks for: recurring questions, pain
points, repeated requests, sentiment split, buying intent, confusion, frustration,
community vocabulary and inside jokes.

Method is lexicon plus pattern matching rather than a language model, for three reasons:
it is auditable, it costs nothing per report, and it cannot hallucinate a sentiment that
is not in the text. Every category below carries example comments so a reader can check
the classifier's work.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field

from app.engine.collectors.comments import Comment

# ------------------------------------------------------------------ lexicons
POSITIVE = ["thank", "thanks", "thank you", "amazing", "best", "great", "helpful",
            "love", "awesome", "excellent", "superb", "respect", "gem", "lifesaver",
            "clear", "op ", "legend", "god", "bhagwan", "shukriya", "dhanyavad",
            "helped", "cleared", "understood", "samajh aaya", "mast", "badhiya"]
NEGATIVE = ["waste", "useless", "boring", "wrong", "bad", "worst", "hate", "scam",
            "fake", "misleading", "clickbait", "disappointed", "poor", "bekar",
            "galat", "faltu", "time waste", "not good", "didn't work", "doesn't work"]
CONFUSION = ["confused", "confusing", "didn't understand", "did not understand",
             "not clear", "unclear", "samajh nahi", "samajh nahin", "doubt", "doubts",
             "how does", "what is the difference", "which one", "kaunsa", "kya karu",
             "kya karun", "please explain", "explain again", "lost"]
FRUSTRATION = ["still not", "again and again", "no reply", "no response", "nobody",
               "frustrat", "stuck", "give up", "tired of", "fed up", "pareshan",
               "why is it so", "so difficult", "too hard", "can't find", "cannot find"]
BUYING_INTENT = ["how much", "price", "fees", "fee", "cost", "kitna", "kitne ka",
                 "where to buy", "how to buy", "how to join", "how to enroll",
                 "how to enrol", "link please", "link plz", "send link", "dm me",
                 "want to join", "want to buy", "is it worth", "worth it",
                 "discount", "coupon", "batch kab", "admission kaise", "purchase",
                 "sign up", "book a call", "consultation"]
REQUEST = ["please make", "plz make", "please do", "make a video", "video on",
           "can you make", "kindly make", "request", "next video", "please upload",
           "upload", "please cover", "banao", "bana do", "chahiye", "need a video"]
GRATITUDE_OUTCOME = ["cleared", "passed", "got selected", "got admission", "got the job",
                     "placed", "scored", "percentile", "rank", "converted", "admit",
                     "selected", "qualified", "cracked"]

QUESTION_RE = re.compile(r"[^.?!\n]{8,180}\?")
STOP = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "is", "are",
        "you", "your", "i", "me", "my", "it", "this", "that", "can", "do", "does",
        "please", "sir", "ma'am", "hai", "ka", "ki", "ke", "me", "mein", "se", "ko",
        "kya", "hi", "so", "very", "will", "be", "am", "we", "they", "he", "she",
        "but", "if", "not", "no", "yes", "thanks", "thank"}
TOKEN = re.compile(r"[a-z0-9']+")


@dataclass
class Bucket:
    label: str
    count: int
    share: int
    examples: list[str] = field(default_factory=list)
    ci_low: int | None = None
    ci_high: int | None = None


@dataclass
class CommentAnalysis:
    available: bool = False
    sample_size: int = 0
    videos_sampled: int = 0
    notes: list[str] = field(default_factory=list)

    sentiment: dict[str, int] = field(default_factory=dict)
    sentiment_examples: dict[str, list[str]] = field(default_factory=dict)
    buckets: list[Bucket] = field(default_factory=list)
    top_questions: list[dict] = field(default_factory=list)
    question_themes: list[Bucket] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)
    vocabulary: list[dict] = field(default_factory=list)
    inside_jokes: list[dict] = field(default_factory=list)
    outcome_reports: list[str] = field(default_factory=list)
    most_liked: list[dict] = field(default_factory=list)
    median_likes: int = 0
    unique_authors: int = 0
    author_coverage: int = 0
    top_author_share: int | None = None
    duplicate_rate: int = 0
    question_rate: int = 0
    sentiment_ci: dict[str, tuple[int, int]] = field(default_factory=dict)
    sample_read: str = ""
    read: str = ""


def _hits(text: str, terms: list[str]) -> bool:
    low = text.lower()
    for term in terms:
        term = term.lower()
        if " " in term or not term.isalnum():
            if term in low:
                return True
        elif re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", low):
            return True
    return False


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[int, int]:
    """95% Wilson score interval, reported as whole percentages."""
    if n <= 0:
        return 0, 0
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** .5) / den
    return round(max(0, centre - margin) * 100), round(min(1, centre + margin) * 100)


def _clean(t: str, limit: int = 190) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit] + ("…" if len(t) > limit else "")


def analyse(comments: list[Comment], *, notes: list[str] | None = None,
            creator_terms: list[str] | None = None) -> CommentAnalysis:
    ca = CommentAnalysis(notes=list(notes or []))
    if not comments:
        return ca

    ca.available = True
    ca.sample_size = len(comments)
    ca.videos_sampled = len({c.video_url for c in comments if c.video_url})
    ca.median_likes = int(statistics.median([c.likes for c in comments]))
    authors = [c.author.strip().lower() for c in comments if c.author and c.author.strip()]
    ca.unique_authors = len(set(authors))
    ca.author_coverage = round(len(authors) / len(comments) * 100)
    if authors:
        ca.top_author_share = round(max(Counter(authors).values()) / len(authors) * 100)
    normalised = [re.sub(r"\W+", " ", c.text.lower()).strip() for c in comments]
    ca.duplicate_rate = round((len(normalised) - len(set(normalised))) / len(normalised) * 100)
    ca.question_rate = round(sum("?" in c.text for c in comments) / len(comments) * 100)

    # ------------------------------------------------------------- sentiment
    pos = [c for c in comments if _hits(c.text, POSITIVE) and not _hits(c.text, NEGATIVE)]
    neg = [c for c in comments if _hits(c.text, NEGATIVE)]
    neu = [c for c in comments if c not in pos and c not in neg]
    n = len(comments)
    ca.sentiment = {
        "positive": round(len(pos) / n * 100),
        "neutral": round(len(neu) / n * 100),
        "negative": round(len(neg) / n * 100),
    }
    drift = 100 - sum(ca.sentiment.values())
    ca.sentiment["neutral"] += drift
    ca.sentiment_ci = {
        "positive": _wilson(len(pos), n),
        "neutral": _wilson(len(neu), n),
        "negative": _wilson(len(neg), n),
    }
    ca.sentiment_examples = {
        "positive": [_clean(c.text) for c in sorted(pos, key=lambda c: -c.likes)[:3]],
        "negative": [_clean(c.text) for c in sorted(neg, key=lambda c: -c.likes)[:3]],
        "neutral": [_clean(c.text) for c in sorted(neu, key=lambda c: -c.likes)[:2]],
    }

    # --------------------------------------------------------------- buckets
    for label, terms in [
        ("Buying intent", BUYING_INTENT),
        ("Confusion", CONFUSION),
        ("Frustration", FRUSTRATION),
        ("Content requests", REQUEST),
        ("Outcome reports", GRATITUDE_OUTCOME),
    ]:
        matched = [c for c in comments if _hits(c.text, terms)]
        if not matched:
            continue
        ca.buckets.append(Bucket(
            label=label, count=len(matched),
            share=round(len(matched) / n * 100),
            examples=[_clean(c.text) for c in sorted(matched, key=lambda c: -c.likes)[:4]],
            ci_low=_wilson(len(matched), n)[0],
            ci_high=_wilson(len(matched), n)[1],
        ))
    ca.buckets.sort(key=lambda b: -b.count)

    ca.requests = [_clean(c.text) for c in
                   sorted([c for c in comments if _hits(c.text, REQUEST)],
                          key=lambda c: -c.likes)[:8]]
    ca.outcome_reports = [_clean(c.text) for c in
                          sorted([c for c in comments if _hits(c.text, GRATITUDE_OUTCOME)],
                                 key=lambda c: -c.likes)[:6]]

    # ------------------------------------------------------------- questions
    qs: list[tuple[str, int]] = []
    for c in comments:
        for q in QUESTION_RE.findall(c.text):
            q = _clean(q)
            if len(q) > 12:
                qs.append((q, c.likes))
    qs.sort(key=lambda t: -t[1])
    ca.top_questions = [{"question": q, "likes": lk} for q, lk in qs[:15]]

    qtext = [q for q, _ in qs]
    for label, terms in [
        ("Eligibility and prerequisites", ["eligible", "eligibility", "can i", "am i",
                                           "after 12", "after graduation", "kar sakta",
                                           "kar sakti", "qualification"]),
        ("Cost and value", ["fees", "fee", "price", "cost", "kitna", "worth", "expensive",
                            "affordable", "free"]),
        ("Process and how-to", ["how to", "how do", "process", "steps", "kaise",
                                "procedure", "apply"]),
        ("Timing and deadlines", ["when", "last date", "kab", "deadline", "date",
                                  "how long", "duration", "time"]),
        ("Comparison and choice", [" vs ", "better", "which one", "difference between",
                                   "or ", "should i choose", "kaunsa"]),
        ("Outcome and career", ["job", "salary", "placement", "package", "career",
                                "scope", "future"]),
    ]:
        matched = [q for q in qtext if any(t in q.lower() for t in terms)]
        if matched:
            ca.question_themes.append(Bucket(
                label=label, count=len(matched),
                share=round(len(matched) / max(len(qtext), 1) * 100),
                examples=matched[:3],
            ))
    ca.question_themes.sort(key=lambda b: -b.count)

    # ------------------------------------------------------------ vocabulary
    creator_low = {t.lower() for t in (creator_terms or [])}
    counter: Counter = Counter()
    for c in comments:
        for w in TOKEN.findall(c.text.lower()):
            if len(w) < 3 or w in STOP:
                continue
            counter[w] += 1
    ca.vocabulary = [{"word": w, "count": k}
                     for w, k in counter.most_common(40) if k >= max(3, n // 60)][:24]

    # ------------------------------------------------------- inside jokes
    # Repeated short phrases the audience uses that the creator does not — the closest
    # measurable proxy for in-group language.
    phrase: Counter = Counter()
    for c in comments:
        toks = [t for t in TOKEN.findall(c.text.lower()) if t not in STOP and len(t) > 2]
        for i in range(len(toks) - 1):
            phrase[" ".join(toks[i:i + 2])] += 1
    for ph, k in phrase.most_common(60):
        if k < max(3, n // 50):
            continue
        if any(t in creator_low for t in ph.split()):
            continue
        ca.inside_jokes.append({"phrase": ph, "count": k})
        if len(ca.inside_jokes) >= 10:
            break

    ca.most_liked = [{"text": _clean(c.text, 240), "likes": c.likes,
                      "video": c.video_title[:70]}
                     for c in sorted(comments, key=lambda c: -c.likes)[:8]]

    # ------------------------------------------------------------------ read
    ca.sample_read = (
        f"The sample contains {ca.unique_authors:,} unique named authors; author metadata is "
        f"present on {ca.author_coverage}% of comments. Exact duplicate text is "
        f"{ca.duplicate_rate}% and the most frequent named author supplies "
        f"{ca.top_author_share if ca.top_author_share is not None else 0}% of authored rows. "
        "Intervals quantify sample precision only; relevance-ranked public comments are not a "
        "random sample of every viewer."
    )
    bits = []
    if ca.sentiment["positive"]:
        lo, hi = ca.sentiment_ci["positive"]
        bits.append(f"{ca.sentiment['positive']}% carry positive lexicon markers "
                    f"(95% Wilson interval {lo}–{hi}%)")
    if ca.question_themes:
        bits.append(f"the single largest question cluster is "
                    f"\"{ca.question_themes[0].label.lower()}\" at "
                    f"{ca.question_themes[0].share}% of extracted questions")
    intent = next((b for b in ca.buckets if b.label == "Buying intent"), None)
    if intent:
        bits.append(f"{intent.share}% contain buying-intent markers such as price, "
                    f"enrolment or link language; this is not conversion")
    conf = next((b for b in ca.buckets if b.label == "Confusion"), None)
    if conf and conf.share >= 8:
        bits.append(f"{conf.share}% contain confusion markers, creating a content hypothesis "
                    f"to validate")
    ca.read = ("Across " + f"{n:,} public comments: " + "; ".join(bits) + "."
               if bits else "")
    return ca
