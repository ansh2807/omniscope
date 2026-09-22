"""Reference data the inference engine reasons against.

Everything here is a *prior*. Rules in rules.py move the posterior away from these
numbers when creator-specific evidence justifies it. Update the constants when the
underlying market data is refreshed and re-run — the whole engine shifts with it.
"""
from __future__ import annotations

# ---------------------------------------------------------------- market priors
# DataReportal / Hootsuite, India, 2026.
INDIA_IG_GENDER = {"male": 0.672, "female": 0.328}
INDIA_DEVICE = {"android": 0.94, "ios": 0.04, "desktop_tablet": 0.02}
INDIA_TIER = {"tier_1": 0.38, "tier_2": 0.37, "tier_3": 0.25}

# Instagram engagement-rate bands (education/how-to niche, 2026).
ENGAGEMENT_BANDS = [
    (0,       10_000,   0.040, 0.060),
    (10_000,  100_000,  0.025, 0.040),
    (100_000, 500_000,  0.015, 0.028),
    (500_000, 10**9,    0.008, 0.018),
]
REEL_VS_STATIC_MULTIPLIER = 3.2

AGE_BUCKETS = ["15-17", "18-20", "21-24", "25-30", "31+"]
INCOME_BUCKETS = ["0-5L", "5-10L", "10-20L", "20-50L", "50L+"]
TIER_BUCKETS = ["tier_1", "tier_2", "tier_3"]
FORMAT_BUCKETS = ["short_form", "long_form", "carousel_static", "text_chat"]
TEMP_BUCKETS = ["cold", "warm", "hot"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# ------------------------------------------------------------------- lexicons
# Topic -> trigger terms. Matched against bios, channel keywords and content titles.
TOPIC_LEXICON: dict[str, list[str]] = {
    "board_exams": ["class 12", "class 11", "cbse", "boards", "board exam", "one shot",
                    "revision", "ncert", "compartment", "sample paper", "pyq"],
    "commerce_subjects": ["accountancy", "accounts", "business studies", "economics",
                          "macro economics", "partnership", "goodwill", "cash flow",
                          "b.com", "bba", "commerce"],
    "entrance_cat": ["cat exam", "cat 2", "iim", "mba", "percentile", "varc", "dilr",
                     "gdpi", "wat", "fms", "xat", "snap", "b-school", "bschool"],
    "entrance_gov": ["upsc", "ssc", "ias", "ips", "cgl", "banking exam", "rrb"],
    "cuet_admissions": ["cuet", "srcc", "du admission", "merit list", "counselling",
                        "cut off", "cutoff", "allotment", "willingness form", "seat",
                        "admission form", "pucet", "usol", "cdoe", "dhe"],
    "finance_certifications": ["cfa", "frm", "acca", "cpa", "cma", "nism", "ncfm",
                               "financial modeling", "financial modelling", "fmva", "ca "],
    "careers_jobs": ["career", "job", "jobs", "internship", "intern", "placement",
                     "resume", "cv", "interview", "salary", "package", "lpa", "big 4",
                     "hiring", "recruit"],
    "study_abroad": ["study abroad", "scholarship", "fully funded", "masters abroad",
                     "ielts", "gre", "visa", "uk", "canada", "germany", "ireland"],
    "entrepreneurship": ["startup", "founder", "business idea", "side hustle",
                         "freelance", "entrepreneur"],
    "investing": ["stock market", "invest", "trading", "mutual fund", "portfolio",
                  "sip", "crypto", "fd "],
    "ai_tech": ["ai", "artificial intelligence", "chatgpt", "coding", "python",
                "data science", "machine learning", "prompt", "llm", "rag",
                "fastapi", "react", "ai agent", "automation"],
    "productivity": ["productivity", "habit", "discipline", "time management",
                     "motivation", "mindset"],
    "school_science": ["neet", "jee", "physics", "chemistry", "biology", "iit"],
    # Open-domain topics improve report differentiation, but do not map to a private
    # age/life-stage prior. They remain general-creator content classifications.
    "creative_arts": ["watercolour", "watercolor", "painting", "sketchbook", "drawing",
                      "illustration", "portrait", "brush", "canvas", "photography"],
    "fitness_wellness": ["workout", "fitness", "protein", "mobility", "fat loss",
                         "strength", "cardio", "yoga", "nutrition", "meal prep"],
    "beauty_style": ["skincare", "makeup", "fashion", "outfit", "haircare", "beauty",
                     "serum", "foundation", "styling"],
    "food_cooking": ["recipe", "cooking", "kitchen", "baking", "ingredients", "meal",
                     "restaurant", "street food"],
    "gaming": ["gameplay", "gaming", "esports", "walkthrough", "stream", "minecraft",
               "valorant", "bgmi"],
    "travel": ["travel", "itinerary", "hotel", "flight", "backpacking", "destination",
               "road trip", "tour"],
    "entertainment": ["comedy", "sketch", "reaction", "vlog", "prank", "roast",
                      "behind the scenes"],
}

# Candidate content-language phrases. The engine emits only candidates actually observed
# in collected bios/titles/keywords; they do not establish how followers speak.
VOCAB_LEXICON: dict[str, list[str]] = {
    "board_exams": ["one shot", "marks fixed", "sure shot", "revision", "backlog",
                    "boards", "compartment", "PYQ", "sir"],
    "entrance_cat": ["percentile", "VARC", "DILR", "converts", "calls", "WAT-GD-PI",
                     "profile", "work-ex", "gap year", "SOP", "non-target", "mocks"],
    "cuet_admissions": ["merit list", "counselling", "willingness form", "cut-off",
                        "seat", "allotment", "last date", "vacant seats"],
    "finance_certifications": ["worth it", "scope", "fees", "eligibility", "roadmap"],
    "careers_jobs": ["package", "LPA", "Big 4", "stipend", "off-campus", "placement"],
    "study_abroad": ["fully funded", "scholarship", "IELTS", "SOP", "visa", "PR"],
    "investing": ["returns", "SIP", "portfolio", "market"],
}

HINDI_MARKERS = ["kya", "kaise", "hai", "nahi", "aur", "karo", "kare", "ke liye",
                 "sabse", "puri", "jankari", "bhaiya", "yodha", "जानकारी", "कैसे",
                 "क्या", "में", "और"]

CITY_TIER_1 = ["Delhi NCR", "Mumbai", "Bengaluru", "Hyderabad", "Chennai",
               "Pune", "Kolkata", "Ahmedabad"]
CITY_TIER_2 = ["Lucknow", "Jaipur", "Indore", "Bhopal", "Patna", "Kanpur",
               "Nagpur", "Chandigarh", "Coimbatore", "Ranchi"]


# ------------------------------------------------------------------ archetypes
# Historical archetype reference shapes. The current truth contract does not emit these
# private demographic priors as creator-specific measurements.
ARCHETYPES: dict[str, dict] = {
    "exam_prep_educator": {
        "label": "School exam-prep educator",
        "topics": ["board_exams", "commerce_subjects", "school_science"],
        "age": {"15-17": 0.36, "18-20": 0.40, "21-24": 0.16, "25-30": 0.06, "31+": 0.02},
        "income": {"0-5L": 0.42, "5-10L": 0.33, "10-20L": 0.17, "20-50L": 0.06, "50L+": 0.02},
        "tier": {"tier_1": 0.28, "tier_2": 0.42, "tier_3": 0.30},
        "format": {"short_form": 0.24, "long_form": 0.60, "carousel_static": 0.07, "text_chat": 0.09},
        "temperature": {"cold": 0.58, "warm": 0.30, "hot": 0.12},
        "gender_male": 0.56,
        "seasonality": [92, 100, 95, 45, 60, 55, 35, 30, 35, 55, 80, 90],
        "confidence": 0.80,
        "one_liner": "School students working through a fixed syllabus against a hard exam date",
        "buyer": "parent",
    },
    "entrance_mentor": {
        "label": "Competitive-entrance mentor",
        "topics": ["entrance_cat", "entrance_gov"],
        "age": {"15-17": 0.02, "18-20": 0.13, "21-24": 0.45, "25-30": 0.31, "31+": 0.09},
        "income": {"0-5L": 0.31, "5-10L": 0.33, "10-20L": 0.26, "20-50L": 0.08, "50L+": 0.02},
        "tier": {"tier_1": 0.52, "tier_2": 0.33, "tier_3": 0.15},
        "format": {"short_form": 0.58, "long_form": 0.12, "carousel_static": 0.24, "text_chat": 0.06},
        "temperature": {"cold": 0.62, "warm": 0.28, "hot": 0.10},
        "gender_male": 0.62,
        "seasonality": [75, 80, 70, 55, 30, 25, 35, 70, 85, 95, 90, 45],
        "confidence": 0.70,
        "one_liner": "Graduates and early-career professionals deciding whether to bet a year on an entrance exam",
        "buyer": "self",
    },
    "career_finance_creator": {
        "label": "Career & certification creator",
        "topics": ["finance_certifications", "careers_jobs", "study_abroad"],
        "age": {"15-17": 0.04, "18-20": 0.22, "21-24": 0.40, "25-30": 0.27, "31+": 0.07},
        "income": {"0-5L": 0.45, "5-10L": 0.28, "10-20L": 0.18, "20-50L": 0.07, "50L+": 0.02},
        "tier": {"tier_1": 0.47, "tier_2": 0.36, "tier_3": 0.17},
        "format": {"short_form": 0.54, "long_form": 0.27, "carousel_static": 0.13, "text_chat": 0.06},
        "temperature": {"cold": 0.70, "warm": 0.22, "hot": 0.08},
        "gender_male": 0.68,
        "seasonality": [55, 55, 60, 75, 80, 85, 80, 70, 65, 60, 55, 50],
        "confidence": 0.68,
        "one_liner": "Undergraduates and freshers shopping for the credential that will get them hired",
        "buyer": "self",
    },
    "admissions_desk": {
        "label": "Admissions & counselling desk",
        "topics": ["cuet_admissions"],
        "age": {"15-17": 0.18, "18-20": 0.57, "21-24": 0.20, "25-30": 0.04, "31+": 0.01},
        "income": {"0-5L": 0.53, "5-10L": 0.29, "10-20L": 0.13, "20-50L": 0.04, "50L+": 0.01},
        "tier": {"tier_1": 0.33, "tier_2": 0.44, "tier_3": 0.23},
        "format": {"short_form": 0.20, "long_form": 0.68, "carousel_static": 0.05, "text_chat": 0.07},
        "temperature": {"cold": 0.31, "warm": 0.44, "hot": 0.25},
        "gender_male": 0.54,
        "seasonality": [12, 12, 15, 25, 45, 95, 100, 90, 70, 25, 15, 12],
        "confidence": 0.82,
        "one_liner": "School-leavers mid-admission, racing a counselling deadline",
        "buyer": "parent",
    },
    "skill_educator": {
        "label": "Skills & upskilling educator",
        "topics": ["ai_tech", "entrepreneurship", "productivity"],
        "age": {"15-17": 0.03, "18-20": 0.18, "21-24": 0.35, "25-30": 0.32, "31+": 0.12},
        "income": {"0-5L": 0.32, "5-10L": 0.30, "10-20L": 0.24, "20-50L": 0.11, "50L+": 0.03},
        "tier": {"tier_1": 0.55, "tier_2": 0.32, "tier_3": 0.13},
        "format": {"short_form": 0.56, "long_form": 0.24, "carousel_static": 0.14, "text_chat": 0.06},
        "temperature": {"cold": 0.68, "warm": 0.24, "hot": 0.08},
        "gender_male": 0.64,
        "seasonality": [65, 65, 65, 70, 70, 70, 70, 70, 70, 70, 65, 60],
        "confidence": 0.60,
        "one_liner": "Working professionals and students buying skills rather than degrees",
        "buyer": "self",
    },
    "generalist_creator": {
        "label": "General creator",
        "topics": [],
        "age": {"15-17": 0.10, "18-20": 0.24, "21-24": 0.31, "25-30": 0.24, "31+": 0.11},
        "income": {"0-5L": 0.40, "5-10L": 0.29, "10-20L": 0.20, "20-50L": 0.08, "50L+": 0.03},
        "tier": dict(INDIA_TIER),
        "format": {"short_form": 0.55, "long_form": 0.25, "carousel_static": 0.14, "text_chat": 0.06},
        "temperature": {"cold": 0.70, "warm": 0.22, "hot": 0.08},
        "gender_male": 0.65,
        "seasonality": [60] * 12,
        "confidence": 0.45,
        "one_liner": "A broad audience with no single dominant intent",
        "buyer": "self",
    },
}


def engagement_band(followers: int | None) -> tuple[float, float]:
    if not followers:
        return (0.02, 0.04)
    for lo, hi, low, high in ENGAGEMENT_BANDS:
        if lo <= followers < hi:
            return (low, high)
    return (0.01, 0.02)


# ======================================================================
# Full-brief taxonomies. Each archetype declares the shape of its audience
# across every dimension the brief asks for. Rules in rules.py adjust these.
# ======================================================================

OCCUPATION_BUCKETS = ["school_student", "college_student", "job_seeker", "fresher",
                      "working_professional", "manager", "founder", "freelancer_creator"]
EDU_BUCKETS = ["school", "college_ug", "postgrad_mba", "engineering", "commerce_ca",
               "other_professional"]
CAREER_BUCKETS = ["student", "fresher", "mid_level", "senior", "cxo_founder"]
SOPHISTICATION_BUCKETS = ["casual_viewer", "returning_viewer", "loyal_follower",
                          "fan_community"]
CONSUMPTION_BUCKETS = ["short_video", "long_video", "carousel_static", "reading_text",
                       "podcast_audio", "email_newsletter"]
DEVICE_BUCKETS = ["android", "ios", "desktop", "tablet"]
ENGLISH_LEVELS = ["low", "medium", "medium_high", "high"]

# Rough state clusters used when only a tier mix is known. Not a claim about any
# individual follower — a statement about where this category's audience concentrates.
STATE_CLUSTERS = {
    "hindi_belt": ["Uttar Pradesh", "Delhi NCR", "Bihar", "Madhya Pradesh", "Rajasthan",
                   "Haryana", "Jharkhand", "Uttarakhand", "Chhattisgarh"],
    "west": ["Maharashtra", "Gujarat", "Goa"],
    "south": ["Karnataka", "Telangana", "Tamil Nadu", "Andhra Pradesh", "Kerala"],
    "east": ["West Bengal", "Odisha", "Assam"],
    "north_west": ["Punjab", "Haryana", "Himachal Pradesh", "Chandigarh", "Jammu & Kashmir"],
}

ARCHETYPE_TAXONOMY: dict[str, dict] = {
    "exam_prep_educator": {
        "occupation": {"school_student": 0.72, "college_student": 0.14, "job_seeker": 0.02,
                       "fresher": 0.02, "working_professional": 0.06, "manager": 0.01,
                       "founder": 0.01, "freelancer_creator": 0.02},
        "education": {"school": 0.76, "college_ug": 0.15, "postgrad_mba": 0.01,
                      "engineering": 0.02, "commerce_ca": 0.05, "other_professional": 0.01},
        "career": {"student": 0.88, "fresher": 0.04, "mid_level": 0.05, "senior": 0.02,
                   "cxo_founder": 0.01},
        "sophistication": {"casual_viewer": 0.44, "returning_viewer": 0.34,
                           "loyal_follower": 0.17, "fan_community": 0.05},
        "consumption": {"short_video": 0.22, "long_video": 0.58, "carousel_static": 0.07,
                        "reading_text": 0.06, "podcast_audio": 0.04, "email_newsletter": 0.03},
        "device": {"android": 0.92, "ios": 0.05, "desktop": 0.02, "tablet": 0.01},
        "states": "hindi_belt",
        "english": "medium",
        "regional": "Hindi, with regional-language homes across the Hindi belt",
    },
    "entrance_mentor": {
        "occupation": {"school_student": 0.02, "college_student": 0.32, "job_seeker": 0.12,
                       "fresher": 0.24, "working_professional": 0.22, "manager": 0.05,
                       "founder": 0.01, "freelancer_creator": 0.02},
        "education": {"school": 0.01, "college_ug": 0.34, "postgrad_mba": 0.08,
                      "engineering": 0.40, "commerce_ca": 0.12, "other_professional": 0.05},
        "career": {"student": 0.34, "fresher": 0.38, "mid_level": 0.22, "senior": 0.05,
                   "cxo_founder": 0.01},
        "sophistication": {"casual_viewer": 0.48, "returning_viewer": 0.30,
                           "loyal_follower": 0.16, "fan_community": 0.06},
        "consumption": {"short_video": 0.56, "long_video": 0.12, "carousel_static": 0.22,
                        "reading_text": 0.06, "podcast_audio": 0.02, "email_newsletter": 0.02},
        "device": {"android": 0.85, "ios": 0.11, "desktop": 0.03, "tablet": 0.01},
        "states": "west",
        "english": "high",
        "regional": "English-dominant; regional language mainly at home",
    },
    "career_finance_creator": {
        "occupation": {"school_student": 0.04, "college_student": 0.52, "job_seeker": 0.16,
                       "fresher": 0.14, "working_professional": 0.09, "manager": 0.02,
                       "founder": 0.01, "freelancer_creator": 0.02},
        "education": {"school": 0.03, "college_ug": 0.52, "postgrad_mba": 0.07,
                      "engineering": 0.14, "commerce_ca": 0.20, "other_professional": 0.04},
        "career": {"student": 0.61, "fresher": 0.24, "mid_level": 0.12, "senior": 0.02,
                   "cxo_founder": 0.01},
        "sophistication": {"casual_viewer": 0.56, "returning_viewer": 0.26,
                           "loyal_follower": 0.13, "fan_community": 0.05},
        "consumption": {"short_video": 0.52, "long_video": 0.26, "carousel_static": 0.13,
                        "reading_text": 0.05, "podcast_audio": 0.02, "email_newsletter": 0.02},
        "device": {"android": 0.87, "ios": 0.09, "desktop": 0.03, "tablet": 0.01},
        "states": "west",
        "english": "medium_high",
        "regional": "Hinglish primary; strong regional-language comprehension",
    },
    "admissions_desk": {
        "occupation": {"school_student": 0.62, "college_student": 0.22, "job_seeker": 0.03,
                       "fresher": 0.02, "working_professional": 0.05, "manager": 0.01,
                       "founder": 0.01, "freelancer_creator": 0.04},
        "education": {"school": 0.66, "college_ug": 0.26, "postgrad_mba": 0.01,
                      "engineering": 0.02, "commerce_ca": 0.03, "other_professional": 0.02},
        "career": {"student": 0.86, "fresher": 0.06, "mid_level": 0.05, "senior": 0.02,
                   "cxo_founder": 0.01},
        "sophistication": {"casual_viewer": 0.26, "returning_viewer": 0.42,
                           "loyal_follower": 0.24, "fan_community": 0.08},
        "consumption": {"short_video": 0.18, "long_video": 0.64, "carousel_static": 0.05,
                        "reading_text": 0.07, "podcast_audio": 0.02, "email_newsletter": 0.04},
        "device": {"android": 0.94, "ios": 0.03, "desktop": 0.02, "tablet": 0.01},
        "states": "north_west",
        "english": "low",
        "regional": "Hindi primary with strong Punjabi presence in the catchment",
    },
    "skill_educator": {
        "occupation": {"school_student": 0.03, "college_student": 0.28, "job_seeker": 0.14,
                       "fresher": 0.13, "working_professional": 0.28, "manager": 0.07,
                       "founder": 0.04, "freelancer_creator": 0.03},
        "education": {"school": 0.02, "college_ug": 0.36, "postgrad_mba": 0.12,
                      "engineering": 0.32, "commerce_ca": 0.10, "other_professional": 0.08},
        "career": {"student": 0.30, "fresher": 0.22, "mid_level": 0.33, "senior": 0.11,
                   "cxo_founder": 0.04},
        "sophistication": {"casual_viewer": 0.52, "returning_viewer": 0.28,
                           "loyal_follower": 0.15, "fan_community": 0.05},
        "consumption": {"short_video": 0.50, "long_video": 0.26, "carousel_static": 0.12,
                        "reading_text": 0.06, "podcast_audio": 0.03, "email_newsletter": 0.03},
        "device": {"android": 0.82, "ios": 0.12, "desktop": 0.05, "tablet": 0.01},
        "states": "south",
        "english": "high",
        "regional": "English-dominant professional register",
    },
    "generalist_creator": {
        "occupation": {"school_student": 0.14, "college_student": 0.30, "job_seeker": 0.12,
                       "fresher": 0.14, "working_professional": 0.20, "manager": 0.05,
                       "founder": 0.02, "freelancer_creator": 0.03},
        "education": {"school": 0.14, "college_ug": 0.42, "postgrad_mba": 0.08,
                      "engineering": 0.18, "commerce_ca": 0.12, "other_professional": 0.06},
        "career": {"student": 0.46, "fresher": 0.24, "mid_level": 0.22, "senior": 0.06,
                   "cxo_founder": 0.02},
        "sophistication": {"casual_viewer": 0.58, "returning_viewer": 0.26,
                           "loyal_follower": 0.12, "fan_community": 0.04},
        "consumption": {"short_video": 0.52, "long_video": 0.24, "carousel_static": 0.13,
                        "reading_text": 0.06, "podcast_audio": 0.03, "email_newsletter": 0.02},
        "device": {"android": 0.90, "ios": 0.07, "desktop": 0.02, "tablet": 0.01},
        "states": "hindi_belt",
        "english": "medium",
        "regional": "Mixed",
    },
}

LABELS = {
    "school_student": "School student", "college_student": "College student",
    "job_seeker": "Active job seeker", "fresher": "Fresher (0–2 yrs)",
    "working_professional": "Working professional", "manager": "Manager",
    "founder": "Founder", "freelancer_creator": "Freelancer / creator",
    "school": "School (Class 9–12)", "college_ug": "Undergraduate",
    "postgrad_mba": "Postgraduate / MBA", "engineering": "Engineering",
    "commerce_ca": "Commerce / CA / CS / CMA", "other_professional": "Other professional",
    "student": "Student", "mid_level": "Mid-level", "senior": "Senior",
    "cxo_founder": "CXO / Founder",
    "casual_viewer": "Casual viewer", "returning_viewer": "Returning viewer",
    "loyal_follower": "Loyal follower", "fan_community": "Fan community",
    "short_video": "Short-form video", "long_video": "Long-form video",
    "carousel_static": "Carousel / static", "reading_text": "Reading / text",
    "podcast_audio": "Podcast / audio", "email_newsletter": "Email / newsletter",
    "android": "Android", "ios": "iPhone", "desktop": "Desktop", "tablet": "Tablet",
}


CITY_TO_STATE = {
    "delhi": "Delhi NCR", "noida": "Uttar Pradesh (NCR)", "gurgaon": "Haryana (NCR)",
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh", "varanasi": "Uttar Pradesh",
    "patna": "Bihar", "ranchi": "Jharkhand", "bhopal": "Madhya Pradesh",
    "indore": "Madhya Pradesh", "jaipur": "Rajasthan", "chandigarh": "Chandigarh",
    "mohali": "Punjab", "ludhiana": "Punjab", "patiala": "Punjab",
    "panchkula": "Haryana", "ambala": "Haryana", "shimla": "Himachal Pradesh",
    "mumbai": "Maharashtra", "pune": "Maharashtra", "nagpur": "Maharashtra",
    "ahmedabad": "Gujarat", "surat": "Gujarat",
    "bengaluru": "Karnataka", "bangalore": "Karnataka",
    "hyderabad": "Telangana", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "kochi": "Kerala", "kolkata": "West Bengal", "bhubaneswar": "Odisha",
    "guwahati": "Assam",
}
