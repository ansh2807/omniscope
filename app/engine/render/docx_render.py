"""Word renderer — same thirteen sections as the HTML report, laid out for print."""
from __future__ import annotations

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from app.schemas import CohortPayload, ReportPayload

ACC = RGBColor(0x1B, 0x4F, 0x8C)
MUT = RGBColor(0x5A, 0x5A, 0x5A)
RED = RGBColor(0xA3, 0x2A, 0x22)
GRN = RGBColor(0x1E, 0x7B, 0x34)


def _style(doc: Document) -> None:
    n = doc.styles["Normal"]
    n.font.name, n.font.size = "Calibri", Pt(10)
    for name, size in (("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11)):
        st = doc.styles[name]
        st.font.name, st.font.size, st.font.color.rgb, st.font.bold = "Calibri", Pt(size), ACC, True


def _p(doc, text, *, size=10, bold=False, italic=False, color=None, after=6):
    par = doc.add_paragraph()
    par.paragraph_format.space_after = Pt(after)
    r = par.add_run(str(text))
    r.font.size, r.bold, r.italic = Pt(size), bold, italic
    if color:
        r.font.color.rgb = color
    return par


def _table(doc, headers, rows):
    if not rows:
        return None
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(str(h))
        r.bold, r.font.size, r.font.color.rgb = True, Pt(7.5), ACC
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row[:len(headers)]):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run("" if val is None else str(val))
            r.font.size = Pt(8)
    doc.add_paragraph()
    return t


def _callout(doc, kind, title, body):
    col = {"risk": RED, "correction": RGBColor(0x8A, 0x61, 0x00),
           "opportunity": GRN}.get(kind, ACC)
    _p(doc, f"{kind.upper()} — {title}", size=9.5, bold=True, color=col, after=2)
    _p(doc, body, size=9, after=10)


def _dist(d):
    return " · ".join(f"{k} {v}%" for k, v in d.as_pct().items()) or "Unavailable"


def _status(x):
    value = x.status.value
    return (value.upper() if value != "modelled" else
            f"MODELLED {round(x.confidence * 100)}%")


def _agency_status(m: dict | None) -> str:
    if not m:
        return "UNAVAILABLE"
    status = str(m.get("status") or "unavailable")
    conf = m.get("confidence")
    if status == "modelled" and conf is not None:
        return f"MODELLED {round(float(conf) * 100)}%"
    if status == "calculated" and conf is not None:
        return f"CALCULATED {round(float(conf) * 100)}%"
    return status.upper()


def _agency_summary(m: dict | None) -> str:
    if not m or m.get("status") == "unavailable":
        return "Unavailable"
    value = m.get("value")
    if isinstance(value, dict):
        if value.get("score") is not None:
            label = value.get("label")
            return f"{value['score']}" + (f" · {label}" if label else "")
        if value.get("risk_band"):
            rng = value.get("risk_score_range") or []
            band = value["risk_band"]
            return f"{band} ({rng[0]}–{rng[1]})" if len(rng) == 2 else band
        if value.get("per_placement_range"):
            lo, hi = value["per_placement_range"][:2]
            return f"{lo:,}–{hi:,} public views"
        if value.get("change_pct") is not None:
            direction = value.get("direction") or ""
            return f"{value['change_pct']}% vs catalogue" + (f" · {direction}" if direction else "")
        if "named_brands" in value:
            brands = value.get("named_brands") or []
            return ", ".join(brands) if brands else (value.get("summary") or "Markers observed")
        if value.get("exact_overlap_status"):
            return "Exact overlap unavailable · topic affinity reported separately"
        return "See interpretation"
    if isinstance(value, list) and value and isinstance(value[0], dict):
        if "value" in value[0]:
            return " · ".join(str(x.get("value")) for x in value if x.get("value"))
        if "handle" in value[0]:
            return " · ".join(str(x.get("handle")) for x in value if x.get("handle"))
        if "insight" in value[0]:
            return f"{len(value)} evidence-qualified insight(s)"
        return f"{len(value)} item(s)"
    return str(value)


def _agency_section(doc: Document, p: ReportPayload, *, n_prefix: str = "") -> None:
    ag = p.agency if isinstance(p.agency, dict) else None
    if not ag:
        return
    doc.add_heading(f"{n_prefix}5. Agency Buying Desk", level=1)
    _p(doc,
       "Marketing-company diligence layer covering audience quality, demographics, "
       "fake-follower anomaly screens, interests, engagement, overlap, lookalikes, "
       "contacts, estimated reach, brand collaborations, influence score, audience "
       "insights, brand affinity and historical performance. Every claim is statused; "
       "nothing private is fabricated.",
       size=9, italic=True, color=MUT)
    _p(doc, f"Methodology {ag.get('methodology_version', '1.0.0')}.", size=8.5, color=MUT)
    labels = [
        ("audience_quality", "Audience quality"),
        ("demographics", "Demographics"),
        ("fake_follower_anomaly", "Fake follower estimates"),
        ("interests", "Interests"),
        ("engagement", "Engagement"),
        ("audience_overlap", "Audience overlap"),
        ("lookalike_creators", "Lookalike creators"),
        ("contact_details", "Contact details"),
        ("estimated_reach", "Estimated reach"),
        ("brand_collaborations", "Brand collaborations"),
        ("influence_score", "Influence score"),
        ("audience_insights", "Audience insights"),
        ("brand_affinity", "Brand affinity"),
        ("historical_performance", "Historical performance"),
    ]
    rows = []
    for key, label in labels:
        m = ag.get(key) or {}
        interp = m.get("interpretation") or ""
        formula = m.get("formula") or ""
        detail = interp + (f" | {formula}" if formula else "")
        rows.append([label, _agency_summary(m), detail[:320], _agency_status(m)])
    _table(doc, ["Metric", "Result", "Interpretation / method", "Status"], rows)

    lk = ag.get("lookalike_creators") or {}
    if lk.get("status") != "unavailable" and isinstance(lk.get("value"), list) and lk["value"]:
        doc.add_heading("Lookalike creators", level=2)
        _p(doc, "Ranked by public content/topic affinity — not shared followers.",
           size=8.5, italic=True, color=MUT)
        _table(doc, ["Creator", "Platform", "Followers", "Score", "Coverage", "Scope"],
               [[f"{row.get('display_name') or row.get('handle')} (@{row.get('handle')})",
                 row.get("platform"),
                 f"{row['followers']:,}" if row.get("followers") else "—",
                 row.get("lookalike_score"),
                 f"{row.get('feature_coverage_pct', '—')}%",
                 row.get("scope")]
                for row in lk["value"][:10]])

    ct = ag.get("contact_details") or {}
    if ct.get("status") == "observed" and isinstance(ct.get("value"), list) and ct["value"]:
        doc.add_heading("Public contact details", level=2)
        _table(doc, ["Type", "Value", "Platform", "Source"],
               [[row.get("type"), row.get("value"), row.get("platform"), row.get("source_url")]
                for row in ct["value"]])

    bc = ag.get("brand_collaborations") or {}
    if bc.get("status") != "unavailable" and isinstance(bc.get("value"), dict):
        doc.add_heading("Brand collaborations", level=2)
        brands = bc["value"].get("named_brands") or []
        if brands:
            _p(doc, "Named brands: " + ", ".join(brands), size=9)
        if bc["value"].get("summary"):
            _p(doc, bc["value"]["summary"], size=9)
        _p(doc, bc.get("interpretation") or "", size=8.5, color=MUT)

    ai = ag.get("audience_insights") or {}
    if ai.get("status") != "unavailable" and isinstance(ai.get("value"), list) and ai["value"]:
        doc.add_heading("Audience insights", level=2)
        _table(doc, ["Insight", "Value", "Decision use", "Status"],
               [[row.get("insight"),
                 f"{row.get('value')} {row.get('unit') or ''}".strip()
                 if row.get("value") is not None else "—",
                 row.get("decision"),
                 str(row.get("status", "")).upper()]
                for row in ai["value"]])

    hp = ag.get("historical_performance") or {}
    if hp.get("status") != "unavailable" and isinstance(hp.get("value"), dict):
        doc.add_heading("Historical performance", level=2)
        v = hp["value"]
        _table(doc, ["Catalogue median", "Current median", "Change", "Direction"],
               [[f"{v['catalogue_median']:,}" if v.get("catalogue_median") is not None else "—",
                 f"{v['current_median']:,}" if v.get("current_median") is not None else "—",
                 f"{v['change_pct']}%" if v.get("change_pct") is not None else "—",
                 v.get("direction") or "—"]])
        _p(doc, hp.get("interpretation") or "", size=8.5, color=MUT)


def _desk_body(doc: Document, desk: dict | None, *, n_prefix: str = "") -> None:
    if not desk:
        return
    doc.add_heading(f"{n_prefix}0. Marketing desk", level=1)
    _p(doc, desk.get("one_liner") or "", size=12, bold=True, after=8)
    _p(doc, desk.get("job") or "", size=10)
    _p(doc, desk.get("posture") or "", size=9, italic=True, color=MUT)
    if desk.get("narrative"):
        _p(doc, desk["narrative"], size=10)
    needs = [n for n in (desk.get("needs") or []) if isinstance(n, dict)]
    if needs:
        _table(doc, ["Need", "Status", "Evidence", "Next"],
               [[n.get("title") or "", n.get("status") or "",
                 (n.get("evidence") or "")[:180], (n.get("next_step") or "")[:180]]
                for n in needs])
    for fw in desk.get("frameworks") or []:
        if not isinstance(fw, dict):
            continue
        doc.add_heading(fw.get("name") or "Framework", level=2)
        cells = [c for c in (fw.get("cells") or []) if isinstance(c, dict)]
        if cells:
            _table(doc, ["Slot", "Fill", "Status"],
                   [[c.get("slot") or "", c.get("fill") or "", c.get("status") or ""]
                    for c in cells])
    for pb in desk.get("playbooks") or []:
        if not isinstance(pb, dict):
            continue
        doc.add_heading(pb.get("title") or "Playbook", level=2)
        _p(doc, pb.get("why") or "", size=9)
        if pb.get("steps"):
            _p(doc, " · ".join(pb["steps"]), size=9)
        if pb.get("cannot"):
            _p(doc, pb["cannot"], size=8.5, italic=True, color=MUT)
    if desk.get("week_plan"):
        _p(doc, "This week: " + " · ".join(desk["week_plan"]), size=9)
    if desk.get("cannot_know"):
        _p(doc, "Will not be invented: " + " · ".join(desk["cannot_know"]),
           size=8.5, italic=True, color=MUT)


def _creator_body(doc: Document, p: ReportPayload, *, n_prefix: str = "") -> None:
    a, c, f, s, ov = p.audience, p.content, p.funnel, p.seo, p.overview
    cm, br, gr, dx = p.comments, p.brand, p.growth, p.diagnostics
    vr = p.verification
    _desk_body(doc, p.desk if isinstance(p.desk, dict) else None, n_prefix=n_prefix)

    doc.add_heading(f"{n_prefix}1. Executive Summary", level=1)
    _p(doc, a.one_liner, size=12, bold=True, after=10)
    if p.headline_stats:
        _table(doc, [x["label"] for x in p.headline_stats],
               [[x["value"] for x in p.headline_stats], [x["note"] for x in p.headline_stats]])
    doc.add_heading("Executive dashboard", level=2)
    _table(doc, ["Life-stage model confidence", "Brand evidence rubric",
                 "Funnel evidence rubric", "Growth trend"],
           [[f"{round(a.overall_confidence*100)}%",
             f"{br.total}/50" if br else "—",
             f"{f.total}/70" if f else "—",
             (gr.trend or "not measurable") if gr else "—"]])
    if dx:
        doc.add_heading("Research confidence and decision risk", level=2)
        _table(doc, ["Research completeness", "Observed/calculated dimensions",
                     "View Gini", "Effective platforms"],
               [[f"{dx.evidence_score}/100",
                 f"{dx.evidence_counts.get('observed', 0) + dx.evidence_counts.get('calculated', 0)}/{len(dx.evidence_dimensions)}",
                 dx.view_gini if dx.view_gini is not None else "—",
                 dx.effective_platforms if dx.effective_platforms is not None else "—"]])
        _p(doc, dx.evidence_read, size=8.5, italic=True, color=MUT)
    if vr:
        doc.add_heading("Identity and claim verification", level=2)
        _table(doc, ["Identity status", "Identity evidence score", "Primary surfaces",
                     "Related surfaces", "Withheld/conflicted", "Independent hosts"],
               [[vr.get("identity_status", "insufficient").upper(),
                 f"{round(vr.get('identity_score', 0) * 100)}%",
                 vr.get("primary_accounts", vr.get("accepted_accounts", 0)),
                 vr.get("related_accounts", 0), vr.get("withheld_accounts", 0),
                 vr.get("independent_source_count", 0)]])
        if vr.get("conflicts"):
            _callout(doc, "risk", "Evidence conflicts detected",
                     "Conflicted values are withheld. Review the verification ledger before use.")
    mb = p.media_buy if isinstance(p.media_buy, dict) else None
    if mb:
        doc.add_heading("Media-buy decision scorecard", level=2)
        _table(doc, ["Verdict", "Fit score", "Coverage", "Code"],
               [[mb.get("label"), mb.get("fit_score") if mb.get("fit_score") is not None else "—",
                 f"{mb.get('coverage_pct', 0)}%", str(mb.get("verdict", "")).upper()]])
        if mb.get("components"):
            _table(doc, ["Component", "Score", "Weight", "Status", "Note"],
                   [[c.get("name"),
                     c.get("score") if c.get("score") is not None else "—",
                     c.get("weight"), str(c.get("status", "")).upper(), c.get("note")]
                    for c in mb["components"]])
        if mb.get("next_steps"):
            _p(doc, "Next steps: " + " · ".join(mb["next_steps"]), size=9)
        _p(doc, mb.get("method") or "", size=8.5, italic=True, color=MUT)

    for co in a.callouts:
        _callout(doc, co["kind"], co["title"], co["body"])

    doc.add_heading(f"{n_prefix}2. Creator Overview", level=1)
    rows = []
    if ov:
        if ov.positioning:
            rows.append(["Positioning", ov.positioning])
        if ov.credentials:
            rows.append(["Credentials", " · ".join(ov.credentials)])
        if ov.content_pillars:
            rows.append(["Content pillars", " · ".join(ov.content_pillars)])
        if ov.product_stack:
            rows.append(["Product stack", " · ".join(ov.product_stack)])
        if ov.format_range:
            rows.append(["Format range", ov.format_range])
        if ov.press:
            rows.append(["Press & stage", " · ".join(ov.press)])
        if ov.base_location:
            rows.append(["Base", ov.base_location])
    _table(doc, ["Attribute", "Detail"], rows)

    doc.add_heading(f"{n_prefix}3. Cross-Platform Presence", level=1)
    _table(doc, ["Platform", "Account role", "Handle", "Followers", "Items", "Collected via", "Note"],
           [[r["platform"], r.get("role", "—"), r["handle"], r["followers"], r["items"],
             r.get("tier", "—"), r["note"]] for r in p.platform_matrix])
    if vr and vr.get("accounts"):
        doc.add_heading("Cross-source identity graph", level=2)
        _p(doc, "Follower size never establishes identity; scores combine named, linked and independent evidence.",
           size=8.5, italic=True, color=MUT)
        _table(doc, ["Surface", "Relationship", "Status", "Score", "Evidence", "Conflicts / gaps"],
               [[x.get("platform"), x.get("role", "candidate").replace("_", " ").title(),
                 x.get("status"), f"{round(x.get('score', 0)*100)}%",
                 " · ".join(x.get("signals") or []),
                 " · ".join(x.get("conflicts") or [])]
                for x in vr["accounts"]])
    if dx and dx.platform_hhi is not None:
        doc.add_heading("Distribution concentration", level=2)
        _p(doc, f"HHI {dx.platform_hhi}; effective platform count {dx.effective_platforms}; "
                f"concentration {dx.platform_concentration}. Summed follows are not unique people.",
           size=9)
        _table(doc, ["Platform", "Public follows", "Share of summed follows"],
               [[x["platform"], f"{x['followers']:,}", f"{x['share']}%"]
                for x in dx.platform_shares])

    if p.raw.rejected:
        doc.add_heading("Candidates considered and rejected", level=2)
        _p(doc, "A profile that lists a stranger's account is worse than one that lists "
                "nothing, so every discovered surface has to prove it belongs to the "
                "subject before it is recorded. These did not.", size=9, italic=True,
           color=MUT)
        _table(doc, ["Platform", "Candidate", "Why rejected"],
               [[r["platform"], r["url"], r["reason"]] for r in p.raw.rejected])

    doc.add_heading(f"{n_prefix}4. Audience Intelligence", level=1)
    rows = [
        ["Age / life stage", _dist(a.age), a.age.reasoning, _status(a.age)],
        ["Gender", _dist(a.gender), a.gender.reasoning, _status(a.gender)],
        ["City tier", _dist(a.city_tier), a.city_tier.reasoning, _status(a.city_tier)],
        ["Income", _dist(a.income), a.income.reasoning, _status(a.income)],
        ["Device", _dist(a.device), a.device.reasoning, _status(a.device)],
        ["Audience temperature", _dist(a.temperature), a.temperature.reasoning,
         _status(a.temperature)],
    ]
    for e in list(a.country_split) + [x for x in
                                      (a.top_cities, a.education, a.career_stage, a.language) if x]:
        val = ", ".join(e.value) if isinstance(e.value, list) else e.value
        rows.append([e.key.replace("_", " ").title(), val or "Unavailable", e.reasoning,
                     _status(e)])
    _table(doc, ["Dimension", "Result", "Reasoning", "Status"], rows)

    doc.add_heading("Private attributes not manufactured", level=2)
    _p(doc, "Occupation, education, career-level, relationship-depth and total consumption "
            "percentages require first-party analytics or survey data. UNAVAILABLE.",
       size=9, italic=True, color=MUT)
    for label, dist in (("Occupation", a.occupation), ("Education", a.education_mix),
                        ("Career level", a.career_mix), ("Sophistication", a.sophistication),
                        ("Consumption", a.consumption)):
        if dist:
            _table(doc, [label] + list(dist.as_pct().keys()),
                   [["share"] + [f"{v}%" for v in dist.as_pct().values()]])
    extra = []
    for est in (a.states, a.english_proficiency, a.regional_language):
        if est:
            val = ", ".join(est.value) if isinstance(est.value, list) else est.value
            extra.append([est.key.replace("_", " ").title(), val or "Unavailable", est.reasoning,
                          _status(est)])
    _table(doc, ["Dimension", "Result", "Reasoning", "Status"], extra)

    if a.interests:
        doc.add_heading("Creator content topics, ranked", level=2)
        _table(doc, ["Rank", "Topic", "Share of topic signals"],
               [[i["rank"], i["topic"], f"{i['share']}%"] for i in a.interests])
    doc.add_heading("Content-need hypotheses to test", level=2)
    _table(doc, ["Dimension", "Profile"],
           [[k.replace("_", " ").title(), v] for k, v in a.psychographics.items()])
    if a.vocabulary:
        _p(doc, "Vocabulary observed in collected content metadata: " +
           " · ".join(a.vocabulary), size=9, color=MUT)
    if a.behaviours:
        doc.add_heading("Measured behaviour", level=2)
        _table(doc, ["Behaviour", "Measurement", "Why it matters"],
               [[b["label"], b["value"], b["note"]] for b in a.behaviours])
    if dx:
        doc.add_heading("Evidence ledger", level=2)
        _table(doc, ["Decision dimension", "State", "Current evidence", "Next evidence"],
               [[e.dimension, e.status.upper(), e.evidence,
                 e.unlock if e.status != "observed" else "No additional source required."]
                for e in dx.evidence_dimensions])
        if dx.topic_read:
            _callout(doc, "insight", "Content portfolio breadth", dx.topic_read)

    _agency_section(doc, p, n_prefix=n_prefix)

    doc.add_heading(f"{n_prefix}6. Content Analysis", level=1)
    if vr:
        _p(doc, (f"Scope: {vr.get('primary_accounts', vr.get('accepted_accounts', 0))} "
                 f"verified primary surface(s) plus {vr.get('related_accounts', 0)} verified "
                 "related surface(s). Each is analysed separately in section 10; unverified "
                 "candidates and independent press evidence are excluded."),
           size=8.5, italic=True, color=MUT)
    if c and c.measured_items >= 4:
        _table(doc, ["Measured items", "Collected top", "Latest/recent median", "Older sample median"],
               [[c.measured_items, f"{c.top_views:,}",
                 f"{c.current_median:,}" if c.current_median else "—",
                  f"{c.catalogue_median:,}" if c.catalogue_median else "—"]])
        if dx and dx.view_gini is not None:
            doc.add_heading("Delivery distribution and winner dependence", level=2)
            _table(doc, ["P25", "Median", "P75", "IQR", "MAD", "Gini",
                         "Top-fifth share", "Breakout rate"],
                   [[f"{dx.view_p25:,}", f"{dx.view_median:,}", f"{dx.view_p75:,}",
                     f"{dx.view_iqr:,}", f"{dx.view_mad:,}", dx.view_gini,
                     f"{dx.top20_share}%", f"{dx.breakout_rate}% at ≥ {dx.breakout_threshold:,}"]])
            _p(doc, dx.volatility_read, size=9)
        if dx and dx.title_features:
            doc.add_heading("Title construction diagnostic", level=2)
            _table(doc, ["Construction", "Rule", "Items", "Usage", "Median views", "Lift"],
                   [[x.feature, x.definition, x.items, f"{x.share}%",
                     f"{x.median_views:,}" if x.median_views is not None else "—",
                     f"{x.lift}x" if x.lift is not None else "—"] for x in dx.title_features])
            _p(doc, f"Lexical diversity {dx.lexical_diversity}. {dx.title_read}", size=8.5,
               italic=True, color=MUT)
        if c.winning_patterns:
            doc.add_heading("What works right now (age-adjusted)", level=2)
            _table(doc, ["Phrase", "Items", "Cohort lift", "Median views"],
                   [[w.phrase, w.n, f"{w.lift}x", f"{w.median_views:,}"]
                    for w in c.winning_patterns])
        if c.losing_patterns:
            doc.add_heading("What does not work", level=2)
            _table(doc, ["Phrase", "Items", "Cohort lift", "Median views"],
                   [[w.phrase, w.n, f"{w.lift}x", f"{w.median_views:,}"]
                    for w in c.losing_patterns])
        if c.catalogue_patterns:
            doc.add_heading("What built the channel (historical, not age-adjusted)", level=2)
            _table(doc, ["Phrase", "Items", "Lift", "Median views"],
                   [[w.phrase, w.n, f"{w.lift}x", f"{w.median_views:,}"]
                    for w in c.catalogue_patterns])
        doc.add_heading("Best and worst performers", level=2)
        _table(doc, ["Title", "Views", "Age (days)"],
               [[x.title[:88], f"{x.views:,}", x.age_days if x.age_days is not None else "—"]
                for x in list(c.top_performers) + list(c.worst_performers)])
        if c.format_verdict:
            _callout(doc, "insight", "Format", c.format_verdict)
        if dx and dx.format_ratio is not None:
            _callout(doc, "insight", "Non-parametric format effect", dx.format_read)
        if c.series:
            doc.add_heading("Multi-part series", level=2)
            _table(doc, ["Series", "Parts", "Part 1", "Final", "Attrition"],
                   [[s_["name"], s_["parts"], f"{s_['first_views']:,}",
                     f"{s_['last_views']:,}", f"{s_['attrition']}%"] for s_ in c.series])
        if c.promo_gap:
            _callout(doc, "risk", "Promotional markers correlate with lower sampled views",
                     f"Non-promotional titles carry a sample median of {c.organic_median:,} views; "
                     f"promotional content carries {c.promo_median:,} — a "
                     f"{round(c.promo_gap*100)}% difference. Association, not causal proof.")
        if c.seasonality_measured:
            doc.add_heading("Cadence and seasonality (measured)", level=2)
            _p(doc, f"Peak {c.peak_month}, trough {c.trough_month}, "
                    f"{c.cadence_per_month} items/month across {c.active_months} active months.",
               size=9)
            _table(doc, list(a.seasonality.keys()), [list(a.seasonality.values())])
        else:
            _p(doc, "Seasonality unavailable: an exhaustive multi-month history was not "
                    "collected. Category calendars are not substituted.", size=9,
               italic=True, color=MUT)
        if dx and dx.median_gap_days is not None:
            doc.add_heading("Publishing-system diagnostics", level=2)
            _table(doc, ["Exact-date items", "Window", "Median gap", "P90 gap", "Burstiness"],
                   [[dx.publishing_items, f"{dx.publishing_window_days} days",
                     f"{dx.median_gap_days} days", f"{dx.p90_gap_days} days", dx.burstiness]])
            _p(doc, dx.publishing_read, size=8.5, color=MUT)
    else:
        _p(doc, "Fewer than four items carried a public view count, so content analysis "
                "could not run. UNAVAILABLE.", italic=True, color=MUT)

    doc.add_heading(f"{n_prefix}7. Comment & Sentiment Analysis", level=1)
    _p(doc, p.sentiment.get("scope_note", ""), size=9, italic=True, color=MUT)
    if cm and cm.available:
        _table(doc, ["Comments analysed", "Videos", "Positive", "Neutral", "Negative",
                     "Median likes"],
               [[f"{cm.sample_size:,}", cm.videos_sampled,
                 f"{cm.sentiment.get('positive', 0)}%", f"{cm.sentiment.get('neutral', 0)}%",
                 f"{cm.sentiment.get('negative', 0)}%", cm.median_likes]])
        _table(doc, ["Unique named authors", "Author coverage", "Duplicate text",
                     "Question rate", "Top-author share"],
               [[cm.unique_authors, f"{cm.author_coverage}%", f"{cm.duplicate_rate}%",
                 f"{cm.question_rate}%",
                 f"{cm.top_author_share}%" if cm.top_author_share is not None else "—"]])
        _p(doc, cm.sample_read, size=8.5, italic=True, color=MUT)
        if cm.read:
            _callout(doc, "opportunity", "What the comments say", cm.read)
        if cm.question_themes:
            doc.add_heading("What they are asking", level=2)
            _table(doc, ["Question theme", "Share", "Example (verbatim)"],
                   [[q.label, f"{q.share}%", (q.examples[0] if q.examples else "")]
                    for q in cm.question_themes])
        if cm.top_questions:
            _p(doc, "Most-liked questions: " + " | ".join(
                f'"{q["question"]}" ({q["likes"]} likes)' for q in cm.top_questions[:6]),
               size=8.5)
        if cm.buckets:
            doc.add_heading("Intent, confusion and frustration", level=2)
            _table(doc, ["Category", "Comments", "Share", "Example (verbatim)"],
                   [[b.label, b.count, f"{b.share}% (95% CI {b.ci_low}–{b.ci_high}%)",
                     (b.examples[0] if b.examples else "")]
                    for b in cm.buckets])
        if cm.vocabulary:
            _p(doc, "Audience vocabulary: " + " · ".join(
                f"{v['word']} ({v['count']})" for v in cm.vocabulary[:18]), size=8.5)
        if cm.inside_jokes:
            _p(doc, "Recurring in-group phrases: " + " · ".join(
                f"{j['phrase']} ({j['count']})" for j in cm.inside_jokes[:8]), size=8.5)
        if cm.most_liked:
            doc.add_heading("Most-liked comments", level=2)
            _table(doc, ["Comment", "Likes"],
                   [[m["text"], m["likes"]] for m in cm.most_liked])
    if p.sentiment.get("verbatim_available"):
        _table(doc, ["Theme", "Frequency", "Share", "Representative quote"],
               [[t["theme"], t["frequency"], f"{t['share']}%", t["quote"]]
                for t in p.sentiment["themes"]])
        if p.sentiment.get("read"):
            _callout(doc, "opportunity", "The marketing implication", p.sentiment["read"])
    else:
        _p(doc, "No verbatim public review text found; platform comment threads require "
                "authentication. Sentiment is UNAVAILABLE rather than modelled.", size=9)

    doc.add_heading(f"{n_prefix}8. Competitor Landscape", level=1)
    if p.competitors and getattr(p.competitors, "assessed", False):
        _p(doc, p.competitors.verdict, size=10, bold=True)
        _table(doc, ["Account", "Followers", "vs subject", "Content overlap",
                     "Topic/stage affinity", "Strength", "Weakness"],
               [[f"{cp.display_name or cp.handle} (@{cp.handle}, {cp.platform})",
                 f"{cp.followers:,}" if cp.followers else (cp.note or "—"),
                 cp.size_vs_subject or "—",
                 f"{cp.content_overlap}%" if cp.content_overlap is not None else "—",
                 cp.audience_overlap or "—", cp.strength, cp.weakness]
                for cp in p.competitors.competitors])
    else:
        _p(doc, getattr(p.competitors, "reason", "Competitor discovery not enabled for this "
                        "run.") if p.competitors else
                "Competitor discovery not enabled for this run.", size=9, italic=True)

    doc.add_heading(f"{n_prefix}9. SEO & Discoverability", level=1)
    if s and s.assessed:
        _p(doc, s.verdict, size=10, bold=True)
        _table(doc, ["Grade", "Owns page one", "Name collision", "Owned properties"],
               [[s.grade, s.owns_page_one, s.collision_risk, len(s.owned_properties)]])
        if dx and dx.serp_results:
            doc.add_heading("Branded SERP control diagnostics", level=2)
            _table(doc, ["Owned/platform top 3", "Owned/platform top 10",
                         "First controlled rank", "Reciprocal rank", "Collisions"],
                   [[f"{dx.owned_top3}/3", f"{dx.owned_top10}/{dx.serp_results}",
                     dx.first_owned_rank or "—", dx.reciprocal_rank, dx.collision_count]])
            _p(doc, dx.serp_read, size=8.5, color=MUT)
        if s.competing_entities:
            _p(doc, "Competing for this name: " + "; ".join(s.competing_entities), size=9)
    else:
        _p(doc, getattr(s, "reason_not_assessed", ""), size=9, italic=True, color=MUT)
    if s and s.intent_clusters:
        _table(doc, ["Cluster", "Share", "Intent", "Commercial value", "Gap"],
               [[i["cluster"], f"{i['share']}%", i["intent"], i["value"], i["gap"]]
                for i in s.intent_clusters])
    if s and s.keyword_footprint:
        _p(doc, "Declared keywords: " + " · ".join(s.keyword_footprint), size=8.5, color=MUT)
        _p(doc, s.keyword_note, size=9)
    if s and s.related_searches:
        doc.add_heading("What people actually search for (keyless)", level=2)
        _p(doc, s.autocomplete_note, size=9)
        _p(doc, " · ".join(s.related_searches), size=8.5, color=MUT)
        if s.autocomplete_intents:
            _table(doc, ["Search intent", "Queries", "Share", "Examples"],
                   [[i["intent"], i["count"], f"{i['share']}%", ", ".join(i["examples"])]
                    for i in s.autocomplete_intents])
    kl = p.raw.keyless or {}
    if kl.get("wikipedia_title") or kl.get("podcasts") or kl.get("wikidata_id"):
        doc.add_heading("Off-platform footprint (keyless)", level=2)
        if kl.get("wikidata_id"):
            desc = (f" {kl['wikidata_description']}" if kl.get("wikidata_description") else "")
            _p(doc, f"Wikidata — {kl['wikidata_id']}. Structured public claims, not a login-walled page reading.{desc}",
               size=9)
        if kl.get("image_url"):
            src = kl.get("image_source") or "wikimedia"
            _p(doc, f"Portrait — {kl['image_url']} ({src}). Official Wikimedia image, not an Instagram avatar.",
               size=9)
        if kl.get("wikipedia_title"):
            _p(doc, f"Wikipedia — {kl['wikipedia_title']}: {kl.get('wikipedia_extract','')}",
               size=9)
            for sec in (kl.get("wikipedia_sections") or [])[:4]:
                title = (sec or {}).get("title") or ""
                body = (sec or {}).get("extract") or ""
                if title and body:
                    _p(doc, f"{title} — {body}", size=9)
        if kl.get("podcasts"):
            _table(doc, ["Podcast", "Type", "Publisher", "Released"],
                   [[x["title"], x["kind"], x.get("publisher") or "—",
                     x.get("released") or "—"] for x in kl["podcasts"]])

    doc.add_heading(f"{n_prefix}10. Platform-by-Platform Analysis", level=1)
    for pl in p.platforms:
        doc.add_heading(f"{pl.platform.title()}"
                        + (f" — @{pl.handle}" if pl.handle else "")
                        + f" — {pl.relationship.replace('_', ' ').title()}", level=2)
        if pl.status != "analysed":
            _p(doc, f"{pl.status.upper()}: {pl.note}", size=9, italic=True, color=MUT)
        rows = [
            ["Positioning", pl.positioning],
            ["Follower authenticity", f"{pl.follower_quality} — {pl.follower_note}"],
            ["Engagement evidence", f"{pl.engagement_quality} — {pl.engagement_note}"],
            ["Community evidence", f"{pl.community_strength} — {pl.community_note}"],
            ["Historical view dispersion", f"{pl.virality} — {pl.virality_note}"],
        ]
        if pl.posting_frequency:
            rows.append(["Posting frequency", pl.posting_frequency])
        if pl.content_categories:
            rows.append(["Content categories", " · ".join(
                f"{x['category']} {x['share']}%" for x in pl.content_categories)])
        if pl.tone:
            rows.append(["Tone", " · ".join(f"{x['tone']} {x['share']}%" for x in pl.tone)])
        if pl.hooks:
            rows.append(["Hooks", " · ".join(
                f"{x['hook']} ({x['share']}%)" for x in pl.hooks)])
        if pl.ctas:
            rows.append(["Calls to action", " · ".join(
                f"{x['cta']} ({x['mentions']})" for x in pl.ctas)])
        if pl.hashtags:
            rows.append(["Hashtags", " ".join(x["tag"] for x in pl.hashtags)])
        rows.append(["Visual style", pl.visual_style])
        if pl.storytelling:
            rows.append(["Storytelling", pl.storytelling])
        rows.append(["SEO", pl.seo_note])
        _table(doc, ["Attribute", "Detail"], rows)

    doc.add_heading(f"{n_prefix}11. Brand Analysis", level=1)
    if br:
        _p(doc, br.perception, size=10, bold=True)
        _table(doc, ["Pillar", "Score", "Evidence", "Reading"],
               [[x.name, f"{x.score}/10", "; ".join(x.evidence) or "—", x.why]
                for x in br.pillars])
        _p(doc, "Brand promise: " + br.promise, size=9.5, bold=True)
        _table(doc, ["Proof points"], [[x] for x in br.proof])
        if br.personality:
            _p(doc, "Personality: " + " · ".join(
                f"{x['trait']} {x['share']}%" for x in br.personality), size=9)
        if br.voice:
            _p(doc, "Voice: " + " · ".join(
                f"{v['axis']} reads {v['reads']}" for v in br.voice), size=9)
        doc.add_heading("SWOT", level=2)
        _table(doc, ["Strengths", "Weaknesses"],
               [["\n".join("• " + x for x in br.swot.get("strengths", [])),
                 "\n".join("• " + x for x in br.swot.get("weaknesses", []))]])
        _table(doc, ["Opportunities", "Threats"],
               [["\n".join("• " + x for x in br.swot.get("opportunities", [])),
                 "\n".join("• " + x for x in br.swot.get("threats", []))]])
        _p(doc, f"Positioning: {br.position_note} {br.consistency}", size=9, color=MUT)

    doc.add_heading(f"{n_prefix}12. Growth Analysis", level=1)
    if gr and gr.measurable:
        _p(doc, gr.trend_note, size=10, bold=True)
        _table(doc, ["Era", "Window", "Items", "Median views", "Median length", "Topics"],
               [[e.label, f"{e.start} – {e.end}", e.items, f"{e.median_views:,}",
                 f"{e.median_duration_min} min" if e.median_duration_min else "—",
                 ", ".join(e.top_topics)] for e in gr.eras])
        _table(doc, ["Quarter", "Items", "Median views"],
               [[x["period"], x["items"], f"{x['median_views']:,}"] for x in gr.trajectory])
        for label, val in (("Content evolution", gr.content_evolution),
                           ("Audience evolution", gr.audience_evolution),
                           ("Brand evolution", gr.brand_evolution)):
            if val:
                _callout(doc, "insight", label, val)
    elif gr:
        _p(doc, gr.reason, size=9, italic=True, color=MUT)
    if gr and gr.bottlenecks:
        doc.add_heading("Growth bottlenecks", level=2)
        _table(doc, ["Bottleneck", "Evidence", "Effect"],
               [[b["bottleneck"], b["evidence"], b["effect"]] for b in gr.bottlenecks])
    if gr and gr.missed:
        doc.add_heading("Missed opportunities", level=2)
        _table(doc, ["Missed", "Evidence"],
               [[m["missed"], m.get("evidence", "")] for m in gr.missed])
    if gr and gr.future:
        doc.add_heading("Future plays", level=2)
        _table(doc, ["Play", "Why now"], [[x["play"], x["why"]] for x in gr.future])

    doc.add_heading(f"{n_prefix}13. Marketing Funnel Assessment", level=1)
    _p(doc, "Public offer and routing evidence. Conversion, revenue and retention remain "
       "unavailable without first-party data.", size=9, italic=True, color=MUT)
    _table(doc, ["Evidence rubric", "Price rungs", "Permissioned channels", "Verified list/CRM"],
           [[f"{f.total}/70", len(f.rungs), len(f.permissioned_channels),
             "yes" if f.owned_audience else "not observed"]])
    if dx:
        doc.add_heading("Offer architecture and routing diagnostics", level=2)
        _table(doc, ["Observed SKUs", "Priced SKUs", "Log price span",
                     "Largest adjacent gap", "Routing evidence coverage"],
               [[dx.sku_count, dx.priced_sku_count,
                 dx.log_price_span if dx.log_price_span is not None else "—",
                 f"{dx.max_adjacent_price_gap}x" if dx.max_adjacent_price_gap else "—",
                 f"{dx.route_readiness}/100"]])
        _table(doc, ["Component", "Observed", "Weight"],
               [[x["component"], "yes" if x["observed"] else "no", x["weight"]]
                for x in dx.route_components])
        _p(doc, dx.offer_read, size=8.5, italic=True, color=MUT)
    _table(doc, ["Stage", "Detail"], [[st["stage"], st["detail"]] for st in f.stages])
    _p(doc, "Stage order is illustrative; no conversion rate or drop-off was measured.",
       size=8, italic=True, color=MUT)
    if f.rungs:
        doc.add_heading("Observed price ladder", level=2)
        _table(doc, ["Tier", "Product", "Price"],
               [[r.tier, r.name, f"₹{int(r.price_inr):,}"] for r in f.rungs])
    doc.add_heading("Evidence-coverage rubric", level=2)
    _table(doc, ["Dimension", "Score", "Reasoning"],
           [[sc.dimension, f"{sc.value}/10", sc.why] for sc in f.scores])
    _callout(doc, "opportunity", "Strongest", f.strength)
    _callout(doc, "risk", "Weakest", f.gap)

    doc.add_heading(f"{n_prefix}14. Audience Personas", level=1)
    for pe in a.personas:
        doc.add_heading(f"{pe.name} — {pe.tag}", level=2)
        _table(doc, ["Attribute", "Detail"],
               [["Status", f"Hypothesis · {round(pe.confidence*100)}% · {pe.basis}"],
                ["Goal", pe.goal], ["Pain", pe.pain], ["Watches", pe.watches],
                ["Buys", pe.buys], ["Also on", pe.also_on], ["Reach them with", pe.reach_with]])

    doc.add_heading(f"{n_prefix}15. Growth Opportunities", level=1)
    _table(doc, ["Area", "Opportunity", "Effort", "Impact"],
           [[o["area"], o["what"], o["effort"], o["impact"]] for o in p.opportunities])

    doc.add_heading(f"{n_prefix}16. Strategic Recommendations", level=1)
    _table(doc, ["Priority", "Who", "Do this", "Because"],
           [[r["priority"], r["who"], r["what"], r["why"]] for r in p.recommendations])
    _table(doc, ["If you are…", "Then"], [[x["who"], x["do"]] for x in a.activation])
    if dx:
        doc.add_heading("Decision-gate validation register", level=2)
        _table(doc, ["Blocked dimension", "Why insufficient", "Required evidence"],
               [[e.dimension, e.evidence, e.unlock] for e in dx.evidence_dimensions
                if e.status in ("unavailable", "modelled")])

    doc.add_heading(f"{n_prefix}17. Appendix: Method, Limits & Sources", level=1)
    _table(doc, ["Label", "Meaning"], [
        ["OBSERVED", "Read from a public page or supplied first-party analytics. No inference."],
        ["CALCULATED", "Arithmetic or classification over observed inputs; scope is stated."],
        ["MODELLED n%", "Directional hypothesis from content-stage evidence; verify before use."],
        ["UNAVAILABLE", "Not obtainable publicly. Not modelled, not guessed."]])
    if vr:
        doc.add_heading("Verification ledger", level=2)
        _p(doc, (f"{vr.get('query_count', 0)} purpose-labelled discovery queries; "
                 f"{vr.get('provider_count', 0)} licensed search providers; "
                 f"{vr.get('independent_source_count', 0)} independent hosts. "
                 "Search results discover candidates but do not prove ownership."),
           size=8.5, color=MUT)
        _table(doc, ["Claim", "Value used", "Status", "Confidence", "Method / conflict"],
               [[x.get("key"), x.get("value"), x.get("status"),
                 f"{round(x.get('confidence', 0)*100)}%",
                 x.get("conflict") or x.get("method")]
                for x in vr.get("claims", [])])
        if vr.get("conflicts"):
            _table(doc, ["Conflict type", "Claim", "What disagreed"],
                   [[x.get("type"), x.get("claim"), x.get("detail")]
                    for x in vr["conflicts"]])
    if dx:
        doc.add_heading("Formula glossary", level=2)
        _table(doc, ["Metric", "Formula", "Permitted interpretation"],
               [[x["metric"], x["formula"], x["use"]] for x in dx.formula_glossary])
        doc.add_heading("Source independence", level=2)
        _p(doc, dx.source_read, size=8.5, color=MUT)
    _table(doc, ["Data", "Why", "How you could get it"],
           [[u["data"], u["why"], u["how"]] for u in a.unavailable])
    _p(doc, "Sources: " + " · ".join(acc.url for acc in p.raw.accounts), size=8, color=MUT)
    _p(doc, f"Signals fired ({len(a.signals_fired)}): " + ", ".join(a.signals_fired),
       size=8, color=MUT)
    _p(doc, "Compliance: generated only from public information. No account was logged into, "
            "no authentication bypassed, no CAPTCHA solved; robots.txt honoured throughout. "
            "Login-walled data is analyst-supplied or left explicitly unavailable — never "
            "fabricated.", size=8.5, italic=True, color=MUT)


def render(payload: ReportPayload, path: str) -> str:
    doc = Document()
    _style(doc)
    _p(doc, "AUDIENCE INTELLIGENCE REPORT", size=9, bold=True, color=ACC, after=8)
    h = doc.add_heading(payload.subject_name, level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _p(doc, f"{payload.subject_handle} · {payload.audience.archetype_label}",
       size=10, italic=True, color=MUT, after=10)
    _p(doc, (f"Generated {payload.generated_at:%d %B %Y %H:%M} UTC · engine "
             f"v{payload.engine_version} · life-stage model confidence "
             f"{round(payload.audience.overall_confidence*100)}% · "
             f"{len(payload.audience.signals_fired)} signals · "
             f"{len(payload.raw.accounts)} surfaces"), size=8.5, color=MUT, after=14)
    _creator_body(doc, payload)
    doc.save(path)
    return path


def render_cohort(cp: CohortPayload, path: str) -> str:
    doc = Document()
    _style(doc)
    co = cp.cohort
    _p(doc, f"360° AUDIENCE INTELLIGENCE · {len(cp.reports)} CREATORS",
       size=9, bold=True, color=ACC, after=8)
    doc.add_heading(co.headline if co else cp.title, level=0)
    if co:
        _p(doc, co.lede, size=12, after=12)
    _p(doc, (f"Generated {cp.generated_at:%d %B %Y %H:%M} UTC · engine v{cp.engine_version} · "
             f"summed public follows {co.total_audience:,} (duplicates unknown)" if co else ""),
       size=8.5, color=MUT)

    if co:
        doc.add_heading("Cohort Summary", level=1)
        for f in co.findings:
            _callout(doc, f["kind"], f["title"], f["body"])
        doc.add_heading("Side by side", level=2)
        _table(doc, ["Creator", "Summed follows", "Modelled/observed life-stage", "M/F",
                     "Income", "Language", "Platform", "Price ceiling", "Peak", "Stage conf."],
               [[m["name"], m["audience"], m["modal_age"], m["gender"], m["income_modal"],
                 m["language"], m["primary_platform"], m["price_ceiling"], m["peak_month"],
                 m["confidence"]] for m in co.matrix])
        doc.add_heading("Follower overlap and topic affinity", level=2)
        _table(doc, ["Pair", "Follower overlap", "Affinity hypothesis", "Topic similarity"],
               [[f"{o.a} x {o.b}", "UNAVAILABLE", o.mechanism,
                 f"{o.topic_similarity}% (modelled)"]
                for o in co.overlaps])
        doc.add_heading("Lifecycle position", level=2)
        _table(doc, ["Creator", "Median age", "Modal band", "Archetype"],
               [[l["name"], l["median_age"], l["modal_band"], l["archetype"]]
                for l in co.lifecycle])
        doc.add_heading("Pilot diligence", level=2)
        _table(doc, ["Creator", "Public evidence", "Efficiency", "Ceiling", "Recommendation"],
               [[v.name, v.best_for, v.efficiency, v.scale_ceiling, v.recommendation]
                for v in co.verdicts])

    for i, p in enumerate(cp.reports, start=1):
        doc.add_page_break()
        _p(doc, f"CREATOR {i:02d} · {p.audience.archetype_label}",
           size=9, bold=True, color=ACC, after=6)
        doc.add_heading(p.subject_name, level=0)
        _p(doc, p.subject_handle, size=10, italic=True, color=MUT, after=10)
        _creator_body(doc, p, n_prefix=f"{i}.")
    doc.save(path)
    return path
