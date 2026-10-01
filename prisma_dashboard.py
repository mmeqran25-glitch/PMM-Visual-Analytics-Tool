from __future__ import annotations

from collections import Counter
from io import BytesIO
import html

import pandas as pd
import streamlit as st

APP_VERSION = "v0.14.8-prisma"
REQUIRED_MASTER_COLUMNS = {
    "Study ID",
    "Identification Source",
    "Duplicate Status",
    "Title/Abstract Decision",
    "Full Text Available",
    "Full-Text Decision",
    "Full-Text Exclusion Reason",
    "Temporal Eligibility Decision",
}
ELIGIBLE_TEMPORAL = {
    "Eligible – within temporal window",
    "Eligible – foundational exception",
}
ADVANCE_TA = {
    "Include for Full-Text Screening",
    "Unclear – Proceed to Full Text",
}

PRISMA_CSS = """
<style>
.block-container {padding-top:1.4rem; padding-bottom:3rem; max-width:1550px;}
:root {--navy:#12385e; --teal:#0f6b78; --gold:#b99236; --line:#d8e3ec;}
.prisma-hero {border:1px solid #d5e1eb;border-radius:20px;padding:18px 22px;background:linear-gradient(135deg,#fbfdff,#f5f9fc 58%,#fff);box-shadow:0 8px 24px rgba(18,56,94,.07);margin-bottom:1rem;}
.prisma-hero .k {font-size:.76rem;font-weight:850;letter-spacing:.08em;text-transform:uppercase;color:#0f6b78;}
.prisma-hero h1 {margin:.2rem 0 .2rem;color:#12385e;font-size:1.8rem;}
.prisma-hero .s {color:#60758a;font-size:.92rem;}
.stage-band {border-left:5px solid #12385e;background:#f5f9fd;border-radius:11px;padding:9px 13px;font-weight:850;color:#12385e;margin:1rem 0 .55rem;}
.audit-ok {border-left:5px solid #238636;background:#f1fbf4;border-radius:10px;padding:10px 13px;margin:.6rem 0;}
.audit-warn {border-left:5px solid #d29922;background:#fff9e8;border-radius:10px;padding:10px 13px;margin:.6rem 0;}
.prisma-note {border-left:5px solid #4c83b6;background:#f5f9fd;border-radius:10px;padding:10px 13px;margin:.6rem 0;color:#38556d;}
[data-testid="stMetric"] {border:1px solid #dce6ee;background:#fff;padding:10px 12px;border-radius:13px;}
[data-testid="stMetricValue"] {color:#12385e;}
div.stButton > button {border-radius:12px;min-height:78px;font-weight:800;white-space:pre-line;border:1px solid #b9cbd9;background:#fff;color:#12385e;}
div.stButton > button:hover {border-color:#0f6b78;background:#f5fbfc;}
</style>
"""
def _clean_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _read_sheet(file_bytes: bytes, sheet_name: str, header=0) -> pd.DataFrame:
    return pd.read_excel(BytesIO(file_bytes), sheet_name=sheet_name, header=header)


@st.cache_data(show_spinner=False)
def load_prisma_workbook(file_bytes: bytes) -> dict:
    xls = pd.ExcelFile(BytesIO(file_bytes))
    if "Master Screening" not in xls.sheet_names:
        raise ValueError("Required sheet 'Master Screening' was not found.")
    if "Search Log" not in xls.sheet_names:
        raise ValueError("Required sheet 'Search Log' was not found.")

    master = _read_sheet(file_bytes, "Master Screening", header=0)
    missing = REQUIRED_MASTER_COLUMNS - set(master.columns)
    if missing:
        raise ValueError("Missing Master Screening columns: " + ", ".join(sorted(missing)))

    search = _read_sheet(file_bytes, "Search Log", header=3)
    return {"master": master, "search": search, "sheet_names": xls.sheet_names}


def _normalize_ft_reason(reason: str) -> str:
    text = _clean_text(reason).lower()
    if not text:
        return "Unspecified"
    if "language criterion" in text:
        return "Language criterion"
    if "temporal" in text or "publication year" in text or "outside the 2016" in text:
        return "Temporal criterion"
    if "resilience level" in text or "organizational resilience" in text or "infrastructure-network resilience" in text:
        return "Wrong resilience level / construct"
    return "Construct / scope mismatch"


