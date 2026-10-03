from __future__ import annotations

import re
from typing import Dict, Iterable, Tuple

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from master_utils import (
    active_cluster_register,
    active_dimensions,
    active_themes,
    current_mapping_rows,
    dimension_evidence_summary,
    dimension_theme_map,
    retired_themes,
    traceability_checks,
    unthemed_active_clusters,
)


BI_DASH_VERSION = "v0.16.12-bi"

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


def _apply_context_display_limit(df: pd.DataFrame, selection: str) -> pd.DataFrame:
    """Apply an optional visual-only Top-N limit without changing the filtered corpus."""
    if df.empty or selection == "All":
        return df.copy()
    match = re.search(r"(\d+)", str(selection))
    if not match:
        return df.copy()
    return df.head(int(match.group(1))).copy()


COUNTRY_PATTERNS = [
    ("Indonesia", [r"\bindonesia\b"]),
    ("Poland", [r"\bpoland\b", r"\bpolish\b"]),
    ("China", [r"\bchina\b", r"\bchinese\b"]),
    ("Pakistan", [r"\bpakistan\b"]),
    ("Switzerland", [r"\bswitzerland\b", r"\bswiss\b"]),
    ("United States", [r"\bunited states\b", r"\busa\b", r"\bu\.s\.\b", r"\bcentral florida\b"]),
    ("Ukraine", [r"\bukraine\b"]),
    ("Sweden", [r"\bsweden\b", r"\bgothenburg\b"]),
    ("Saudi Arabia", [r"\bsaudi arabia\b", r"\bksa\b"]),
    ("Slovakia", [r"\bslovak republic\b", r"\bslovakia\b"]),
    ("South Africa", [r"\bsouth africa\b", r"\bsouth african\b"]),
    ("Nigeria", [r"\bnigeria\b"]),
    ("Rwanda", [r"\brwanda\b"]),
    ("Portugal", [r"\bportugal\b"]),
    ("Lithuania", [r"\blithuania\b", r"\bvilnius\b"]),
    ("Ethiopia", [r"\bethiopia\b", r"\boromia\b", r"\bamhara\b", r"\btigray\b"]),
    ("Lesotho", [r"\blesotho\b"]),
    ("Iraq", [r"\biraq\b"]),
    ("Malawi", [r"\bmalawi\b"]),
    ("Malaysia", [r"\bmalaysia\b"]),
    ("Netherlands", [r"\bnetherlands\b", r"\bdutch\b"]),
    ("Australia", [r"\baustralia\b", r"\bnew south wales\b"]),
    ("Austria", [r"\baustria\b", r"\baustrian\b"]),
    ("Hungary", [r"\bhungary\b", r"\bhungarian\b"]),
    ("United Kingdom", [r"\bunited kingdom\b", r"\buk\b", r"\bbritain\b", r"\bbritish\b"]),
    ("India", [r"\bindia\b", r"\bindian\b"]),
    ("Brazil", [r"\bbrazil\b"]),
    ("Canada", [r"\bcanada\b"]),
    ("Germany", [r"\bgermany\b", r"\bgerman\b"]),
    ("France", [r"\bfrance\b", r"\bfrench\b"]),
    ("Spain", [r"\bspain\b", r"\bspanish\b"]),
    ("Italy", [r"\bitaly\b", r"\bitalian\b"]),
    ("Yemen", [r"\byemen\b"]),
    ("Egypt", [r"\begypt\b"]),
    ("Jordan", [r"\bjordan\b"]),
    ("United Arab Emirates", [r"\bunited arab emirates\b", r"\buae\b"]),
    ("Oman", [r"\boman\b"]),
    ("Qatar", [r"\bqatar\b"]),
    ("Turkey", [r"\bturkey\b", r"\btürkiye\b"]),
]

SECTOR_PATTERNS = [
    ("Telecommunications / ICT", [r"telecommunication", r"\bict\b", r"information and communication technology", r"software", r"information systems", r"\bit\b"]),
    ("Construction / Engineering / EPC", [r"construction", r"engineering", r"\bepc\b", r"infrastructure", r"project engineering"]),
    ("Public Sector / Government", [r"public sector", r"government", r"public service", r"public administration", r"state information"]),
    ("Energy / Utilities", [r"energy", r"solar", r"power", r"electric", r"utility", r"utilities", r"water sector"]),
    ("Oil & Gas / Petrochemical", [r"oil and gas", r"petrochemical", r"upstream", r"well-construction"]),
    ("Manufacturing / Industrial", [r"manufactur", r"industrial", r"production-oriented"]),
    ("Mining", [r"mining"]),
    ("Higher Education / Research", [r"higher education", r"universit", r"academic", r"research institution", r"e-learning"]),
    ("Logistics / Transport", [r"logistic", r"transport", r"\btsl\b"]),
    ("Defence / Aerospace", [r"defence", r"defense", r"space center", r"boeing", r"aerospace"]),
    ("Financial Services", [r"financial service", r"bank", r"finance"]),
    ("Consulting / Professional Services", [r"consult", r"professional service", r"business consulting"]),
    ("Non-profit / Development", [r"non-profit", r"nonprofit", r"non-governmental", r"development project"]),
    ("Cross-sector / Multi-sector", [r"cross-sector", r"multi-sector", r"multisector", r"multiple sector", r"several sector", r"project-driven organisations"]),
]


def _country_bi_group(value: str) -> str:
    text = _text(value)
    low = text.lower()
    if not low:
        return "Not specified"
    if any(x in low for x in [
        "not explicitly", "not specified", "no empirical country", "country not identified",
        "conceptual article", "location countries not", "model testing is ongoing",
    ]):
        return "Not specified / Conceptual"
    if any(x in low for x in [
        "multinational", "multi-country", "international", "cross-border",
        "two continents", "seven major sites", "global",
    ]):
        matched = []
        for label, patterns in COUNTRY_PATTERNS:
            if any(re.search(p, low) for p in patterns):
                matched.append(label)
        if len(set(matched)) > 1:
            return "International / Multi-country"
        if len(set(matched)) == 1 and "international" not in low:
            return matched[0]
        return "International / Multi-country"
    matched = []
    for label, patterns in COUNTRY_PATTERNS:
        if any(re.search(p, low) for p in patterns):
            matched.append(label)
    matched = list(dict.fromkeys(matched))
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return "International / Multi-country"
    if len(text) <= 36 and all(sep not in text for sep in [" / ", ";", " – ", " — "]):
        return text
    return "Other / Context-specific"


def _sector_bi_group(value: str) -> str:
    text = _text(value)
    low = text.lower()
    if not low:
        return "Not specified"
    matches = []
    for label, patterns in SECTOR_PATTERNS:
        if any(re.search(p, low) for p in patterns):
            matches.append(label)
    matches = list(dict.fromkeys(matches))
    if not matches:
        return "Other / Context-specific"
    if "Cross-sector / Multi-sector" in matches or len(matches) >= 3:
        return "Cross-sector / Multi-sector"
    return matches[0]


def _top_n_with_other(df: pd.DataFrame, label_col: str, value_col: str = "Studies", n: int = 10) -> pd.DataFrame:
    """Return top N categories plus one Other row so the chart remains compact but complete."""
    if df.empty:
        return df.copy()
    ordered = df.sort_values(value_col, ascending=False).reset_index(drop=True)
    top = ordered.head(n).copy()
    remainder = ordered.iloc[n:]
    if not remainder.empty:
        other_value = int(pd.to_numeric(remainder[value_col], errors="coerce").fillna(0).sum())
        if other_value > 0:
            top = pd.concat(
                [top, pd.DataFrame([{label_col: "Other", value_col: other_value}])],
                ignore_index=True,
            )
    return top


