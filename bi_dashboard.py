from __future__ import annotations

import re
from typing import Dict, Iterable, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


UNIVERSE_OPTIONS = [
    "All Sources",
    "Profiled Studies",
    "Evidence Contributors",
    "Pass Contributors",
]


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _first_nonblank(row: pd.Series, columns: Iterable[str]) -> str:
    for col in columns:
        if col in row.index:
            value = _text(row.get(col))
            if value:
                return value
    return ""


def _dedupe(df: pd.DataFrame, key: str) -> pd.DataFrame:
    if df.empty or key not in df.columns:
        return pd.DataFrame(columns=df.columns)
    out = df.copy()
    out[key] = out[key].fillna("").astype(str).str.strip()
    out = out[out[key].ne("")]
    return out.drop_duplicates(subset=[key], keep="last").copy()


def _broad_eligibility(value: str) -> str:
    text = _text(value).lower()
    if text.startswith("eligible"):
        return "Eligible"
    if text.startswith("supporting"):
        return "Supporting Only"
    if text.startswith("not eligible"):
        return "Not Eligible"
    return "Unclassified"


def _broad_publication_type(value: str) -> str:
    text = _text(value).lower()
    if not text:
        return "Unknown"
    if any(x in text for x in ["standard", "professional framework", "professional/grey", "professional report"]):
        return "Professional / Standard"
    if any(x in text for x in ["systematic review", "scoping review", "literature review", "evidence synthesis", "review article"]):
        return "Review / Evidence Synthesis"
    if any(x in text for x in ["doctoral", "phd", "master", "thesis", "dissertation"]):
        return "Thesis / Dissertation"
    if any(x in text for x in ["conference", "proceedings", "symposium"]):
        return "Conference"
    if "book" in text or "chapter" in text:
        return "Book / Chapter"
    if any(x in text for x in ["preprint", "working paper"]):
        return "Preprint / Working Paper"
    if any(x in text for x in ["journal", "article", "paper"]):
        return "Journal Article"
    if "report" in text:
        return "Report"
    return "Other"


def _broad_methodology(value: str) -> str:
    text = _text(value).lower()
    if not text:
        return "Unknown"
    if "mixed" in text or ("quantitative" in text and "qualitative" in text):
        return "Mixed Methods"
    if any(x in text for x in ["systematic review", "scoping review", "evidence synthesis", "literature review", "review"]):
        return "Review / Synthesis"
    if any(x in text for x in ["professional", "standard", "grey evidence"]):
        return "Professional / Standard"
    if any(x in text for x in ["conceptual", "model development", "framework development"]) and "quantitative" not in text:
        return "Conceptual / Model Development"
    if any(x in text for x in ["qualitative", "interview", "focus group", "case study", "case-based"]):
        return "Qualitative"
    if any(x in text for x in ["quantitative", "survey", "pls-sem", "sem", "statistical", "regression"]):
        return "Quantitative"
    return "Other Empirical / Hybrid"


def _year_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").round().astype("Int64")