def calculate_prisma(data: dict, file_bytes: bytes) -> dict:
    master = data["master"].copy()
    search = data["search"].copy()

    master = master[master["Study ID"].notna()].copy()
    master["Study ID"] = master["Study ID"].astype(str).str.strip()

    completed = search[search["Search Status"].astype(str).str.strip().eq("Completed")].copy()
    for col in ["Records Identified", "Marked Ineligible by Automation", "Removed for Other Reasons Before Screening"]:
        if col in completed.columns:
            completed[col] = pd.to_numeric(completed[col], errors="coerce").fillna(0)

    seed_mask = master["Identification Source"].astype(str).str.contains(
        "Previously downloaded", case=False, na=False
    )
    seed_records = int(seed_mask.sum())
    formal_raw = int(completed.get("Records Identified", pd.Series(dtype=float)).sum())
    raw_total = seed_records + formal_raw

    dup_mask = master["Duplicate Status"].astype(str).str.strip().eq("Duplicate – removed")
    active = master.loc[~dup_mask].copy()
    screened = int(active["Title/Abstract Decision"].notna().sum())
    ta_excluded = int(active["Title/Abstract Decision"].astype(str).str.strip().eq("Exclude").sum())

    advancing = active[active["Title/Abstract Decision"].astype(str).str.strip().isin(ADVANCE_TA)].copy()
    temporal = advancing["Temporal Eligibility Decision"].astype(str).str.strip()
    eligible = advancing[temporal.isin(ELIGIBLE_TEMPORAL)].copy()
    pre_retrieval_excluded = int(temporal.str.startswith("Exclude", na=False).sum())

    automation_removed = int(completed.get("Marked Ineligible by Automation", pd.Series(dtype=float)).sum())
    other_removed = int(completed.get("Removed for Other Reasons Before Screening", pd.Series(dtype=float)).sum())
    duplicates_removed = raw_total - screened - automation_removed - other_removed
    removed_before = duplicates_removed + automation_removed + other_removed

    ft_raw = eligible["Full Text Available"]
    ft_available = ft_raw.astype(str).str.strip()
    ft_decision = eligible["Full-Text Decision"].astype(str).str.strip()
    ft_missing = ft_raw.isna() | ft_available.isin(["", "nan", "None"])
    not_retrieved = int(ft_available.eq("No").sum())
    assessed = int(ft_available.eq("Yes").sum())
    outstanding = int(ft_missing.sum())
    included = int(ft_decision.eq("Include").sum())
    excluded = int(ft_decision.eq("Exclude").sum())

    ta_decision = active["Title/Abstract Decision"].astype(str).str.strip()
    row_groups = {
        "screened": active.loc[active["Title/Abstract Decision"].notna()].copy(),
        "ta_excluded": active.loc[ta_decision.eq("Exclude")].copy(),
        "pre_retrieval": advancing.loc[temporal.str.startswith("Exclude", na=False)].copy(),
        "eligible": eligible.copy(),
        "not_retrieved": eligible.loc[ft_available.eq("No")].copy(),
        "assessed": eligible.loc[ft_available.eq("Yes")].copy(),
        "outstanding": eligible.loc[ft_missing].copy(),
        "included": eligible.loc[ft_decision.eq("Include")].copy(),
        "ft_excluded": eligible.loc[ft_decision.eq("Exclude")].copy(),
    }

    reason_counts = Counter(
        _normalize_ft_reason(v)
        for v in eligible.loc[ft_decision.eq("Exclude"), "Full-Text Exclusion Reason"].tolist()
    )

    source_breakdown = []
    if "Database / Register" in completed.columns:
        src = completed.groupby("Database / Register", dropna=False)["Records Identified"].sum().sort_values(ascending=False)
        source_breakdown = [(str(k), int(v)) for k, v in src.items() if pd.notna(k)]

    classification_counts = Counter()
    for sheet in data["sheet_names"]:
        if not str(sheet).endswith(" Results"):
            continue
        try:
            df = _read_sheet(file_bytes, sheet, header=3)
        except Exception:
            continue
        class_cols = [c for c in df.columns if isinstance(c, str) and "Classification" in c]
        if not class_cols:
            continue
        col = class_cols[0]
        classification_counts.update(_clean_text(v) for v in df[col].dropna().tolist())

    global_duplicate_rows = int(dup_mask.sum())
    duplicate_detail = {
        "Re-identified existing seed": int(classification_counts.get("Re-identified Existing Seed", 0)),
        "Duplicate export versions": int(classification_counts.get("Duplicate export version", 0)),
        "Duplicate prior formal searches": int(classification_counts.get("Duplicate prior formal search", 0)),
        "Global duplicate Study IDs": global_duplicate_rows,
    }

    stream_summary = []
    if "Search Stream" in eligible.columns:
        for stream, grp in eligible.groupby("Search Stream", dropna=False):
            stream_summary.append({
                "Stream": _clean_text(stream) or "Unspecified",
                "Eligible for retrieval": len(grp),
                "Not retrieved": int(grp["Full Text Available"].astype(str).str.strip().eq("No").sum()),
                "Outstanding": int(grp["Full Text Available"].isna().sum()),
                "Assessed": int(grp["Full Text Available"].astype(str).str.strip().eq("Yes").sum()),
                "Included": int(grp["Full-Text Decision"].astype(str).str.strip().eq("Include").sum()),
                "Excluded": int(grp["Full-Text Decision"].astype(str).str.strip().eq("Exclude").sum()),
            })

    checks = {
        "Raw = removed before screening + screened": raw_total == removed_before + screened,
        "Screened = TA excluded + pre-retrieval excluded + eligible": screened == ta_excluded + pre_retrieval_excluded + len(eligible),
        "Eligible = not retrieved + assessed + outstanding": len(eligible) == not_retrieved + assessed + outstanding,
        "Assessed = included + excluded": assessed == included + excluded,
        "Duplicate audit detail = duplicate total": sum(duplicate_detail.values()) == duplicates_removed,
    }

    return {
        "seed_records": seed_records,
        "formal_raw": formal_raw,
        "raw_total": raw_total,
        "automation_removed": automation_removed,
        "other_removed": other_removed,
        "duplicates_removed": duplicates_removed,
        "removed_before": removed_before,
        "screened": screened,
        "ta_excluded": ta_excluded,
        "pre_retrieval_excluded": pre_retrieval_excluded,
        "eligible": len(eligible),
        "not_retrieved": not_retrieved,
        "assessed": assessed,
        "outstanding": outstanding,
        "included": included,
        "excluded": excluded,
        "reason_counts": reason_counts,
        "source_breakdown": source_breakdown,
        "duplicate_detail": duplicate_detail,
        "stream_summary": stream_summary,
        "row_groups": row_groups,
        "checks": checks,
        "status": "FINAL" if outstanding == 0 else "OPEN / INTERIM",
    }


