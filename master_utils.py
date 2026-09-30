from __future__ import annotations

from io import BytesIO
import re
from typing import Dict, Iterable, List, Tuple, Any

import pandas as pd

HEADER_ROW_ZERO_BASED = 3  # workbook headers are on Excel row 4

CORE_SHEETS = [
    "01_Source_Register",
    "02_Capability_Eligibility",
    "03_Study_Profile",
    "04_Verbatim_Evidence",
    "05_First_Order_Coding",
    "06_DeNovo_Clustering",
    "06A_Cluster_Register",
    "07_Descriptive_Themes",
    "08_Candidate_Dimensions",
    "10_Study_Families",
    "11_Decision_Log",
]

REQUIRED_COLUMNS = {
    "01_Source_Register": ["Study_ID"],
    "02_Capability_Eligibility": ["Study_ID", "Dimension_Formation_Decision"],
    "04_Verbatim_Evidence": ["Evidence_ID", "Study_ID", "Meaning_Unit_Verbatim", "Meaning_Unit_Status", "PM_Practice_Maturity_Evidence_Gate"],
    "05_First_Order_Coding": ["Code_ID", "Evidence_ID", "Study_ID", "First_Order_Code", "Code_Fidelity_Status"],
    "06_DeNovo_Clustering": ["Mapping_ID", "Code_ID", "Study_ID", "Cluster_ID", "Mapping_Status"],
    "06A_Cluster_Register": ["Cluster_ID", "Working_Cluster_Label", "Cluster_Status"],
    "07_Descriptive_Themes": ["Theme_ID", "Working_Theme_Label", "Included_Cluster_IDs", "Theme_Status"],
    "08_Candidate_Dimensions": ["Dimension_ID", "Candidate_Dimension_Name", "Supporting_Theme_IDs", "Dimension_Status"],
}


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.dropna(how="all")
    df.columns = [str(c).strip() if c is not None else "" for c in df.columns]
    for c in df.columns:
        if df[c].dtype == "object":
            df[c] = df[c].map(lambda x: x.strip() if isinstance(x, str) else x)
    return df


def load_master_workbook(file_bytes: bytes) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]]]:
    """Read the workbook into DataFrames without modifying the source bytes.

    v0.7 also keeps a raw copy of the README rows so the presentation layer can
    show the latest workbook checkpoint/version without relying on stale embedded
    stability-audit prose. The raw helper frame is internal and is never written
    back to the workbook.
    """
    xls = pd.ExcelFile(BytesIO(file_bytes), engine="openpyxl")
    frames: Dict[str, pd.DataFrame] = {}
    structure: List[Dict[str, Any]] = []
    for sheet in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sheet, header=HEADER_ROW_ZERO_BASED)
            df = _clean_df(df)
        except Exception:
            # Some metadata sheets may not follow the row-4 tabular layout.
            df = pd.DataFrame()
        frames[sheet] = df
        structure.append({"Sheet": sheet, "Rows": int(len(df)), "Columns": int(len(df.columns))})

    if "00_README" in xls.sheet_names:
        try:
            raw = pd.read_excel(xls, sheet_name="00_README", header=None)
            frames["__README_RAW__"] = raw
        except Exception:
            frames["__README_RAW__"] = pd.DataFrame()
    return frames, structure


def validate_master(frames: Dict[str, pd.DataFrame]) -> List[str]:
    issues: List[str] = []
    for sheet, cols in REQUIRED_COLUMNS.items():
        if sheet not in frames:
            issues.append(f"Missing required sheet: {sheet}")
            continue
        missing = [c for c in cols if c not in frames[sheet].columns]
        if missing:
            issues.append(f"{sheet}: missing required columns: {', '.join(missing)}")
    return issues


def nonblank_count(df: pd.DataFrame, col: str) -> int:
    if col not in df.columns:
        return 0
    s = df[col]
    return int((s.notna() & s.astype(str).str.strip().ne("")).sum())


