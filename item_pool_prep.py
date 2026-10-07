from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from defense_mode import measurement_spec_table
from master_utils import (
    active_cluster_register,
    active_dimensions,
    active_themes,
    current_mapping_rows,
    split_ids,
)

ITEM_POOL_PREP_VERSION = "v0.17.2-item-prep"


def _s(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _dimension_row(frames: Dict[str, pd.DataFrame], did: str) -> pd.Series | None:
    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        return None
    hit = dims[dims["Dimension_ID"].astype(str).str.upper().eq(did.upper())]
    return None if hit.empty else hit.iloc[-1]


def _measurement_row(frames: Dict[str, pd.DataFrame], did: str) -> pd.Series | None:
    tbl = measurement_spec_table(frames)
    if tbl.empty or "Dimension_ID" not in tbl.columns:
        return None
    hit = tbl[tbl["Dimension_ID"].astype(str).str.upper().eq(did.upper())]
    return None if hit.empty else hit.iloc[-1]


def _theme_cluster_maps(frames: Dict[str, pd.DataFrame], did: str):
    row = _dimension_row(frames, did)
    if row is None:
        return set(), set(), {}, {}

    theme_ids = set(x.upper() for x in split_ids(row.get("Supporting_Theme_IDs"), "THM"))
    themes = active_themes(frames)
    cluster_ids: set[str] = set()
    cluster_to_theme: Dict[str, str] = {}
    theme_labels: Dict[str, str] = {}

    if not themes.empty:
        for _, tr in themes.iterrows():
            tid = _s(tr.get("Theme_ID")).upper()
            if tid not in theme_ids:
                continue
            theme_labels[tid] = _s(tr.get("Working_Theme_Label"))
            for pcl in split_ids(tr.get("Included_Cluster_IDs"), "PCL"):
                pid = pcl.upper()
                cluster_ids.add(pid)
                cluster_to_theme[pid] = tid

    return theme_ids, cluster_ids, cluster_to_theme, theme_labels


def item_pool_anchor_table(frames: Dict[str, pd.DataFrame], did: str) -> pd.DataFrame:
    theme_ids, cluster_ids, cluster_to_theme, theme_labels = _theme_cluster_maps(frames, did)
    if not cluster_ids:
        return pd.DataFrame()

    mappings = current_mapping_rows(frames).copy()
    if mappings.empty or not {"Code_ID", "Cluster_ID"}.issubset(mappings.columns):
        return pd.DataFrame()

    mappings["_ClusterU"] = mappings["Cluster_ID"].astype(str).str.upper()
    base = mappings[mappings["_ClusterU"].isin(cluster_ids)].copy()
    if base.empty:
        return pd.DataFrame()

    coding = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    evidence = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()

    if not coding.empty and "Code_ID" in coding.columns:
        keep = [
            c for c in [
                "Code_ID", "Evidence_ID", "Study_ID", "First_Order_Code",
                "Code_Fidelity_Status", "Focal_Function", "Managed_Object",
            ] if c in coding.columns
        ]
        code_small = coding[keep].drop_duplicates(subset=["Code_ID"], keep="last")
        base = base.merge(code_small, on="Code_ID", how="left", suffixes=("", "_Coding"))

    if not evidence.empty and "Evidence_ID" in evidence.columns and "Evidence_ID" in base.columns:
        keep = [
            c for c in [
                "Evidence_ID", "Study_ID", "Original_Author_Term",
                "Author_Parent_Construct", "Author_Defined_Relationship",
                "Meaning_Unit_Verbatim", "Context_Verbatim",
                "PM_Practice_Maturity_Evidence_Gate", "Meaning_Unit_Status",
                "Source_Page_Location", "Page_Location", "Source_Locator",
            ] if c in evidence.columns
        ]
        ev_small = evidence[keep].drop_duplicates(subset=["Evidence_ID"], keep="last")
        base = base.merge(ev_small, on="Evidence_ID", how="left", suffixes=("", "_Evidence"))

    clusters = active_cluster_register(frames)
    cluster_labels: Dict[str, str] = {}
    cluster_status: Dict[str, str] = {}
    if not clusters.empty and "Cluster_ID" in clusters.columns:
        for _, cr in clusters.iterrows():
            pid = _s(cr.get("Cluster_ID")).upper()
            cluster_labels[pid] = _s(cr.get("Working_Cluster_Label"))
            cluster_status[pid] = _s(cr.get("Cluster_Status"))

    base["Theme_ID"] = base["_ClusterU"].map(cluster_to_theme)
    base["Theme_Label"] = base["Theme_ID"].map(theme_labels)
    base["Cluster_Label"] = base["_ClusterU"].map(cluster_labels)
    base["Cluster_Status"] = base["_ClusterU"].map(cluster_status)
    base["Dimension_ID"] = did

    if "Study_ID" not in base.columns and "Study_ID_Coding" in base.columns:
        base["Study_ID"] = base["Study_ID_Coding"]
    elif "Study_ID_Coding" in base.columns:
        base["Study_ID"] = base["Study_ID"].where(
            base["Study_ID"].astype(str).str.strip().ne(""),
            base["Study_ID_Coding"],
        )

    sort_cols = [c for c in ["Theme_ID", "Cluster_ID", "Study_ID", "Code_ID"] if c in base.columns]
    if sort_cols:
        base = base.sort_values(sort_cols)

    if "Code_ID" in base.columns:
        base = base.drop_duplicates(subset=["Code_ID"], keep="last")

    return base.drop(columns=["_ClusterU"], errors="ignore")


def _coverage_table(anchors: pd.DataFrame) -> pd.DataFrame:
    if anchors.empty:
        return pd.DataFrame()
    group_cols = [c for c in ["Theme_ID", "Theme_Label", "Cluster_ID", "Cluster_Label", "Cluster_Status"] if c in anchors.columns]
    if not group_cols:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for keys, g in anchors.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        rec = {c: _s(v) for c, v in zip(group_cols, keys)}
        rec["FOCs"] = int(g["Code_ID"].nunique()) if "Code_ID" in g.columns else len(g)
        rec["Source_Records"] = int(g["Study_ID"].nunique()) if "Study_ID" in g.columns else 0
        rec["Evidence_Records"] = int(g["Evidence_ID"].nunique()) if "Evidence_ID" in g.columns else 0
        rows.append(rec)
    return pd.DataFrame(rows)


def _facet_rows(measurement: pd.Series | None) -> pd.DataFrame:
    if measurement is None:
        return pd.DataFrame()
    text = _s(measurement.get("Required_Content_Facets"))
    if not text:
        return pd.DataFrame()
    parts = [x.strip() for x in text.replace("\n", ";").split(";") if x.strip()]
    return pd.DataFrame({
        "Facet_No": list(range(1, len(parts) + 1)),
        "Required_Content_Facet": parts,
        "Mapping_Status": ["Human content mapping required"] * len(parts),
    })


def render_item_pool_preparation(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("### Item-Pool Preparation")
    st.caption(
        f"{ITEM_POOL_PREP_VERSION} · Source-grounded content staging before questionnaire wording. "
        "This view does not convert FOCs directly into survey items."
    )

    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        st.info("No current Candidate Dimensions are available.")
        return

    labels = dict(zip(
        dims["Dimension_ID"].astype(str),
        dims.get("Candidate_Dimension_Name", pd.Series("", index=dims.index)).astype(str),
    ))
    dids = dims["Dimension_ID"].astype(str).tolist()
    did = st.selectbox(
        "Dimension for item-pool preparation",
        dids,
        format_func=lambda x: f"{x} — {labels.get(x, '')}",
        key="item_pool_prep_dimension",
    )

    measurement = _measurement_row(frames, did)
    anchors = item_pool_anchor_table(frames, did)
    facets = _facet_rows(measurement)

    st.markdown(f"## {did} — {labels.get(did, '')}")

    if measurement is not None:
        m1, m2 = st.columns(2)
        with m1:
            st.markdown("#### Measurement brief")
            for label, col in [
                ("Form", "Pre_Item_Measurement_Form"),
                ("Item referent", "Item_Referent"),
                ("Applicability / N-A", "Applicability_NA_Control"),
                ("Disposition", "Pre_Item_Disposition"),
            ]:
                val = _s(measurement.get(col))
                if val:
                    st.markdown(f"**{label}:** {val}")
        with m2:
            st.markdown("#### Guardrails")
            for label, col in [
                ("Exclude / contamination", "Exclude_or_Contamination_Rule"),
                ("Aggregation", "Aggregation_Control"),
                ("Validation gate", "Validation_Gate"),
            ]:
                val = _s(measurement.get(col))
                if val:
                    st.markdown(f"**{label}:** {val}")

    st.markdown("#### A. Required content facets")
    if facets.empty:
        st.warning("No DEC-589 Required_Content_Facets were detected for this Dimension.")
    else:
        st.dataframe(facets, use_container_width=True, hide_index=True)
        st.caption(
            "Facet-to-FOC assignment is intentionally not automated. It should be reviewed using "
            "whole-function meaning, managed object, author parent construct, and source context."
        )

    st.markdown("#### B. Evidence-anchor coverage")
    coverage = _coverage_table(anchors)
    if coverage.empty:
        st.warning("No current mapped evidence anchors were detected for this Dimension.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("FOC anchors", int(anchors["Code_ID"].nunique()) if "Code_ID" in anchors.columns else len(anchors))
    c2.metric("PCLs", int(anchors["Cluster_ID"].nunique()) if "Cluster_ID" in anchors.columns else 0)
    c3.metric("Source records", int(anchors["Study_ID"].nunique()) if "Study_ID" in anchors.columns else 0)
    provisional = 0
    if "Cluster_Status" in anchors.columns:
        provisional = int(anchors.loc[
            anchors["Cluster_Status"].astype(str).str.contains("Provisional", case=False, na=False),
            "Cluster_ID",
        ].nunique())
    c4.metric("Provisional PCLs", provisional)

    st.dataframe(coverage, use_container_width=True, hide_index=True, height=380)

    st.markdown("#### C. Source-grounded content anchors")
    theme_options = ["All"] + sorted(x for x in anchors.get("Theme_ID", pd.Series(dtype=str)).dropna().astype(str).unique() if x)
    cluster_options = ["All"] + sorted(x for x in anchors.get("Cluster_ID", pd.Series(dtype=str)).dropna().astype(str).unique() if x)
    f1, f2 = st.columns(2)
    chosen_theme = f1.selectbox("Theme filter", theme_options, key="item_pool_theme_filter")
    chosen_cluster = f2.selectbox("PCL filter", cluster_options, key="item_pool_cluster_filter")

    shown = anchors.copy()
    if chosen_theme != "All" and "Theme_ID" in shown.columns:
        shown = shown[shown["Theme_ID"].astype(str).eq(chosen_theme)]
    if chosen_cluster != "All" and "Cluster_ID" in shown.columns:
        shown = shown[shown["Cluster_ID"].astype(str).eq(chosen_cluster)]

    display_cols = [
        c for c in [
            "Theme_ID", "Theme_Label", "Cluster_ID", "Cluster_Label", "Cluster_Status",
            "Code_ID", "First_Order_Code", "Study_ID", "Evidence_ID",
            "Original_Author_Term", "Author_Parent_Construct",
            "Author_Defined_Relationship", "PM_Practice_Maturity_Evidence_Gate",
        ] if c in shown.columns
    ]
    st.dataframe(shown[display_cols], use_container_width=True, hide_index=True, height=560)

    st.markdown("#### D. Item-drafting safeguards")
    safeguards = pd.DataFrame({
        "Rule": [
            "Do not use 1 FOC = 1 questionnaire item",
            "Preserve managed object and PM-practice referent",
            "Retain source-defined qualifiers when construct-relevant",
            "Do not turn outcomes/states into maturity-practice indicators",
            "Respect DEC-589 exclusion / contamination boundary",
            "Use applicability/N-A where respondent observability is limited",
            "Do not collapse multifacet content into one unweighted score before validation",
        ],
        "Purpose": [
            "Avoid redundant and overly literal item pools",
            "Protect construct fidelity",
            "Avoid semantic dilution",
            "Protect PMM vs outcome / Project Resilience separation",
            "Protect discriminant content validity",
            "Reduce forced or uninformed responses",
            "Preserve measurement architecture until expert/pilot/empirical validation",
        ],
    })
    st.dataframe(safeguards, use_container_width=True, hide_index=True)

    csv_cols = [
        c for c in [
            "Dimension_ID", "Theme_ID", "Theme_Label", "Cluster_ID", "Cluster_Label",
            "Cluster_Status", "Code_ID", "First_Order_Code", "Study_ID", "Evidence_ID",
            "Original_Author_Term", "Author_Parent_Construct",
            "Author_Defined_Relationship", "Meaning_Unit_Verbatim",
            "PM_Practice_Maturity_Evidence_Gate",
        ] if c in anchors.columns
    ]
    csv_bytes = anchors[csv_cols].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download evidence anchors for item drafting (.csv)",
        data=csv_bytes,
        file_name=f"{did}_item_pool_evidence_anchors.csv",
        mime="text/csv",
        use_container_width=False,
    )