def _stage_button(
    label: str,
    value: int,
    focus_key: str,
    note: str = "",
    element_key: str | None = None,
) -> None:
    """Render a clickable PRISMA box with a unique Streamlit widget identity."""
    text = f"{label}\n(n = {value:,})"
    if note:
        text += f"\n{note}"

    # focus_key controls the analytical drill-down; element_key only makes
    # the visual widget unique when the same analytical population is shown twice.
    widget_key = element_key or focus_key
    if st.button(
        text,
        key=f"prisma_box_{widget_key}",
        use_container_width=True,
    ):
        st.session_state["prisma_focus"] = focus_key
        st.rerun()

def _arrow() -> None:
    st.markdown(
        "<div style='text-align:center;font-size:1.55rem;color:#4c83b6;line-height:1.1'>↓</div>",
        unsafe_allow_html=True,
    )


def _display_record_table(df: pd.DataFrame, key_prefix: str) -> None:
    if df is None or df.empty:
        st.info("No study records are available for this box.")
        return

    view = df.copy()
    if "Search Stream" in view.columns:
        streams = sorted([x for x in view["Search Stream"].dropna().astype(str).unique().tolist() if x])
        if streams:
            selected = st.multiselect(
                "Filter by stream",
                streams,
                default=streams,
                key=f"{key_prefix}_stream_filter",
            )
            if selected:
                view = view[view["Search Stream"].astype(str).isin(selected)]

    search_text = st.text_input(
        "Search Study ID / title",
        key=f"{key_prefix}_record_search",
        placeholder="e.g., SR058 or maturity",
    ).strip().lower()
    if search_text:
        sid = view["Study ID"].astype(str).str.lower() if "Study ID" in view.columns else pd.Series("", index=view.index)
        title = view["Title"].astype(str).str.lower() if "Title" in view.columns else pd.Series("", index=view.index)
        view = view[sid.str.contains(search_text, na=False) | title.str.contains(search_text, na=False)]

    preferred = [
        "Study ID",
        "Title",
        "Authors",
        "Year",
        "Search Stream",
        "Identification Source",
        "Title/Abstract Exclusion Reason",
        "Temporal Eligibility Decision",
        "Full Text Available",
        "Full-Text Decision",
        "Full-Text Exclusion Reason",
        "Final Inclusion Status",
    ]
    cols = [c for c in preferred if c in view.columns]
    st.caption(f"Showing {len(view):,} study record(s).")
    st.dataframe(view[cols], use_container_width=True, hide_index=True, height=430)