def _raw_context_detail(filtered: pd.DataFrame, raw_col: str, group_func) -> pd.DataFrame:
    if filtered.empty or raw_col not in filtered.columns:
        return pd.DataFrame()
    detail = filtered[["Study_ID", raw_col]].copy()
    detail[raw_col] = detail[raw_col].fillna("").astype(str).str.strip()
    detail = detail[detail[raw_col].ne("")]
    if detail.empty:
        return pd.DataFrame()
    detail["BI_Group"] = detail[raw_col].map(group_func)
    detail = (
        detail.groupby(["BI_Group", raw_col])["Study_ID"]
        .nunique()
        .reset_index(name="Studies")
        .sort_values(["BI_Group", "Studies", raw_col], ascending=[True, False, True])
    )
    return detail


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

    st.markdown("#### Context Explorer")
    st.caption(
        "BI Grouped is designed for interpretation and thesis-ready visuals. "
        "Raw Context Values preserves every original Country_Context / Sector_Context entry for audit review."
    )

    control1, control2, control3 = st.columns([1.0, 1.0, 1.1])
    context_axis = control1.radio(
        "Context dimension",
        ["Country", "Sector"],
        horizontal=True,
        key="bi_context_axis",
    )
    context_mode = control2.radio(
        "Display mode",
        ["BI Grouped", "Raw Context Values"],
        horizontal=True,
        key="bi_context_mode",
    )
    top_n = control3.selectbox(
        "Chart size",
        [10, 15, 20],
        index=0,
        key="bi_context_top_n",
        help="The chart remains compact. All remaining categories are rolled into Other; raw values stay available below.",
    )

    if context_axis == "Country":
        raw_col = "Country_Context"
        group_func = _country_bi_group
        axis_title = "Country context"
    else:
        raw_col = "Sector_Context"
        group_func = _sector_bi_group
        axis_title = "Sector context"

    if raw_col not in filtered.columns:
        st.info(f"{raw_col} is not available in the current workbook.")
        return

    work = filtered[["Study_ID", raw_col]].copy()
    work[raw_col] = work[raw_col].fillna("").astype(str).str.strip()
    work = work[work[raw_col].ne("")]
    if work.empty:
        st.info(f"No populated {raw_col} values are available under the current filters.")
        return

    if context_mode == "BI Grouped":
        work["Display_Category"] = work[raw_col].map(group_func)
        dist = (
            work.groupby("Display_Category")["Study_ID"]
            .nunique()
            .reset_index(name="Studies")
            .sort_values("Studies", ascending=False)
        )
        chart = _top_n_with_other(dist, "Display_Category", "Studies", int(top_n))
        y_col = "Display_Category"
        title = f"{axis_title} — Top {top_n} BI groups + Other"
    else:
        dist = (
            work.groupby(raw_col)["Study_ID"]
            .nunique()
            .reset_index(name="Studies")
            .sort_values("Studies", ascending=False)
        )
        chart = _top_n_with_other(dist, raw_col, "Studies", int(top_n))
        y_col = raw_col
        title = f"{axis_title} — Top {top_n} raw values + Other"

    fig = px.bar(
        chart.sort_values("Studies"),
        x="Studies",
        y=y_col,
        orientation="h",
        text="Studies",
        title=title,
    )
    fig.update_yaxes(title="")
    fig.update_xaxes(title="Unique studies", dtick=1)
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        height=470,
        margin=dict(l=20, r=55, t=60, b=30),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    total_values = int(work[raw_col].nunique())
    grouped_values = int(work[raw_col].map(group_func).nunique())
    context_studies = int(work["Study_ID"].nunique())
    st.caption(
        f"Coverage under current filters: {context_studies} studies with populated {raw_col} · "
        f"{total_values} original values · {grouped_values} BI groups. "
        "The Other bar aggregates categories outside the displayed Top-N; no study is discarded."
    )

    detail = _raw_context_detail(filtered, raw_col, group_func)
    with st.expander(f"View all original {raw_col} values and BI grouping", expanded=False):
        if not detail.empty:
            st.dataframe(detail, use_container_width=True, hide_index=True, height=460)
        else:
            st.info("No populated context values are available.")

    # Keep the Country × Sector relationship available, but use compact BI groups
    # so the heatmap remains interpretable rather than reproducing long raw phrases.
    if {"Country_Context", "Sector_Context"}.issubset(filtered.columns):
        matrix = filtered[["Study_ID", "Country_Context", "Sector_Context"]].copy()
        matrix["Country_Context"] = matrix["Country_Context"].fillna("").astype(str).str.strip()
        matrix["Sector_Context"] = matrix["Sector_Context"].fillna("").astype(str).str.strip()
        matrix = matrix[
            matrix["Country_Context"].ne("") & matrix["Sector_Context"].ne("")
        ].copy()
        if not matrix.empty:
            matrix["Country_Group"] = matrix["Country_Context"].map(_country_bi_group)
            matrix["Sector_Group"] = matrix["Sector_Context"].map(_sector_bi_group)

            country_rank = (
                matrix.groupby("Country_Group")["Study_ID"].nunique()
                .sort_values(ascending=False).head(10).index
            )
            sector_rank = (
                matrix.groupby("Sector_Group")["Study_ID"].nunique()
                .sort_values(ascending=False).head(10).index
            )
            heat = matrix[
                matrix["Country_Group"].isin(country_rank)
                & matrix["Sector_Group"].isin(sector_rank)
            ].copy()
            if not heat.empty:
                st.markdown("#### Country × Sector — compact BI matrix")
                fig = px.density_heatmap(
                    heat,
                    x="Sector_Group",
                    y="Country_Group",
                    title="Top BI country groups × sector groups",
                )
                fig.update_layout(height=520, xaxis_title="", yaxis_title="")
                st.plotly_chart(fig, use_container_width=True)

    profiled = filtered[filtered["Profiled"]].copy()
    if not profiled.empty:
        country_complete = (
            profiled["Country_Context"].fillna("").astype(str).str.strip().ne("").mean() * 100
            if "Country_Context" in profiled.columns else 0
        )
        sector_complete = (
            profiled["Sector_Context"].fillna("").astype(str).str.strip().ne("").mean() * 100
            if "Sector_Context" in profiled.columns else 0
        )
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



def _dimension_support_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Current dimension support breadth with study/context descriptors."""
    base = dimension_evidence_summary(frames, include_challenged=True)
    if base.empty:
        return base

    dmap = dimension_theme_map(frames)
    maps = current_mapping_rows(frames)
    profile = frames.get("03_Study_Profile", pd.DataFrame()).copy()
    if not profile.empty and "Study_ID" in profile.columns:
        profile["Study_ID"] = profile["Study_ID"].fillna("").astype(str).str.strip()

    themes = active_themes(frames)
    theme_to_clusters = {}
    if not themes.empty:
        for _, r in themes.iterrows():
            tid = _text(r.get("Theme_ID"))
            vals = re.findall(r"\bPCL-\d{3}\b", _text(r.get("Included_Cluster_IDs")), flags=re.I)
            theme_to_clusters[tid] = [v.upper() for v in vals]

    rows = []
    for _, r in base.iterrows():
        did = _text(r.get("Dimension_ID"))
        tids = []
        if not dmap.empty:
            tids = dmap.loc[dmap["Dimension_ID"].astype(str).eq(did), "Theme_ID"].astype(str).tolist()
        cids = []
        for tid in tids:
            cids.extend(theme_to_clusters.get(tid, []))
        cids = list(dict.fromkeys(cids))

        mm = pd.DataFrame()
        if not maps.empty and "Cluster_ID" in maps.columns:
            status = maps.get("Mapping_Status", pd.Series("", index=maps.index)).fillna("").astype(str).str.strip()
            mm = maps[
                maps["Cluster_ID"].fillna("").astype(str).str.upper().isin(cids)
                & status.isin(["Stable", "Provisional"])
            ].copy()

        study_ids = set(mm.get("Study_ID", pd.Series(dtype=str)).dropna().astype(str).str.strip()) if not mm.empty else set()
        study_ids.discard("")

        countries = set()
        sectors = set()
        methods = set()
        if study_ids and not profile.empty:
            pp = profile[profile["Study_ID"].isin(study_ids)].copy()
            for col, target in [
                ("Country_Context", countries),
                ("Sector_Context", sectors),
                ("Methodological_Family", methods),
            ]:
                if col in pp.columns:
                    vals = pp[col].fillna("").astype(str).str.strip()
                    target.update(v for v in vals if v)

        rows.append({
            "Dimension_ID": did,
            "Dimension": _text(r.get("Candidate_Dimension_Name")),
            "Studies": len(study_ids),
            "FOCs": int(r.get("FOCs", 0) or 0),
            "PCLs": int(r.get("Clusters", 0) or 0),
            "Themes": int(r.get("Themes", 0) or 0),
            "Countries": len(countries),
            "Sectors": len(sectors),
            "Methodological families": len(methods),
            "Dimension_Status": _text(r.get("Dimension_Status")),
        })
    return pd.DataFrame(rows)


def _dimension_concentration_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Evidence concentration by current dimension using mapped FOCs per study."""
    dmap = dimension_theme_map(frames)
    themes = active_themes(frames)
    maps = current_mapping_rows(frames)
    if dmap.empty or themes.empty or maps.empty:
        return pd.DataFrame()

    theme_to_clusters = {}
    for _, r in themes.iterrows():
        theme_to_clusters[_text(r.get("Theme_ID"))] = [
            x.upper() for x in re.findall(r"\bPCL-\d{3}\b", _text(r.get("Included_Cluster_IDs")), flags=re.I)
        ]

    dim_names = {}
    dims = active_dimensions(frames)
    if not dims.empty:
        dim_names = dict(zip(dims["Dimension_ID"].astype(str), dims["Candidate_Dimension_Name"].astype(str)))

    rows = []
    for did, g in dmap.groupby("Dimension_ID"):
        tids = g["Theme_ID"].astype(str).tolist()
        cids = []
        for tid in tids:
            cids.extend(theme_to_clusters.get(tid, []))
        cids = list(dict.fromkeys(cids))
        status = maps.get("Mapping_Status", pd.Series("", index=maps.index)).fillna("").astype(str).str.strip()
        mm = maps[
            maps["Cluster_ID"].fillna("").astype(str).str.upper().isin(cids)
            & status.isin(["Stable", "Provisional"])
        ].copy()
        if mm.empty or "Study_ID" not in mm.columns or "Code_ID" not in mm.columns:
            continue
        by_study = mm.groupby("Study_ID")["Code_ID"].nunique().sort_values(ascending=False)
        total = int(by_study.sum())
        if total <= 0:
            continue
        top1 = float(by_study.iloc[0] / total * 100)
        top5 = float(by_study.head(5).sum() / total * 100)
        rows.append({
            "Dimension_ID": str(did),
            "Dimension": dim_names.get(str(did), ""),
            "FOCs": total,
            "Studies": int(by_study.index.nunique()),
            "Top study share (%)": top1,
            "Top 5 studies share (%)": top5,
        })
    return pd.DataFrame(rows)


def _revision_summary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    log = frames.get("11_Decision_Log", pd.DataFrame()).copy()
    if log.empty:
        return pd.DataFrame(columns=["Revision type", "Count"])
    # Build one searchable text blob per decision row safely. Some workbook
    # cells can carry numeric / datetime / pandas scalar values that make
    # Series.agg(" ".join) raise TypeError even after broad casting.
    blob = log.apply(
        lambda row: " ".join(_text(value) for value in row.tolist()).lower(),
        axis=1,
    )
    patterns = [
        ("Reassignment / re-home", r"reassign|re-home|rehome"),
        ("Boundary review", r"boundary|heterogeneity|homogeneity"),
        ("Split", r"\bsplit\b"),
        ("Merge", r"\bmerge|merged|merger"),
        ("Retirement / dissolution", r"retir|dissol|withdraw"),
        ("Rename", r"\brename|renam"),
    ]
    rows=[]
    for label, pat in patterns:
        rows.append({"Revision type":label,"Count":int(blob.str.contains(pat,regex=True,na=False).sum())})
    return pd.DataFrame(rows)


