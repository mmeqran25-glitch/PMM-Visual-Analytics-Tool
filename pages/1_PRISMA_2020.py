from __future__ import annotations

from collections import Counter
from io import BytesIO
import html

import pandas as pd
import streamlit as st

APP_VERSION = "v0.14.4-prisma"
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

st.set_page_config(
    page_title=f"PRISMA 2020 | Academic Research Workspace | {APP_VERSION}",
    page_icon="📚",
    layout="wide",
)

st.markdown(
    """
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
div.stButton > button {border-radius:12px;min-height:72px;font-weight:800;white-space:pre-line;}
</style>
""",
    unsafe_allow_html=True,
)


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

    ft_available = eligible["Full Text Available"].astype(str).str.strip()
    ft_decision = eligible["Full-Text Decision"].astype(str).str.strip()
    not_retrieved = int(ft_available.eq("No").sum())
    assessed = int(ft_available.eq("Yes").sum())
    outstanding = int(eligible["Full Text Available"].isna().sum())
    included = int(ft_decision.eq("Include").sum())
    excluded = int(ft_decision.eq("Exclude").sum())

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
        "checks": checks,
        "status": "FINAL" if outstanding == 0 else "OPEN / INTERIM",
    }


def _stage_button(label: str, value: int, key: str) -> None:
    if st.button(f"{label}\n{value:,}", key=key, use_container_width=True):
        st.session_state["prisma_focus"] = key


def render_flow(m: dict) -> None:
    st.markdown('<div class="stage-band">IDENTIFICATION</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        _stage_button("Databases / registers", m["formal_raw"], "identification")
    with c2:
        _stage_button("Historical seed corpus", m["seed_records"], "seed")

    st.markdown("<div style='text-align:center;font-size:1.5rem;color:#4c83b6'>↓</div>", unsafe_allow_html=True)
    _stage_button("Records identified — all routes", m["raw_total"], "raw_total")
    st.markdown("<div style='text-align:center;font-size:1.5rem;color:#4c83b6'>↓</div>", unsafe_allow_html=True)
    _stage_button("Removed before screening", m["removed_before"], "removed")

    st.markdown('<div class="stage-band">SCREENING</div>', unsafe_allow_html=True)
    _stage_button("Records screened", m["screened"], "screened")
    a, b = st.columns(2)
    with a:
        _stage_button("Records excluded at title / abstract", m["ta_excluded"], "ta_excluded")
    with b:
        _stage_button("Pre-retrieval eligibility exclusions", m["pre_retrieval_excluded"], "pre_retrieval")

    st.markdown('<div class="stage-band">RETRIEVAL & ELIGIBILITY</div>', unsafe_allow_html=True)
    _stage_button("Reports sought for retrieval", m["eligible"], "eligible")
    a, b, c = st.columns(3)
    with a:
        _stage_button("Reports not retrieved", m["not_retrieved"], "not_retrieved")
    with b:
        _stage_button("Reports assessed for eligibility", m["assessed"], "assessed")
    with c:
        _stage_button("Outstanding retrieval / FT processing", m["outstanding"], "outstanding")

    st.markdown('<div class="stage-band">CURRENT FULL-TEXT OUTCOME</div>', unsafe_allow_html=True)
    a, b = st.columns(2)
    with a:
        _stage_button("Currently included after full-text assessment", m["included"], "included")
    with b:
        _stage_button("Full-text reports excluded", m["excluded"], "ft_excluded")


def render_focus(m: dict) -> None:
    focus = st.session_state.get("prisma_focus", "removed")
    st.markdown("### Drill-down / Audit detail")
    if focus in {"identification", "raw_total"}:
        df = pd.DataFrame(m["source_breakdown"], columns=["Database / Register", "Raw records identified"])
        if m["seed_records"]:
            df = pd.concat([
                df,
                pd.DataFrame([{
                    "Database / Register": "Historical seed corpus — original source undocumented",
                    "Raw records identified": m["seed_records"],
                }]),
            ], ignore_index=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    elif focus == "seed":
        st.info(
            f"Historical seed corpus: {m['seed_records']:,} registered records. Its original identification route is intentionally not retroactively attributed to a database."
        )
    elif focus == "removed":
        st.dataframe(
            pd.DataFrame([
                {"Removal category": "Duplicate records", "n": m["duplicates_removed"]},
                {"Removal category": "Marked ineligible by automation", "n": m["automation_removed"]},
                {"Removal category": "Other reasons before screening", "n": m["other_removed"]},
            ]),
            use_container_width=True,
            hide_index=True,
        )
        st.markdown("**Duplicate audit decomposition**")
        st.dataframe(
            pd.DataFrame([{"Duplicate pathway": k, "n": v} for k, v in m["duplicate_detail"].items()]),
            use_container_width=True,
            hide_index=True,
        )
    elif focus == "ft_excluded":
        st.dataframe(
            pd.DataFrame([{"Full-text exclusion reason": k, "n": v} for k, v in m["reason_counts"].most_common()]),
            use_container_width=True,
            hide_index=True,
        )
    elif focus in {"eligible", "not_retrieved", "assessed", "outstanding", "included"}:
        st.dataframe(pd.DataFrame(m["stream_summary"]), use_container_width=True, hide_index=True)
    elif focus == "pre_retrieval":
        st.info(
            "This box is a transparent study-workflow extension: temporal/foundational eligibility was resolved before full-text retrieval. It is not a separate mandatory PRISMA 2020 box."
        )
    else:
        st.info("This stage is recorded in the Screening MASTER and can be expanded to study-level IDs in a later drill-down layer.")


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
    st.stop()

file_bytes = uploaded.getvalue()
try:
    data = load_prisma_workbook(file_bytes)
    metrics = calculate_prisma(data, file_bytes)
except Exception as exc:
    st.error(f"Could not build PRISMA reconciliation: {exc}")
    st.stop()

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