def render_flow(m: dict) -> None:
    st.markdown('<div class="stage-band">IDENTIFICATION</div>', unsafe_allow_html=True)
    left, right = st.columns([1, 1])
    with left:
        st.caption("PRISMA 2020 identification route")
        _stage_button("Records identified from databases / registers", m["formal_raw"], "identification")
    with right:
        st.caption("Review-specific transparency box")
        _stage_button(
            "Historical seed records — original identification route undocumented",
            m["seed_records"],
            "seed",
            "Extension",
        )

    _arrow()
    _stage_button("Total records identified in the review database", m["raw_total"], "raw_total")
    _arrow()

    main, side = st.columns([1.35, 1])
    with main:
        _stage_button(
            "Records remaining for screening",
            m["screened"],
            "screened",
            element_key="screened_remaining",
        )
    with side:
        st.caption("Removed before screening")
        _stage_button("Records removed before screening", m["removed_before"], "removed")
        st.caption(
            f"Duplicates {m['duplicates_removed']:,} · Automation {m['automation_removed']:,} · Other {m['other_removed']:,}"
        )

    st.markdown('<div class="stage-band">SCREENING</div>', unsafe_allow_html=True)
    main, side = st.columns([1.35, 1])
    with main:
        _stage_button("Records screened", m["screened"], "screened")
    with side:
        _stage_button("Records excluded", m["ta_excluded"], "ta_excluded", "Title / abstract")
    _arrow()

    main, side = st.columns([1.35, 1])
    with main:
        _stage_button(
            "Reports sought for retrieval",
            m["eligible"],
            "eligible",
            element_key="eligible_after_screening",
        )
    with side:
        st.caption("Review-specific eligibility gate")
        _stage_button(
            "Records excluded before retrieval",
            m["pre_retrieval_excluded"],
            "pre_retrieval",
            "Temporal / foundational eligibility · Extension",
        )

    st.markdown('<div class="stage-band">RETRIEVAL & ELIGIBILITY</div>', unsafe_allow_html=True)
    main, side = st.columns([1.35, 1])
    with main:
        _stage_button("Reports sought for retrieval", m["eligible"], "eligible")
    with side:
        _stage_button("Reports not retrieved", m["not_retrieved"], "not_retrieved")
    _arrow()

    main, side = st.columns([1.35, 1])
    with main:
        _stage_button("Reports assessed for eligibility", m["assessed"], "assessed")
    with side:
        _stage_button("Reports excluded after full-text assessment", m["excluded"], "ft_excluded")

    if m["outstanding"] > 0:
        st.markdown(
            f'<div class="audit-warn"><b>Open workflow status — not a final PRISMA box:</b> '
            f'{m["outstanding"]:,} reports remain without a documented retrieval/full-text outcome. '
            'The diagram is therefore an interim research-workflow snapshot.</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            f"Open outstanding records (n = {m['outstanding']:,})",
            key="prisma_box_outstanding",
            use_container_width=True,
        ):
            st.session_state["prisma_focus"] = "outstanding"
            st.rerun()

    st.markdown('<div class="stage-band">INCLUDED — CURRENT INTERIM STATUS</div>', unsafe_allow_html=True)
    _stage_button(
        "Study records currently included after full-text assessment",
        m["included"],
        "included",
        "Interim while retrieval remains open" if m["outstanding"] else "Current completed flow",
    )