def render_supervisor_bi_overview(filtered: pd.DataFrame, full_catalog: pd.DataFrame, frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Supervisor BI Overview")
    st.caption(
        "A compact academic overview of how the evidence corpus was transformed, where support comes from, "
        "how broadly current dimensions are supported, and where analytical uncertainty remains."
    )

    counts = dashboard_counts(full_catalog, frames)
    maps = current_mapping_rows(frames)
    clusters = active_cluster_register(frames)
    themes = active_themes(frames)
    dims = active_dimensions(frames)

    stable = provisional = challenged = 0
    mapped_focs = 0
    if not maps.empty:
        status = maps.get("Mapping_Status", pd.Series("", index=maps.index)).fillna("").astype(str).str.strip()
        stable = int(status.eq("Stable").sum())
        provisional = int(status.eq("Provisional").sum())
        challenged = int(status.eq("Challenged").sum())
        if "Code_ID" in maps.columns:
            mapped_focs = int(maps.loc[status.isin(["Stable","Provisional"]), "Code_ID"].nunique())

    st.markdown("#### Evidence transformation chain")
    chain = [
        ("Source studies", counts["sources"]),
        ("Pass contributors", counts["pass_contributors"]),
        ("Pass evidence", counts["pass_evidence"]),
        ("Mapped FOCs", mapped_focs),
        ("PCLs", len(clusters)),
        ("Themes", len(themes)),
        ("Dimensions", len(dims)),
    ]
    cols = st.columns(len(chain))
    for col,(label,val) in zip(cols,chain):
        col.metric(label,f"{int(val):,}")

    st.info(
        "These counts represent different analytical units. The chain is a traceability progression, not a claim that each stage is a simple one-to-one filter."
    )

    st.markdown("#### Corpus shape and literature-reported PMM architecture")
    left,right = st.columns(2)
    with left:
        year_df = filtered.dropna(subset=["Year"]).copy()
        if not year_df.empty:
            all_year = year_df.groupby("Year")["Study_ID"].nunique().reset_index(name="All selected studies")
            pass_year = (
                year_df[year_df["Pass_Evidence"]>0]
                .groupby("Year")["Study_ID"].nunique()
                .reset_index(name="Pass contributors")
            )
            yr = all_year.merge(pass_year,on="Year",how="left").fillna(0)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=yr["Year"],y=yr["All selected studies"],name="All selected studies"))
            fig.add_trace(go.Bar(x=yr["Year"],y=yr["Pass contributors"],name="Pass contributors"))
            fig.update_layout(
                barmode="group",
                title="Corpus vs analytical contributors by publication year",
                xaxis_title="Publication year",
                yaxis_title="Studies",
                height=420,
                margin=dict(l=20,r=20,t=60,b=30),
            )
            st.plotly_chart(fig,use_container_width=True)
    with right:
        reported = build_reported_author_groupings(frames)
        if not reported.empty:
            lit = reported.copy()
            lit["Reported_Group_Name"] = lit["Reported_Group_Name"].fillna("").astype(str).str.strip()
            lit["Study_ID"] = lit["Study_ID"].fillna("").astype(str).str.strip()
            lit = lit[lit["Reported_Group_Name"].ne("") & lit["Study_ID"].ne("")].copy()

            # Literature-only view: count exact author-reported construct names.
            # No synonym merging or mapping to our derived PCL/Theme/Dimension system.
            lit["_name_key"] = lit["Reported_Group_Name"].str.casefold()
            canon = (
                lit.sort_values(["_name_key","Study_ID"])
                .drop_duplicates(subset=["_name_key"], keep="first")
                [["_name_key","Reported_Group_Name"]]
            )
            lit_count = (
                lit.groupby("_name_key")["Study_ID"]
                .nunique().reset_index(name="Studies")
                .merge(canon,on="_name_key",how="left")
                .sort_values(["Studies","Reported_Group_Name"],ascending=[False,True])
                .head(15)
            )
            if not lit_count.empty:
                fig = px.bar(
                    lit_count.sort_values("Studies"),
                    x="Studies",
                    y="Reported_Group_Name",
                    orientation="h",
                    text="Studies",
                    title="Most frequently reported author-defined PMM constructs",
                )
                fig.update_yaxes(title="")
                fig.update_xaxes(title="Unique studies reporting the exact construct name", dtick=1)
                fig.update_traces(textposition="outside", cliponaxis=False)
                fig.update_layout(height=420,margin=dict(l=20,r=70,t=60,b=30))
                st.plotly_chart(fig,use_container_width=True)
                st.caption(
                    "Literature-only view. Bars count unique studies using the exact author-reported construct name "
                    "(Dimension / Domain / Area / Pillar etc.). Synonyms are not merged and no current PCL, Theme, "
                    "or derived PMM Dimension is used in this chart."
                )
        else:
            st.info("No author-reported PMM dimensions/domains/areas/pillars are currently recoverable from 04_Verbatim_Evidence.")

    st.markdown("#### Source-study reported architecture — descriptive preview")
    reported_groups = build_reported_author_groupings(frames)
    if not reported_groups.empty:
        reported_studies = sorted(reported_groups["Study_ID"].dropna().astype(str).unique().tolist())
        preferred_reported = ["SR067","SR051","SR403","SR875","SR018"]
        default_reported = next((x for x in preferred_reported if x in reported_studies), reported_studies[0])
        preview_study = st.selectbox(
            "Select a source study to view its reported Dimensions / Domains / Areas / Pillars",
            reported_studies,
            index=reported_studies.index(default_reported),
            key="bi_supervisor_reported_architecture_study",
        )
        _render_reported_groups_for_study(frames, preview_study, compact=True)
        st.caption(
            "This block reports only the source study's own architecture. No derived PMM Dimension from our de novo analysis is shown in this literature section."
        )
    else:
        st.info("No explicitly reported source-study architecture groupings are currently recoverable.")

    st.markdown("#### Stability and revision signals")
    a,b = st.columns(2)
    with a:
        status_df = pd.DataFrame([
            {"Mapping status":"Stable","Count":stable},
            {"Mapping status":"Provisional","Count":provisional},
            {"Mapping status":"Challenged","Count":challenged},
        ])
        status_total = int(status_df["Count"].sum())
        status_df["Percent"] = (
            status_df["Count"] / status_total * 100 if status_total else 0
        )
        status_df["Label"] = status_df.apply(
            lambda r: f"{int(r['Count']):,} ({r['Percent']:.1f}%)",
            axis=1,
        )
        fig = px.bar(
            status_df,
            x="Count",
            y="Mapping status",
            orientation="h",
            text="Label",
            title="Current FOC → PCL mapping status",
        )
        fig.update_yaxes(title="")
        fig.update_xaxes(
            title="Current mapping rows",
            rangemode="tozero",
            range=[0, max(1, float(status_df["Count"].max()) * 1.18)],
        )
        fig.update_traces(textposition="outside", cliponaxis=False)
        fig.update_layout(height=360, margin=dict(l=20, r=95, t=55, b=35))
        st.plotly_chart(fig,use_container_width=True)
        st.caption(
            "Counts and percentages are shown explicitly so smaller Provisional and Challenged groups remain visible "
            "alongside the much larger Stable group."
        )
    with b:
        revisions = _revision_summary(frames)
        if not revisions.empty:
            fig = px.bar(
                revisions.sort_values("Count"),
                x="Count",y="Revision type",orientation="h",
                text="Count",
                title="Decision-log revision signals (keyword-derived)",
            )
            fig.update_yaxes(title="")
            fig.update_traces(textposition="outside", cliponaxis=False)
            fig.update_layout(height=360, margin=dict(l=20, r=60, t=55, b=35))
            st.plotly_chart(fig,use_container_width=True)
            st.caption(
                "Exploratory audit signal only: counts are unique Decision Log rows matching each keyword family. "
                "One decision can legitimately appear in more than one category, so these bars are not mutually exclusive event totals."
            )

    st.markdown("#### Current watchlist")
    unthemed = unthemed_active_clusters(frames)
    retired = retired_themes(frames)
    q1,q2,q3,q4 = st.columns(4)
    q1.metric("Challenged FOCs", challenged)
    q1.caption("Still unresolved")
    q2.metric("Unthemed active PCLs", len(unthemed))
    q2.caption("Awaiting defensible Theme home")
    q3.metric("Retired Themes retained", len(retired))
    q3.caption("Audit history preserved")
    q4.metric("Provisional mappings", provisional)
    q4.caption("Current but not fully stable")

    st.caption(
        "Supervisor interpretation: a non-zero watchlist is not automatically a weakness. It shows that unresolved cases are retained explicitly rather than force-fitted."
    )


