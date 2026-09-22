"""Real observed data, frozen as fixtures.

These are genuine figures collected from the four creators' public pages on
5 August 2026. They let the inference engine and renderers be tested without a
network round-trip, and they act as regression cases: if a rule change moves one of
these audience models in a way you did not intend, the tests will tell you.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.schemas import (ContentItem, PlatformAccount, Product, RawProfile,
                         Testimonial)

NOW = datetime(2026, 8, 5)


def _vid(title, views, days_ago, dur=900, platform="youtube"):
    return ContentItem(platform=platform, title=title, views=views,
                       duration_seconds=dur, published_at=NOW - timedelta(days=days_ago),
                       url=f"https://youtu.be/{abs(hash(title)) % 10**11}")


# ---------------------------------------------------------------- Sunil Panda
def sunil_panda() -> RawProfile:
    yt = PlatformAccount(
        platform="youtube", handle="sunilpandaofficial",
        url="https://www.youtube.com/@sunilpandaofficial",
        display_name="Sunil Panda-The Educator",
        bio=("Sunil Panda- The Educator Is a Commerce Education Platform Trusted by Million "
             "of Students across India & neighbouring countries."),
        followers=1_010_000, posts=4500,
        keywords=["sunil panda", "sunil sir", "commerce", "accounts class 12",
                  "class 12 Accounts sunil panda", "cbse class 12", "cuet", "CUET exam",
                  "cbse class 11", "business studies class 12", "cbse class 12 economics",
                  "micro economics class 12 cbse", "one shot revision class 12",
                  "Accountancy class 12", "Accounts best teacher class 12"],
        content=[
            _vid("Introduction to Accounting | BASICS Part 1. for B.com, BBA Semester I", 1_000_000, 1800, 1462),
            _vid("Final Accounts | Part 1. Most Important For B.com/ BBA 1st Semester", 923_000, 1800, 1536),
            _vid("Issue of shares One Shot | 15 Marks in 1 Video. Class 12 Accounts", 649_000, 1100, 8574),
            _vid("Management | Complete revision in ONE SHOT | Class 12 Business studies", 647_000, 1100, 741),
            _vid("COMPLETE MACRO ECONOMICS IN ONE SHOT | 22 MARKS GUARANTEE", 614_000, 1400, 6040),
            _vid("Last 5 Days Strategy For 60 Marks in Class 12th ACCOUNTANCY COMPARTMENT EXAM 2026", 31_000, 13, 1008),
            _vid("The first podcast of my life | CUET 2026 AIR 1 in Commerce", 12_000, 21, 1818),
            _vid("DROP OR NO DROP ? Hardest Decision for every CUET 2026 Aspirants", 10_000, 21, 1114),
            _vid("BIGGEST SERIES FOR CLASS 12 COMMERCE STUDENTS ANNOUNCED | Target 90%", 7_200, 4, 659),
            _vid("Goodwill Valuation | Part 2 | All Adjustments in Net Profit | Class 12 Accounts", 6_600, 21, 2287),
            _vid("Goodwill Valuation | Part 3 | Super profit Method | Class 12 Accounts", 4_100, 21, 1208),
            _vid("Goodwill Valuation | Part 4 | Capitalisation Method | Class 12 Accounts", 3_900, 21, 1591),
            _vid("National income | Part 1 | Circular flow of income | Class 12 Macro Economics", 5_800, 21, 1402),
            _vid("National income | Part 2 | Types of Goods and Questions | Class 12", 3_600, 14, 1692),
            _vid("National income | Part 3 | Basics of NUMERICALS | Class 12 Macro Economics", 3_500, 14, 1818),
            _vid("National income | Part 4 | Production Method | NUMERICALS | Class 12", 1_800, 5, 1530),
            _vid("National income | Part 5 | Income & Expenditure Method | NUMERICALS", 1_300, 4, 2242),
            _vid("National income | Part 6 | Precautions regarding production method | Class 12", 1_100, 3, 1170),
            _vid("National income | Part 7 | Most Important Theory | Class 12 Economics", 892, 2, 1366),
            _vid("Change in Profit Sharing Ratio | Part 1 | Class 12 Accountancy", 5_600, 14, 1941),
            _vid("Change in Profit Sharing Ratio | Part 3 Revaluation A/c | Class 12", 3_200, 10, 1887),
            _vid("Admission of a Partner | Part 1 Basic, New & Sacrificing Ratio | Class 12", 2_400, 1, 2372),
            _vid("Nature & Significance of Management | ONE SHOT | Class 12th Business studies", 2_000, 0, 3693),
        ],
    )
    ig = PlatformAccount(
        platform="instagram", handle="sunilpandaofficial",
        url="https://www.instagram.com/sunilpandaofficial/",
        display_name="Sunil Panda", followers=70_000, following=38,
        bio=("The Educator Learner | TEDx Speaker | Motivator Founder of SPCC "
             "YouTube - 1 MILLION + Family"),
        highlights=["CUET 25 TOPPERS", "SPCC TO SRCC 3.0", "College Preference", "Memes/Fun",
                    "Mindmaps Diagrams", "English 2022-23", "Quotes", "CUET", "COMMERCE SONG"],
        external_links=["https://linktr.ee/sunilpanda_2023"],
        needs_manual=False,
    )
    tg = PlatformAccount(platform="telegram", handle="sunilpanda2022",
                         url="https://t.me/s/sunilpanda2022",
                         display_name="Sunil panda", followers=None)
    app = PlatformAccount(platform="appstore", handle="6474612736",
                          url="https://apps.apple.com/app/id6474612736",
                          display_name="SPCC by Sunil sir",
                          products=[Product(name="SPCC by Sunil sir", kind="app", price_inr=0)])
    lt = PlatformAccount(platform="linktree", handle="sunilpanda_2023",
                         url="https://linktr.ee/sunilpanda_2023",
                         display_name="SUNIL PANDA 2022-23",
                         external_links=["https://t.me/sunilpanda2022",
                                         "https://www.instagram.com/sunilpandaofficial/"],
                         products=[Product(name="SPCC COMBO ECO BST ACCOUNTS COMBO COURSE",
                                           price_inr=1499, kind="course")])
    return RawProfile(seed_url="https://www.instagram.com/sunilpandaofficial/",
                      seed_platform="instagram", seed_handle="sunilpandaofficial",
                      display_name="Sunil Panda", accounts=[ig, yt, tg, app, lt])


# ------------------------------------------------------------- Chanchal Singh
def chanchal_singh() -> RawProfile:
    ig = PlatformAccount(
        platform="instagram", handle="chanchal_iim",
        url="https://www.instagram.com/chanchal_iim/",
        display_name="Chanchal Singh | MBA Mentor", followers=33_300, following=52,
        bio="IIM AHMEDABAD, MBA. Ace interview | CV | CAT. Consult 1:1 topmate.io/chanchal_singh",
        highlights=["Self Prep for CAT", "Resume", "Info carousels", "Workshops"],
        external_links=["https://topmate.io/chanchal_singh"],
    )
    yt = PlatformAccount(
        platform="youtube", handle="chanchal_IIMAhmedabad",
        url="https://www.youtube.com/@chanchal_IIMAhmedabad",
        display_name="Chanchal Singh (Ms.)", followers=193, posts=35,
        bio="Welcome, Hustlers! I'm Chanchal, an IIM Ahmedabad alum.",
        content=[
            _vid("My marketing journey after MBA from IIM Ahmedabad. Sales reality", 22_000, 200, 58),
            _vid("IIM Bangalore Summer Internship Placements", 1_500, 150, 51),
            _vid("MBA interview questions asked in IIM AHMEDABAD interview. After CAT", 1_500, 160, 47),
            _vid("CAT 2025 slots, MBA", 1_400, 140, 44),
            _vid("My marketing journey after MBA from IIM AHMEDABAD part 2", 1_300, 190, 55),
            _vid("MBA is tough", 2_400, 210, 39),
            _vid("Self Preparation for CAT Exam Episode 4", 1_600, 230, 52),
            _vid("Crack CAT exam through Self Preparation Episode 2", 1_100, 250, 49),
            _vid("FMS SOP that converted", 672, 180, 43),
            _vid("CAT Exam 2025 Complete detail under 5 mins", 511, 365, 280),
            _vid("AWT topic - is a rise in bschool fees justifiable, asked in IIMA", 1_400, 120, 46),
            _vid("If MBA/IIM is your dream then ideal time to start prep for freshers & workex", 979, 110, 41),
        ],
    )
    tm = PlatformAccount(
        platform="topmate", handle="chanchal_singh", url="https://topmate.io/chanchal_singh",
        display_name="Chanchal Singh",
        bio="Product Manager || Key Account Manager (MT) Dabur || ABG Textiles || IIM AHMEDABAD'20 || B.H.U'18",
        raw={"rating": 5.0, "rating_count": 41},
        products=[
            Product(name="Ask me anything and get answer in DM", price_inr=150, kind="service"),
            Product(name="2 GD/AWT Practice + resources", price_inr=452, kind="service"),
            Product(name="Logical Fear Burster", price_inr=799, kind="service"),
            Product(name="30 days to CAT (Fear Buster)", price_inr=799, kind="service"),
            Product(name="Mock PI Interviews", price_inr=799, kind="service"),
            Product(name="FMS SOP From Scratch", price_inr=999, kind="service"),
            Product(name="CAT Prep Coaching", price_inr=999, kind="service"),
            Product(name="GAP Year Answer in Interview", price_inr=1799, kind="service"),
            Product(name="One Mock Personal Interview practice", price_inr=1799, kind="service"),
            Product(name="CAT + Profile Strategy", price_inr=1999, kind="service"),
            Product(name="MBA colleges form filling help", price_inr=2299, kind="service"),
            Product(name="MOCK INTERVIEW PACKAGE", price_inr=2397, kind="package"),
            Product(name="PI Answer from Scratch", price_inr=2499, kind="service"),
            Product(name="GDPI Prep from Scratch (Answer+Mock)", price_inr=9999, kind="package"),
        ],
        testimonials=[
            Testimonial(text=("She was amazing, so helpful and easy to speak to. She made a "
                              "personalised strategy and cleared a lot of mental roadblocks for me."),
                        author="Ranaika", rating=5.0, dated="22nd Feb, 2026"),
            Testimonial(text="She knows exactly what she is talking about, it was very helpful and insightful",
                        author="Anonymous", rating=5.0, dated="29th Nov, 2025"),
            Testimonial(text="Great experience—supportive guidance that made my SOP much more focused",
                        author="Sahil singla", rating=5.0, dated="3rd Dec, 2025"),
            Testimonial(text="You brought clarity into my thoughts.", author="Geetima sharma",
                        rating=5.0, dated="27th Nov, 2025"),
        ],
    )
    return RawProfile(seed_url="https://www.instagram.com/chanchal_iim/",
                      seed_platform="instagram", seed_handle="chanchal_iim",
                      display_name="Chanchal Singh", accounts=[ig, yt, tm])


# --------------------------------------------------------------- RJ Shubham
def rj_shubham() -> RawProfile:
    ig = PlatformAccount(
        platform="instagram", handle="rj_shubham_reports",
        url="https://www.instagram.com/rj_shubham_reports/",
        display_name="Rj_shubham_Reports", followers=1_919, following=0,
        bio="Just focusing on Education", highlights=["PU Admission 25"],
    )
    yt = PlatformAccount(
        platform="youtube", handle="RJSHUBHAMCHANDEL",
        url="https://www.youtube.com/@RJSHUBHAMCHANDEL",
        display_name="RJ SHUBHAM", followers=28_600, posts=1000,
        bio="EMPOWERING THE LIFE OF FELLOW STUDENTS",
        content=[
            _vid("How to fill Chandigarh Colleges Admission Form Step By Step Live Demo", 22_000, 30, 240),
            _vid("Second Counselling in chandigarh colleges| Vacant seats and 2nd merit List date", 5_700, 21, 228),
            _vid("How to attend Chandigarh college Counselling? DHE Chandigarh Admission 2026", 5_600, 21, 377),
            _vid("Final Merit List of Chandigarh colleges| Dhe chandigarh Allotment list today", 4_500, 21, 281),
            _vid("Chandigarh colleges Admission updates| willingness form and 2nd counselling", 3_900, 14, 248),
            _vid("Merit list of chandigarh colleges out| How to check and when to pay fees", 3_800, 21, 261),
            _vid("Final Merit List of Panjab University Chandigarh? All important updates", 3_600, 14, 256),
            _vid("Merit list out for panjab university chandigarh ug course| What Next?", 2_900, 21, 263),
            _vid("PU Admission form open now for BSc and BPharmacy| Seats, Fees", 2_600, 30, 300),
            _vid("3rd counselling Good news for all students| Chandigarh colleges| Dhe chandigarh", 2_500, 14, 268),
            _vid("DHE Chandigarh 4th Counselling? 3rd counselling Merit list? What to do now?", 2_300, 12, 253),
            _vid("Panjab University Chandigarh Final merit list of UG Courses| Last date", 2_000, 14, 153),
            _vid("Panjab university merit list out| How to check? What next, fee payment", 1_700, 14, 226),
            _vid("How to check Panjab University Chandigarh Merit List| BA/Bcom", 1_400, 13, 228),
            _vid("Chandigarh Colleges Classes Notice| Orientation and Classes Date 2026", 1_200, 9, 224),
            _vid("Didn't get Admission in college? what to do now?", 881, 7, 267),
            _vid("PU entrance Exam result out| How to check PU LLB Result", 662, 21, 165),
            _vid("How to get Admission in Online/Usol/Cdoe Course in panjab university", 519, 7, 326),
            _vid("Admission open| USOL/CDOE Detailed Admission process| Last Date", 433, 8, 99),
            _vid("Admission open in CGC University Mohali| 100% Scholarship free form filling", 363, 21, 195),
            _vid("How to get admission in chandigarh university Phase-2| Free form filling", 278, 21, 288),
            _vid("CGC University Classes Date| How to join induction/Orientation programme", 269, 21, 344),
            _vid("CGC University Mohali Admission Last Date today| Free admission", 227, 21, 142),
            _vid("BTech CSE, AI& ML Last few seats CGC UNIVERSITY MOHALI| 1 crore package", 129, 21, 225),
        ],
    )
    return RawProfile(seed_url="https://www.instagram.com/rj_shubham_reports/",
                      seed_platform="instagram", seed_handle="rj_shubham_reports",
                      display_name="RJ Shubham", accounts=[ig, yt])


# -------------------------------------------------------------- Ishaan Arora
def ishaan_arora() -> RawProfile:
    ig = PlatformAccount(
        platform="instagram", handle="ishaanarora1",
        url="https://www.instagram.com/ishaanarora1/",
        display_name="Ishaan Arora | Career & Education",
        followers=419_000, following=992, verified=True,
        bio=("I help you boost your CAREER. Taught 50K+, 5000+ people placed. "
             "Leading Educator & Counsellor. CoFounder - FinLadder"),
        highlights=["England", "France 2.0", "Ireland", "Netherlands", "Scotland",
                    "Italy", "Switzerland", "Bali", "Belgium", "Malaysia"],
        external_links=["https://superprofile.bio/bookings/ishaanarora1"],
    )
    yt = PlatformAccount(
        platform="youtube", handle="ishaanarora.official5",
        url="https://www.youtube.com/channel/UCkOtNAT3-B2rAPEleWaytrA",
        display_name="Ishaan Arora", followers=199_000, posts=333,
        bio=("I help you grow your career! internships, courses, paid work, study abroad. "
             "TEDx and Josh Talks speaker. Real life Jeetu Bhaiya."),
        keywords=["ishaan arora", "josh talks ishaan arora", "finladder", "tedx ishaan arora",
                  "finance", "finance career", "study abroad", "financial modeling", "frm",
                  "cfa", "scholarship", "internships", "career growth", "ca", "commerce",
                  "mba abroad", "finance jobs", "free finance courses"],
        content=[
            _vid("Top 5 FREE Finance Courses for JOB", 575_000, 1000, 392),
            _vid("Complete Roadmap for Making a Successful FINANCE Career", 498_000, 1000, 802),
            _vid("High Paying Finance Courses you CAN'T Miss", 466_000, 1400, 583),
            _vid("5 Top Finance Courses for Jobs | Short vs Long Term", 460_000, 700, 788),
            _vid("How to study abroad for free? Fully Funded Scholarships", 341_000, 700, 452),
            _vid("How to make 1 lakh/Month as a College Student", 318_000, 700, 832),
            _vid("Best NISM Courses for Jobs + Skills You Must Learn in Finance", 105_000, 330, 1021),
            _vid("Step-By-Step Guide To Get a 1 Lakh+ Job at SEBI", 50_000, 240, 590),
            _vid("How to Build a Finance Career with AI? GARP Risk & AI Course", 46_000, 240, 540),
            _vid("5 High-Paying Finance Jobs AI Is Creating", 38_000, 240, 779),
            _vid("Is ACCA Worth It in 2026? Fees, Salary, Jobs", 31_000, 210, 634),
            _vid("Is CFA Still Worth It In 2026?", 27_000, 30, 662),
            _vid("5 Degrees That WASTE Your Time and Money", 22_000, 120, 542),
            _vid("Top 6 Job-Friendly AI Courses | Jobs UPTO 35LPA", 20_000, 210, 716),
            _vid("The Most Future-Proof & High-Demand Career for the Next Decade", 14_000, 60, 560),
            _vid("Big 4 Jobs After Graduation | How I cracked Big 4", 10_000, 120, 745),
            _vid("5 High-Paying Finance Jobs AI Can't Replace in 2026", 9_900, 60, 729),
            _vid("How to Save Up to 90,000 on CFA Fees? CFA Scholarship 2026", 6_800, 60, 412),
            _vid("How To Get International Finance Jobs From India", 6_700, 30, 767),
            _vid("CPA US Career Guide 2026 | Eligibility, Salary & Job Opportunities", 4_900, 30, 728),
            _vid("CMA US Complete Guide 2026 | Salary, Fees, Jobs, Eligibility", 3_000, 30, 551),
            _vid("Invest in the US Stock Market from India with Only 90", 2_800, 210, 896),
            _vid("3 High-Income Skills That Can Get You Global Clients in 2026", 2_400, 60, 653),
            _vid("5 AI Business Ideas That Can Make You 1 Lakh/Month in 2026", 1_600, 30, 583),
            _vid("The Only Trading Masterclass You'll Ever Need", 1_500, 270, 2856),
            _vid("Is an MBA relevant in the age of AI?", 1_300, 60, 462),
            _vid("Don't Move to the UK Without a Strategy: 2026 Roadmap", 563, 60, 642),
        ],
    )
    sp = PlatformAccount(
        platform="superprofile", handle="ishaanarora1",
        url="https://superprofile.bio/bookings/ishaanarora1",
        display_name="Ishaan Arora",
        products=[
            Product(name="Investment Analysis & Portfolio Management", price_inr=2198, kind="course"),
            Product(name="Financial Modeling & Valuations (incl. guaranteed internship)",
                    price_inr=7500, kind="course"),
        ],
    )
    return RawProfile(seed_url="https://www.instagram.com/ishaanarora1/",
                      seed_platform="instagram", seed_handle="ishaanarora1",
                      display_name="Ishaan Arora", accounts=[ig, yt, sp])


ALL = {
    "sunil_panda": sunil_panda,
    "chanchal_singh": chanchal_singh,
    "rj_shubham": rj_shubham,
    "ishaan_arora": ishaan_arora,
}
