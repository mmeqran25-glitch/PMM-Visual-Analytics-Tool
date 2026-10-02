from __future__ import annotations

import re
from typing import Dict, Any, Iterable

import pandas as pd
import streamlit as st

from master_utils import (
    active_cluster_register,
    active_dimensions,
    active_themes,
    current_mapping_rows,
    dimension_theme_map,
    theme_cluster_map,
)

EVIDENCE_MATRIX_VERSION = "v0.16.0"


def _clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _fill_from_suffix(df: pd.DataFrame, columns: Iterable[str], suffix: str) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        alt = f"{col}{suffix}"
        if alt not in out.columns:
            continue
        if col not in out.columns:
            out[col] = out[alt]
        else:
            cur = out[col].fillna("").astype(str).str.strip()
            out[col] = out[col].where(cur.ne(""), out[alt])
    return out


def _family_lookup(frames: Dict[str, pd.DataFrame]) -> tuple[dict[str, str], bool, str]:
    """Return Study_ID -> evidence-family mapping when the MASTER records one.

    The function is deliberately conservative: it only accepts explicit family/canonical
    identifiers and never infers independence from author names or titles.
    """
    candidates = [
        ("10_Study_Families", ["Study_Family_ID", "Family_ID", "Evidence_Family_ID", "Source_Family_ID", "Canonical_Study_ID"]),
        ("03_Study_Profile", ["Study_Family_ID", "Family_ID", "Evidence_Family_ID", "Source_Family_ID", "Canonical_Study_ID"]),
    ]
    for sheet, cols in candidates:
        df = frames.get(sheet, pd.DataFrame()).copy()
        if df.empty or "Study_ID" not in df.columns:
            continue
        family_col = next((c for c in cols if c in df.columns), None)
        if not family_col:
            continue
        sub = df[["Study_ID", family_col]].copy()
        sub["Study_ID"] = sub["Study_ID"].fillna("").astype(str).str.strip()
        sub[family_col] = sub[family_col].fillna("").astype(str).str.strip()
        sub = sub[sub["Study_ID"].ne("")].drop_duplicates(subset=["Study_ID"], keep="last")
        if sub.empty:
            continue
        lookup = {
            str(r["Study_ID"]).strip(): (str(r[family_col]).strip() or str(r["Study_ID"]).strip())
            for _, r in sub.iterrows()
        }
        return lookup, True, f"{sheet}.{family_col}"
    return {}, False, ""