def render_dimension_support_bi(frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Dimension Support")
    support = _dimension_support_table(frames)
    if support.empty:
        st.info("No current Dimension support table could be built.")
        return

    st.markdown("#### Breadth of support")
    st.dataframe(
        support.sort_values(["Studies","FOCs"],ascending=False),
        use_container_width=True,hide_index=True
    )

    fig = px.scatter(
        support,
        x="Studies",y="FOCs",size="PCLs",color="Themes",
        hover_name="Dimension",
        hover_data=["Dimension_ID","Countries","Sectors","Methodological families","Dimension_Status"],
        title="Study breadth × FOC volume by current Dimension",
    )
    fig.update_layout(height=520)
    st.plotly_chart(fig,use_container_width=True)

    concentration = _dimension_concentration_table(frames)
    if not concentration.empty:
        st.markdown("#### Evidence concentration / dependency")
        st.caption(
            "Lower concentration generally indicates that support is distributed across more studies. "
            "This is a dependency diagnostic, not a quality score."
        )
        fig = px.bar(
            concentration.sort_values("Top 5 studies share (%)"),
            x="Top 5 studies share (%)",y="Dimension",orientation="h",
            hover_data=["Dimension_ID","Studies","FOCs","Top study share (%)"],
            title="Share of each Dimension's mapped FOCs contributed by its top five studies",
        )
        fig.update_yaxes(title="")
        fig.update_xaxes(range=[0,100],title="Top five studies' share (%)")
        fig.update_layout(height=max(420,55*len(concentration)+150))
        st.plotly_chart(fig,use_container_width=True)
        st.dataframe(concentration,use_container_width=True,hide_index=True)


def render_gaps_integrity_bi(frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Gaps & Integrity")
    unthemed = unthemed_active_clusters(frames)
    checks = traceability_checks(frames)

    a,b = st.columns([1,1.2])
    with a:
        st.markdown("#### Analytical gaps")
        maps = current_mapping_rows(frames)
        challenged = 0
        if not maps.empty and "Mapping_Status" in maps.columns:
            challenged = int(maps["Mapping_Status"].fillna("").astype(str).str.strip().eq("Challenged").sum())
        st.metric("Challenged FOCs",challenged)
        st.metric("Unthemed active PCLs",len(unthemed))
        if not unthemed.empty:
            cols=[c for c in ["Cluster_ID","Working_Cluster_Label","Cluster_Status"] if c in unthemed.columns]
            st.dataframe(unthemed[cols],use_container_width=True,hide_index=True,height=320)
    with b:
        st.markdown("#### Traceability / integrity checks")
        if checks.empty:
            st.info("No integrity checks are available.")
        else:
            st.dataframe(checks,use_container_width=True,hide_index=True,height=460)



def _evidence_intelligence_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if ev.empty:
        return ev

    for col in ["Evidence_ID","Study_ID","Meaning_Unit_Verbatim","Context_Verbatim",
                "Original_Author_Term","Author_Parent_Construct","Author_Defined_Relationship",
                "Evidence_Form","Conceptual_Role","Evidence_Origin",
                "PM_Practice_Maturity_Evidence_Gate","Gate_Rationale","Explicitness",
                "Direction","Source_Fidelity_Status","Source_Verification_Date",
                "Reviewer","Analyst_Memo","Split_Parent_Evidence_ID","Printed_Page",
                "PDF_Page_if_Different","Section_or_Item","Source_Component","Meaning_Unit_Status",
                "Atomicity_Status"]:
        if col not in ev.columns:
            ev[col] = ""

    ev["_Gate_Group"] = (
        ev["PM_Practice_Maturity_Evidence_Gate"].fillna("").astype(str).str.strip()
        .replace({"":"Unspecified"})
    )

    def direction_group(v):
        t=_text(v).lower()
        if not t:
            return "Unspecified"
        if any(x in t for x in ["negative","gap","failure","absence","weakness","deficien"]):
            return "Negative / Gap"
        if any(x in t for x in ["positive","enabling","mature","practice present"]):
            return "Positive / Enabling"
        if any(x in t for x in ["mixed","boundary","ambivalent"]):
            return "Mixed / Boundary"
        if any(x in t for x in ["neutral","architecture","progression"]):
            return "Neutral / Architecture"
        return "Other"

    ev["_Direction_Group"] = ev["Direction"].map(direction_group)

    def form_group(v):
        t=_text(v).lower()
        if not t:
            return "Unspecified"
        if "questionnaire" in t or "survey item" in t:
            return "Questionnaire / Item"
        if "indicator" in t or "operational" in t:
            return "Indicator / Operationalisation"
        if "maturity" in t and "criterion" in t:
            return "Maturity Criterion"
        if any(x in t for x in ["practice","capability"]):
            return "Practice / Capability"
        if any(x in t for x in ["gap","failure","deficien"]):
            return "Gap / Failure"
        if any(x in t for x in ["architecture","progression","level logic"]):
            return "Architecture / Progression"
        if "interview" in t or "focus group" in t or "theme" in t:
            return "Qualitative Finding"
        return "Other"

    ev["_Form_Group"] = ev["Evidence_Form"].map(form_group)

    def origin_group(v):
        t=_text(v).lower()
        if not t:
            return "Unspecified"
        if any(x in t for x in ["professional standard","standard","professional framework"]):
            return "Professional / Standard"
        if any(x in t for x in ["questionnaire","instrument","scale"]):
            return "Instrument / Measurement"
        if any(x in t for x in ["interview","focus group","empirical","case","survey"]):
            return "Empirical"
        if any(x in t for x in ["model development","framework development","conceptual"]):
            return "Model / Conceptual"
        if any(x in t for x in ["literature-derived","review"]):
            return "Literature-derived / Review"
        return "Other"

    ev["_Origin_Group"] = ev["Evidence_Origin"].map(origin_group)
    return ev


def _evidence_traceability_row(frames: Dict[str, pd.DataFrame], evidence_id: str) -> dict:
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    codes = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    maps = current_mapping_rows(frames)
    themes = active_themes(frames)
    dims = active_dimensions(frames)

    out = {
        "evidence": None,
        "codes": pd.DataFrame(),
        "mappings": pd.DataFrame(),
        "theme_rows": pd.DataFrame(),
        "dimension_rows": pd.DataFrame(),
    }
    if ev.empty or "Evidence_ID" not in ev.columns:
        return out

    hit = ev[ev["Evidence_ID"].astype(str).str.strip().eq(str(evidence_id).strip())]
    if hit.empty:
        return out
    out["evidence"] = hit.iloc[0].to_dict()

    if not codes.empty and "Evidence_ID" in codes.columns:
        c = codes[codes["Evidence_ID"].astype(str).str.strip().eq(str(evidence_id).strip())].copy()
        out["codes"] = c
    else:
        c = pd.DataFrame()

    if not c.empty and not maps.empty and "Code_ID" in maps.columns:
        mids = set(c["Code_ID"].dropna().astype(str).str.strip())
        m = maps[maps["Code_ID"].astype(str).str.strip().isin(mids)].copy()
        out["mappings"] = m
    else:
        m = pd.DataFrame()

    cluster_ids = set()
    if not m.empty and "Cluster_ID" in m.columns:
        cluster_ids = set(
            m["Cluster_ID"].dropna().astype(str).str.strip()
        )
        cluster_ids.discard("")

    theme_rows=[]
    if cluster_ids and not themes.empty:
        for _,r in themes.iterrows():
            tids = re.findall(r"\bPCL-\d{3}\b", _text(r.get("Included_Cluster_IDs")), flags=re.I)
            if any(x.upper() in {c.upper() for c in cluster_ids} for x in tids):
                theme_rows.append(r.to_dict())
    out["theme_rows"] = pd.DataFrame(theme_rows)

    theme_ids=set()
    if not out["theme_rows"].empty and "Theme_ID" in out["theme_rows"].columns:
        theme_ids=set(out["theme_rows"]["Theme_ID"].dropna().astype(str).str.strip())

    dim_rows=[]
    if theme_ids and not dims.empty:
        for _,r in dims.iterrows():
            tids = re.findall(r"\bTHM-\d{3}\b", _text(r.get("Supporting_Theme_IDs")), flags=re.I)
            if any(x.upper() in {t.upper() for t in theme_ids} for x in tids):
                dim_rows.append(r.to_dict())
    out["dimension_rows"] = pd.DataFrame(dim_rows)
    return out


def render_evidence_intelligence(frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Evidence Intelligence")
    st.caption(
        "Evidence-level analytics derived directly from 04_Verbatim_Evidence. "
        "This page shows what kinds of evidence entered the analysis, how each record was gated and verified, "
        "and how a selected evidence record traces forward into the current analytical structure."
    )

    ev=_evidence_intelligence_table(frames)
    if ev.empty:
        st.info("04_Verbatim_Evidence is empty or unavailable.")
        return

    total=len(ev)
    studies=int(ev["Study_ID"].fillna("").astype(str).str.strip().replace("",pd.NA).dropna().nunique())
    pass_n=int(ev["_Gate_Group"].str.casefold().eq("pass").sum())
    supporting_n=int(ev["_Gate_Group"].str.contains("Supporting",case=False,na=False).sum())
    split_n=int(ev["Split_Parent_Evidence_ID"].fillna("").astype(str).str.strip().ne("").sum())
    verified_n=int(ev["Source_Fidelity_Status"].fillna("").astype(str).str.strip().ne("").sum())

    k1,k2,k3,k4,k5,k6=st.columns(6)
    k1.metric("Evidence records",f"{total:,}")
    k2.metric("Studies represented",f"{studies:,}")
    k3.metric("Pass evidence",f"{pass_n:,}")
    k4.metric("Supporting only",f"{supporting_n:,}")
    k5.metric("Split-derived records",f"{split_n:,}")
    k6.metric("Fidelity-status recorded",f"{verified_n:,}")

    st.markdown("#### Evidence profile")
    a,b=st.columns(2)
    with a:
        gate=ev["_Gate_Group"].value_counts().rename_axis("Gate").reset_index(name="Records")
        fig=px.bar(gate.sort_values("Records"),x="Records",y="Gate",orientation="h",title="Evidence analytical gate")
        fig.update_yaxes(title="")
        fig.update_layout(height=360)
        st.plotly_chart(fig,use_container_width=True)
    with b:
        direction=ev["_Direction_Group"].value_counts().rename_axis("Direction").reset_index(name="Records")
        fig=px.bar(direction.sort_values("Records"),x="Records",y="Direction",orientation="h",title="Evidence direction")
        fig.update_yaxes(title="")
        fig.update_layout(height=360)
        st.plotly_chart(fig,use_container_width=True)

    c,d=st.columns(2)
    with c:
        form=ev["_Form_Group"].value_counts().rename_axis("Evidence form").reset_index(name="Records")
        fig=px.bar(form.sort_values("Records"),x="Records",y="Evidence form",orientation="h",title="Evidence form profile")
        fig.update_yaxes(title="")
        fig.update_layout(height=420)
        st.plotly_chart(fig,use_container_width=True)
    with d:
        origin=ev["_Origin_Group"].value_counts().rename_axis("Evidence origin").reset_index(name="Records")
        fig=px.bar(origin.sort_values("Records"),x="Records",y="Evidence origin",orientation="h",title="Evidence provenance profile")
        fig.update_yaxes(title="")
        fig.update_layout(height=420)
        st.plotly_chart(fig,use_container_width=True)

    st.markdown("#### Evidence verification and auditability")
    v1,v2=st.columns(2)
    with v1:
        fidelity=(
            ev["Source_Fidelity_Status"].fillna("").astype(str).str.strip()
            .replace("","Unspecified").value_counts()
            .rename_axis("Fidelity status").reset_index(name="Records")
        )
        fig=px.bar(fidelity.sort_values("Records"),x="Records",y="Fidelity status",orientation="h",title="Source-fidelity status")
        fig.update_yaxes(title="")
        fig.update_layout(height=360)
        st.plotly_chart(fig,use_container_width=True)
    with v2:
        dates=pd.to_datetime(ev["Source_Verification_Date"],errors="coerce")
        timeline=(
            pd.DataFrame({"Date":dates})
            .dropna()
            .groupby("Date").size().reset_index(name="Verified records")
            .sort_values("Date")
        )
        if not timeline.empty:
            timeline["Cumulative verified"]=timeline["Verified records"].cumsum()
            fig=px.line(timeline,x="Date",y="Cumulative verified",markers=True,title="Cumulative source verification")
            fig.update_layout(height=360)
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.info("No usable source verification dates were found.")

    st.markdown("#### Study contribution at evidence level")
    study=(
        ev.groupby("Study_ID").agg(
            Total_Evidence=("Evidence_ID","nunique"),
            Pass_Evidence=("_Gate_Group",lambda x:int(x.astype(str).str.casefold().eq("pass").sum())),
            Supporting_Only=("_Gate_Group",lambda x:int(x.astype(str).str.contains("Supporting",case=False,na=False).sum())),
            Split_Derived=("Split_Parent_Evidence_ID",lambda x:int(x.fillna("").astype(str).str.strip().ne("").sum())),
        ).reset_index()
    )
    top=study.sort_values(["Pass_Evidence","Total_Evidence"],ascending=False).head(20)
    if not top.empty:
        fig=px.bar(
            top.sort_values("Pass_Evidence"),
            x="Pass_Evidence",y="Study_ID",orientation="h",
            hover_data=["Total_Evidence","Supporting_Only","Split_Derived"],
            title="Top studies by Pass evidence contribution",
        )
        fig.update_yaxes(title="")
        fig.update_layout(height=560)
        st.plotly_chart(fig,use_container_width=True)

    st.markdown("---")
    st.markdown("#### Evidence → FOC → PCL → Theme → Dimension traceability explorer")
    ids=sorted(ev["Evidence_ID"].dropna().astype(str).str.strip().replace("",pd.NA).dropna().unique().tolist())
    default_idx=0
    selected=st.selectbox(
        "Evidence ID",
        ids,
        index=default_idx,
        key="bi_evidence_trace_id",
        help="Select any evidence record to inspect how it traces forward through the current analytical structure.",
    )
    tr=_evidence_traceability_row(frames,selected)
    e=tr["evidence"]
    if e is None:
        st.info("The selected evidence record could not be resolved.")
        return

    st.markdown("##### Source-grounded evidence")
    x1,x2,x3=st.columns(3)
    x1.write(f"**Study:** {_text(e.get('Study_ID'))}")
    x1.write(f"**Page:** {_text(e.get('Printed_Page'))}")
    x1.write(f"**Section / item:** {_text(e.get('Section_or_Item'))}")
    x2.write(f"**Author term:** {_text(e.get('Original_Author_Term'))}")
    x2.write(f"**Parent construct:** {_text(e.get('Author_Parent_Construct'))}")
    x2.write(f"**Author relationship:** {_text(e.get('Author_Defined_Relationship'))}")
    x3.write(f"**Gate:** {_text(e.get('PM_Practice_Maturity_Evidence_Gate'))}")
    x3.write(f"**Atomicity:** {_text(e.get('Atomicity_Status'))}")
    x3.write(f"**Fidelity:** {_text(e.get('Source_Fidelity_Status'))}")

    st.markdown("**Meaning Unit Verbatim**")
    st.info(_text(e.get("Meaning_Unit_Verbatim")) or "Not recorded.")
    if _text(e.get("Context_Verbatim")):
        with st.expander("Context Verbatim"):
            st.write(_text(e.get("Context_Verbatim")))
    if _text(e.get("Gate_Rationale")):
        st.markdown("**Gate rationale**")
        st.write(_text(e.get("Gate_Rationale")))
    if _text(e.get("Analyst_Memo")):
        with st.expander("Analyst memo"):
            st.write(_text(e.get("Analyst_Memo")))

    st.markdown("##### Forward trace")
    codes=tr["codes"]
    maps=tr["mappings"]
    th=tr["theme_rows"]
    dm=tr["dimension_rows"]

    c1,c2,c3,c4=st.columns(4)
    c1.metric("FOCs",len(codes))
    c2.metric("Current PCL mappings",len(maps))
    c3.metric("Current Themes",len(th))
    c4.metric("Current Dimensions",len(dm))

    if not codes.empty:
        cols=[c for c in ["Code_ID","First_Order_Code","Code_Fidelity_Status","Source_to_Code_Rationale"] if c in codes.columns]
        st.markdown("**First-Order Code(s)**")
        st.dataframe(codes[cols],use_container_width=True,hide_index=True)
    if not maps.empty:
        cols=[c for c in ["Code_ID","Cluster_ID","Working_Cluster_Label","Mapping_Status","Mapping_Rationale","Boundary_Rationale"] if c in maps.columns]
        st.markdown("**PCL mapping(s)**")
        st.dataframe(maps[cols],use_container_width=True,hide_index=True)
    if not th.empty:
        cols=[c for c in ["Theme_ID","Working_Theme_Label","Theme_Status"] if c in th.columns]
        st.markdown("**Theme(s)**")
        st.dataframe(th[cols],use_container_width=True,hide_index=True)
    if not dm.empty:
        cols=[c for c in ["Dimension_ID","Candidate_Dimension_Name","Dimension_Status"] if c in dm.columns]
        st.markdown("**Dimension(s)**")
        st.dataframe(dm[cols],use_container_width=True,hide_index=True)

    st.info(
        "Interpretation: this explorer is intended for auditability. It allows a supervisor to select an evidence record "
        "and inspect how—or whether—it contributes to the current higher-order analytical structure."
    )



ARCHITECTURE_LABEL_RULES = [
    ("Dimension", r"\bdimensions?\b"),
    ("Domain", r"\bdomains?\b"),
    ("Pillar", r"\bpillars?\b"),
    ("Capability Area", r"\bcapabilit(?:y|ies)\s+areas?\b"),
    ("Process Area", r"\bprocess\s+areas?\b"),
    ("Component", r"\bcomponents?\b"),
    ("Factor", r"\bfactors?\b"),
    ("Criterion", r"\bcriteri(?:on|a)\b"),
    ("Indicator / Index", r"\bindicators?\b|\bindexes?\b|\bindices\b"),
    ("Questionnaire / Scale Item", r"\bquestionnaire\b|\bscale\s+items?\b|\bsurvey\s+items?\b|\bitems?\b"),
    ("Maturity Level / Stage", r"\bmaturity\s+levels?\b|\blevels?\b|\bstages?\b"),
]


def _architecture_label_type(row: pd.Series) -> tuple[str, str]:
    """Return an author-label type only when the workbook text explicitly supports it."""
    fields = [
        ("Author_Defined_Relationship", _text(row.get("Author_Defined_Relationship"))),
        ("Evidence_Form", _text(row.get("Evidence_Form"))),
        ("Source_Component", _text(row.get("Source_Component"))),
    ]
    for field_name, value in fields:
        low = value.lower()
        if not low:
            continue
        for label, pattern in ARCHITECTURE_LABEL_RULES:
            if re.search(pattern, low, flags=re.I):
                return label, field_name
    return "Unclassified / Review", ""


def _architecture_view_type(row: pd.Series) -> str:
    blob = " ".join([
        _text(row.get("Evidence_Form")),
        _text(row.get("Source_Component")),
        _text(row.get("Author_Defined_Relationship")),
        _text(row.get("Author_Parent_Construct")),
    ]).lower()
    if re.search(r"questionnaire|survey item|scale item|instrument|assessment|measurement|indicator|operationali", blob):
        return "Assessment / Measurement Architecture"
    if re.search(r"maturity level|progression|progressive|stage\b|standardize|measure|control|continuously improve", blob):
        return "Maturity Progression"
    if re.search(r"dimension|domain|pillar|capability area|process area|component|model architecture|framework architecture", blob):
        return "Conceptual / Model Architecture"
    return "Unclassified / Review"


def _normalized_structural_role(label: str, row: pd.Series) -> str:
    """Broad role only; does not force an L1/L2 hierarchy."""
    if label in {"Dimension", "Domain", "Pillar", "Capability Area", "Process Area"}:
        return "Architecture grouping — relative level requires confirmation"
    if label in {"Component", "Factor"}:
        return "Component / grouping candidate — level requires confirmation"
    if label == "Criterion":
        return "Assessment criterion"
    if label == "Indicator / Index":
        return "Measurement indicator"
    if label == "Questionnaire / Scale Item":
        return "Questionnaire / scale item"
    if label == "Maturity Level / Stage":
        return "Progression / maturity level"
    form = _text(row.get("Evidence_Form")).lower()
    if any(x in form for x in ["practice", "capability"]):
        return "Operational capability / practice"
    if any(x in form for x in ["gap", "failure", "deficien"]):
        return "Gap / immature-state evidence"
    return "Unclassified / Review"


def _construct_origin_type(row: pd.Series) -> tuple[str, str]:
    """Conservative provenance reading from explicit workbook text; no hidden inference."""
    sources = [
        _text(row.get("Evidence_Origin")),
        _text(row.get("Gate_Rationale")),
        _text(row.get("Analyst_Memo")),
        _text(row.get("Author_Defined_Relationship")),
    ]
    blob = " ".join(sources).lower()
    named = []
    for name, pattern in [
        ("PMBOK", r"\bpmbok\b"),
        ("OPM3", r"\bopm3\b"),
        ("P3M3", r"\bp3m3\b"),
        ("Kerzner", r"\bkerzner\b"),
        ("CMMI", r"\bcmmi\b"),
    ]:
        if re.search(pattern, blob, flags=re.I):
            named.append(name)
    if named:
        return "Inherited / adapted from named prior framework", ", ".join(named)
    if re.search(r"author[- ]developed|developed by (the )?authors?|current[- ]study.*develop", blob):
        return "Current study / author-developed", ""
    if re.search(r"literature[- ]derived|derived from (the )?literature|literature review|prior literature", blob):
        return "Prior literature / synthesis", ""
    if re.search(r"adapted from|adopted from|inherited from|borrowed from", blob):
        return "Inherited / adapted from prior source", ""
    if re.search(r"professional standard|professional framework|standard-based", blob):
        return "Professional standard / framework", ""
    return "Unresolved / review", ""


def _current_study_role(row: pd.Series) -> str:
    blob = " ".join([
        _text(row.get("Evidence_Origin")),
        _text(row.get("Gate_Rationale")),
        _text(row.get("Analyst_Memo")),
        _text(row.get("Source_Component")),
    ]).lower()
    if re.search(r"author[- ]developed|model development|framework development|developed by", blob):
        return "Developed / constructed"
    if re.search(r"adapted|adopted|extended|extension", blob):
        return "Adapted / extended"
    if re.search(r"validated|validation", blob):
        return "Validated"
    if re.search(r"empirical|survey|interview|focus group|case study|tested|testing", blob):
        return "Tested / applied empirically"
    if re.search(r"literature review|synthesi|literature[- ]derived", blob):
        return "Synthesized from prior literature"
    return "Unresolved / review"


def build_author_architecture_candidates(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Read-only pilot reconstruction of source-study architecture from 04_Verbatim_Evidence.
    It preserves author wording and deliberately leaves ambiguous hierarchy unresolved.
    """
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if ev.empty or "Study_ID" not in ev.columns:
        return pd.DataFrame()

    needed = [
        "Evidence_ID","Study_ID","Printed_Page","PDF_Page_if_Different","Section_or_Item",
        "Source_Component","Author_Parent_Construct","Author_Defined_Relationship",
        "Meaning_Unit_Verbatim","Original_Author_Term","Meaning_Unit_Status",
        "Evidence_Form","Conceptual_Role","Evidence_Origin",
        "PM_Practice_Maturity_Evidence_Gate","Gate_Rationale","Explicitness",
        "Source_Fidelity_Status","Analyst_Memo",
    ]
    for col in needed:
        if col not in ev.columns:
            ev[col] = ""

    ev["Study_ID"] = ev["Study_ID"].fillna("").astype(str).str.strip()
    ev = ev[ev["Study_ID"].ne("")].copy()

    rows = []
    for _, r in ev.iterrows():
        original = _text(r.get("Original_Author_Term"))
        parent = _text(r.get("Author_Parent_Construct"))
        relationship = _text(r.get("Author_Defined_Relationship"))
        form = _text(r.get("Evidence_Form"))
        component = _text(r.get("Source_Component"))
        gate = _text(r.get("PM_Practice_Maturity_Evidence_Gate"))

        structural_blob = " ".join([relationship, form, component, parent]).lower()
        is_candidate = bool(
            (original and parent)
            or re.search(
                r"dimension|domain|pillar|capability area|process area|component|factor|criterion|indicator|"
                r"questionnaire|scale item|maturity level|progression|architecture|provenance|assessment",
                structural_blob,
                flags=re.I,
            )
            or "architecture/provenance" in gate.lower()
        )
        if not is_candidate:
            continue

        label, label_basis = _architecture_label_type(r)
        view = _architecture_view_type(r)
        role = _normalized_structural_role(label, r)
        origin, source_model = _construct_origin_type(r)
        study_role = _current_study_role(r)

        if label == "Questionnaire / Scale Item":
            level = "Measurement item — relative level not forced"
        elif label == "Indicator / Index":
            level = "Indicator — relative level not forced"
        elif label == "Maturity Level / Stage":
            level = "Progression level — separate from construct hierarchy"
        else:
            level = "Unresolved — requires whole-study confirmation"

        if label != "Unclassified / Review":
            explicitness = "Explicit structural label"
            status = "Pilot explicit"
        elif parent and original:
            explicitness = "Reconstructable relation candidate"
            status = "Review required"
        else:
            explicitness = "Ambiguous"
            status = "Review required"

        system_suffix = {
            "Conceptual / Model Architecture": "CONCEPT",
            "Assessment / Measurement Architecture": "ASSESS",
            "Maturity Progression": "PROGRESSION",
            "Unclassified / Review": "REVIEW",
        }.get(view, "REVIEW")

        rows.append({
            "Study_ID": _text(r.get("Study_ID")),
            "Architecture_System_ID": f"{_text(r.get('Study_ID'))}-{system_suffix}",
            "Architecture_View_Type": view,
            "Architecture_Unit_Verbatim": original or _text(r.get("Meaning_Unit_Verbatim")),
            "Author_Label_Type": label,
            "Author_Label_Basis": label_basis,
            "Normalized_Structural_Role": role,
            "Architecture_Level": level,
            "Author_Parent_Construct_Verbatim": parent,
            "Author_Relationship_Verbatim": relationship,
            "Current_Study_Role": study_role,
            "Construct_Origin_Type": origin,
            "Source_Model_or_Framework": source_model,
            "Architecture_Explicitness": explicitness,
            "Architecture_Status": status,
            "Evidence_ID": _text(r.get("Evidence_ID")),
            "Source_Page": _text(r.get("Printed_Page")) or _text(r.get("PDF_Page_if_Different")),
            "Section_or_Item": _text(r.get("Section_or_Item")),
            "Evidence_Form": form,
            "Evidence_Origin_Verbatim": _text(r.get("Evidence_Origin")),
            "Evidence_Gate": gate,
            "Conceptual_Role": _text(r.get("Conceptual_Role")),
            "Source_Fidelity_Status": _text(r.get("Source_Fidelity_Status")),
            "Current_Use_Restriction": (
                "Descriptive / provenance only — quarantined from de novo PCL, Theme, and Dimension formation"
            ),
        })

    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw

    keys = [
        "Study_ID","Architecture_System_ID","Architecture_View_Type",
        "Architecture_Unit_Verbatim","Author_Label_Type",
        "Normalized_Structural_Role","Architecture_Level",
        "Author_Parent_Construct_Verbatim","Author_Relationship_Verbatim",
        "Current_Study_Role","Construct_Origin_Type","Source_Model_or_Framework",
        "Architecture_Explicitness","Architecture_Status","Current_Use_Restriction",
    ]

    def join_unique(series):
        vals = []
        for v in series:
            t = _text(v)
            if t and t not in vals:
                vals.append(t)
        return " | ".join(vals)

    agg = (
        raw.groupby(keys, dropna=False)
        .agg(
            Supporting_Evidence_IDs=("Evidence_ID", join_unique),
            Source_Pages=("Source_Page", join_unique),
            Sections=("Section_or_Item", join_unique),
            Evidence_Forms=("Evidence_Form", join_unique),
            Evidence_Origins=("Evidence_Origin_Verbatim", join_unique),
            Evidence_Gates=("Evidence_Gate", join_unique),
            Conceptual_Roles=("Conceptual_Role", join_unique),
            Fidelity_Statuses=("Source_Fidelity_Status", join_unique),
        )
        .reset_index()
    )
    agg.insert(0, "Architecture_Record_ID", [f"AA-{i:05d}" for i in range(1, len(agg)+1)])
    return agg



AUTHOR_GROUP_TYPES = [
    ("Dimension", r"\bdimensions?\b"),
    ("Domain", r"\bdomains?\b"),
    ("Pillar", r"\bpillars?\b"),
    ("Knowledge Area", r"\bknowledge\s+areas?\b"),
    ("Management Area", r"\bmanagement\s+areas?\b"),
    ("Assessment Area", r"\bassessment\s+areas?\b"),
    ("Capability Area", r"\bcapabilit(?:y|ies)\s+areas?\b"),
    ("Process Area", r"\bprocess\s+areas?\b"),
    ("Area", r"\bareas?\b"),
]


def _explicit_group_type(text: str) -> str:
    low = _text(text).lower()
    if not low:
        return ""
    for label, pattern in AUTHOR_GROUP_TYPES:
        if re.search(pattern, low, flags=re.I):
            return label
    return ""


NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty"
)


def _reported_group_name_exclusion_reason(name: str) -> str:
    """
    Guard against false positives in literature-reported constructs.
    The chart is for individually named constructs, not instruments, levels,
    counts, or aggregate architecture statements.
    """
    text = _text(name)
    low = text.lower()
    if not low:
        return "Blank"

    if re.search(
        r"likert|multiple[- ]choice|questionnaire|survey questions?|questions?\b|"
        r"response options?|rating scale|point scale|scale points?|items?\b",
        low,
        flags=re.I,
    ):
        return "Measurement format / questionnaire content"

    if re.search(
        r"^\s*(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth)\s+"
        r"(?:maturity\s+)?(?:level|stage)\b|"
        r"\b(?:maturity\s+)?(?:level|stage)\s*\d+\b",
        low,
        flags=re.I,
    ):
        return "Maturity level / progression descriptor"

    # Aggregate statements such as:
    # "10 management areas / 41 second-class targets"
    # "14 dimensions / knowledge areas"
    # "ten project management knowledge areas"
    count_token = rf"(?:\d+|{NUMBER_WORDS})"
    grouping_plural = (
        r"(?:dimensions?|domains?|pillars?|knowledge\s+areas?|management\s+areas?|"
        r"assessment\s+areas?|capability\s+areas?|process\s+areas?|\bareas?\b)"
    )
    if re.search(rf"\b{count_token}\b.*\b{grouping_plural}\b", low, flags=re.I):
        return "Aggregate architecture statement"

    if "/" in text and re.search(
        r"dimension|domain|pillar|area|target|question|item|level",
        low,
        flags=re.I,
    ):
        return "Aggregate / compound architecture statement"

    if re.fullmatch(
        r"(?:dimensions?|domains?|pillars?|areas?|knowledge areas?|management areas?|"
        r"assessment areas?|capability areas?|process areas?)",
        low.strip(),
        flags=re.I,
    ):
        return "Generic construct-type label without a construct name"

    return ""


def _is_valid_reported_group_name(name: str) -> bool:
    return _reported_group_name_exclusion_reason(name) == ""




REPORTED_CONSTRUCT_RELATION_RULES = [
    # High-precision rules observed directly in 04_Verbatim_Evidence.
    ("Dimension", r"^(?:Main dimension of|Conceptual dimension of)$", None),
    ("Domain", r"^(?:Assessment domain of|Core domain of)$", None),
    ("Pillar", r"^(?:Pillar of|Framework pillar of)$", None),
    ("Area", r"^Area of$", None),
    ("Assessment Area", r"^Assessment area of$", None),
    ("Key Process Area", r"^KPA named as$", None),
    (
        "Capability Construct",
        r"^Measured/tested as one of the current-study capability constructs$",
        None,
    ),
    (
        "Building Block",
        r"^Building block of$",
        r"Author-defined High-Order Architecture",
    ),
    (
        "Maturity Cluster",
        r"^Cluster identified across \d+ of \d+ analysed PMMMs$",
        r"Source-defined maturity cluster",
    ),
    (
        "High-Order Construct",
        r"^Named high-order construct$",
        r"Author-defined High-Order Construct",
    ),
]


def _reported_construct_type_from_row(row: pd.Series) -> str:
    """
    High-precision classifier for author-reported PMM structural constructs.

    Inclusion is based on explicit Author_Defined_Relationship values observed
    in the workbook. Some relationships also require a matching architecture
    Evidence_Form to prevent lower-level practices being misclassified.
    """
    rel = _text(row.get("Author_Defined_Relationship"))
    form = _text(row.get("Evidence_Form"))
    if not rel:
        return ""
    for label, rel_pattern, form_pattern in REPORTED_CONSTRUCT_RELATION_RULES:
        if not re.fullmatch(rel_pattern, rel, flags=re.I):
            continue
        if form_pattern and not re.search(form_pattern, form, flags=re.I):
            continue
        return label
    return ""


def build_reported_author_groupings(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Extract only explicitly source-labelled PMM structural constructs.

    This deliberately favors precision over recall. It does not infer a
    Dimension/Domain/Area from generic words in Evidence_Form, Source_Component,
    free text, or from the semantic appearance of a term.
    """
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if ev.empty or "Study_ID" not in ev.columns:
        return pd.DataFrame()

    for col in [
        "Evidence_ID","Study_ID","Original_Author_Term","Author_Parent_Construct",
        "Author_Defined_Relationship","Evidence_Form","Meaning_Unit_Verbatim",
        "Printed_Page","PDF_Page_if_Different",
        "PM_Practice_Maturity_Evidence_Gate","Evidence_Origin",
        "Source_Fidelity_Status","Meaning_Unit_Status",
    ]:
        if col not in ev.columns:
            ev[col] = ""

    rows = []
    for _, r in ev.iterrows():
        sid = _text(r.get("Study_ID"))
        name = _text(r.get("Original_Author_Term"))
        if not sid or not name:
            continue

        construct_type = _reported_construct_type_from_row(r)
        if not construct_type:
            continue
        if not _is_valid_reported_group_name(name):
            continue

        rows.append({
            "Study_ID": sid,
            "Reported_Group_Name": name,
            "Reported_Group_Type": construct_type,
            "Author_Parent_Construct": _text(r.get("Author_Parent_Construct")),
            "Evidence_Basis": "Explicit author-defined structural relationship",
            "Evidence_ID": _text(r.get("Evidence_ID")),
            "Source_Page": _text(r.get("Printed_Page")) or _text(r.get("PDF_Page_if_Different")),
            "Author_Relationship_Verbatim": _text(r.get("Author_Defined_Relationship")),
            "Evidence_Form": _text(r.get("Evidence_Form")),
            "Evidence_Gate": _text(r.get("PM_Practice_Maturity_Evidence_Gate")),
            "Evidence_Origin": _text(r.get("Evidence_Origin")),
            "Source_Fidelity_Status": _text(r.get("Source_Fidelity_Status")),
        })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    def join_unique(series):
        vals = []
        for v in series:
            t = _text(v)
            if t and t not in vals:
                vals.append(t)
        return " | ".join(vals)

    return (
        out.groupby(
            ["Study_ID","Reported_Group_Name","Reported_Group_Type"],
            dropna=False,
        )
        .agg(
            Author_Parent_Constructs=("Author_Parent_Construct", join_unique),
            Evidence_Basis=("Evidence_Basis", join_unique),
            Supporting_Evidence_IDs=("Evidence_ID", join_unique),
            Source_Pages=("Source_Page", join_unique),
            Author_Relationships=("Author_Relationship_Verbatim", join_unique),
            Evidence_Forms=("Evidence_Form", join_unique),
            Evidence_Gates=("Evidence_Gate", join_unique),
            Evidence_Origins=("Evidence_Origin", join_unique),
            Fidelity_Statuses=("Source_Fidelity_Status", join_unique),
        )
        .reset_index()
    )


def build_reported_construct_review_queue(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Architecture-like records not admitted to the high-precision construct set.
    They are retained for later manual review instead of being guessed into the chart.
    """
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if ev.empty or "Study_ID" not in ev.columns:
        return pd.DataFrame()
    for col in [
        "Evidence_ID","Study_ID","Original_Author_Term","Author_Parent_Construct",
        "Author_Defined_Relationship","Evidence_Form","Printed_Page",
        "PDF_Page_if_Different","PM_Practice_Maturity_Evidence_Gate",
    ]:
        if col not in ev.columns:
            ev[col] = ""

    mask = (
        ev["Evidence_Form"].fillna("").astype(str).str.contains(
            r"architecture|high-order|cluster|domain|pillar|main factor",
            case=False, regex=True
        )
        | ev["PM_Practice_Maturity_Evidence_Gate"].fillna("").astype(str).str.contains(
            "Architecture/Provenance", case=False, regex=False
        )
    )
    cand = ev[mask].copy()
    rows = []
    for _, r in cand.iterrows():
        if _reported_construct_type_from_row(r):
            continue
        name = _text(r.get("Original_Author_Term"))
        if not name:
            continue
        rows.append({
            "Study_ID": _text(r.get("Study_ID")),
            "Candidate_Term": name,
            "Author_Parent_Construct": _text(r.get("Author_Parent_Construct")),
            "Author_Defined_Relationship": _text(r.get("Author_Defined_Relationship")),
            "Evidence_Form": _text(r.get("Evidence_Form")),
            "Evidence_ID": _text(r.get("Evidence_ID")),
            "Source_Page": _text(r.get("Printed_Page")) or _text(r.get("PDF_Page_if_Different")),
            "Review_Status": "Not shown in literature construct chart — manual classification required",
        })
    return pd.DataFrame(rows)


def build_aggregate_architecture_statements(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Keep aggregate statements such as '10 PMBOK areas + 4 literature-added areas' visible."""
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if ev.empty or "Study_ID" not in ev.columns:
        return pd.DataFrame()
    for col in [
        "Evidence_ID","Study_ID","Meaning_Unit_Verbatim","Original_Author_Term",
        "Author_Defined_Relationship","Printed_Page","PDF_Page_if_Different",
        "Evidence_Origin","PM_Practice_Maturity_Evidence_Gate",
    ]:
        if col not in ev.columns:
            ev[col] = ""

    rows = []
    for _, r in ev.iterrows():
        blob = " ".join([
            _text(r.get("Meaning_Unit_Verbatim")),
            _text(r.get("Original_Author_Term")),
            _text(r.get("Author_Defined_Relationship")),
        ])
        if not re.search(r"\b\d+\b", blob):
            continue
        if not re.search(
            r"dimension|domain|pillar|knowledge\s+area|management\s+area|assessment\s+area|"
            r"capability\s+area|process\s+area|\bareas?\b",
            blob,
            flags=re.I,
        ):
            continue
        rows.append({
            "Study_ID": _text(r.get("Study_ID")),
            "Aggregate_Architecture_Statement": blob.strip(),
            "Evidence_ID": _text(r.get("Evidence_ID")),
            "Source_Page": _text(r.get("Printed_Page")) or _text(r.get("PDF_Page_if_Different")),
            "Evidence_Origin": _text(r.get("Evidence_Origin")),
            "Evidence_Gate": _text(r.get("PM_Practice_Maturity_Evidence_Gate")),
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates(
            subset=["Study_ID","Aggregate_Architecture_Statement","Evidence_ID"]
        )
    return out


def _render_reported_groups_for_study(
    frames: Dict[str, pd.DataFrame],
    study_id: str,
    *,
    compact: bool = False,
) -> None:
    groups = build_reported_author_groupings(frames)
    agg = build_aggregate_architecture_statements(frames)

    gg = groups[groups["Study_ID"].eq(study_id)].copy() if not groups.empty else pd.DataFrame()
    aa = agg[agg["Study_ID"].eq(study_id)].copy() if not agg.empty else pd.DataFrame()

    st.markdown("#### Author-reported Dimensions / Domains / Areas / Pillars")
    st.caption(
        "These are source-study constructs reported by the authors. They are displayed for description/provenance only "
        "and remain quarantined from the de novo PCL → Theme → Dimension derivation."
    )

    if gg.empty:
        st.info(
            "No individually named Dimension/Domain/Area/Pillar is explicitly recoverable from the current "
            "04_Verbatim_Evidence rows for this study. Aggregate statements, if present, are shown below."
        )
    else:
        type_counts = (
            gg.groupby("Reported_Group_Type")["Reported_Group_Name"]
            .nunique().sort_values(ascending=False)
        )
        summary = " · ".join(f"{k}: {int(v)}" for k, v in type_counts.items())
        st.success(f"{study_id} — {summary}")

        for group_type in type_counts.index:
            part = gg[gg["Reported_Group_Type"].eq(group_type)].copy()
            names = sorted(part["Reported_Group_Name"].astype(str).unique().tolist())
            st.markdown(f"**{group_type}{'s' if not group_type.endswith('s') else ''} ({len(names)})**")
            for name in names:
                st.markdown(f"- {name}")

        if not compact:
            with st.expander("Evidence supporting these reported groupings", expanded=False):
                cols = [
                    "Reported_Group_Type","Reported_Group_Name","Author_Parent_Constructs",
                    "Evidence_Basis","Supporting_Evidence_IDs","Source_Pages",
                    "Author_Relationships","Evidence_Forms","Evidence_Origins",
                    "Evidence_Gates","Fidelity_Statuses",
                ]
                st.dataframe(
                    gg[[c for c in cols if c in gg.columns]],
                    use_container_width=True,
                    hide_index=True,
                    height=430,
                )

    if not aa.empty:
        st.markdown("##### Aggregate architecture statements")
        st.caption(
            "These statements report a number or composition of areas/dimensions but may not individually evidence every member name."
        )
        for _, row in aa.iterrows():
            st.markdown(
                f"- {_text(row.get('Aggregate_Architecture_Statement'))} "
                f"— Evidence {_text(row.get('Evidence_ID'))}"
            )


def render_study_architecture_explorer(frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Study Architecture Explorer — Pilot")
    st.warning(
        "Methodological quarantine: this view reconstructs structures reported by source studies for descriptive, "
        "provenance, and later comparative use only. It must not inform or revise the de novo PCL → Theme → Dimension "
        "formation until that derivation is formally closed."
    )

    arch = build_author_architecture_candidates(frames)
    if arch.empty:
        st.info("No source-architecture candidates could be reconstructed from 04_Verbatim_Evidence.")
        return

    studies = sorted(arch["Study_ID"].dropna().astype(str).unique().tolist())
    preferred = ["SR067","SR051","SR403","SR875","SR018"]
    default_study = next((x for x in preferred if x in studies), studies[0])
    selected = st.selectbox(
        "Study",
        studies,
        index=studies.index(default_study),
        key="bi_architecture_study",
    )
    ss = arch[arch["Study_ID"].eq(selected)].copy()

    # Put the actual author-reported dimensions/domains/areas first; this is
    # the primary user-facing purpose of the explorer.
    _render_reported_groups_for_study(frames, selected)
    st.divider()

    explicit = int(ss["Architecture_Status"].eq("Pilot explicit").sum())
    review = int(ss["Architecture_Status"].eq("Review required").sum())
    views = int(ss["Architecture_View_Type"].nunique())
    parents = int(
        ss["Author_Parent_Construct_Verbatim"].fillna("").astype(str).str.strip()
        .replace("", pd.NA).dropna().nunique()
    )
    frameworks = sorted(
        set(
            x.strip()
            for cell in ss["Source_Model_or_Framework"].fillna("").astype(str)
            for x in cell.split(",")
            if x.strip()
        )
    )

    a,b,c,d,e = st.columns(5)
    a.metric("Architecture units", len(ss))
    b.metric("Explicitly labelled", explicit)
    c.metric("Require review", review)
    d.metric("Architecture views", views)
    e.metric("Reported parent constructs", parents)

    if frameworks:
        st.caption("Named prior frameworks explicitly detected in provenance text: " + ", ".join(frameworks))

    tabs = st.tabs([
        "Reported Architecture",
        "Views & Provenance",
        "Source Evidence",
        "Schema / Guardrails",
    ])

    with tabs[0]:
        st.markdown("#### Source-native architecture units")
        st.caption(
            "Author wording is preserved. Architecture_Level remains unresolved unless the workbook explicitly supports "
            "a relative position; the pilot does not manufacture L1/L2 links."
        )
        higher = ss[
            ss["Author_Label_Type"].isin(
                ["Dimension","Domain","Pillar","Capability Area","Process Area","Component","Factor"]
            )
        ].copy()
        if not higher.empty:
            show = [
                "Architecture_Record_ID","Architecture_View_Type","Architecture_Unit_Verbatim",
                "Author_Label_Type","Author_Parent_Construct_Verbatim",
                "Author_Relationship_Verbatim","Construct_Origin_Type",
                "Source_Model_or_Framework","Architecture_Status","Supporting_Evidence_IDs",
            ]
            st.dataframe(higher[[c for c in show if c in higher.columns]], use_container_width=True, hide_index=True)
        else:
            st.info("No explicitly labelled higher/grouping architecture units were detected for this study.")

        lower = ss[
            ss["Author_Label_Type"].isin(
                ["Criterion","Indicator / Index","Questionnaire / Scale Item","Maturity Level / Stage"]
            )
            | ss["Normalized_Structural_Role"].isin(
                ["Operational capability / practice","Assessment criterion","Measurement indicator",
                 "Questionnaire / scale item","Progression / maturity level"]
            )
        ].copy()
        if not lower.empty:
            with st.expander("Lower-level criteria, indicators, items, practices, and progression records", expanded=False):
                show = [
                    "Architecture_Record_ID","Architecture_Unit_Verbatim","Author_Label_Type",
                    "Normalized_Structural_Role","Author_Parent_Construct_Verbatim",
                    "Author_Relationship_Verbatim","Evidence_Gates","Source_Pages",
                ]
                st.dataframe(lower[[c for c in show if c in lower.columns]], use_container_width=True, hide_index=True, height=480)

    with tabs[1]:
        view_counts = (
            ss.groupby(["Architecture_View_Type","Construct_Origin_Type"])
            .size().reset_index(name="Architecture units")
            .sort_values("Architecture units", ascending=False)
        )
        if not view_counts.empty:
            fig = px.bar(
                view_counts,
                x="Architecture units",y="Architecture_View_Type",
                color="Construct_Origin_Type",orientation="h",
                title=f"{selected}: architecture views × provenance reading",
            )
            fig.update_yaxes(title="")
            fig.update_layout(height=420)
            st.plotly_chart(fig,use_container_width=True)

        prov_cols = [
            "Architecture_Record_ID","Architecture_Unit_Verbatim","Architecture_View_Type",
            "Current_Study_Role","Construct_Origin_Type","Source_Model_or_Framework",
            "Evidence_Origins","Architecture_Explicitness",
        ]
        st.dataframe(ss[[c for c in prov_cols if c in ss.columns]],use_container_width=True,hide_index=True,height=440)

    with tabs[2]:
        raw_cols = [
            "Architecture_Record_ID","Architecture_Unit_Verbatim","Author_Parent_Construct_Verbatim",
            "Author_Relationship_Verbatim","Supporting_Evidence_IDs","Source_Pages","Sections",
            "Evidence_Forms","Evidence_Gates","Conceptual_Roles","Fidelity_Statuses",
        ]
        st.dataframe(ss[[c for c in raw_cols if c in ss.columns]],use_container_width=True,hide_index=True,height=520)
        st.download_button(
            "Download selected study architecture (CSV)",
            data=ss.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"{selected}_author_architecture_pilot.csv",
            mime="text/csv",
            key="bi_architecture_download",
        )

    with tabs[3]:
        st.markdown(
            """
**Pilot interpretation rules**

- Author terminology is preserved verbatim; normalization never replaces it.
- A word such as *Dimension*, *Domain*, *Pillar*, or *Factor* does not by itself determine an L1/L2 position.
- A parent-child link is not created unless source fields support it.
- Measurement items and indicators are not treated as constructs merely because they sit beneath a construct.
- Inherited PMBOK/OPM3/P3M3/Kerzner/CMMI architecture is flagged as provenance, not independent construct discovery.
- Repetition of the same source-native unit across Evidence rows is aggregated rather than double-counted.
- Review required is a legitimate outcome; the pilot prefers unresolved structure to an invented hierarchy.
- This entire view remains isolated from de novo PCL/Theme/Dimension formation until derivation lock.
"""
        )
        review_queue = build_reported_construct_review_queue(frames)
        review_study = review_queue[review_queue["Study_ID"].eq(selected)].copy() if not review_queue.empty else pd.DataFrame()
        if not review_study.empty:
            st.markdown("#### Architecture-like source terms withheld from the main literature chart")
            st.caption(
                "These records are intentionally not classified as Dimensions/Domains/Areas/Pillars because the source relationship "
                "does not meet the explicit high-precision rules. They remain available for manual review."
            )
            st.dataframe(review_study, use_container_width=True, hide_index=True, height=320)

        unresolved = ss[ss["Architecture_Status"].eq("Review required")].copy()
        if not unresolved.empty:
            st.markdown("#### Records requiring whole-study confirmation")
            cols = [
                "Architecture_Record_ID","Architecture_Unit_Verbatim","Author_Parent_Construct_Verbatim",
                "Author_Relationship_Verbatim","Evidence_Forms","Supporting_Evidence_IDs",
            ]
            st.dataframe(unresolved[[c for c in cols if c in unresolved.columns]],use_container_width=True,hide_index=True,height=340)

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
            "Supervisor Overview",
            "Evidence Base",
            "Evidence Intelligence",
            "Study Architecture Explorer",
            "Dimension Support",
            "Stability & Revisions",
            "Gaps & Integrity",
        ],
        horizontal=True,
        key="bi_dashboard_page",
    )
    st.caption(f"Universe: {universe} · Current filtered rows: {len(filtered)}")
    st.divider()

    if page == "Supervisor Overview":
        render_supervisor_bi_overview(filtered, catalog, frames)
    elif page == "Evidence Base":
        render_overview(filtered, catalog, frames)
        st.divider()
        render_time_context(filtered)
        st.divider()
        render_evidence_quality(filtered, frames)
    elif page == "Evidence Intelligence":
        render_evidence_intelligence(frames)
    elif page == "Study Architecture Explorer":
        render_study_architecture_explorer(frames)
    elif page == "Dimension Support":
        render_dimension_support_bi(frames)
    elif page == "Stability & Revisions":
        render_novelty_stability(filtered, frames)
        st.divider()
        revisions = _revision_summary(frames)
        if not revisions.empty:
            st.markdown("#### Revision activity summary")
            st.dataframe(revisions, use_container_width=True, hide_index=True)
    else:
        render_gaps_integrity_bi(frames)

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