def status_counts(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if col not in df.columns:
        return pd.DataFrame(columns=[col, "Count"])
    s = df[col].dropna().astype(str).str.strip()
    s = s[s.ne("")]
    out = s.value_counts(dropna=False).rename_axis(col).reset_index(name="Count")
    return out


def split_ids(value: Any, prefix: str | None = None) -> List[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    # Prefer explicit ID extraction so prose notes do not become false links.
    if prefix:
        found = re.findall(rf"\b{re.escape(prefix)}-\d{{3}}\b", text, flags=re.IGNORECASE)
        return list(dict.fromkeys(x.upper() for x in found))
    parts = re.split(r"[;,|\n]+", text)
    return [p.strip() for p in parts if p.strip()]


def active_cluster_register(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = frames.get("06A_Cluster_Register", pd.DataFrame()).copy()
    if df.empty or "Cluster_ID" not in df.columns:
        return df
    ids = df["Cluster_ID"].fillna("").astype(str).str.strip()
    mask = ids.str.match(r"^PCL-\d{3}$", case=False, na=False)
    if "Cluster_Status" in df.columns:
        mask &= ~df["Cluster_Status"].fillna("").astype(str).str.contains("Retired|Dissolved", case=False, regex=True)
    return df.loc[mask].copy()


def active_themes(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = frames.get("07_Descriptive_Themes", pd.DataFrame()).copy()
    if df.empty or "Theme_ID" not in df.columns:
        return df
    ids = df["Theme_ID"].fillna("").astype(str).str.strip()
    mask = ids.str.match(r"^THM-\d{3}$", case=False, na=False)
    if "Theme_Status" in df.columns:
        mask &= ~df["Theme_Status"].fillna("").astype(str).str.contains("Retired", case=False, regex=True)
    return df.loc[mask].copy()


def retired_themes(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return historical retired Theme rows for optional audit-history views only.

    These rows are never treated as current Themes and are excluded from all
    current-state counts and higher-order dimension logic.
    """
    df = frames.get("07_Descriptive_Themes", pd.DataFrame()).copy()
    if df.empty or "Theme_ID" not in df.columns:
        return df
    ids = df["Theme_ID"].fillna("").astype(str).str.strip()
    mask = ids.str.match(r"^THM-\d{3}$", case=False, na=False)
    if "Theme_Status" not in df.columns:
        return df.iloc[0:0].copy()
    status = df["Theme_Status"].fillna("").astype(str).str.strip()
    mask &= status.str.contains("Retired", case=False, regex=True)
    return df.loc[mask].copy()


def active_dimensions(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return the current working Candidate Dimensions.

    Workbooks can retain multiple generations of DIM rows for audit history.
    Current candidates may therefore appear either as canonical rows with an
    explicit active status, or as a later SG4 working/audit block whose
    cross-audit result is recorded in Core_Capability_Logic while legacy rows
    remain Historical/Suspended above it.

    Selection rules are content-based rather than tied to a workbook version:
    1) never treat Historical/Superseded/Suspended/Retired/etc. rows as current;
    2) prefer explicit active-status DIM rows when present;
    3) otherwise admit current working rows that have a PASS/PROVISIONAL
       cross-audit result, a working label, definition and inclusion anchor;
    4) when the working row carries descriptive inclusion text instead of THM
       IDs, recover the last source-grounded THM/PCL membership recorded for the
       same DIM ID from the retained historical row. This preserves lineage
       without reactivating the historical label/status.
    """
    df = frames.get("08_Candidate_Dimensions", pd.DataFrame()).copy()
    if df.empty or "Dimension_ID" not in df.columns:
        return df

    ids = df["Dimension_ID"].fillna("").astype(str).str.strip()
    dim_mask = ids.str.match(r"^DIM-\d{3}$", case=False, na=False)
    dims = df.loc[dim_mask].copy()
    if dims.empty:
        return dims

    status = (
        dims["Dimension_Status"].fillna("").astype(str).str.strip()
        if "Dimension_Status" in dims.columns
        else pd.Series("", index=dims.index, dtype=str)
    )
    inactive_pattern = r"Retired|Rejected|Withdrawn|Historical|Superseded|Suspended"
    inactive = status.str.contains(inactive_pattern, case=False, regex=True, na=False)

    # Canonical current rows with an explicit non-inactive status.
    explicit_current = dims.loc[status.ne("") & ~inactive].copy()
    if not explicit_current.empty:
        return explicit_current.drop_duplicates(subset=["Dimension_ID"], keep="last").copy()

    # Some audited workbooks hold the current working set in a secondary SG4
    # block. In those rows the original columns receive the secondary header by
    # position: Candidate_Dimension_Name=working label,
    # Analytical_Definition=dominant function,
    # Supporting_Theme_IDs=primary inclusion anchor,
    # Core_Capability_Logic=cross-audit decision.
    logic = (
        dims["Core_Capability_Logic"].fillna("").astype(str).str.strip()
        if "Core_Capability_Logic" in dims.columns
        else pd.Series("", index=dims.index, dtype=str)
    )
    label = (
        dims["Candidate_Dimension_Name"].fillna("").astype(str).str.strip()
        if "Candidate_Dimension_Name" in dims.columns
        else pd.Series("", index=dims.index, dtype=str)
    )
    definition = (
        dims["Analytical_Definition"].fillna("").astype(str).str.strip()
        if "Analytical_Definition" in dims.columns
        else pd.Series("", index=dims.index, dtype=str)
    )
    inclusion = (
        dims["Supporting_Theme_IDs"].fillna("").astype(str).str.strip()
        if "Supporting_Theme_IDs" in dims.columns
        else pd.Series("", index=dims.index, dtype=str)
    )

    working_mask = (
        status.eq("")
        & logic.str.contains(r"\bPASS\b", case=False, regex=True, na=False)
        & logic.str.contains(r"PROVISIONAL|STABLE|CURRENT|ACTIVE", case=False, regex=True, na=False)
        & label.ne("")
        & definition.ne("")
        & inclusion.ne("")
    )
    working = dims.loc[working_mask].copy()
    if working.empty:
        return dims.iloc[0:0].copy()

    # Recover explicit THM/PCL memberships from the retained canonical lineage
    # row for the same DIM ID when the working block uses descriptive anchors.
    for idx, row in working.iterrows():
        did = str(row.get("Dimension_ID", "")).strip()
        lineage = dims.loc[dims["Dimension_ID"].astype(str).str.strip().eq(did)].copy()
        if lineage.empty:
            continue

        if "Supporting_Theme_IDs" in working.columns:
            cur = str(row.get("Supporting_Theme_IDs", "") or "")
            if not re.search(r"\bTHM-\d{3}\b", cur, flags=re.IGNORECASE):
                candidates = [
                    str(v) for v in lineage["Supporting_Theme_IDs"].dropna().tolist()
                    if re.search(r"\bTHM-\d{3}\b", str(v), flags=re.IGNORECASE)
                ]
                if candidates:
                    working.at[idx, "Supporting_Theme_IDs"] = candidates[-1]

        if "Underlying_Cluster_IDs" in working.columns:
            cur = str(row.get("Underlying_Cluster_IDs", "") or "")
            if not re.search(r"\bPCL-\d{3}\b", cur, flags=re.IGNORECASE):
                candidates = [
                    str(v) for v in lineage["Underlying_Cluster_IDs"].dropna().tolist()
                    if re.search(r"\bPCL-\d{3}\b", str(v), flags=re.IGNORECASE)
                ]
                if candidates:
                    working.at[idx, "Underlying_Cluster_IDs"] = candidates[-1]

        if "Dimension_Status" in working.columns:
            working.at[idx, "Dimension_Status"] = logic.loc[idx]

    return working.drop_duplicates(subset=["Dimension_ID"], keep="last").copy()


def dashboard_metrics(frames: Dict[str, pd.DataFrame]) -> Dict[str, int]:
    src = frames.get("01_Source_Register", pd.DataFrame())
    elig = frames.get("02_Capability_Eligibility", pd.DataFrame())
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame())
    codes = frames.get("05_First_Order_Coding", pd.DataFrame())
    maps = frames.get("06_DeNovo_Clustering", pd.DataFrame())
    clusters = frames.get("06A_Cluster_Register", pd.DataFrame())
    themes = frames.get("07_Descriptive_Themes", pd.DataFrame())
    dims = frames.get("08_Candidate_Dimensions", pd.DataFrame())

    eligible = 0
    if "Dimension_Formation_Decision" in elig.columns:
        eligible = int((elig["Dimension_Formation_Decision"].astype(str).str.strip() == "Eligible").sum())

    analytical_mu = 0
    if "Meaning_Unit_Status" in ev.columns:
        analytical_mu = int((ev["Meaning_Unit_Status"].astype(str).str.strip() == "Approved").sum())

    pass_mu = 0
    if "PM_Practice_Maturity_Evidence_Gate" in ev.columns:
        pass_mu = int((ev["PM_Practice_Maturity_Evidence_Gate"].astype(str).str.strip() == "Pass").sum())

    pass_codes = 0
    if "Code_Fidelity_Status" in codes.columns:
        pass_codes = int(codes["Code_Fidelity_Status"].fillna("").astype(str).str.strip().str.match(r"^Pass(?:\s|$|-|–)", case=False, na=False).sum())

    clustered_codes = 0
    if not maps.empty and "Cluster_ID" in maps.columns:
        mask = maps["Cluster_ID"].fillna("").astype(str).str.match(r"^PCL-\d{3}$", case=False, na=False)
        if "Mapping_Status" in maps.columns:
            mask &= maps["Mapping_Status"].fillna("").astype(str).str.strip().isin(["Stable", "Provisional"])
        clustered_codes = int(maps.loc[mask, "Code_ID"].nunique()) if "Code_ID" in maps.columns else int(mask.sum())

    active_clusters = len(active_cluster_register(frames))
    active_theme_count = len(active_themes(frames))
    dimension_count = len(active_dimensions(frames))

    return {
        "sources": nonblank_count(src, "Study_ID"),
        "eligible_studies": eligible,
        "analytical_meaning_units": analytical_mu,
        "pass_meaning_units": pass_mu,
        "pass_first_order_codes": pass_codes,
        "clustered_codes": clustered_codes,
        "active_clusters": int(active_clusters),
        "active_themes": int(active_theme_count),
        "candidate_dimensions": int(dimension_count),
    }


def theme_cluster_map(frames: Dict[str, pd.DataFrame], include_retired: bool = False) -> pd.DataFrame:
    themes = frames.get("07_Descriptive_Themes", pd.DataFrame()).copy()
    if themes.empty:
        return pd.DataFrame(columns=["Theme_ID", "Theme_Label", "Theme_Status", "Cluster_ID"])
    if not include_retired and "Theme_Status" in themes.columns:
        themes = themes[~themes["Theme_Status"].fillna("").astype(str).str.contains("Retired", case=False, regex=True)]
    rows = []
    for _, r in themes.iterrows():
        for cid in split_ids(r.get("Included_Cluster_IDs"), "PCL"):
            rows.append({
                "Theme_ID": r.get("Theme_ID", ""),
                "Theme_Label": r.get("Working_Theme_Label", ""),
                "Theme_Status": r.get("Theme_Status", ""),
                "Cluster_ID": cid,
            })
    return pd.DataFrame(rows)


def cluster_members(frames: Dict[str, pd.DataFrame], cluster_id: str) -> pd.DataFrame:
    maps = frames.get("06_DeNovo_Clustering", pd.DataFrame()).copy()
    codes = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if maps.empty or "Cluster_ID" not in maps.columns:
        return pd.DataFrame()
    m = maps[maps["Cluster_ID"].astype(str).str.strip() == str(cluster_id).strip()].copy()
    # Keep the presentation/audit view focused on current mappings. Historical mapping
    # rows remain in the MASTER for auditability but should not duplicate current tree branches.
    if not m.empty and "Mapping_Status" in m.columns:
        historical = m["Mapping_Status"].fillna("").astype(str).str.contains(
            r"Retired|Historical|Superseded|Withdrawn|Reassigned", case=False, regex=True
        )
        m = m[~historical].copy()
    if m.empty:
        return m
    if not codes.empty and "Code_ID" in codes.columns:
        keep = [c for c in ["Code_ID", "Evidence_ID", "Study_ID", "First_Order_Code", "Code_Fidelity_Status", "Source_to_Code_Rationale"] if c in codes.columns]
        m = m.merge(codes[keep], on="Code_ID", how="left", suffixes=("", "_coding"))
    if not ev.empty and "Evidence_ID" in ev.columns:
        keep = [c for c in ["Evidence_ID", "Meaning_Unit_Verbatim", "Context_Verbatim", "Original_Author_Term", "Author_Parent_Construct", "Author_Defined_Relationship", "Printed_Page", "PM_Practice_Maturity_Evidence_Gate"] if c in ev.columns]
        # Prefer the mapping Evidence_ID; if unavailable after merge, use coding Evidence_ID.
        evidence_key = "Evidence_ID"
        if evidence_key not in m.columns and "Evidence_ID_coding" in m.columns:
            m[evidence_key] = m["Evidence_ID_coding"]
        if evidence_key in m.columns:
            m = m.merge(ev[keep], on="Evidence_ID", how="left", suffixes=("", "_evidence"))
    return m


def theme_lineage(frames: Dict[str, pd.DataFrame], theme_id: str) -> Dict[str, Any]:
    themes = frames.get("07_Descriptive_Themes", pd.DataFrame())
    clusters = frames.get("06A_Cluster_Register", pd.DataFrame())
    theme_rows = themes[themes.get("Theme_ID", pd.Series(dtype=str)).astype(str).str.strip() == str(theme_id).strip()] if not themes.empty else pd.DataFrame()
    if theme_rows.empty:
        return {"theme": None, "clusters": pd.DataFrame(), "members": pd.DataFrame()}
    theme = theme_rows.iloc[0].to_dict()
    cids = split_ids(theme.get("Included_Cluster_IDs"), "PCL")
    cdf = clusters[clusters["Cluster_ID"].isin(cids)].copy() if not clusters.empty and "Cluster_ID" in clusters.columns else pd.DataFrame()
    members = []
    for cid in cids:
        part = cluster_members(frames, cid)
        if not part.empty:
            part = part.copy()
            part["Theme_ID"] = theme_id
            members.append(part)
    mdf = pd.concat(members, ignore_index=True) if members else pd.DataFrame()
    return {"theme": theme, "clusters": cdf, "members": mdf}


def cluster_theme_lookup(frames: Dict[str, pd.DataFrame]) -> Dict[str, List[str]]:
    links = theme_cluster_map(frames, include_retired=True)
    out: Dict[str, List[str]] = {}
    if links.empty:
        return out
    for cid, g in links.groupby("Cluster_ID"):
        out[str(cid)] = g["Theme_ID"].astype(str).tolist()
    return out


def dimension_theme_map(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    # Use only current analytical dimension rows. The sheet can also contain
    # audit/narrative rows that repeat DIM identifiers for boundary tests.
    dims = active_dimensions(frames).copy()
    if dims.empty:
        return pd.DataFrame(columns=["Dimension_ID", "Dimension_Name", "Dimension_Status", "Theme_ID"])
    rows = []
    for _, r in dims.iterrows():
        did = r.get("Dimension_ID")
        if pd.isna(did) or not str(did).strip():
            continue
        for tid in split_ids(r.get("Supporting_Theme_IDs"), "THM"):
            rows.append({
                "Dimension_ID": did,
                "Dimension_Name": r.get("Candidate_Dimension_Name", ""),
                "Dimension_Status": r.get("Dimension_Status", ""),
                "Theme_ID": tid,
            })
    return pd.DataFrame(rows)


def traceability_checks(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    results: List[Dict[str, Any]] = []

    def add(check: str, severity: str, count: int, note: str):
        results.append({"Check": check, "Severity": severity, "Issues": int(count), "Interpretation": note})

    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame())
    codes = frames.get("05_First_Order_Coding", pd.DataFrame())
    maps = current_mapping_rows(frames)
    creg_all = frames.get("06A_Cluster_Register", pd.DataFrame()).copy()
    creg = creg_all[creg_all.get("Cluster_ID", pd.Series(dtype=str)).fillna("").astype(str).str.match(r"^PCL-\d{3}$", case=False, na=False)].copy() if not creg_all.empty else creg_all
    themes_all = frames.get("07_Descriptive_Themes", pd.DataFrame()).copy()
    themes = themes_all[themes_all.get("Theme_ID", pd.Series(dtype=str)).fillna("").astype(str).str.match(r"^THM-\d{3}$", case=False, na=False)].copy() if not themes_all.empty else themes_all
    dims_all = frames.get("08_Candidate_Dimensions", pd.DataFrame()).copy()
    if not dims_all.empty and "Dimension_ID" in dims_all.columns:
        did = dims_all["Dimension_ID"].fillna("").astype(str).str.strip()
        dstatus = dims_all.get("Dimension_Status", pd.Series(index=dims_all.index, dtype=object)).fillna("").astype(str).str.strip()
        dims = dims_all[did.str.match(r"^DIM-\d{3}$", case=False, na=False) & dstatus.ne("")].copy()
    else:
        dims = dims_all

    # Duplicate IDs
    for name, df, col in [
        ("Evidence IDs are unique", ev, "Evidence_ID"),
        ("Code IDs are unique", codes, "Code_ID"),
        ("Mapping IDs are unique", maps, "Mapping_ID"),
        ("Cluster IDs are unique", creg, "Cluster_ID"),
        ("Theme IDs are unique", themes, "Theme_ID"),
        ("Dimension IDs are unique", dims, "Dimension_ID"),
    ]:
        if col in df.columns:
            s = df[col].dropna().astype(str).str.strip()
            s = s[s.ne("")]
            dup = int(s.duplicated().sum())
            add(name, "Error" if dup else "OK", dup, "Duplicate identifiers break one-to-one traceability." if dup else "No duplicate IDs detected.")

    # Code -> evidence
    if "Evidence_ID" in codes.columns and "Evidence_ID" in ev.columns:
        eids = set(ev["Evidence_ID"].dropna().astype(str))
        missing = codes["Evidence_ID"].dropna().astype(str).map(lambda x: x not in eids).sum()
        add("Every code links to an existing evidence record", "Error" if missing else "OK", int(missing), "Missing evidence links require repair." if missing else "All code-to-evidence links resolve.")

    # Mapping -> code
    if "Code_ID" in maps.columns and "Code_ID" in codes.columns:
        cids = set(codes["Code_ID"].dropna().astype(str))
        missing = maps["Code_ID"].dropna().astype(str).map(lambda x: x not in cids).sum()
        add("Every mapping links to an existing first-order code", "Error" if missing else "OK", int(missing), "Missing code links require repair." if missing else "All mapping-to-code links resolve.")

    # Cluster IDs in mappings -> register, ignoring intentionally blank challenged/unclustered rows.
    if "Cluster_ID" in maps.columns and "Cluster_ID" in creg.columns:
        known = set(creg["Cluster_ID"].dropna().astype(str))
        s = maps["Cluster_ID"].dropna().astype(str).str.strip()
        s = s[s.ne("")]
        missing = int((~s.isin(known)).sum())
        add("Mapped Cluster_ID values exist in the cluster register", "Error" if missing else "OK", missing, "Unknown cluster IDs require repair." if missing else "All nonblank mapped clusters resolve.")

    # Only pass fidelity codes should be positively clustered.
    if "Code_ID" in maps.columns and "Cluster_ID" in maps.columns and "Code_ID" in codes.columns and "Code_Fidelity_Status" in codes.columns:
        m = maps[maps["Cluster_ID"].notna() & maps["Cluster_ID"].astype(str).str.strip().ne("")][["Code_ID", "Cluster_ID"]].copy()
        c = codes[["Code_ID", "Code_Fidelity_Status"]].copy()
        x = m.merge(c, on="Code_ID", how="left")
        ok_pass = x["Code_Fidelity_Status"].fillna("").astype(str).str.strip().str.match(r"^Pass(?:\s|$|-|–)", case=False, na=False)
        bad = int((~ok_pass).sum())
        add("Clustered codes have fidelity-Pass status", "Warning" if bad else "OK", bad, "Review any current clustered code that is not fidelity-Pass." if bad else "All current clustered codes are fidelity-Pass.")

    # Theme cluster references
    known_clusters = set(creg["Cluster_ID"].dropna().astype(str)) if "Cluster_ID" in creg.columns else set()
    missing_theme_refs = 0
    if "Included_Cluster_IDs" in themes.columns:
        for v in themes["Included_Cluster_IDs"].dropna():
            missing_theme_refs += sum(1 for x in split_ids(v, "PCL") if x not in known_clusters)
    add("Theme cluster references resolve to the cluster register", "Error" if missing_theme_refs else "OK", missing_theme_refs, "Unknown theme-to-cluster links require repair." if missing_theme_refs else "All theme cluster references resolve.")

    # Dimension theme refs (future-proofed)
    known_themes = set(themes["Theme_ID"].dropna().astype(str)) if "Theme_ID" in themes.columns else set()
    missing_dim_refs = 0
    if "Supporting_Theme_IDs" in dims.columns:
        for v in dims["Supporting_Theme_IDs"].dropna():
            missing_dim_refs += sum(1 for x in split_ids(v, "THM") if x not in known_themes)
    add("Dimension theme references resolve to descriptive themes", "Error" if missing_dim_refs else "OK", missing_dim_refs, "Unknown dimension-to-theme links require repair." if missing_dim_refs else "All current dimension-theme references resolve (or no dimensions exist yet).")

    return pd.DataFrame(results)


def cluster_coverage_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    creg = active_cluster_register(frames)
    maps = current_mapping_rows(frames)
    links = theme_cluster_map(frames, include_retired=True)
    if creg.empty:
        return pd.DataFrame()
    out = creg[[c for c in ["Cluster_ID", "Working_Cluster_Label", "Cluster_Status"] if c in creg.columns]].copy()
    if not maps.empty and "Cluster_ID" in maps.columns:
        current_mapped = maps[maps["Mapping_Status"].fillna("").astype(str).str.strip().isin(["Stable", "Provisional"])].copy() if "Mapping_Status" in maps.columns else maps.copy()
        current_mapped = current_mapped[current_mapped["Cluster_ID"].fillna("").astype(str).str.match(r"^PCL-\d{3}$", case=False, na=False)]
        agg = current_mapped.groupby("Cluster_ID").agg(
            Codes=("Code_ID", "nunique"),
            Studies=("Study_ID", "nunique"),
        ).reset_index()
        out = out.merge(agg, on="Cluster_ID", how="left")
    if not links.empty:
        theme_agg = links.groupby("Cluster_ID")["Theme_ID"].apply(lambda s: "; ".join(sorted(set(map(str, s))))).reset_index(name="Theme_IDs")
        out = out.merge(theme_agg, on="Cluster_ID", how="left")
    for c in ["Codes", "Studies"]:
        if c in out.columns:
            out[c] = out[c].fillna(0).astype(int)
    return out


def current_mapping_rows(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Current SG2 rows only: Stable, Provisional, or Challenged active FOCs."""
    df = frames.get("06_DeNovo_Clustering", pd.DataFrame()).copy()
    if df.empty or "Mapping_Status" not in df.columns:
        return df
    status = df["Mapping_Status"].fillna("").astype(str).str.strip()
    out = df[status.isin(["Stable", "Provisional", "Challenged"])].copy()
    if "Code_ID" in out.columns:
        out = out[out["Code_ID"].fillna("").astype(str).str.match(r"^CD-", case=False, na=False)]
    return out


def provisional_dimensions(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = active_dimensions(frames)
    if df.empty or "Dimension_Status" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["Dimension_Status"].fillna("").astype(str).str.contains("Provisional", case=False, regex=False)].copy()


def challenged_dimensions(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = active_dimensions(frames)
    if df.empty or "Dimension_Status" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["Dimension_Status"].fillna("").astype(str).str.contains("Challenged|Reopened", case=False, regex=True)].copy()


def mapping_status_summary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    cur = current_mapping_rows(frames)
    if cur.empty:
        return pd.DataFrame(columns=["Level", "Status", "Count", "Percent"])
    s = cur["Mapping_Status"].fillna("").astype(str).str.strip()
    counts = s.value_counts().rename_axis("Status").reset_index(name="Count")
    total = int(counts["Count"].sum()) or 1
    counts["Percent"] = counts["Count"] / total * 100
    counts.insert(0, "Level", "FOC → Cluster mapping")
    return counts


def structural_status_summary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    specs = [
        ("FOC → Cluster mapping", current_mapping_rows(frames), "Mapping_Status"),
        ("Active clusters", active_cluster_register(frames), "Cluster_Status"),
        ("Active themes", active_themes(frames), "Theme_Status"),
    ]
    for level, df, col in specs:
        if df.empty or col not in df.columns:
            continue
        s = df[col].fillna("").astype(str).str.strip()
        counts = s[s.ne("")].value_counts()
        total = int(counts.sum()) or 1
        for status, count in counts.items():
            rows.append({"Level": level, "Status": status, "Count": int(count), "Percent": float(count) / total * 100})
    return pd.DataFrame(rows)


def stability_audit_rows(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Read STAB40-* audit rows embedded in 08_Candidate_Dimensions."""
    df = frames.get("08_Candidate_Dimensions", pd.DataFrame()).copy()
    if df.empty or "Dimension_ID" not in df.columns:
        return pd.DataFrame()
    ids = df["Dimension_ID"].fillna("").astype(str).str.strip()
    x = df[ids.str.match(r"^STAB40-\d+$", case=False, na=False)].copy()
    if x.empty:
        return x
    x = x.rename(columns={
        "Dimension_ID": "Audit_ID",
        "Candidate_Dimension_Name": "Test",
        "Analytical_Definition": "Observed_Result",
        "Supporting_Theme_IDs": "Decision_Interpretation",
    })
    keep = [c for c in ["Audit_ID", "Test", "Observed_Result", "Decision_Interpretation"] if c in x.columns]
    return x[keep].reset_index(drop=True)


def progression_gate(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    audits = stability_audit_rows(frames)
    if audits.empty:
        return {"completed": None, "target": None, "percent": None, "text": ""}
    row = audits[audits["Audit_ID"].astype(str).str.upper() == "STAB40-08"]
    if row.empty:
        return {"completed": None, "target": None, "percent": None, "text": ""}
    text_blob = " ".join(str(v) for v in row.iloc[0].tolist() if pd.notna(v))
    pairs = [(int(a), int(b)) for a, b in re.findall(r"\b(\d+)\s*/\s*(\d+)\b", text_blob)]
    if not pairs:
        return {"completed": None, "target": None, "percent": None, "text": text_blob}
    # Audit prose can contain theme lists such as THM-001/008/009. The corpus gate
    # is the fraction with the largest denominator (e.g., 53/132).
    completed, target = max(pairs, key=lambda x: x[1])
    pct = (completed / target * 100) if target else None
    return {"completed": completed, "target": target, "percent": pct, "text": text_blob}


def dimension_evidence_summary(frames: Dict[str, pd.DataFrame], include_challenged: bool = False) -> pd.DataFrame:
    dims = active_dimensions(frames)
    if not include_challenged and not dims.empty and "Dimension_Status" in dims.columns:
        dims = dims[dims["Dimension_Status"].fillna("").astype(str).str.contains("Provisional", case=False, regex=False)].copy()
    themes = active_themes(frames)
    theme_to_clusters: Dict[str, List[str]] = {}
    if not themes.empty:
        for _, r in themes.iterrows():
            theme_to_clusters[str(r.get("Theme_ID", "")).strip()] = split_ids(r.get("Included_Cluster_IDs"), "PCL")
    cur = current_mapping_rows(frames)
    mapped = cur[cur["Mapping_Status"].fillna("").astype(str).str.strip().isin(["Stable", "Provisional"])].copy() if not cur.empty else pd.DataFrame()
    rows = []
    for _, r in dims.iterrows():
        tids = split_ids(r.get("Supporting_Theme_IDs"), "THM")
        cids: List[str] = []
        for tid in tids:
            cids.extend(theme_to_clusters.get(tid, []))
        cids = list(dict.fromkeys(cids))
        mm = mapped[mapped["Cluster_ID"].fillna("").astype(str).isin(cids)].copy() if not mapped.empty and "Cluster_ID" in mapped.columns else pd.DataFrame()
        rows.append({
            "Dimension_ID": str(r.get("Dimension_ID", "")).strip(),
            "Candidate_Dimension_Name": r.get("Candidate_Dimension_Name", ""),
            "Dimension_Status": r.get("Dimension_Status", ""),
            "Themes": len(tids),
            "Clusters": len(cids),
            "FOCs": int(mm["Code_ID"].nunique()) if not mm.empty and "Code_ID" in mm.columns else 0,
            "Studies": int(mm["Study_ID"].nunique()) if not mm.empty and "Study_ID" in mm.columns else 0,
        })
    return pd.DataFrame(rows)


def unthemed_active_clusters(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    creg = active_cluster_register(frames)
    links = theme_cluster_map(frames, include_retired=False)
    themed = set(links["Cluster_ID"].dropna().astype(str)) if not links.empty else set()
    if creg.empty or "Cluster_ID" not in creg.columns:
        return pd.DataFrame()
    out = creg[~creg["Cluster_ID"].astype(str).isin(themed)].copy()
    coverage = cluster_coverage_table(frames)
    if not coverage.empty and "Cluster_ID" in coverage.columns:
        add_cols = [c for c in ["Cluster_ID", "Codes", "Studies"] if c in coverage.columns]
        out = out.merge(coverage[add_cols], on="Cluster_ID", how="left")
    return out


def unassigned_active_themes(frames: Dict[str, pd.DataFrame], provisional_only: bool = True) -> pd.DataFrame:
    themes = active_themes(frames)
    dims = provisional_dimensions(frames) if provisional_only else active_dimensions(frames)
    assigned: set[str] = set()
    for _, r in dims.iterrows():
        assigned.update(split_ids(r.get("Supporting_Theme_IDs"), "THM"))
    if themes.empty or "Theme_ID" not in themes.columns:
        return pd.DataFrame()
    return themes[~themes["Theme_ID"].astype(str).isin(assigned)].copy()

# ---------------------------------------------------------------------------
# v0.7 visual-analytics helpers
# ---------------------------------------------------------------------------

def master_snapshot(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """Return the latest workbook checkpoint and computed live structural counts.

    The checkpoint/version is read from 00_README when available. Structural
    counts are recomputed from analytical sheets so the app does not depend on
    narrative summary text for live metrics.
    """
    raw = frames.get("__README_RAW__", pd.DataFrame())
    title = ""
    status_text = ""
    next_action = ""
    if not raw.empty:
        def row_text(i: int) -> str:
            if i >= len(raw):
                return ""
            vals = [str(v).strip() for v in raw.iloc[i].tolist() if pd.notna(v) and str(v).strip()]
            return " | ".join(vals)
        title = row_text(0)
        status_text = row_text(2) or row_text(3)
        # Current workbooks place the next action in the row-3/4 narrative.
        for i in [2, 3, 1]:
            t = row_text(i)
            m = re.search(r"Next action\s*:\s*(.+)$", t, flags=re.IGNORECASE)
            if m:
                next_action = m.group(1).strip()
                break

    version_match = re.search(r"\bv\d+(?:\.\d+)+\b", title, flags=re.IGNORECASE)
    version = version_match.group(0) if version_match else ""
    current_dec = re.search(r"CURRENT\s+(DEC-\d+)", status_text, flags=re.IGNORECASE)
    title_dec = re.search(r"\b(DEC-\d+)\b", title, flags=re.IGNORECASE)
    if current_dec:
        decision = current_dec.group(1).upper()
    elif title_dec:
        decision = title_dec.group(1).upper()
    else:
        decision_matches = re.findall(r"\bDEC-\d+\b", status_text, flags=re.IGNORECASE)
        decision = decision_matches[0].upper() if decision_matches else ""

    pairs = [(int(a), int(b)) for a, b in re.findall(r"\b(\d+)\s*/\s*(\d+)\b", status_text)]
    completed = target = None
    if pairs:
        completed, target = max(pairs, key=lambda x: x[1])
    else:
        gate = progression_gate(frames)
        completed, target = gate.get("completed"), gate.get("target")
    percent = (completed / target * 100) if completed is not None and target else None

    metrics = dashboard_metrics(frames)
    cur = current_mapping_rows(frames)
    mapped = 0
    challenged = 0
    active_focs = 0
    if not cur.empty and "Code_ID" in cur.columns:
        active_focs = int(cur["Code_ID"].nunique())
        if "Mapping_Status" in cur.columns:
            status = cur["Mapping_Status"].fillna("").astype(str).str.strip()
            mapped = int(cur.loc[status.isin(["Stable", "Provisional"]), "Code_ID"].nunique())
            challenged = int(cur.loc[status.eq("Challenged"), "Code_ID"].nunique())

    clusters = active_cluster_register(frames)
    themes = active_themes(frames)
    dims = active_dimensions(frames)

    def count_status(df: pd.DataFrame, col: str, pattern: str) -> int:
        if df.empty or col not in df.columns:
            return 0
        return int(df[col].fillna("").astype(str).str.contains(pattern, case=False, regex=True).sum())

    return {
        "title": title,
        "version": version,
        "decision": decision,
        "status_text": status_text,
        "next_action": next_action,
        "completed": completed,
        "target": target,
        "percent": percent,
        "active_focs": active_focs or metrics.get("pass_first_order_codes", 0),
        "mapped_focs": mapped or metrics.get("clustered_codes", 0),
        "challenged_focs": challenged,
        "active_clusters": int(len(clusters)),
        "stable_clusters": count_status(clusters, "Cluster_Status", r"\bStable\b"),
        "provisional_clusters": count_status(clusters, "Cluster_Status", r"Provisional"),
        "active_themes": int(len(themes)),
        "stable_themes": count_status(themes, "Theme_Status", r"\bStable\b"),
        "provisional_themes": count_status(themes, "Theme_Status", r"Provisional"),
        "active_dimensions": int(len(dims)),
        "stable_dimensions": count_status(dims, "Dimension_Status", r"\bStable\b"),
        "provisional_dimensions": count_status(dims, "Dimension_Status", r"Provisional"),
        "challenged_dimensions": count_status(dims, "Dimension_Status", r"Challenged|Reopened"),
    }


def theme_summary_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Current Theme -> Cluster -> FOC/Study breadth summary."""
    themes = active_themes(frames)
    cur = current_mapping_rows(frames)
    if themes.empty:
        return pd.DataFrame()
    mapped = cur.copy()
    if not mapped.empty and "Mapping_Status" in mapped.columns:
        mapped = mapped[mapped["Mapping_Status"].fillna("").astype(str).str.strip().isin(["Stable", "Provisional"])]
    dmap = dimension_theme_map(frames)
    dim_lookup: Dict[str, List[str]] = {}
    if not dmap.empty:
        for tid, g in dmap.groupby("Theme_ID"):
            dim_lookup[str(tid)] = sorted(set(g["Dimension_ID"].astype(str)))
    rows = []
    for _, r in themes.iterrows():
        tid = str(r.get("Theme_ID", "")).strip()
        cids = split_ids(r.get("Included_Cluster_IDs"), "PCL")
        mm = mapped[mapped["Cluster_ID"].fillna("").astype(str).isin(cids)].copy() if not mapped.empty and "Cluster_ID" in mapped.columns else pd.DataFrame()
        rows.append({
            "Theme_ID": tid,
            "Theme_Label": r.get("Working_Theme_Label", ""),
            "Theme_Status": r.get("Theme_Status", ""),
            "Clusters": len(cids),
            "FOCs": int(mm["Code_ID"].nunique()) if not mm.empty and "Code_ID" in mm.columns else 0,
            "Studies": int(mm["Study_ID"].nunique()) if not mm.empty and "Study_ID" in mm.columns else 0,
            "Dimension_IDs": "; ".join(dim_lookup.get(tid, [])),
        })
    return pd.DataFrame(rows)


def challenged_foc_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Traceable table of current challenged FOCs with source-near context."""
    cur = current_mapping_rows(frames)
    if cur.empty or "Mapping_Status" not in cur.columns:
        return pd.DataFrame()
    out = cur[cur["Mapping_Status"].fillna("").astype(str).str.strip().eq("Challenged")].copy()
    if out.empty:
        return out

    codes = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()

    # Fill code/evidence fields from authoritative sheets when the mapping sheet
    # does not carry the latest source-near values.
    if not codes.empty and "Code_ID" in codes.columns:
        keep = [c for c in [
            "Code_ID", "Evidence_ID", "Study_ID", "First_Order_Code", "Source_to_Code_Rationale",
            "Alternative_Code_Considered", "Code_Fidelity_Status"
        ] if c in codes.columns]
        out = out.merge(codes[keep], on="Code_ID", how="left", suffixes=("", "_coding"))
        for col in ["Evidence_ID", "Study_ID", "First_Order_Code"]:
            alt = f"{col}_coding"
            if alt in out.columns:
                if col not in out.columns:
                    out[col] = out[alt]
                else:
                    out[col] = out[col].where(out[col].notna() & out[col].astype(str).str.strip().ne(""), out[alt])
    if not ev.empty and "Evidence_ID" in ev.columns and "Evidence_ID" in out.columns:
        keep = [c for c in [
            "Evidence_ID", "Meaning_Unit_Verbatim", "Context_Verbatim", "Original_Author_Term",
            "Author_Parent_Construct", "Author_Defined_Relationship", "Printed_Page"
        ] if c in ev.columns]
        out = out.merge(ev[keep], on="Evidence_ID", how="left", suffixes=("", "_evidence"))

    preferred = [
        "Code_ID", "Study_ID", "Evidence_ID", "First_Order_Code", "Meaning_Unit_Verbatim", "Context_Verbatim",
        "Original_Author_Term", "Author_Parent_Construct", "Author_Defined_Relationship",
        "Closest_Competing_Cluster", "Boundary_Rationale", "Mapping_Rationale",
        "Alternative_Code_Considered", "Source_to_Code_Rationale", "Printed_Page"
    ]
    cols = [c for c in preferred if c in out.columns]
    return out[cols].drop_duplicates(subset=["Code_ID"] if "Code_ID" in cols else None).reset_index(drop=True)


def provisional_cluster_summary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    creg = active_cluster_register(frames)
    if creg.empty or "Cluster_Status" not in creg.columns:
        return pd.DataFrame()
    out = creg[creg["Cluster_Status"].fillna("").astype(str).str.contains("Provisional", case=False, regex=False)].copy()
    if out.empty:
        return out
    coverage = cluster_coverage_table(frames)
    if not coverage.empty and "Cluster_ID" in coverage.columns:
        add = [c for c in ["Cluster_ID", "Codes", "Studies", "Theme_IDs"] if c in coverage.columns]
        out = out.merge(coverage[add], on="Cluster_ID", how="left")
    cols = [c for c in [
        "Cluster_ID", "Working_Cluster_Label", "Cluster_Status", "Codes", "Studies", "Theme_IDs",
        "Operational_Definition", "Inclusion_Boundary", "Exclusion_Boundary",
        "Nearest_Conceptual_Neighbours", "Challenge_Review_Decision", "Audit_Sensitivity_Flag",
        "Audit_Disposition", "Audit_Rationale"
    ] if c in out.columns]
    return out[cols].reset_index(drop=True)


def mu_context_audit_summary(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    df = frames.get("04A_MU_Context_Audit", pd.DataFrame()).copy()
    if df.empty:
        return {"total": 0, "risk": pd.DataFrame(), "decisions": pd.DataFrame(), "changed_mu": pd.DataFrame(), "changed_foc": pd.DataFrame()}
    risk = status_counts(df, "Risk_Tier") if "Risk_Tier" in df.columns else pd.DataFrame()
    decisions = status_counts(df, "Audit_Decision") if "Audit_Decision" in df.columns else pd.DataFrame()
    changed_mu = pd.DataFrame()
    if {"Pre_Audit_Meaning_Unit", "Post_Audit_Meaning_Unit"}.issubset(df.columns):
        pre = df["Pre_Audit_Meaning_Unit"].fillna("").astype(str).str.strip()
        post = df["Post_Audit_Meaning_Unit"].fillna("").astype(str).str.strip()
        changed_mu = df[pre.ne(post)].copy()
    changed_foc = pd.DataFrame()
    if {"Pre_Audit_First_Order_Code", "Post_Audit_First_Order_Code"}.issubset(df.columns):
        pre = df["Pre_Audit_First_Order_Code"].fillna("").astype(str).str.strip()
        post = df["Post_Audit_First_Order_Code"].fillna("").astype(str).str.strip()
        changed_foc = df[pre.ne(post)].copy()
    return {
        "total": int(len(df)),
        "risk": risk,
        "decisions": decisions,
        "changed_mu": changed_mu,
        "changed_foc": changed_foc,
        "table": df,
    }


def current_dimension_evidence_summary(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Evidence breadth for all current (non-retired) dimensions, including Stable."""
    return dimension_evidence_summary(frames, include_challenged=True)