def render_focus(m: dict) -> None:
    focus = st.session_state.get("prisma_focus", "removed")
    titles = {
        "identification": "Records identified from databases / registers",
        "seed": "Historical seed records",
        "raw_total": "All identification routes",
        "removed": "Records removed before screening",
        "screened": "Records screened",
        "ta_excluded": "Title / abstract exclusions",
        "pre_retrieval": "Pre-retrieval eligibility exclusions",
        "eligible": "Reports sought for retrieval",
        "not_retrieved": "Reports not retrieved",
        "assessed": "Reports assessed for eligibility",
        "outstanding": "Outstanding retrieval / full-text processing",
        "included": "Currently included study records",
        "ft_excluded": "Full-text exclusions",
    }
    st.markdown(f"### Drill-down · {titles.get(focus, focus)}")

    if focus in {"identification", "raw_total"}:
        df = pd.DataFrame(m["source_breakdown"], columns=["Database / Register", "Raw records identified"])
        if m["seed_records"]:
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        [{
                            "Database / Register": "Historical seed corpus — original source undocumented",
                            "Raw records identified": m["seed_records"],
                        }]
                    ),
                ],
                ignore_index=True,
            )
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(
            "Raw identification totals are search-run counts. Duplicate raw hits do not all have a canonical Study ID, so study-level drill-down begins after canonicalisation."
        )
        return

    if focus == "seed":
        st.info(
            f"Historical seed corpus: {m['seed_records']:,} records. The original discovery route is deliberately left undocumented rather than retrospectively assigned to a database."
        )
        return

    if focus == "removed":
        st.dataframe(
            pd.DataFrame(
                [
                    {"Removal category": "Duplicate records", "n": m["duplicates_removed"]},
                    {"Removal category": "Marked ineligible by automation", "n": m["automation_removed"]},
                    {"Removal category": "Other reasons before screening", "n": m["other_removed"]},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("**Duplicate audit decomposition**")
        st.dataframe(
            pd.DataFrame([{"Duplicate pathway": k, "n": v} for k, v in m["duplicate_detail"].items()]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "The duplicate total reconciles across re-identified seed hits, duplicate export versions, prior formal-search duplicates, and globally removed duplicate Study IDs."
        )
        return

    rows = m.get("row_groups", {}).get(focus, pd.DataFrame())

    if focus == "ta_excluded" and not rows.empty and "Title/Abstract Exclusion Reason" in rows.columns:
        reasons = (
            rows["Title/Abstract Exclusion Reason"]
            .fillna("Unspecified")
            .astype(str)
            .value_counts()
            .rename_axis("Title / abstract exclusion reason")
            .reset_index(name="n")
        )
        st.dataframe(reasons, use_container_width=True, hide_index=True)

    if focus == "pre_retrieval":
        st.info(
            "This is a review-specific workflow extension, not a mandatory standalone PRISMA 2020 box. It records the temporal/foundational eligibility gate applied before retrieval."
        )
        if not rows.empty and "Temporal Eligibility Decision" in rows.columns:
            tmp = (
                rows["Temporal Eligibility Decision"]
                .fillna("Unspecified")
                .astype(str)
                .value_counts()
                .rename_axis("Temporal eligibility decision")
                .reset_index(name="n")
            )
            st.dataframe(tmp, use_container_width=True, hide_index=True)

    if focus == "ft_excluded":
        st.dataframe(
            pd.DataFrame(
                [{"Grouped full-text exclusion reason": k, "n": v} for k, v in m["reason_counts"].most_common()]
            ),
            use_container_width=True,
            hide_index=True,
        )
        if not rows.empty:
            rows = rows.copy()
            rows["Grouped FT exclusion reason"] = rows["Full-Text Exclusion Reason"].map(_normalize_ft_reason)
            categories = sorted(rows["Grouped FT exclusion reason"].dropna().unique().tolist())
            selected_reason = st.selectbox(
                "Inspect a grouped exclusion reason",
                ["All"] + categories,
                key="ft_reason_drill_filter",
            )
            if selected_reason != "All":
                rows = rows[rows["Grouped FT exclusion reason"].eq(selected_reason)]

    if focus in {"eligible", "not_retrieved", "assessed", "outstanding", "included", "ft_excluded"}:
        st.markdown("**By review stream**")
        st.dataframe(pd.DataFrame(m["stream_summary"]), use_container_width=True, hide_index=True)

    _display_record_table(rows, f"focus_{focus}")

def render_analytical_summary(m: dict) -> None:
    st.subheader("PRISMA Process Analysis")
    st.caption(
        "Descriptive process analysis of study-selection progress. These indicators are not quality scores "
        "and should not be used to rank the PMM and PR evidence streams."
    )

    raw = max(m["raw_total"], 1)
    screened = max(m["screened"], 1)
    eligible = max(m["eligible"], 1)
    assessed = max(m["assessed"], 1)
    excluded = max(m["excluded"], 1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pre-screen removal", f"{m['removed_before'] / raw:.1%}", f"{m['removed_before']:,} / {m['raw_total']:,}")
    c2.metric("Title/abstract exclusion", f"{m['ta_excluded'] / screened:.1%}", f"{m['ta_excluded']:,} / {m['screened']:,}")
    c3.metric("Reached retrieval", f"{m['eligible'] / screened:.1%}", f"{m['eligible']:,} / {m['screened']:,}")
    c4.metric("FT processing complete", f"{m['assessed'] / eligible:.1%}", f"{m['assessed']:,} / {m['eligible']:,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Not retrieved", f"{m['not_retrieved'] / eligible:.1%}", f"{m['not_retrieved']:,}")
    c6.metric("Outstanding", f"{m['outstanding'] / eligible:.1%}", f"{m['outstanding']:,}")
    c7.metric("Included among assessed", f"{m['included'] / assessed:.1%}", f"{m['included']:,} / {m['assessed']:,}")
    c8.metric("Excluded among assessed", f"{m['excluded'] / assessed:.1%}", f"{m['excluded']:,} / {m['assessed']:,}")

    st.markdown("#### Stage conversion")
    stage_df = pd.DataFrame([
        {"Stage": "Identified", "n": m["raw_total"], "% of identified": m["raw_total"] / raw},
        {"Stage": "Screened", "n": m["screened"], "% of identified": m["screened"] / raw},
        {"Stage": "Retrieval eligible", "n": m["eligible"], "% of identified": m["eligible"] / raw},
        {"Stage": "FT assessed", "n": m["assessed"], "% of identified": m["assessed"] / raw},
        {"Stage": "Currently included", "n": m["included"], "% of identified": m["included"] / raw},
    ])
    st.dataframe(
        stage_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "% of identified": st.column_config.ProgressColumn(
                "% of identified", min_value=0.0, max_value=1.0, format="percent"
            )
        },
    )

    st.markdown("#### Processing progress by evidence stream")
    stream_df = pd.DataFrame(m["stream_summary"])
    if not stream_df.empty:
        stream_df = stream_df.copy()
        stream_df["Processing completion"] = stream_df.apply(
            lambda r: (r["Assessed"] / r["Eligible for retrieval"]) if r["Eligible for retrieval"] else 0,
            axis=1,
        )
        st.dataframe(
            stream_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Processing completion": st.column_config.ProgressColumn(
                    "Processing completion", min_value=0.0, max_value=1.0, format="percent"
                )
            },
        )
        st.warning(
            "PMM and PR are at different processing depths. Inclusion percentages should not be interpreted "
            "as comparative evidence strength until retrieval and full-text processing are complete in both streams."
        )

    st.markdown("#### Full-text exclusion profile")
    reason_df = pd.DataFrame([
        {"Reason": k, "n": v, "% of FT exclusions": v / excluded}
        for k, v in m["reason_counts"].most_common()
    ])
    if not reason_df.empty:
        st.dataframe(
            reason_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "% of FT exclusions": st.column_config.ProgressColumn(
                    "% of FT exclusions", min_value=0.0, max_value=1.0, format="percent"
                )
            },
        )

    language_n = int(m["reason_counts"].get("Language criterion", 0))
    if m["excluded"]:
        st.info(
            f"Interim interpretation: {language_n:,} of {m['excluded']:,} full-text exclusions "
            f"({language_n / m['excluded']:.1%}) are currently attributable to the language criterion. "
            "This describes the selection process; it is not a quality finding."
        )

    if m["outstanding"] > 0:
        st.markdown(
            f'<div class="audit-warn"><b>Interpretation limit:</b> {m["outstanding"]:,} reports remain outstanding. '
            'All downstream inclusion/exclusion rates are interim until the retrieval queue is closed.</div>',
            unsafe_allow_html=True,
        )



def render_prisma_dashboard() -> None:
    st.markdown(PRISMA_CSS, unsafe_allow_html=True)
    st.markdown(
        '<section class="prisma-hero">'
        '<div class="k">Academic Research Workspace · Systematic Review</div>'
        '<h1>PRISMA 2020 — Study Selection Flow</h1>'
        '<div class="s">Interactive, read-only reconciliation from the Screening MASTER. The workbook remains the source of truth.</div>'
        '</section>',
        unsafe_allow_html=True,
    )
    
    st.caption(
        "Upload the current Screening / PRISMA workbook. This page does not modify the workbook and does not alter the PMM dimension-derivation MASTER."
    )
    
    uploaded = st.file_uploader("Upload Screening / PRISMA workbook (.xlsx)", type=["xlsx"], key="prisma_screening_upload")
    
    if uploaded is None:
        st.info("Upload the current screening workbook to generate the live PRISMA 2020 flow and audit checks.")
        return
    
    file_bytes = uploaded.getvalue()
    try:
        data = load_prisma_workbook(file_bytes)
        metrics = calculate_prisma(data, file_bytes)
    except Exception as exc:
        st.error(f"Could not build PRISMA reconciliation: {exc}")
        return
    
    ok = all(metrics["checks"].values())
    if ok:
        st.markdown(
            f'<div class="audit-ok"><b>PRISMA reconciliation passed.</b> All core denominator checks balance. Current status: <b>{html.escape(metrics["status"])}</b>.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="audit-warn"><b>PRISMA reconciliation needs review.</b> At least one denominator check does not balance. Treat the flow as provisional until resolved.</div>',
            unsafe_allow_html=True,
        )
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Identified", f"{metrics['raw_total']:,}")
    k2.metric("Screened", f"{metrics['screened']:,}")
    k3.metric("Currently included", f"{metrics['included']:,}")
    k4.metric("Outstanding", f"{metrics['outstanding']:,}", metrics["status"])
    
    left, right = st.columns([1.38, .92], gap="large")
    with left:
        render_flow(metrics)
    with right:
        st.markdown("### Reconciliation checks")
        checks_df = pd.DataFrame(
            [{"Check": name, "Status": "PASS" if passed else "REVIEW"} for name, passed in metrics["checks"].items()]
        )
        st.dataframe(checks_df, use_container_width=True, hide_index=True)
    
        st.markdown("### Current status")
        st.write(f"**{metrics['status']}**")
        if metrics["outstanding"] > 0:
            st.warning(
                f"{metrics['outstanding']:,} reports still have no documented retrieval outcome. The included count is therefore interim, not the final systematic-review denominator."
            )
        else:
            st.success("No outstanding retrieval/full-text processing remains. The flow can be treated as final after the usual methodological sign-off.")
    
        st.markdown(
            '<div class="prisma-note"><b>PRISMA adaptation note:</b> The pre-retrieval temporal/foundational eligibility box is retained because it is an explicit stage in this review workflow. It should be described in the methods as a study-specific extension to the standard PRISMA flow.</div>',
            unsafe_allow_html=True,
        )
    
    st.divider()
    render_focus(metrics)
    
    st.divider()
    render_analytical_summary(metrics)
    
    with st.expander("Methodological note for thesis / supervisor"):
        st.markdown(
            """
    - The flow is computed from the current Screening MASTER rather than copied from a historical batch snapshot.
    - Historical seed records remain explicitly labelled as having an undocumented original identification source; no database is inferred retrospectively.
    - Duplicate removal is auditable across re-identified seed records, export-version duplicates, prior formal-search duplicates, and globally removed duplicate Study IDs.
    - Full-text exclusion reasons are grouped only for presentation; the source workbook retains the original detailed reason text.
    - Until the outstanding retrieval/full-text queue reaches zero, the included count should be described as **current/interim** rather than final.
            """
        )
    