def _qa_percent(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.map(lambda x: x * 100 if pd.notna(x) and x <= 1.5 else x)


def build_study_catalog(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One BI row per Source Register Study_ID with profile/evidence metrics merged in."""
    src = _dedupe(frames.get("01_Source_Register", pd.DataFrame()), "Study_ID")
    if src.empty:
        return pd.DataFrame()
    if "Title" not in src.columns and "Study_Title" in src.columns:
        src = src.rename(columns={"Study_Title": "Title"})

    keep_src = [
        c for c in [
            "Study_ID", "Title", "Authors", "Year", "Source_Publication_Type",
            "Study_Design", "Methodological_Family", "QA_Judgment", "QA_Percent",
            "Study_Family_Status", "Primary_Evidence_Stream", "Source_Register_Status",
        ] if c in src.columns
    ]
    catalog = src[keep_src].copy()
    rename_src = {
        "Title": "Source_Title",
        "Authors": "Source_Authors",
        "Year": "Source_Year",
        "Study_Design": "Source_Study_Design",
        "Methodological_Family": "Source_Methodological_Family",
    }
    catalog = catalog.rename(columns=rename_src)

    profile = _dedupe(frames.get("03_Study_Profile", pd.DataFrame()), "Study_ID")
    if not profile.empty and "Title" not in profile.columns and "Study_Title" in profile.columns:
        profile = profile.rename(columns={"Study_Title": "Title"})
    profile_ids = set(profile.get("Study_ID", pd.Series(dtype=str)).astype(str)) if not profile.empty else set()
    if not profile.empty:
        keep_profile = [
            c for c in [
                "Study_ID", "Title", "Authors", "Year", "Country_Context", "Sector_Context",
                "Organization_Level", "Study_Design", "Methodological_Family",
                "PMM_Model_or_Framework", "Unit_of_Analysis", "Evidence_Source_Role",
                "Study_Family_ID", "Profile_Status",
            ] if c in profile.columns
        ]
        profile = profile[keep_profile].copy().rename(columns={
            "Title": "Profile_Title",
            "Authors": "Profile_Authors",
            "Year": "Profile_Year",
            "Study_Design": "Profile_Study_Design",
            "Methodological_Family": "Profile_Methodological_Family",
        })
        catalog = catalog.merge(profile, on="Study_ID", how="left")

    elig = _dedupe(frames.get("02_Capability_Eligibility", pd.DataFrame()), "Study_ID")
    if not elig.empty:
        keep_elig = [c for c in ["Study_ID", "Dimension_Formation_Decision", "Primary_or_Secondary_Role", "Priority"] if c in elig.columns]
        catalog = catalog.merge(elig[keep_elig], on="Study_ID", how="left")

    catalog["Study_Title"] = catalog.apply(
        lambda r: _first_nonblank(r, ["Profile_Title", "Source_Title"]), axis=1
    )
    catalog["Authors_Display"] = catalog.apply(
        lambda r: _first_nonblank(r, ["Profile_Authors", "Source_Authors"]), axis=1
    )
    catalog["Year"] = _year_numeric(
        catalog.apply(lambda r: _first_nonblank(r, ["Profile_Year", "Source_Year"]), axis=1)
    )
    catalog["Study_Design_Display"] = catalog.apply(
        lambda r: _first_nonblank(r, ["Profile_Study_Design", "Source_Study_Design"]), axis=1
    )
    catalog["Methodology_Display"] = catalog.apply(
        lambda r: _first_nonblank(r, ["Profile_Methodological_Family", "Source_Methodological_Family"]), axis=1
    )
    catalog["Methodology_Group"] = catalog["Methodology_Display"].map(_broad_methodology)

    publication_source = catalog.get("Source_Publication_Type", pd.Series("", index=catalog.index))
    catalog["Publication_Group"] = publication_source.fillna("").astype(str).map(_broad_publication_type)

    decision = catalog.get("Dimension_Formation_Decision", pd.Series("", index=catalog.index))
    catalog["Eligibility_Group"] = decision.fillna("").astype(str).map(_broad_eligibility)

    catalog["QA_Percent_Display"] = _qa_percent(
        catalog.get("QA_Percent", pd.Series(index=catalog.index, dtype=float))
    )
    catalog["Profiled"] = catalog["Study_ID"].astype(str).isin(profile_ids)

    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if not ev.empty and "Study_ID" in ev.columns:
        ev["Study_ID"] = ev["Study_ID"].fillna("").astype(str).str.strip()
        ev = ev[ev["Study_ID"].ne("")]
        gate = ev.get("PM_Practice_Maturity_Evidence_Gate", pd.Series("", index=ev.index)).fillna("").astype(str).str.strip()
        ev["_pass"] = gate.str.lower().eq("pass").astype(int)
        ev["_supporting"] = gate.str.lower().eq("supporting only").astype(int)
        ev["_architecture"] = gate.str.lower().str.contains("architecture/provenance", regex=False).astype(int)
        metrics = ev.groupby("Study_ID").agg(
            Evidence_Records=("Study_ID", "size"),
            Pass_Evidence=("_pass", "sum"),
            Supporting_Evidence=("_supporting", "sum"),
            Architecture_Evidence=("_architecture", "sum"),
        ).reset_index()
        catalog = catalog.merge(metrics, on="Study_ID", how="left")

    for col in ["Evidence_Records", "Pass_Evidence", "Supporting_Evidence", "Architecture_Evidence"]:
        if col not in catalog.columns:
            catalog[col] = 0
        catalog[col] = pd.to_numeric(catalog[col], errors="coerce").fillna(0).astype(int)

    codes = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    if not codes.empty and {"Study_ID", "Code_ID"}.issubset(codes.columns):
        codes["Study_ID"] = codes["Study_ID"].fillna("").astype(str).str.strip()
        foc = codes[codes["Study_ID"].ne("")].groupby("Study_ID")["Code_ID"].nunique().rename("FOC_Count").reset_index()
        catalog = catalog.merge(foc, on="Study_ID", how="left")
    if "FOC_Count" not in catalog.columns:
        catalog["FOC_Count"] = 0
    catalog["FOC_Count"] = pd.to_numeric(catalog["FOC_Count"], errors="coerce").fillna(0).astype(int)

    return catalog


def filter_catalog(
    catalog: pd.DataFrame,
    universe: str,
    year_range: Tuple[int, int] | None = None,
    countries: Iterable[str] | None = None,
    sectors: Iterable[str] | None = None,
    methods: Iterable[str] | None = None,
    publication_groups: Iterable[str] | None = None,
) -> pd.DataFrame:
    if catalog.empty:
        return catalog.copy()
    out = catalog.copy()

    if universe == "Profiled Studies":
        out = out[out["Profiled"]]
    elif universe == "Evidence Contributors":
        out = out[out["Evidence_Records"] > 0]
    elif universe == "Pass Contributors":
        out = out[out["Pass_Evidence"] > 0]

    if year_range is not None and out["Year"].notna().any():
        lo, hi = year_range
        out = out[out["Year"].between(lo, hi, inclusive="both")]

    def apply_membership(col: str, values: Iterable[str] | None):
        nonlocal out
        vals = [str(x) for x in (values or []) if str(x)]
        if vals and col in out.columns:
            out = out[out[col].fillna("").astype(str).isin(vals)]

    apply_membership("Country_Context", countries)
    apply_membership("Sector_Context", sectors)
    apply_membership("Methodology_Group", methods)
    apply_membership("Publication_Group", publication_groups)
    return out.copy()


def dashboard_counts(catalog: pd.DataFrame, frames: Dict[str, pd.DataFrame]) -> Dict[str, int | float | str]:
    sources = int(catalog["Study_ID"].nunique()) if not catalog.empty else 0
    profiled = int(catalog.loc[catalog["Profiled"], "Study_ID"].nunique()) if not catalog.empty else 0
    contributors = int(catalog.loc[catalog["Evidence_Records"] > 0, "Study_ID"].nunique()) if not catalog.empty else 0
    pass_contributors = int(catalog.loc[catalog["Pass_Evidence"] > 0, "Study_ID"].nunique()) if not catalog.empty else 0

    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame())
    evidence_records = int(len(ev))
    pass_evidence = 0
    if not ev.empty and "PM_Practice_Maturity_Evidence_Gate" in ev.columns:
        pass_evidence = int(ev["PM_Practice_Maturity_Evidence_Gate"].fillna("").astype(str).str.strip().str.lower().eq("pass").sum())

    years = catalog["Year"].dropna().astype(int) if not catalog.empty and "Year" in catalog.columns else pd.Series(dtype=int)
    period = f"{int(years.min())}–{int(years.max())}" if not years.empty else "N/A"

    return {
        "sources": sources,
        "profiled": profiled,
        "contributors": contributors,
        "pass_contributors": pass_contributors,
        "evidence_records": evidence_records,
        "pass_evidence": pass_evidence,
        "period": period,
    }


def context_completeness(catalog: pd.DataFrame) -> pd.DataFrame:
    profiled = catalog[catalog["Profiled"]].copy() if not catalog.empty else pd.DataFrame()
    if profiled.empty:
        return pd.DataFrame(columns=["Field", "Complete", "Total", "Percent"])
    rows = []
    for field in [
        "Country_Context", "Sector_Context", "Organization_Level",
        "PMM_Model_or_Framework", "Unit_of_Analysis", "Study_Family_ID",
    ]:
        if field not in profiled.columns:
            continue
        s = profiled[field].fillna("").astype(str).str.strip()
        complete = int(s.ne("").sum())
        total = int(len(profiled))
        rows.append({
            "Field": field,
            "Complete": complete,
            "Total": total,
            "Percent": (complete / total * 100) if total else 0.0,
        })
    return pd.DataFrame(rows)


def novelty_study_rows(frames: Dict[str, pd.DataFrame], allowed_studies: Iterable[str] | None = None) -> pd.DataFrame:
    df = frames.get("09_Novelty_Tracking", pd.DataFrame()).copy()
    if df.empty or "Study_ID" not in df.columns:
        return pd.DataFrame()

    df["Study_ID"] = df["Study_ID"].fillna("").astype(str).str.strip()
    df = df[df["Study_ID"].str.match(r"^SR\d+$", case=False, na=False)].copy()
    if allowed_studies is not None:
        allowed = {str(x) for x in allowed_studies}
        df = df[df["Study_ID"].isin(allowed)]

    if "Extraction_Order" not in df.columns:
        return pd.DataFrame()
    df["Extraction_Order_Num"] = pd.to_numeric(df["Extraction_Order"], errors="coerce")
    df = df[df["Extraction_Order_Num"].notna()].copy()

    # Later audit rows supersede earlier rows for the same study.
    df["_row_order"] = range(len(df))
    df = df.sort_values(["Study_ID", "_row_order"]).drop_duplicates(subset=["Study_ID"], keep="last")
    df = df.sort_values("Extraction_Order_Num").copy()

    def yes_flag(value: str, kind: str) -> bool:
        text = _text(value).lower()
        if not text:
            return False
        if re.match(r"^\s*no\b", text) or "no new" in text or "not assessed" in text or "n/a" in text:
            return False
        if kind == "reinforcement":
            return "reinforcement" in text or text.startswith("yes")
        if kind == "cluster":
            return bool(re.search(r"\byes\b|opened|new cluster", text))
        if kind == "foc":
            return bool(re.search(r"\byes\b|added|new .*foc|new first", text))
        if kind == "boundary":
            return bool(re.search(r"\byes\b|re-homed|boundary .*change|correction", text))
        if kind == "splitmerge":
            return bool(re.search(r"\byes\b|split|merge|re-homed", text))
        return False

    df["New_FOC_Flag"] = df.get("New_First_Order_Code?", pd.Series("", index=df.index)).map(lambda x: yes_flag(x, "foc"))
    df["New_Cluster_Flag"] = df.get("New_Cluster?", pd.Series("", index=df.index)).map(lambda x: yes_flag(x, "cluster"))
    df["Boundary_Change_Flag"] = df.get("Boundary_Change?", pd.Series("", index=df.index)).map(lambda x: yes_flag(x, "boundary"))
    df["Split_Merge_Flag"] = df.get("Split_or_Merge_Triggered?", pd.Series("", index=df.index)).map(lambda x: yes_flag(x, "splitmerge"))
    df["Reinforcement_Flag"] = df.get("Mainly_Reinforcement?", pd.Series("", index=df.index)).map(lambda x: yes_flag(x, "reinforcement"))
    return df


def _compact_context_values(df: pd.DataFrame, col: str) -> list[str]:
    if df.empty or col not in df.columns:
        return []
    s = df[col].fillna("").astype(str).str.strip()
    return sorted(x for x in s.unique().tolist() if x)


def render_dashboard_filters(catalog: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    st.markdown("### Dashboard filters")
    c1, c2 = st.columns([1, 2])
    with c1:
        universe = st.selectbox(
            "Study universe",
            UNIVERSE_OPTIONS,
            index=0,
            help=(
                "All Sources = Source Register. Profiled Studies = Study Profile rows. "
                "Evidence Contributors = studies with ≥1 evidence record. "
                "Pass Contributors = studies with ≥1 Pass evidence unit."
            ),
            key="bi_universe",
        )

    base = filter_catalog(catalog, universe)

    years = base["Year"].dropna().astype(int) if not base.empty else pd.Series(dtype=int)
    year_range = None
    with c2:
        if not years.empty:
            lo, hi = int(years.min()), int(years.max())
            year_range = st.slider(
                "Publication year",
                min_value=lo,
                max_value=hi,
                value=(lo, hi),
                key=f"bi_year_range_{universe}",
            )

    with st.expander("More filters", expanded=False):
        f1, f2 = st.columns(2)
        countries = f1.multiselect(
            "Country context",
            _compact_context_values(base, "Country_Context"),
            key=f"bi_country_filter_{universe}",
        )
        sectors = f2.multiselect(
            "Sector context",
            _compact_context_values(base, "Sector_Context"),
            key=f"bi_sector_filter_{universe}",
        )
        f3, f4 = st.columns(2)
        methods = f3.multiselect(
            "Methodological family (BI grouping)",
            _compact_context_values(base, "Methodology_Group"),
            key=f"bi_method_filter_{universe}",
        )
        pubs = f4.multiselect(
            "Publication type (BI grouping)",
            _compact_context_values(base, "Publication_Group"),
            key=f"bi_pub_filter_{universe}",
        )

    filtered = filter_catalog(
        catalog,
        universe,
        year_range=year_range,
        countries=countries,
        sectors=sectors,
        methods=methods,
        publication_groups=pubs,
    )

    st.caption(
        f"Current filter result: {filtered['Study_ID'].nunique() if not filtered.empty else 0} studies/source records. "
        "Country and sector charts use only records with populated context metadata."
    )
    return filtered, universe


def render_overview(filtered: pd.DataFrame, full_catalog: pd.DataFrame, frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Research Corpus Overview")
    counts = dashboard_counts(full_catalog, frames)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Source records", counts["sources"])
    k2.metric("Profiled studies", counts["profiled"])
    k3.metric("Evidence contributors", counts["contributors"])
    k4.metric("Pass contributors", counts["pass_contributors"])
    k5.metric("Pass evidence", counts["pass_evidence"])
    k6.metric("Study period", counts["period"])

    st.caption(
        "These are different analytical universes and are intentionally shown separately; "
        "they should not be described interchangeably as 'number of studies'. "
        "KPI cards describe the full loaded corpus; the charts below respond to the active dashboard filters."
    )

    left, right = st.columns([1.05, 1.0])
    with left:
        current_n = int(filtered["Study_ID"].nunique()) if not filtered.empty else 0
        eligible = int((filtered.get("Eligibility_Group", pd.Series(dtype=str)) == "Eligible").sum()) if not filtered.empty else 0
        contributors = int((filtered.get("Evidence_Records", pd.Series(dtype=int)) > 0).sum()) if not filtered.empty else 0
        pass_contrib = int((filtered.get("Pass_Evidence", pd.Series(dtype=int)) > 0).sum()) if not filtered.empty else 0
        fig = go.Figure(go.Funnel(
            y=["Current filter", "Eligible", "Evidence contributors", "Pass contributors"],
            x=[current_n, eligible, contributors, pass_contrib],
            textinfo="value+percent initial",
        ))
        fig.update_layout(title="Analytical funnel — current filters", height=390, margin=dict(l=20, r=20, t=60, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        comp = context_completeness(full_catalog)
        if not comp.empty:
            fig = px.bar(
                comp,
                x="Percent",
                y="Field",
                orientation="h",
                text=comp["Percent"].map(lambda x: f"{x:.1f}%"),
                title="Study-profile metadata completeness",
            )
            fig.update_xaxes(range=[0, 100], title="Complete (%)")
            fig.update_yaxes(title="")
            fig.update_layout(height=390, margin=dict(l=20, r=20, t=60, b=20))
            st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        year_df = filtered.dropna(subset=["Year"]).copy()
        if not year_df.empty:
            by_year = year_df.groupby("Year")["Study_ID"].nunique().reset_index(name="Studies")
            fig = px.bar(by_year, x="Year", y="Studies", title="Studies / records by publication year")
            fig.update_layout(height=350, margin=dict(l=20, r=20, t=55, b=20))
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        sector = filtered.copy()
        if "Sector_Context" in sector.columns:
            sector["Sector_Context"] = sector["Sector_Context"].fillna("").astype(str).str.strip()
            top = (
                sector[sector["Sector_Context"].ne("")]
                .groupby("Sector_Context")["Study_ID"].nunique()
                .sort_values(ascending=False)
                .head(12)
                .reset_index(name="Studies")
            )
            if not top.empty:
                fig = px.bar(top.sort_values("Studies"), x="Studies", y="Sector_Context", orientation="h", title="Top sector contexts")
                fig.update_yaxes(title="")
                fig.update_layout(height=350, margin=dict(l=20, r=20, t=55, b=20))
                st.plotly_chart(fig, use_container_width=True)


def render_time_context(filtered: pd.DataFrame) -> None:
    st.subheader("Time & Context Explorer")
    year_df = filtered.dropna(subset=["Year"]).copy()
    if year_df.empty:
        st.info("No year data are available under the current filters.")
        return

    by_year = year_df.groupby("Year")["Study_ID"].nunique().reset_index(name="Studies").sort_values("Year")
    by_year["Cumulative"] = by_year["Studies"].cumsum()

    a, b = st.columns(2)
    with a:
        fig = px.bar(by_year, x="Year", y="Studies", title="Studies by publication year")
        fig.update_layout(height=360)
        st.plotly_chart(fig, use_container_width=True)
    with b:
        fig = px.line(by_year, x="Year", y="Cumulative", markers=True, title="Cumulative corpus growth")
        fig.update_layout(height=360)
        st.plotly_chart(fig, use_container_width=True)

    method_year = (
        year_df.groupby(["Year", "Methodology_Group"])["Study_ID"].nunique()
        .reset_index(name="Studies")
    )
    if not method_year.empty:
        fig = px.bar(
            method_year,
            x="Year",
            y="Studies",
            color="Methodology_Group",
            title="Methodological family over time",
        )
        fig.update_layout(height=420, legend_title_text="BI grouping")
        st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    country_top = pd.DataFrame()
    sector_top = pd.DataFrame()
    if "Country_Context" in filtered.columns:
        tmp = filtered.copy()
        tmp["Country_Context"] = tmp["Country_Context"].fillna("").astype(str).str.strip()
        country_top = (
            tmp[tmp["Country_Context"].ne("")]
            .groupby("Country_Context")["Study_ID"].nunique()
            .sort_values(ascending=False)
            .head(12)
            .reset_index(name="Studies")
        )
    if "Sector_Context" in filtered.columns:
        tmp = filtered.copy()
        tmp["Sector_Context"] = tmp["Sector_Context"].fillna("").astype(str).str.strip()
        sector_top = (
            tmp[tmp["Sector_Context"].ne("")]
            .groupby("Sector_Context")["Study_ID"].nunique()
            .sort_values(ascending=False)
            .head(12)
            .reset_index(name="Studies")
        )

    with c1:
        if not country_top.empty:
            fig = px.bar(country_top.sort_values("Studies"), x="Studies", y="Country_Context", orientation="h", title="Top country contexts")
            fig.update_yaxes(title="")
            fig.update_layout(height=430)
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        if not sector_top.empty:
            fig = px.bar(sector_top.sort_values("Studies"), x="Studies", y="Sector_Context", orientation="h", title="Top sector contexts")
            fig.update_yaxes(title="")
            fig.update_layout(height=430)
            st.plotly_chart(fig, use_container_width=True)

    if not country_top.empty and not sector_top.empty:
        top_countries = set(country_top["Country_Context"])
        top_sectors = set(sector_top["Sector_Context"])
        matrix = filtered[
            filtered["Country_Context"].fillna("").astype(str).isin(top_countries)
            & filtered["Sector_Context"].fillna("").astype(str).isin(top_sectors)
        ].copy()
        if not matrix.empty:
            fig = px.density_heatmap(
                matrix,
                x="Sector_Context",
                y="Country_Context",
                title="Country × sector coverage matrix",
            )
            fig.update_layout(height=520, xaxis_title="", yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)

    profiled = filtered[filtered["Profiled"]].copy()
    if not profiled.empty:
        country_complete = profiled["Country_Context"].fillna("").astype(str).str.strip().ne("").mean() * 100 if "Country_Context" in profiled.columns else 0
        sector_complete = profiled["Sector_Context"].fillna("").astype(str).str.strip().ne("").mean() * 100 if "Sector_Context" in profiled.columns else 0
        if country_complete < 90 or sector_complete < 90:
            st.warning(
                f"Context coverage is incomplete under the current filter: Country {country_complete:.1f}% · "
                f"Sector {sector_complete:.1f}%. Interpret context distributions as coverage of populated metadata, not the entire corpus."
            )


def render_evidence_quality(filtered: pd.DataFrame, frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Evidence & Quality")
    ids = set(filtered["Study_ID"].astype(str)) if not filtered.empty else set()

    elig = filtered["Eligibility_Group"].value_counts().rename_axis("Decision").reset_index(name="Studies") if not filtered.empty else pd.DataFrame()
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if not ev.empty and "Study_ID" in ev.columns:
        ev["Study_ID"] = ev["Study_ID"].fillna("").astype(str).str.strip()
        ev = ev[ev["Study_ID"].isin(ids)]
    gate_counts = pd.DataFrame()
    if not ev.empty and "PM_Practice_Maturity_Evidence_Gate" in ev.columns:
        gate = ev["PM_Practice_Maturity_Evidence_Gate"].fillna("").astype(str).str.strip()
        gate = gate[gate.ne("")]
        gate_counts = gate.value_counts().rename_axis("Evidence Gate").reset_index(name="Records")

    c1, c2 = st.columns(2)
    with c1:
        if not elig.empty:
            fig = px.pie(elig, names="Decision", values="Studies", hole=.45, title="Study-level eligibility decision")
            fig.update_layout(height=380)
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        if not gate_counts.empty:
            fig = px.pie(gate_counts, names="Evidence Gate", values="Records", hole=.45, title="Evidence-level analytical gate")
            fig.update_layout(height=380)
            st.plotly_chart(fig, use_container_width=True)

    top = filtered[filtered["Pass_Evidence"] > 0].copy()
    if not top.empty:
        top = top.sort_values("Pass_Evidence", ascending=False)
        top15 = top.head(15).copy()
        top15["Study_Label"] = top15["Study_ID"].astype(str) + " — " + top15["Study_Title"].fillna("").astype(str).str.slice(0, 55)
        fig = px.bar(
            top15.sort_values("Pass_Evidence"),
            x="Pass_Evidence",
            y="Study_Label",
            orientation="h",
            hover_data=["Year", "Sector_Context", "Methodology_Group", "FOC_Count"],
            title="Top studies by Pass evidence contribution",
        )
        fig.update_yaxes(title="")
        fig.update_layout(height=520)
        st.plotly_chart(fig, use_container_width=True)

        pareto = top[["Study_ID", "Pass_Evidence"]].copy().sort_values("Pass_Evidence", ascending=False)
        total = pareto["Pass_Evidence"].sum()
        pareto["Cumulative_Percent"] = pareto["Pass_Evidence"].cumsum() / total * 100 if total else 0
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=pareto["Study_ID"], y=pareto["Pass_Evidence"], name="Pass evidence"), secondary_y=False)
        fig.add_trace(go.Scatter(x=pareto["Study_ID"], y=pareto["Cumulative_Percent"], name="Cumulative %", mode="lines"), secondary_y=True)
        fig.update_yaxes(title_text="Pass evidence", secondary_y=False)
        fig.update_yaxes(title_text="Cumulative %", range=[0, 105], secondary_y=True)
        fig.update_layout(title="Evidence contribution Pareto", height=430, xaxis_title="Study ID")
        st.plotly_chart(fig, use_container_width=True)

    qa = filtered.dropna(subset=["QA_Percent_Display"]).copy()
    if not qa.empty:
        qa["Bubble_Size"] = qa["Evidence_Records"].clip(lower=1)
        fig = px.scatter(
            qa,
            x="QA_Percent_Display",
            y="Pass_Evidence",
            size="Bubble_Size",
            color="Methodology_Group",
            hover_name="Study_ID",
            hover_data=["Study_Title", "Year", "QA_Judgment", "Evidence_Records", "FOC_Count"],
            title="QA score × Pass evidence contribution",
            labels={"QA_Percent_Display": "QA (%)", "Pass_Evidence": "Pass evidence"},
        )
        fig.update_layout(height=500)
        st.plotly_chart(fig, use_container_width=True)


def render_novelty_stability(filtered: pd.DataFrame, frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Novelty & Stability")
    ids = filtered["Study_ID"].astype(str).tolist() if not filtered.empty else []
    nov = novelty_study_rows(frames, ids)
    if nov.empty:
        st.info("No study-level novelty records with Extraction_Order are available under the current filters.")
        return

    new_clusters = int(nov["New_Cluster_Flag"].sum())
    boundaries = int(nov["Boundary_Change_Flag"].sum())
    reinforcement = int(nov["Reinforcement_Flag"].sum())
    last_new = nov.loc[nov["New_Cluster_Flag"], "Extraction_Order_Num"]
    last_new_text = int(last_new.max()) if not last_new.empty else "None"

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Study-level records", len(nov))
    k2.metric("New-cluster studies", new_clusters)
    k3.metric("Boundary-change studies", boundaries)
    k4.metric("Reinforcement studies", reinforcement)
    k5.metric("Last order with new cluster", last_new_text)

    events = []
    specs = [
        ("New FOC", "New_FOC_Flag"),
        ("New Cluster", "New_Cluster_Flag"),
        ("Boundary Change", "Boundary_Change_Flag"),
        ("Split / Merge", "Split_Merge_Flag"),
        ("Reinforcement", "Reinforcement_Flag"),
    ]
    for label, col in specs:
        part = nov[nov[col]].copy()
        for _, row in part.iterrows():
            events.append({
                "Extraction Order": row["Extraction_Order_Num"],
                "Event": label,
                "Study_ID": row["Study_ID"],
                "Novelty Summary": _text(row.get("Novelty_Summary")),
            })
    event_df = pd.DataFrame(events)
    if not event_df.empty:
        fig = px.scatter(
            event_df,
            x="Extraction Order",
            y="Event",
            color="Event",
            hover_name="Study_ID",
            hover_data={"Novelty Summary": True, "Event": False},
            title="Novelty / reinforcement events across extraction sequence",
        )
        fig.update_traces(marker=dict(size=12))
        fig.update_layout(height=460, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    trajectory = nov[["Extraction_Order_Num", "Study_ID", "New_Cluster_Flag", "Reinforcement_Flag"]].copy()
    trajectory = trajectory.sort_values("Extraction_Order_Num")
    trajectory["Cumulative_New_Cluster_Studies"] = trajectory["New_Cluster_Flag"].astype(int).cumsum()
    trajectory["Cumulative_Studies"] = range(1, len(trajectory) + 1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trajectory["Extraction_Order_Num"],
        y=trajectory["Cumulative_New_Cluster_Studies"],
        mode="lines+markers",
        name="Cumulative studies opening new clusters",
    ))
    fig.update_layout(
        title="Cumulative structural novelty",
        xaxis_title="Extraction Order",
        yaxis_title="Cumulative new-cluster studies",
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.info(
        "Interpret this page as structural novelty / reinforcement tracking, not as an automatic saturation claim. "
        "Later audits and cross-corpus corrections can legitimately refine boundaries without implying new construct discovery."
    )

    show_cols = [
        c for c in [
            "Study_ID", "Extraction_Order_Num", "New_First_Order_Code?", "New_Cluster?",
            "Boundary_Change?", "Mainly_Reinforcement?", "Novelty_Summary",
            "Cumulative_Stability_Observation",
        ] if c in nov.columns
    ]
    st.dataframe(nov[show_cols], use_container_width=True, hide_index=True, height=420)


def render_research_bi_dashboard(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown(
        '<div class="note-banner"><b>Research Evidence BI Dashboard:</b> '
        'This section describes the evidence corpus itself — studies, time, context, '
        'evidence gates, quality and novelty — rather than the PMM Dimension hierarchy.</div>',
        unsafe_allow_html=True,
    )
    catalog = build_study_catalog(frames)
    if catalog.empty:
        st.info("No Source Register records are available for the BI dashboard.")
        return

    filtered, universe = render_dashboard_filters(catalog)

    page = st.radio(
        "BI page",
        [
            "Research Corpus Overview",
            "Time & Context Explorer",
            "Evidence & Quality",
            "Novelty & Stability",
        ],
        horizontal=True,
        key="bi_dashboard_page",
    )
    st.caption(f"Universe: {universe} · Current filtered rows: {len(filtered)}")
    st.divider()

    if page == "Research Corpus Overview":
        render_overview(filtered, catalog, frames)
    elif page == "Time & Context Explorer":
        render_time_context(filtered)
    elif page == "Evidence & Quality":
        render_evidence_quality(filtered, frames)
    else:
        render_novelty_stability(filtered, frames)

    st.divider()
    with st.expander("Drill-through: studies behind the current filters", expanded=False):
        cols = [
            c for c in [
                "Study_ID", "Study_Title", "Year", "Country_Context", "Sector_Context",
                "Methodology_Group", "Publication_Group", "Eligibility_Group",
                "QA_Judgment", "QA_Percent_Display", "Evidence_Records",
                "Pass_Evidence", "FOC_Count",
            ] if c in filtered.columns
        ]
        drill = filtered[cols].copy() if cols else pd.DataFrame()
        if not drill.empty:
            drill = drill.sort_values(["Year", "Study_ID"], ascending=[False, True], na_position="last")
            st.dataframe(drill, use_container_width=True, hide_index=True, height=430)
        else:
            st.info("No study records match the current filters.")