def build_evidence_links(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build the current Study -> FOC -> PCL -> Theme -> Dimension analytical lineage."""
    cur = current_mapping_rows(frames).copy()
    if cur.empty or "Code_ID" not in cur.columns:
        return pd.DataFrame()

    cur["Code_ID"] = cur["Code_ID"].fillna("").astype(str).str.strip()
    cur = cur[cur["Code_ID"].ne("")].copy()

    codes = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    if not codes.empty and "Code_ID" in codes.columns:
        keep = [c for c in [
            "Code_ID", "Evidence_ID", "Study_ID", "First_Order_Code", "Code_Fidelity_Status",
            "Source_to_Code_Rationale", "Alternative_Code_Considered",
        ] if c in codes.columns]
        cref = codes[keep].drop_duplicates(subset=["Code_ID"], keep="last")
        cur = cur.merge(cref, on="Code_ID", how="left", suffixes=("", "_coding"))
        cur = _fill_from_suffix(cur, ["Evidence_ID", "Study_ID", "First_Order_Code"], "_coding")

    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if not ev.empty and "Evidence_ID" in ev.columns and "Evidence_ID" in cur.columns:
        keep = [c for c in [
            "Evidence_ID", "Meaning_Unit_Verbatim", "Context_Verbatim", "Original_Author_Term",
            "Author_Parent_Construct", "Author_Defined_Relationship", "Printed_Page",
            "PM_Practice_Maturity_Evidence_Gate", "Meaning_Unit_Status",
        ] if c in ev.columns]
        eref = ev[keep].drop_duplicates(subset=["Evidence_ID"], keep="last")
        cur = cur.merge(eref, on="Evidence_ID", how="left", suffixes=("", "_evidence"))

    creg = active_cluster_register(frames).copy()
    if not creg.empty and "Cluster_ID" in creg.columns and "Cluster_ID" in cur.columns:
        keep = [c for c in [
            "Cluster_ID", "Working_Cluster_Label", "Cluster_Status", "Operational_Definition",
            "Inclusion_Boundary", "Exclusion_Boundary", "Nearest_Conceptual_Neighbours",
            "Audit_Sensitivity_Flag", "Audit_Disposition", "Audit_Rationale",
        ] if c in creg.columns]
        cur = cur.merge(creg[keep].drop_duplicates("Cluster_ID", keep="last"), on="Cluster_ID", how="left")

    tlinks = theme_cluster_map(frames, include_retired=False)
    if not tlinks.empty and "Cluster_ID" in cur.columns:
        tlinks = tlinks.rename(columns={"Theme_Label": "Working_Theme_Label"})
        cur = cur.merge(
            tlinks[[c for c in ["Cluster_ID", "Theme_ID", "Working_Theme_Label", "Theme_Status"] if c in tlinks.columns]],
            on="Cluster_ID",
            how="left",
        )

    dlinks = dimension_theme_map(frames)
    if not dlinks.empty and "Theme_ID" in cur.columns:
        dlinks = dlinks.rename(columns={"Dimension_Name": "Candidate_Dimension_Name"})
        cur = cur.merge(
            dlinks[[c for c in ["Theme_ID", "Dimension_ID", "Candidate_Dimension_Name", "Dimension_Status"] if c in dlinks.columns]],
            on="Theme_ID",
            how="left",
        )

    src = frames.get("01_Source_Register", pd.DataFrame()).copy()
    if not src.empty and "Study_ID" in src.columns and "Study_ID" in cur.columns:
        source_fields = [
            "Study_ID", "Title", "Authors", "Author", "Year", "Publication_Year",
            "Country", "Country_Context", "Sector", "Sector_Context", "Study_Design",
            "Methodological_Family", "Source_Publication_Type",
        ]
        keep = [c for c in source_fields if c in src.columns]
        if len(keep) > 1:
            sref = src[keep].drop_duplicates(subset=["Study_ID"], keep="last")
            cur = cur.merge(sref, on="Study_ID", how="left", suffixes=("", "_source"))

    families, family_available, family_source = _family_lookup(frames)
    cur["Evidence_Family_ID"] = cur.get("Study_ID", pd.Series("", index=cur.index)).fillna("").astype(str).str.strip()
    if families:
        cur["Evidence_Family_ID"] = cur["Study_ID"].astype(str).map(families).fillna(cur["Study_ID"].astype(str))
    cur.attrs["family_available"] = family_available
    cur.attrs["family_source"] = family_source
    return cur


def _apply_core_filters(
    rows: pd.DataFrame,
    mapping_statuses: list[str],
    evidence_gates: list[str],
    study_search: str,
) -> pd.DataFrame:
    out = rows.copy()
    if out.empty:
        return out
    if mapping_statuses and "Mapping_Status" in out.columns:
        out = out[out["Mapping_Status"].fillna("").astype(str).isin(mapping_statuses)].copy()
    if evidence_gates and "PM_Practice_Maturity_Evidence_Gate" in out.columns:
        out = out[out["PM_Practice_Maturity_Evidence_Gate"].fillna("").astype(str).isin(evidence_gates)].copy()
    text = _clean_text(study_search).lower()
    if text and "Study_ID" in out.columns:
        source_cols = [c for c in ["Study_ID", "Title", "Authors", "Author", "Year", "Country", "Country_Context", "Sector", "Sector_Context"] if c in out.columns]
        blob = out[source_cols].fillna("").astype(str).agg(" | ".join, axis=1).str.lower()
        out = out[blob.str.contains(re.escape(text), regex=True, na=False)].copy()
    return out


def _support_ids(rows: pd.DataFrame, group_col: str, use_families: bool) -> pd.Series:
    if rows.empty or group_col not in rows.columns:
        return pd.Series(dtype=int)
    support_col = "Evidence_Family_ID" if use_families and "Evidence_Family_ID" in rows.columns else "Study_ID"
    x = rows.dropna(subset=[group_col]).copy()
    x = x[x[group_col].astype(str).str.strip().ne("")]
    if x.empty:
        return pd.Series(dtype=int)
    return x.groupby(group_col)[support_col].nunique()


def _matrix(
    rows: pd.DataFrame,
    row_col: str,
    col_col: str,
    mode: str,
    row_order: list[str] | None = None,
    col_order: list[str] | None = None,
) -> pd.DataFrame:
    if rows.empty or row_col not in rows.columns or col_col not in rows.columns:
        return pd.DataFrame()
    x = rows.copy()
    x[row_col] = x[row_col].fillna("").astype(str).str.strip()
    x[col_col] = x[col_col].fillna("").astype(str).str.strip()
    x = x[x[row_col].ne("") & x[col_col].ne("")]
    if x.empty:
        return pd.DataFrame()

    if mode == "PCL Count":
        value_col = "Cluster_ID"
    elif mode == "FOC Count":
        value_col = "Code_ID"
    else:
        value_col = "Code_ID"

    if value_col not in x.columns:
        x[value_col] = 1

    p = x.pivot_table(
        index=row_col,
        columns=col_col,
        values=value_col,
        aggfunc=pd.Series.nunique if value_col in x.columns else "size",
        fill_value=0,
    )

    if row_order:
        p = p.reindex([r for r in row_order if r in p.index])
    if col_order:
        p = p.reindex(columns=[c for c in col_order if c in p.columns])

    if mode == "Presence":
        return p.gt(0).replace({True: "●", False: ""})
    return p.astype(int)


def build_study_theme_matrix(rows: pd.DataFrame, mode: str = "Presence", theme_ids: list[str] | None = None) -> pd.DataFrame:
    studies = sorted(rows.get("Study_ID", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()) if not rows.empty else []
    themes = theme_ids or sorted(rows.get("Theme_ID", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
    return _matrix(rows, "Study_ID", "Theme_ID", mode, studies, themes)


def build_study_dimension_matrix(rows: pd.DataFrame, mode: str = "Presence", dimension_ids: list[str] | None = None) -> pd.DataFrame:
    studies = sorted(rows.get("Study_ID", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()) if not rows.empty else []
    dims = dimension_ids or sorted(rows.get("Dimension_ID", pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
    return _matrix(rows, "Study_ID", "Dimension_ID", mode, studies, dims)


def build_pcl_theme_matrix(frames: Dict[str, pd.DataFrame], theme_ids: list[str] | None = None) -> pd.DataFrame:
    links = theme_cluster_map(frames, include_retired=False)
    if links.empty:
        return pd.DataFrame()
    if theme_ids:
        links = links[links["Theme_ID"].astype(str).isin(theme_ids)].copy()
    if links.empty:
        return pd.DataFrame()
    links["Presence"] = "●"
    p = links.pivot_table(index="Cluster_ID", columns="Theme_ID", values="Presence", aggfunc="first", fill_value="")
    p = p.reindex(sorted(p.index))
    return p


def _download_csv(label: str, df: pd.DataFrame, filename: str, key: str) -> None:
    if df.empty:
        return
    st.download_button(
        label,
        data=df.reset_index().to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        key=key,
        use_container_width=True,
    )


def _selection_rows(event: Any) -> list[int]:
    if event is None:
        return []
    try:
        return list(event.selection.rows)
    except Exception:
        pass
    if isinstance(event, dict):
        sel = event.get("selection", {})
        if isinstance(sel, dict):
            return list(sel.get("rows", []) or [])
    return []


def _show_matrix(df: pd.DataFrame, key: str, height: int = 560) -> tuple[Any, pd.DataFrame]:
    shown = df.reset_index()
    try:
        event = st.dataframe(
            shown,
            use_container_width=True,
            hide_index=True,
            height=height,
            on_select="rerun",
            selection_mode="single-row",
            key=key,
        )
    except TypeError:
        st.dataframe(shown, use_container_width=True, hide_index=True, height=height)
        event = None
    return event, shown


def _decision_history(frames: Dict[str, pd.DataFrame], identifiers: list[str]) -> pd.DataFrame:
    log = frames.get("11_Decision_Log", pd.DataFrame()).copy()
    ids = [str(x).strip() for x in identifiers if str(x).strip()]
    if log.empty or not ids:
        return pd.DataFrame()
    text_cols = [c for c in log.columns if log[c].dtype == "object"]
    if not text_cols:
        return pd.DataFrame()
    mask = pd.Series(False, index=log.index)
    for c in text_cols:
        s = log[c].fillna("").astype(str)
        for ident in ids:
            mask |= s.str.contains(re.escape(ident), case=False, regex=True, na=False)
    return log.loc[mask].copy()


def _trace_columns(df: pd.DataFrame) -> list[str]:
    preferred = [
        "Study_ID", "Evidence_Family_ID", "Code_ID", "First_Order_Code", "Cluster_ID",
        "Working_Cluster_Label", "Theme_ID", "Working_Theme_Label", "Dimension_ID",
        "Candidate_Dimension_Name", "Evidence_ID", "Meaning_Unit_Verbatim",
        "Original_Author_Term", "Author_Parent_Construct", "Author_Defined_Relationship",
        "PM_Practice_Maturity_Evidence_Gate", "Mapping_Status", "Mapping_Rationale",
        "Boundary_Rationale", "Printed_Page",
    ]
    return [c for c in preferred if c in df.columns]


def _render_trace_details(frames: Dict[str, pd.DataFrame], evidence: pd.DataFrame, title: str) -> None:
    if evidence.empty:
        st.info("No current evidence is linked to this selected matrix cell.")
        return
    st.markdown(f"#### {title}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FOCs", int(evidence["Code_ID"].nunique()) if "Code_ID" in evidence.columns else 0)
    c2.metric("PCLs", int(evidence["Cluster_ID"].nunique()) if "Cluster_ID" in evidence.columns else 0)
    c3.metric("Evidence units", int(evidence["Evidence_ID"].nunique()) if "Evidence_ID" in evidence.columns else len(evidence))
    c4.metric("Evidence families", int(evidence["Evidence_Family_ID"].nunique()) if "Evidence_Family_ID" in evidence.columns else 0)

    cols = _trace_columns(evidence)
    st.dataframe(evidence[cols].drop_duplicates(), use_container_width=True, hide_index=True, height=360)

    ids = []
    for c in ["Code_ID", "Cluster_ID", "Theme_ID", "Dimension_ID"]:
        if c in evidence.columns:
            ids.extend(evidence[c].dropna().astype(str).unique().tolist())
    hist = _decision_history(frames, ids)
    with st.expander(f"Audit / Decision history ({len(hist)} matched rows)"):
        if hist.empty:
            st.caption("No decision-log row explicitly references the selected IDs.")
        else:
            preferred = [c for c in [
                "Decision_ID", "Date", "Decision_Type", "Object_ID", "Affected_IDs",
                "Decision", "Rationale", "Before", "After", "Status", "Notes",
            ] if c in hist.columns]
            show = preferred or hist.columns.tolist()
            st.dataframe(hist[show], use_container_width=True, hide_index=True, height=300)


def _study_label(rows: pd.DataFrame, study_id: str) -> str:
    x = rows[rows["Study_ID"].astype(str).eq(str(study_id))] if "Study_ID" in rows.columns else pd.DataFrame()
    if x.empty:
        return str(study_id)
    r = x.iloc[0]
    parts = [str(study_id)]
    author = _clean_text(r.get("Authors")) or _clean_text(r.get("Author"))
    year = _clean_text(r.get("Year")) or _clean_text(r.get("Publication_Year"))
    if author:
        parts.append(author)
    if year:
        parts.append(year)
    return " — ".join(parts)


def _render_study_theme_tab(
    frames: Dict[str, pd.DataFrame],
    rows: pd.DataFrame,
    mode: str,
    use_families: bool,
    min_support: int,
) -> None:
    themes = active_themes(frames)
    if themes.empty:
        st.info("No current Themes are available.")
        return
    theme_labels = dict(zip(themes["Theme_ID"].astype(str), themes.get("Working_Theme_Label", pd.Series("", index=themes.index)).fillna("").astype(str)))
    support = _support_ids(rows.dropna(subset=["Theme_ID"]) if "Theme_ID" in rows.columns else rows, "Theme_ID", use_families)
    eligible = [tid for tid in themes["Theme_ID"].astype(str).tolist() if int(support.get(tid, 0)) >= min_support]

    selected = st.multiselect(
        "Themes shown as columns",
        eligible,
        default=eligible,
        format_func=lambda x: f"{x} — {theme_labels.get(x, '')}",
        key="ecm_theme_columns",
    )
    if not selected:
        st.info("Select at least one Theme.")
        return

    x = rows[rows["Theme_ID"].fillna("").astype(str).isin(selected)].copy() if "Theme_ID" in rows.columns else pd.DataFrame()
    matrix = build_study_theme_matrix(x, mode=mode, theme_ids=selected)
    if matrix.empty:
        st.info("No Study × Theme links remain after the selected filters.")
        return

    st.caption("Select a study row, then choose one populated Theme below to inspect the full evidence chain.")
    event, shown = _show_matrix(matrix, key="ecm_study_theme_table")
    _download_csv("Download Study × Theme CSV", matrix, "PMM_Study_Theme_Matrix.csv", "ecm_download_theme")

    selected_rows = _selection_rows(event)
    if selected_rows:
        pos = selected_rows[0]
        if 0 <= pos < len(shown):
            study_id = str(shown.iloc[pos]["Study_ID"])
            populated = [c for c in selected if str(shown.iloc[pos].get(c, "")).strip() not in ["", "0"]]
            if populated:
                tid = st.selectbox(
                    "Populated Theme cell to inspect",
                    populated,
                    format_func=lambda z: f"{z} — {theme_labels.get(z, '')}",
                    key=f"ecm_cell_theme_{study_id}",
                )
                ev = x[(x["Study_ID"].astype(str) == study_id) & (x["Theme_ID"].astype(str) == tid)].copy()
                _render_trace_details(frames, ev, f"{_study_label(x, study_id)} × {tid}")


def _render_study_dimension_tab(
    frames: Dict[str, pd.DataFrame],
    rows: pd.DataFrame,
    mode: str,
    use_families: bool,
    min_support: int,
) -> None:
    dims = active_dimensions(frames)
    if dims.empty:
        st.info("No current Candidate Dimensions are available.")
        return
    labels = dict(zip(dims["Dimension_ID"].astype(str), dims.get("Candidate_Dimension_Name", pd.Series("", index=dims.index)).fillna("").astype(str)))
    support = _support_ids(rows.dropna(subset=["Dimension_ID"]) if "Dimension_ID" in rows.columns else rows, "Dimension_ID", use_families)
    eligible = [did for did in dims["Dimension_ID"].astype(str).tolist() if int(support.get(did, 0)) >= min_support]

    selected = st.multiselect(
        "Candidate Dimensions shown as columns",
        eligible,
        default=eligible,
        format_func=lambda x: f"{x} — {labels.get(x, '')}",
        key="ecm_dim_columns",
    )
    if not selected:
        st.info("Select at least one Candidate Dimension.")
        return

    x = rows[rows["Dimension_ID"].fillna("").astype(str).isin(selected)].copy() if "Dimension_ID" in rows.columns else pd.DataFrame()
    matrix = build_study_dimension_matrix(x, mode=mode, dimension_ids=selected)
    if matrix.empty:
        st.info("No Study × Dimension links remain after the selected filters.")
        return

    st.caption("Select a study row, then choose one populated Candidate Dimension below to inspect the full evidence chain.")
    event, shown = _show_matrix(matrix, key="ecm_study_dim_table")
    _download_csv("Download Study × Dimension CSV", matrix, "PMM_Study_Dimension_Matrix.csv", "ecm_download_dim")

    selected_rows = _selection_rows(event)
    if selected_rows:
        pos = selected_rows[0]
        if 0 <= pos < len(shown):
            study_id = str(shown.iloc[pos]["Study_ID"])
            populated = [c for c in selected if str(shown.iloc[pos].get(c, "")).strip() not in ["", "0"]]
            if populated:
                did = st.selectbox(
                    "Populated Dimension cell to inspect",
                    populated,
                    format_func=lambda z: f"{z} — {labels.get(z, '')}",
                    key=f"ecm_cell_dim_{study_id}",
                )
                ev = x[(x["Study_ID"].astype(str) == study_id) & (x["Dimension_ID"].astype(str) == did)].copy()
                _render_trace_details(frames, ev, f"{_study_label(x, study_id)} × {did}")


def _render_boundary_tab(frames: Dict[str, pd.DataFrame]) -> None:
    themes = active_themes(frames)
    labels = dict(zip(themes["Theme_ID"].astype(str), themes.get("Working_Theme_Label", pd.Series("", index=themes.index)).fillna("").astype(str))) if not themes.empty else {}
    tids = themes["Theme_ID"].astype(str).tolist() if not themes.empty else []
    selected = st.multiselect(
        "Themes included in the boundary matrix",
        tids,
        default=tids,
        format_func=lambda x: f"{x} — {labels.get(x, '')}",
        key="ecm_boundary_themes",
    )
    matrix = build_pcl_theme_matrix(frames, selected)
    if matrix.empty:
        st.info("No current PCL × Theme membership links are available.")
        return
    event, shown = _show_matrix(matrix, key="ecm_boundary_table", height=520)
    _download_csv("Download PCL × Theme CSV", matrix, "PMM_PCL_Theme_Boundary_Matrix.csv", "ecm_download_boundary")

    links = theme_cluster_map(frames, include_retired=False)
    membership = links.groupby("Cluster_ID")["Theme_ID"].nunique() if not links.empty else pd.Series(dtype=int)
    overlapping = membership[membership > 1]
    a, b = st.columns(2)
    a.metric("Current PCLs in matrix", len(matrix))
    b.metric("PCLs linked to >1 current Theme", int(len(overlapping)))
    if len(overlapping):
        st.warning("Cross-Theme membership detected. Treat these rows as boundary-review signals, not automatic errors.")

    sel = _selection_rows(event)
    if sel:
        pos = sel[0]
        if 0 <= pos < len(shown):
            cid = str(shown.iloc[pos]["Cluster_ID"])
            creg = active_cluster_register(frames)
            row = creg[creg["Cluster_ID"].astype(str).eq(cid)] if not creg.empty else pd.DataFrame()
            member_themes = links.loc[links["Cluster_ID"].astype(str).eq(cid), "Theme_ID"].astype(str).tolist() if not links.empty else []
            st.markdown(f"#### {cid} boundary profile")
            st.write("**Current Theme membership:** " + (", ".join(member_themes) if member_themes else "None"))
            if not row.empty:
                r = row.iloc[0]
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Working cluster label**")
                    st.write(r.get("Working_Cluster_Label", ""))
                    st.markdown("**Operational definition**")
                    st.write(r.get("Operational_Definition", ""))
                    st.markdown("**Inclusion boundary**")
                    st.write(r.get("Inclusion_Boundary", ""))
                with c2:
                    st.markdown("**Exclusion boundary**")
                    st.write(r.get("Exclusion_Boundary", ""))
                    st.markdown("**Nearest conceptual neighbours**")
                    st.write(r.get("Nearest_Conceptual_Neighbours", ""))
                    st.markdown("**Audit disposition**")
                    st.write(r.get("Audit_Disposition", ""))
            hist = _decision_history(frames, [cid] + member_themes)
            with st.expander(f"Related audit / decision history ({len(hist)} rows)"):
                if hist.empty:
                    st.caption("No explicit decision-log references were found.")
                else:
                    st.dataframe(hist, use_container_width=True, hide_index=True, height=300)


def _diversity_table(rows: pd.DataFrame, group_col: str, label_col: str) -> pd.DataFrame:
    if rows.empty or group_col not in rows.columns:
        return pd.DataFrame()
    x = rows.copy()
    x = x[x[group_col].fillna("").astype(str).str.strip().ne("")]
    if x.empty:
        return pd.DataFrame()
    agg = x.groupby(group_col).agg(
        FOCs=("Code_ID", "nunique"),
        PCLs=("Cluster_ID", "nunique"),
        Studies=("Study_ID", "nunique"),
        Evidence_Families=("Evidence_Family_ID", "nunique"),
    ).reset_index()
    if label_col in x.columns:
        labels = x[[group_col, label_col]].dropna().drop_duplicates(subset=[group_col], keep="last")
        agg = agg.merge(labels, on=group_col, how="left")
    agg["FOCs_per_Study"] = (agg["FOCs"] / agg["Studies"].replace(0, pd.NA)).round(2)
    agg["Study_to_Family_Ratio"] = (agg["Studies"] / agg["Evidence_Families"].replace(0, pd.NA)).round(2)
    return agg.sort_values(["Studies", "FOCs"], ascending=[False, False]).reset_index(drop=True)


def _render_diversity_tab(rows: pd.DataFrame, family_available: bool, family_source: str) -> None:
    st.markdown(
        "Coverage breadth is descriptive only. More studies or more FOCs do not automatically make a Theme or Dimension "
        "theoretically stronger; the matrix is an audit aid for breadth, concentration, and traceability."
    )
    if family_available:
        st.success(f"Independent evidence-family metadata detected: {family_source}")
    else:
        st.info("No explicit family identifier was detected; Evidence Families therefore equal Study IDs in this view.")

    t = _diversity_table(rows, "Theme_ID", "Working_Theme_Label")
    d = _diversity_table(rows, "Dimension_ID", "Candidate_Dimension_Name")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Theme evidence diversity")
        if t.empty:
            st.caption("No linked Theme evidence.")
        else:
            st.dataframe(t, use_container_width=True, hide_index=True, height=520)
    with c2:
        st.markdown("#### Candidate-Dimension evidence diversity")
        if d.empty:
            st.caption("No linked Dimension evidence.")
        else:
            st.dataframe(d, use_container_width=True, hide_index=True, height=520)


def render_evidence_coverage_matrices(frames: Dict[str, pd.DataFrame]) -> None:
    st.subheader("Evidence Coverage & Traceability Matrices")
    st.caption(
        "Study-level coverage matrices adapted to the thesis analytical chain: "
        "Study → Evidence → First-Order Code → PCL → Theme → Candidate Dimension."
    )
    st.markdown(
        '<div style="border-left:5px solid #0f6b78;background:#f4fbfc;border-radius:10px;padding:11px 14px;margin:.2rem 0 1rem 0;">'
        '<b>Interpretation rule:</b> Presence and counts describe evidence coverage and traceability. '
        'They are not quality weights, importance scores, or automatic criteria for retaining a Theme or Dimension.'
        '</div>',
        unsafe_allow_html=True,
    )

    rows = build_evidence_links(frames)
    if rows.empty:
        st.info("The current MASTER does not yet contain enough linked SG2/Theme/Dimension data to build the matrices.")
        return

    family_available = bool(rows.attrs.get("family_available", False))
    family_source = str(rows.attrs.get("family_source", ""))

    statuses = sorted(rows["Mapping_Status"].dropna().astype(str).unique().tolist()) if "Mapping_Status" in rows.columns else []
    default_status = [s for s in ["Stable", "Provisional"] if s in statuses] or statuses
    gates = sorted(rows["PM_Practice_Maturity_Evidence_Gate"].dropna().astype(str).unique().tolist()) if "PM_Practice_Maturity_Evidence_Gate" in rows.columns else []
    default_gates = ["Pass"] if "Pass" in gates else gates

    f1, f2, f3, f4 = st.columns([1.35, 1.35, 1.2, 1.1])
    with f1:
        mapping_statuses = st.multiselect("Mapping status", statuses, default=default_status, key="ecm_status")
    with f2:
        evidence_gates = st.multiselect("Evidence gate", gates, default=default_gates, key="ecm_gate") if gates else []
    with f3:
        mode = st.radio("Cell display", ["Presence", "FOC Count", "PCL Count"], horizontal=False, key="ecm_mode")
    with f4:
        use_families = st.checkbox(
            "Use evidence families for breadth threshold",
            value=family_available,
            disabled=not family_available,
            key="ecm_family_threshold",
        )

    search = st.text_input("Study search", placeholder="SR933, author, year, title, country, sector ...", key="ecm_study_search")
    filtered = _apply_core_filters(rows, mapping_statuses, evidence_gates, search)

    support_basis = "Evidence_Family_ID" if use_families and family_available else "Study_ID"
    max_support = int(filtered[support_basis].nunique()) if not filtered.empty and support_basis in filtered.columns else 1
    min_support = st.slider(
        "Minimum independent support required to display a Theme/Dimension",
        min_value=1,
        max_value=max(1, max_support),
        value=1,
        key="ecm_min_support",
        help="This is a display filter only. It does not decide retention or theoretical importance.",
    )

    a, b, c, d, e = st.columns(5)
    a.metric("Studies", int(filtered["Study_ID"].nunique()) if "Study_ID" in filtered.columns else 0)
    b.metric("Evidence families", int(filtered["Evidence_Family_ID"].nunique()) if "Evidence_Family_ID" in filtered.columns else 0)
    c.metric("FOCs", int(filtered["Code_ID"].nunique()) if "Code_ID" in filtered.columns else 0)
    d.metric("Themes", int(filtered["Theme_ID"].dropna().astype(str).replace("", pd.NA).nunique()) if "Theme_ID" in filtered.columns else 0)
    e.metric("Dimensions", int(filtered["Dimension_ID"].dropna().astype(str).replace("", pd.NA).nunique()) if "Dimension_ID" in filtered.columns else 0)

    tabs = st.tabs([
        "Study × Theme",
        "Study × Candidate Dimension",
        "PCL × Theme Boundary",
        "Evidence Diversity",
    ])
    with tabs[0]:
        _render_study_theme_tab(frames, filtered, mode, use_families and family_available, min_support)
    with tabs[1]:
        _render_study_dimension_tab(frames, filtered, mode, use_families and family_available, min_support)
    with tabs[2]:
        _render_boundary_tab(frames)
    with tabs[3]:
        _render_diversity_tab(filtered, family_available, family_source)
