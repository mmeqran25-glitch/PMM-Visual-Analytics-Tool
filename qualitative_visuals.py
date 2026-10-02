
from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Tuple
from io import BytesIO
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from matplotlib import pyplot as plt
from wordcloud import STOPWORDS, WordCloud

from master_utils import (active_cluster_register, active_dimensions, active_themes, challenged_foc_table, cluster_members, current_mapping_rows, dimension_theme_map, provisional_cluster_summary, retired_themes, split_ids, unthemed_active_clusters)

QUAL_VIS_VERSION = "v0.15.5"

PLOT_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    "toImageButtonOptions": {"format": "png", "filename": "PMM_qualitative_visual", "scale": 3},
}


def _txt(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _short(v, n=46) -> str:
    t = _txt(v)
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _theme_lookup(frames: Dict[str, pd.DataFrame]) -> Dict[str, dict]:
    df = active_themes(frames)
    if df.empty:
        return {}
    return {
        _txt(r.get("Theme_ID")): r.to_dict()
        for _, r in df.iterrows()
        if _txt(r.get("Theme_ID"))
    }


def _dimension_lookup(frames: Dict[str, pd.DataFrame]) -> Dict[str, dict]:
    df = active_dimensions(frames)
    if df.empty:
        return {}
    return {
        _txt(r.get("Dimension_ID")): r.to_dict()
        for _, r in df.iterrows()
        if _txt(r.get("Dimension_ID"))
    }


def build_all_dimensions_sankey(frames: Dict[str, pd.DataFrame]) -> go.Figure:
    """Overview flow for every active Candidate Dimension and its current Themes."""
    dims = _dimension_lookup(frames)
    themes = _theme_lookup(frames)
    dmap = dimension_theme_map(frames)
    if not dims or dmap.empty:
        return go.Figure()

    labels, ids, kinds = [], [], []
    idx = {}

    def add(node_id, label, kind):
        key = f"{kind}:{node_id}"
        if key in idx:
            return idx[key]
        idx[key] = len(labels)
        labels.append(label)
        ids.append(node_id)
        kinds.append(kind)
        return idx[key]

    src, dst, val, htxt = [], [], [], []

    for did, drow in dims.items():
        tids = (
            dmap.loc[
                dmap["Dimension_ID"].astype(str).str.strip().eq(did),
                "Theme_ID",
            ]
            .astype(str).str.strip()
            .drop_duplicates()
            .tolist()
        )
        if not tids:
            continue
        d_idx = add(
            did,
            f"{did}<br>{_short(drow.get('Candidate_Dimension_Name'), 54)}",
            "Dimension",
        )
        for tid in tids:
            trow = themes.get(tid)
            if not trow:
                continue
            t_idx = add(
                tid,
                f"{tid}<br>{_short(trow.get('Working_Theme_Label'), 50)}",
                "Theme",
            )
            weight = 1
            for cid in split_ids(trow.get("Included_Cluster_IDs"), "PCL"):
                members = cluster_members(frames, cid)
                if not members.empty and "Code_ID" in members.columns:
                    weight += int(members["Code_ID"].nunique())
            src.append(d_idx)
            dst.append(t_idx)
            val.append(max(1, weight))
            htxt.append(f"{did} → {tid}<br>{max(1, weight)} mapped FOCs")

    if not src:
        return go.Figure()

    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                pad=12,
                thickness=16,
                line=dict(width=.6),
                label=labels,
                customdata=list(zip(ids, kinds)),
                hovertemplate="%{customdata[1]} %{customdata[0]}<br>%{label}<extra></extra>",
            ),
            link=dict(
                source=src,
                target=dst,
                value=val,
                customdata=htxt,
                hovertemplate="%{customdata}<extra></extra>",
            ),
        )
    )
    fig.update_layout(
        title="PMM analytical overview: All Candidate Dimensions → Themes",
        height=max(760, min(1250, 35 * len(labels) + 220)),
        margin=dict(l=10, r=10, t=70, b=20),
        font=dict(size=11),
    )
    return fig


def build_dimension_sankey(frames: Dict[str, pd.DataFrame], dimension_id: str) -> go.Figure:
    dims = _dimension_lookup(frames)
    themes = _theme_lookup(frames)
    did = str(dimension_id).strip()
    if did not in dims:
        return go.Figure()

    dmap = dimension_theme_map(frames)
    tids = (
        dmap.loc[dmap["Dimension_ID"].astype(str).str.strip().eq(did), "Theme_ID"]
        .astype(str).str.strip().tolist()
        if not dmap.empty
        else []
    )

    labels, ids, kinds = [], [], []
    idx = {}

    def add(node_id, label, kind):
        key = f"{kind}:{node_id}"
        if key in idx:
            return idx[key]
        idx[key] = len(labels)
        labels.append(label)
        ids.append(node_id)
        kinds.append(kind)
        return idx[key]

    drow = dims[did]
    d_idx = add(did, f"{did}<br>{_short(drow.get('Candidate_Dimension_Name'))}", "Dimension")
    src, dst, val, htxt = [], [], [], []

    for tid in tids:
        trow = themes.get(tid)
        if not trow:
            continue
        t_idx = add(tid, f"{tid}<br>{_short(trow.get('Working_Theme_Label'))}", "Theme")
        cids = split_ids(trow.get("Included_Cluster_IDs"), "PCL")
        weights = []
        for cid in cids:
            members = cluster_members(frames, cid)
            weight = int(members["Code_ID"].nunique()) if (not members.empty and "Code_ID" in members.columns) else max(1, len(members))
            weight = max(1, weight)
            weights.append((cid, weight))
        tw = max(1, sum(w for _, w in weights))
        src.append(d_idx); dst.append(t_idx); val.append(tw); htxt.append(f"{did} → {tid}<br>{tw} mapped FOCs")
        for cid, weight in weights:
            c_idx = add(cid, cid, "PCL/Cluster")
            src.append(t_idx); dst.append(c_idx); val.append(weight); htxt.append(f"{tid} → {cid}<br>{weight} mapped FOCs")

    if not src:
        return go.Figure()

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            pad=18, thickness=18, line=dict(width=.6),
            label=labels, customdata=list(zip(ids, kinds)),
            hovertemplate="%{customdata[1]} %{customdata[0]}<br>%{label}<extra></extra>",
        ),
        link=dict(source=src, target=dst, value=val, customdata=htxt,
                  hovertemplate="%{customdata}<extra></extra>"),
    ))
    fig.update_layout(
        title="Analytical derivation flow: Dimension → Theme → PCL/Cluster",
        height=680, margin=dict(l=20, r=20, t=70, b=20), font=dict(size=12)
    )
    return fig


def build_theme_study_matrix(frames: Dict[str, pd.DataFrame], metric: str = "Evidence count") -> pd.DataFrame:
    themes = _theme_lookup(frames)
    rows = []
    for tid, trow in themes.items():
        support = defaultdict(lambda: {"evidence": set(), "codes": set()})
        for cid in split_ids(trow.get("Included_Cluster_IDs"), "PCL"):
            members = cluster_members(frames, cid)
            if members.empty or "Study_ID" not in members.columns:
                continue
            for _, r in members.iterrows():
                sid = _txt(r.get("Study_ID"))
                if not sid:
                    continue
                ev = _txt(r.get("Evidence_ID"))
                code = _txt(r.get("Code_ID"))
                if ev: support[sid]["evidence"].add(ev)
                if code: support[sid]["codes"].add(code)
        for sid, vals in support.items():
            if metric == "Binary study support":
                value = 1
            elif metric == "FOC count":
                value = len(vals["codes"]) or 1
            else:
                value = len(vals["evidence"]) or len(vals["codes"]) or 1
            rows.append({
                "Theme_ID": tid,
                "Theme_Label": _txt(trow.get("Working_Theme_Label")),
                "Study_ID": sid,
                "Value": int(value),
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.pivot_table(
        index=["Theme_ID", "Theme_Label"], columns="Study_ID",
        values="Value", aggfunc="sum", fill_value=0
    ).sort_index()


def build_heatmap_figure(matrix: pd.DataFrame, top_n_studies: int = 25) -> Tuple[go.Figure, pd.DataFrame]:
    if matrix.empty:
        return go.Figure(), pd.DataFrame()
    keep = matrix.sum(axis=0).sort_values(ascending=False).head(top_n_studies).index.tolist()
    shown = matrix.loc[:, keep].copy()
    y = [f"{idx[0]} — {_short(idx[1], 48)}" for idx in shown.index]
    fig = go.Figure(go.Heatmap(
        z=shown.values, x=shown.columns.tolist(), y=y,
        colorscale="Blues", colorbar=dict(title="Support"),
        hovertemplate="Theme: %{y}<br>Study: %{x}<br>Value: %{z}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Theme × Study support heatmap — top {len(keep)} contributing studies",
        height=max(520, min(1000, 34 * len(y) + 170)),
        margin=dict(l=20, r=30, t=70, b=110),
        xaxis=dict(tickangle=-45, title="Study ID"), yaxis=dict(title="")
    )
    return fig, shown


def build_cooccurrence_figure(frames: Dict[str, pd.DataFrame], min_shared_studies: int = 2) -> Tuple[go.Figure, pd.DataFrame]:
    themes = _theme_lookup(frames)
    matrix = build_theme_study_matrix(frames, "Binary study support")
    if matrix.empty:
        return go.Figure(), pd.DataFrame()

    support = {idx[0]: set(row.index[row.astype(float) > 0].astype(str)) for idx, row in matrix.iterrows()}
    tids = [t for t in themes if t in support]
    edges = []
    for a, b in combinations(tids, 2):
        shared = support[a] & support[b]
        if len(shared) >= min_shared_studies:
            edges.append({"Theme_A": a, "Theme_B": b, "Shared_Studies": len(shared), "Studies": "; ".join(sorted(shared))})
    edge_df = pd.DataFrame(edges)

    pos = {}
    for i, tid in enumerate(tids):
        ang = 2 * math.pi * i / max(1, len(tids))
        pos[tid] = (math.cos(ang), math.sin(ang))

    fig = go.Figure()
    if not edge_df.empty:
        mx = max(1, int(edge_df["Shared_Studies"].max()))
        for _, r in edge_df.iterrows():
            a, b = r["Theme_A"], r["Theme_B"]
            x0, y0 = pos[a]; x1, y1 = pos[b]
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines",
                line=dict(width=.8 + 4.2 * int(r["Shared_Studies"]) / mx),
                hoverinfo="text",
                text=[f"{a} ↔ {b}<br>{int(r['Shared_Studies'])} shared studies"] * 2,
                showlegend=False,
            ))

    xs, ys, text, sizes, hover = [], [], [], [], []
    for tid in tids:
        x, y = pos[tid]
        xs.append(x); ys.append(y); text.append(tid)
        sizes.append(22 + min(28, len(support[tid]) * 1.6))
        hover.append(f"{tid}<br>{_short(themes[tid].get('Working_Theme_Label'), 80)}<br>{len(support[tid])} supporting studies")
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers+text", text=text, textposition="top center",
        hovertext=hover, hoverinfo="text",
        marker=dict(size=sizes, line=dict(width=1.2)), showlegend=False
    ))
    fig.update_layout(
        title=f"Theme co-occurrence network — minimum {min_shared_studies} shared studies",
        height=680, margin=dict(l=20, r=20, t=70, b=20),
        xaxis=dict(visible=False, range=[-1.35, 1.35]),
        yaxis=dict(visible=False, range=[-1.35, 1.35], scaleanchor="x", scaleratio=1),
        plot_bgcolor="white"
    )
    return fig, edge_df


def _wordcloud_records(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build unique current analytical text records for Word Cloud exploration."""
    themes = _theme_lookup(frames)
    records = []
    seen = set()
    for tid, trow in themes.items():
        for cid in split_ids(trow.get("Included_Cluster_IDs"), "PCL"):
            members = cluster_members(frames, cid)
            if members.empty:
                continue
            for _, row in members.iterrows():
                evidence_id = _txt(row.get("Evidence_ID"))
                code_id = _txt(row.get("Code_ID"))
                study_id = _txt(row.get("Study_ID"))
                identity = evidence_id or code_id or f"{tid}|{cid}|{study_id}"
                key = (tid, identity)
                if key in seen:
                    continue
                seen.add(key)
                records.append({
                    "Dimension_ID": _txt(row.get("Dimension_ID")),
                    "Theme_ID": tid,
                    "Theme_Label": _txt(trow.get("Working_Theme_Label")),
                    "Code_ID": code_id,
                    "First_Order_Code": _txt(row.get("First_Order_Code")),
                    "Original_Author_Term": _txt(row.get("Original_Author_Term")),
                    "Meaning_Unit_Verbatim": _txt(row.get("Meaning_Unit_Verbatim")),
                    "Evidence_ID": evidence_id,
                    "Study_ID": study_id,
                })
    return pd.DataFrame(records)


def build_wordcloud_frequencies(
    frames: Dict[str, pd.DataFrame],
    source: str = "Original Author Terms",
    dimension_id: str | None = None,
    theme_id: str | None = None,
    max_words: int = 100,
) -> Tuple[Dict[str, int], pd.DataFrame]:
    df = _wordcloud_records(frames)
    if df.empty:
        return {}, df

    if dimension_id and "Dimension_ID" in df.columns:
        df = df[df["Dimension_ID"].eq(str(dimension_id))].copy()
    if theme_id and "Theme_ID" in df.columns:
        df = df[df["Theme_ID"].eq(str(theme_id))].copy()
    if df.empty:
        return {}, df

    source_col = {
        "Original Author Terms": "Original_Author_Term",
        "First-Order Code labels": "First_Order_Code",
        "Meaning Units / Evidence text": "Meaning_Unit_Verbatim",
    }.get(source, "Original_Author_Term")

    text = " ".join(df[source_col].fillna("").astype(str).tolist())
    if not text.strip():
        return {}, df

    # Conservative text cleaning: keep words, remove study/code identifiers and
    # common English stopwords. This is display preprocessing only.
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text.lower())
    stop = set(STOPWORDS) | {
        "project", "projects", "management", "manager", "managers",
        "study", "studies", "research", "using", "use", "used",
        "organization", "organizational", "organisation", "organisational",
        "model", "models", "framework", "frameworks", "approach", "approaches",
        "process", "processes", "system", "systems",
    }
    freq = defaultdict(int)
    for token in tokens:
        token = token.strip("'")
        if token and token not in stop and not token.startswith(("sr", "pcl", "thm", "cd")):
            freq[token] += 1

    ordered = dict(sorted(freq.items(), key=lambda x: (-x[1], x[0]))[: int(max_words)])
    return ordered, df


def build_wordcloud_image(
    frequencies: Dict[str, int],
    width: int = 1500,
    height: int = 850,
) -> bytes:
    if not frequencies:
        return b""
    wc = WordCloud(
        width=width,
        height=height,
        background_color="white",
        max_words=len(frequencies),
        prefer_horizontal=0.9,
        collocations=False,
        random_state=42,
    ).generate_from_frequencies(frequencies)

    fig = plt.figure(figsize=(15, 8.5), dpi=160)
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    fig.tight_layout(pad=0)
    buffer = BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.05, dpi=160)
    plt.close(fig)
    return buffer.getvalue()


def build_theme_boundary_profile(frames: Dict[str, pd.DataFrame], theme_id: str) -> Dict[str, object]:
    """Build a source-grounded boundary profile for one current Theme."""
    themes = active_themes(frames)
    if themes.empty or "Theme_ID" not in themes.columns:
        return {}
    row = themes[themes["Theme_ID"].astype(str).str.strip().eq(str(theme_id).strip())]
    if row.empty:
        return {}
    theme = row.iloc[0].to_dict()
    cids = split_ids(theme.get("Included_Cluster_IDs"), "PCL")

    creg = active_cluster_register(frames)
    if not creg.empty and "Cluster_ID" in creg.columns:
        clusters = creg[creg["Cluster_ID"].astype(str).str.strip().isin(cids)].copy()
    else:
        clusters = pd.DataFrame()

    member_parts = []
    for cid in cids:
        part = cluster_members(frames, cid)
        if not part.empty:
            part = part.copy()
            part["Cluster_ID_Profile"] = cid
            member_parts.append(part)
    members = pd.concat(member_parts, ignore_index=True) if member_parts else pd.DataFrame()

    dmap = dimension_theme_map(frames)
    dim_ids = []
    if not dmap.empty:
        dim_ids = (
            dmap.loc[dmap["Theme_ID"].astype(str).str.strip().eq(str(theme_id).strip()), "Dimension_ID"]
            .dropna().astype(str).str.strip().drop_duplicates().tolist()
        )

    cluster_rows = []
    for cid in cids:
        crow = {}
        if not clusters.empty:
            hit = clusters[clusters["Cluster_ID"].astype(str).str.strip().eq(cid)]
            if not hit.empty:
                crow = hit.iloc[0].to_dict()
        mm = members[members["Cluster_ID_Profile"].eq(cid)].copy() if not members.empty else pd.DataFrame()
        cluster_rows.append({
            "Cluster_ID": cid,
            "Cluster_Label": _txt(crow.get("Working_Cluster_Label")),
            "Cluster_Status": _txt(crow.get("Cluster_Status")),
            "Operational_Definition": _txt(crow.get("Operational_Definition")),
            "Inclusion_Boundary": _txt(crow.get("Inclusion_Boundary")),
            "Exclusion_Boundary": _txt(crow.get("Exclusion_Boundary")),
            "Nearest_Conceptual_Neighbours": _txt(crow.get("Nearest_Conceptual_Neighbours")),
            "FOCs": int(mm["Code_ID"].nunique()) if not mm.empty and "Code_ID" in mm.columns else 0,
            "Studies": int(mm["Study_ID"].nunique()) if not mm.empty and "Study_ID" in mm.columns else 0,
        })
    cluster_table = pd.DataFrame(cluster_rows)

    challenged = challenged_foc_table(frames)
    challenged_count = 0
    if not challenged.empty and cids:
        blob_cols = [x for x in ["Closest_Competing_Cluster", "Boundary_Rationale", "Alternative_Code_Considered"] if x in challenged.columns]
        if blob_cols:
            blob = challenged[blob_cols].fillna("").astype(str).agg(" ".join, axis=1)
            challenged_count = int(blob.map(lambda x: any(cid in x for cid in cids)).sum())

    boundary_fields = ["Operational_Definition", "Inclusion_Boundary", "Exclusion_Boundary"]
    completeness = {}
    for col in boundary_fields:
        if cluster_table.empty or col not in cluster_table.columns:
            completeness[col] = 0.0
        else:
            completeness[col] = float(cluster_table[col].fillna("").astype(str).str.strip().ne("").mean() * 100)

    return {
        "Theme_ID": _txt(theme.get("Theme_ID")),
        "Theme_Label": _txt(theme.get("Working_Theme_Label")),
        "Theme_Status": _txt(theme.get("Theme_Status")),
        "Central_Organizing_Concept": _txt(theme.get("Central_Organizing_Concept")),
        "Theme_Boundary": _txt(theme.get("Theme_Boundary")),
        "Closest_Competing_Theme": _txt(theme.get("Closest_Competing_Theme")),
        "Dimension_IDs": dim_ids,
        "Cluster_IDs": cids,
        "Clusters": len(cids),
        "FOCs": int(members["Code_ID"].nunique()) if not members.empty and "Code_ID" in members.columns else 0,
        "Studies": int(members["Study_ID"].nunique()) if not members.empty and "Study_ID" in members.columns else 0,
        "Evidence_Units": int(members["Evidence_ID"].nunique()) if not members.empty and "Evidence_ID" in members.columns else 0,
        "Challenged_Boundary_Cases": challenged_count,
        "Boundary_Completeness": completeness,
        "Cluster_Table": cluster_table,
    }


def build_negative_deviant_case_matrix(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Consolidate current and resolved boundary/deviant cases without treating them as failures."""
    rows = []

    challenged = challenged_foc_table(frames)
    current_maps = current_mapping_rows(frames)
    cluster_lookup = {}
    if not current_maps.empty and "Code_ID" in current_maps.columns:
        for _, r in current_maps.iterrows():
            cid = _txt(r.get("Cluster_ID"))
            if _txt(r.get("Code_ID")):
                cluster_lookup[_txt(r.get("Code_ID"))] = cid

    if not challenged.empty:
        for _, r in challenged.iterrows():
            cid = _txt(r.get("Code_ID"))
            rows.append({
                "Case_Type": "Challenged FOC",
                "Case_ID": cid,
                "Current_or_Historical": "Current",
                "Status": "Challenged",
                "Study_ID": _txt(r.get("Study_ID")),
                "Cluster_or_Theme": cluster_lookup.get(cid, ""),
                "Closest_Alternative": _txt(r.get("Closest_Competing_Cluster")) or _txt(r.get("Alternative_Code_Considered")),
                "Boundary_or_Rationale": _txt(r.get("Boundary_Rationale")) or _txt(r.get("Mapping_Rationale")) or _txt(r.get("Source_to_Code_Rationale")),
                "Source_Near_Text": _txt(r.get("Meaning_Unit_Verbatim")) or _txt(r.get("Original_Author_Term")),
            })

    provisional = provisional_cluster_summary(frames)
    if not provisional.empty:
        for _, r in provisional.iterrows():
            rows.append({
                "Case_Type": "Provisional Cluster",
                "Case_ID": _txt(r.get("Cluster_ID")),
                "Current_or_Historical": "Current",
                "Status": _txt(r.get("Cluster_Status")),
                "Study_ID": "",
                "Cluster_or_Theme": _txt(r.get("Theme_IDs")),
                "Closest_Alternative": _txt(r.get("Nearest_Conceptual_Neighbours")),
                "Boundary_or_Rationale": _txt(r.get("Challenge_Review_Decision")) or _txt(r.get("Audit_Rationale")) or _txt(r.get("Operational_Definition")),
                "Source_Near_Text": "",
            })

    retired = retired_themes(frames)
    if not retired.empty:
        for _, r in retired.iterrows():
            rows.append({
                "Case_Type": "Retired Theme",
                "Case_ID": _txt(r.get("Theme_ID")),
                "Current_or_Historical": "Historical",
                "Status": _txt(r.get("Theme_Status")),
                "Study_ID": "",
                "Cluster_or_Theme": _txt(r.get("Included_Cluster_IDs")),
                "Closest_Alternative": _txt(r.get("Closest_Competing_Theme")),
                "Boundary_or_Rationale": _txt(r.get("Theme_Boundary")) or _txt(r.get("Central_Organizing_Concept")),
                "Source_Near_Text": "",
            })

    maps = frames.get("06_DeNovo_Clustering", pd.DataFrame()).copy()
    if not maps.empty and "Mapping_Status" in maps.columns:
        status = maps["Mapping_Status"].fillna("").astype(str)
        hist = maps[
            status.str.contains(r"Reassigned|Withdrawn", case=False, regex=True, na=False)
        ].copy()
        if "Code_ID" in hist.columns:
            hist = hist[hist["Code_ID"].fillna("").astype(str).str.match(r"^CD-", case=False, na=False)]
        for _, r in hist.iterrows():
            rows.append({
                "Case_Type": "Resolved Reassignment",
                "Case_ID": _txt(r.get("Code_ID")),
                "Current_or_Historical": "Historical",
                "Status": _txt(r.get("Mapping_Status")),
                "Study_ID": _txt(r.get("Study_ID")),
                "Cluster_or_Theme": _txt(r.get("Cluster_ID")),
                "Closest_Alternative": _txt(r.get("Closest_Competing_Cluster")),
                "Boundary_or_Rationale": _txt(r.get("Boundary_Rationale")) or _txt(r.get("Mapping_Rationale")),
                "Source_Near_Text": "",
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=[
            "Case_Type", "Case_ID", "Current_or_Historical", "Status", "Study_ID",
            "Cluster_or_Theme", "Closest_Alternative", "Boundary_or_Rationale", "Source_Near_Text",
        ])
    return out.drop_duplicates().reset_index(drop=True)


def render_theme_boundary_cards(frames: Dict[str, pd.DataFrame]) -> None:
    themes = active_themes(frames)
    if themes.empty:
        st.info("No current Themes are available.")
        return
    labels = dict(zip(themes["Theme_ID"].astype(str), themes["Working_Theme_Label"].astype(str)))
    tid = st.selectbox(
        "Theme",
        themes["Theme_ID"].astype(str).tolist(),
        format_func=lambda x: f"{x} — {labels.get(x, '')}",
        key="qual_boundary_theme",
    )
    p = build_theme_boundary_profile(frames, tid)
    if not p:
        st.info("No boundary profile could be built for the selected Theme.")
        return

    st.markdown(f"### {p['Theme_ID']} — {p['Theme_Label']}")
    st.caption(f"Status: {p['Theme_Status']} · Dimension(s): {', '.join(p['Dimension_IDs']) or 'Not currently assigned'}")

    a, b, c, d, e = st.columns(5)
    a.metric("Clusters", p["Clusters"])
    b.metric("FOCs", p["FOCs"])
    c.metric("Studies", p["Studies"])
    d.metric("Evidence units", p["Evidence_Units"])
    e.metric("Boundary cases", p["Challenged_Boundary_Cases"])

    left, right = st.columns(2)
    with left:
        st.markdown("**Central organizing concept**")
        st.write(p["Central_Organizing_Concept"] or "Not explicitly populated in the current MASTER.")
        st.markdown("**Theme boundary**")
        st.write(p["Theme_Boundary"] or "Not explicitly populated in the current MASTER.")
    with right:
        st.markdown("**Closest competing Theme**")
        st.write(p["Closest_Competing_Theme"] or "No competing Theme explicitly recorded.")
        comp = p["Boundary_Completeness"]
        st.markdown("**Cluster-level boundary documentation completeness**")
        st.write(
            f"Definition {comp.get('Operational_Definition', 0):.0f}% · "
            f"Inclusion {comp.get('Inclusion_Boundary', 0):.0f}% · "
            f"Exclusion {comp.get('Exclusion_Boundary', 0):.0f}%"
        )

    table = p["Cluster_Table"]
    if isinstance(table, pd.DataFrame) and not table.empty:
        st.markdown("#### Constituent PCL/Cluster boundary table")
        st.dataframe(table, use_container_width=True, hide_index=True, height=min(520, 85 + 38 * len(table)))
        st.download_button(
            "Download Theme boundary table (CSV)",
            table.to_csv(index=False).encode("utf-8-sig"),
            f"{tid}_Theme_Boundary_Table.csv",
            "text/csv",
            use_container_width=True,
        )

    st.info(
        "Interpretation safeguard: boundary completeness describes documentation coverage, not Theme quality. "
        "Theme adequacy still depends on conceptual coherence, internal homogeneity, external heterogeneity, and source fidelity."
    )


def render_negative_deviant_cases(frames: Dict[str, pd.DataFrame]) -> None:
    matrix = build_negative_deviant_case_matrix(frames)
    if matrix.empty:
        st.success("No challenged, provisional, retired, or reassigned boundary cases are recorded in the current workbook.")
        return

    st.markdown("### Negative / Deviant Case Matrix")
    st.caption(
        "This audit display makes non-fitting, contested, provisional, retired, and reassigned cases visible rather than forcing them into the current structure."
    )

    counts = matrix["Case_Type"].value_counts().rename_axis("Case type").reset_index(name="Cases")
    st.dataframe(counts, use_container_width=True, hide_index=True)

    types = matrix["Case_Type"].drop_duplicates().tolist()
    selected = st.multiselect("Case types", types, default=types, key="qual_negative_case_types")
    scope = st.radio("Scope", ["All", "Current only", "Historical only"], horizontal=True, key="qual_negative_scope")

    shown = matrix[matrix["Case_Type"].isin(selected)].copy()
    if scope == "Current only":
        shown = shown[shown["Current_or_Historical"].eq("Current")].copy()
    elif scope == "Historical only":
        shown = shown[shown["Current_or_Historical"].eq("Historical")].copy()

    st.dataframe(shown, use_container_width=True, hide_index=True, height=520)
    st.download_button(
        "Download negative/deviant case matrix (CSV)",
        shown.to_csv(index=False).encode("utf-8-sig"),
        "PMM_Negative_Deviant_Case_Matrix.csv",
        "text/csv",
        use_container_width=True,
    )
    st.info(
        "Methodological note: these rows are not labelled as errors. They document analytic tension, boundary testing, "
        "provisionality, retirement, or reassignment and therefore strengthen the audit trail when interpreted with the recorded rationale."
    )



ENTREQ_ITEMS = [
    (1, "Introduction", "Aim", "State the research question addressed by the qualitative synthesis."),
    (2, "Methods & methodology", "Synthesis methodology", "Identify the synthesis methodology or theoretical framework and justify why it was selected."),
    (3, "Literature search & selection", "Approach to searching", "Report whether searching was pre-planned/comprehensive or iterative/concept-driven."),
    (4, "Literature search & selection", "Inclusion criteria", "Specify inclusion and exclusion criteria used to determine eligible studies."),
    (5, "Literature search & selection", "Data sources", "Describe the information sources searched and when they were searched, with rationale where relevant."),
    (6, "Literature search & selection", "Electronic search strategy", "Report the electronic search strategy, including core concepts, limits and qualitative-search terms where used."),
    (7, "Literature search & selection", "Study screening methods", "Describe title/abstract/full-text screening and who performed screening."),
    (8, "Literature search & selection", "Study characteristics", "Present key characteristics of the included studies."),
    (9, "Literature search & selection", "Study selection results", "Report numbers screened/included/excluded and reasons for exclusion as appropriate."),
    (10, "Appraisal", "Rationale for appraisal", "Explain why and how included studies or findings were appraised."),
    (11, "Appraisal", "Appraisal items", "Identify the appraisal tool, framework or criteria and the domains assessed."),
    (12, "Appraisal", "Appraisal process", "Report who performed appraisal and how disagreements or consensus were handled."),
    (13, "Appraisal", "Appraisal results", "Present appraisal results and explain whether appraisal affected inclusion, weighting or interpretation."),
    (14, "Synthesis of findings", "Data extraction", "State which parts of primary studies were analysed and how data were extracted."),
    (15, "Synthesis of findings", "Software", "Report software used for extraction, coding, management or synthesis, where applicable."),
    (16, "Synthesis of findings", "Number of reviewers", "Identify who participated in coding and analysis."),
    (17, "Synthesis of findings", "Coding", "Describe how the data were coded."),
    (18, "Synthesis of findings", "Study comparison", "Explain how comparisons were made within and across studies during synthesis."),
    (19, "Synthesis of findings", "Derivation of themes", "Explain whether themes/constructs were derived inductively, deductively, or through a combined approach."),
    (20, "Synthesis of findings", "Quotations", "Use source-near quotations/extracts to illustrate themes or constructs and identify their provenance appropriately."),
    (21, "Synthesis of findings", "Synthesis output", "Present an interpretive synthesis that goes beyond a simple summary, such as an analytical framework, model, construct or higher-order interpretation."),
]


def _sheet_has_rows(frames: Dict[str, pd.DataFrame], sheet: str) -> bool:
    df = frames.get(sheet, pd.DataFrame())
    return isinstance(df, pd.DataFrame) and not df.empty


def _entreq_evidence_hint(frames: Dict[str, pd.DataFrame], item_no: int) -> tuple[str, str]:
    """Return evidence availability and a conservative project-specific hint.

    Hints show where documentation may exist. They do not judge ENTREQ compliance.
    """
    if item_no == 1:
        return "Manual thesis check", "Research question/objectives are not established by the MASTER alone; verify the thesis introduction."
    if item_no == 2:
        if all(_sheet_has_rows(frames, s) for s in ["04_Verbatim_Evidence", "05_First_Order_Coding", "06_DeNovo_Clustering", "07_Descriptive_Themes"]):
            return "Strong project hint", "The MASTER records a staged synthesis chain (verbatim evidence → FOC → clustering → Themes), but the methodological rationale still needs explicit thesis reporting."
        return "Manual thesis check", "Methodological rationale must be checked in the thesis methods."
    if item_no == 3:
        return "Manual protocol check", "Search approach cannot be established reliably from the current core analytical sheets."
    if item_no == 4:
        if _sheet_has_rows(frames, "02_Capability_Eligibility"):
            return "Partial project hint", "Eligibility decisions are recorded in 02_Capability_Eligibility; verify that full inclusion/exclusion criteria are explicitly reported in the thesis/protocol."
        return "Manual protocol check", "Verify explicit inclusion/exclusion criteria in the protocol."
    if item_no == 5:
        if _sheet_has_rows(frames, "01_Source_Register"):
            return "Partial project hint", "01_Source_Register provides source-level traceability; verify databases, grey-literature sources, dates and rationale in the written methods."
        return "Manual protocol check", "Data-source reporting is not inferable from current analytical sheets."
    if item_no == 6:
        return "Manual protocol check", "Full electronic search strings and limits should be verified against the search protocol/appendix."
    if item_no == 7:
        if _sheet_has_rows(frames, "02_Capability_Eligibility"):
            return "Partial project hint", "Eligibility decisions exist, but reviewer roles and screening stages require explicit written-method confirmation."
        return "Manual thesis check", "Screening stages and reviewer roles need written-method confirmation."
    if item_no == 8:
        if _sheet_has_rows(frames, "03_Study_Profile"):
            return "Strong project hint", "03_Study_Profile contains study-level characteristics and can support the study-characteristics table."
        return "Manual thesis check", "No populated 03_Study_Profile was detected."
    if item_no == 9:
        if _sheet_has_rows(frames, "01_Source_Register") and _sheet_has_rows(frames, "02_Capability_Eligibility"):
            return "Partial project hint", "Source and eligibility registers can support counts/reasons, but final screening-flow reporting must be verified."
        return "Manual protocol check", "Study-selection results require protocol/flow-diagram verification."
    if item_no in {10, 11, 12, 13}:
        return "Manual appraisal check", "The current core MASTER does not by itself establish the complete appraisal rationale, tool, reviewer process and reported results."
    if item_no == 14:
        if _sheet_has_rows(frames, "04_Verbatim_Evidence"):
            return "Strong project hint", "04_Verbatim_Evidence records extracted source-near evidence units and study provenance."
        return "Manual thesis check", "No populated verbatim-evidence sheet was detected."
    if item_no == 15:
        return "Manual thesis check", "Software use should be stated explicitly in Methods; the analytical workbook/application alone should not substitute for that statement."
    if item_no == 16:
        return "Manual thesis check", "Number and role of reviewers/coders cannot be inferred reliably from the workbook."
    if item_no == 17:
        if _sheet_has_rows(frames, "05_First_Order_Coding"):
            return "Strong project hint", "05_First_Order_Coding records the FOC stage and traceability to evidence units."
        return "Manual thesis check", "No populated first-order coding sheet was detected."
    if item_no == 18:
        if _sheet_has_rows(frames, "06_DeNovo_Clustering"):
            return "Strong project hint", "06_DeNovo_Clustering records code-to-cluster comparisons/mappings; written Methods should explain the constant-comparison logic."
        return "Manual thesis check", "Cross-study comparison logic needs explicit documentation."
    if item_no == 19:
        if _sheet_has_rows(frames, "07_Descriptive_Themes") and _sheet_has_rows(frames, "08_Candidate_Dimensions"):
            return "Strong project hint", "07_Descriptive_Themes and 08_Candidate_Dimensions provide a traceable higher-order derivation structure."
        return "Manual thesis check", "Theme/construct derivation needs explicit explanation."
    if item_no == 20:
        if _sheet_has_rows(frames, "04_Verbatim_Evidence"):
            return "Strong project hint", "Source-near verbatim evidence is retained in 04_Verbatim_Evidence; select representative extracts with provenance for reporting."
        return "Manual thesis check", "Representative source-near extracts need verification."
    if item_no == 21:
        if _sheet_has_rows(frames, "08_Candidate_Dimensions"):
            return "Strong project hint", "08_Candidate_Dimensions plus the derivation visuals support a higher-order synthesis output beyond simple study summary."
        return "Manual thesis check", "Higher-order synthesis output needs verification."
    return "Manual check", "Verify reporting in the thesis and supporting appendices."


ENTREQ_PROVISIONAL_REVIEW = {
    1: ("Ready to verify", "Research aim/question is established in the thesis project; confirm the exact synthesis question and section location."),
    2: ("Ready – rationale needed", "The staged synthesis is explicit in the MASTER; ensure the written methodology names the synthesis approach and explains why it fits this review."),
    3: ("Ready – protocol verification", "Search development is documented in the review workflow; confirm whether the final report describes it as pre-planned/comprehensive, iterative, or a justified combination."),
    4: ("Ready – protocol verification", "Eligibility decisions exist; verify that the full inclusion/exclusion criteria are explicitly stated in the protocol/thesis."),
    5: ("Ready – protocol verification", "Source traceability exists; verify databases, grey-literature sources, search dates, supplementary techniques and rationale in the written methods."),
    6: ("Ready – appendix verification", "Search strings/limits should be reported or placed in an appendix; confirm the final reproducible search syntax."),
    7: ("Ready – methods verification", "Screening decisions exist; confirm title/abstract/full-text stages and who performed each stage."),
    8: ("Ready – strong evidence", "03_Study_Profile can directly support the included-study characteristics table."),
    9: ("Pending final flow counts", "Final screened/included/excluded counts and exclusion reasons should be locked only after the review flow is complete."),
    10: ("Pending appraisal phase", "Keep open until the appraisal rationale is finalised and reported."),
    11: ("Pending appraisal phase", "Keep open until the appraisal framework/tool and assessed domains are finalised."),
    12: ("Pending appraisal phase", "Keep open until reviewer roles/consensus procedures for appraisal are documented."),
    13: ("Pending appraisal results", "Keep open until appraisal results and their effect on inclusion/weighting/interpretation are final."),
    14: ("Ready – strong evidence", "04_Verbatim_Evidence provides source-near extraction traceability; verify the written extraction procedure and analysed study sections."),
    15: ("Ready – methods verification", "Explicitly report the software actually used for extraction, coding, management and synthesis."),
    16: ("Needs explicit statement", "The workbook cannot establish who participated in coding/analysis; this must be stated in the thesis."),
    17: ("Ready – strong evidence", "05_First_Order_Coding provides direct coding traceability; describe how FOCs were generated and fidelity checked."),
    18: ("Ready – strong evidence", "06_DeNovo_Clustering supports within/across-study comparison; describe constant comparison, negative cases and boundary testing."),
    19: ("Ready – strong evidence", "07_Descriptive_Themes and 08_Candidate_Dimensions support inductive progressive abstraction; state clearly which steps were inductive and any theory-informed interpretation."),
    20: ("Ready – select exemplars", "Verbatim evidence exists; select representative source-near extracts and identify provenance in the results."),
    21: ("Ready but not final", "The Candidate-Dimension structure goes beyond study summary, but the final synthesis output should be locked only when the analytical structure is closed."),
}


def _entreq_provisional_review(item_no: int) -> tuple[str, str]:
    return ENTREQ_PROVISIONAL_REVIEW.get(
        item_no,
        ("Manual verification", "Verify this item against the thesis and supporting protocol."),
    )


def build_entreq_audit_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for no, domain, item, guide in ENTREQ_ITEMS:
        evidence_level, hint = _entreq_evidence_hint(frames, no)
        provisional, review_note = _entreq_provisional_review(no)
        rows.append({
            "No.": no,
            "Domain": domain,
            "ENTREQ item": item,
            "Reporting expectation": guide,
            "Project evidence hint": evidence_level,
            "Provisional review": provisional,
            "Review rationale / next action": review_note,
            "Where to verify / current evidence": hint,
            "Status": "Not assessed",
            "Thesis location / note": "",
        })
    return pd.DataFrame(rows)


DECISION_EVENT_PATTERNS = [
    ("Split", [r"\bsplit\b", r"splitting"]),
    ("Merge", [r"\bmerge\b", r"merged", r"merging"]),
    ("Reassignment", [r"reassign", r"re-home", r"rehome", r"remap", r"re-map", r"moved to", r"move to"]),
    ("Retirement / Withdrawal", [r"retir", r"withdraw", r"supersed"]),
    ("Rename", [r"rename", r"renam"]),
    ("Boundary Review", [r"boundary", r"overlap", r"heterogeneity", r"homogeneity"]),
    ("Creation / Addition", [r"creat", r"new cluster", r"new theme", r"new dimension", r"add(?:ed|ition)?"]),
    ("Closure", [r"clos(?:e|ed|ure)", r"finali[sz]", r"lock(?:ed)?"]),
    ("Audit / Review", [r"\baudit\b", r"review"]),
]


def _first_existing_column(df: pd.DataFrame, candidates: List[str]) -> str | None:
    lookup = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        hit = lookup.get(candidate.lower())
        if hit is not None:
            return hit
    return None


def _decision_sequence(decision_id: str, fallback: int) -> int:
    m = re.search(r"(\d+)", _txt(decision_id))
    return int(m.group(1)) if m else fallback


def _decision_event_type(text: str) -> str:
    low = _txt(text).lower()
    for label, patterns in DECISION_EVENT_PATTERNS:
        if any(re.search(p, low, flags=re.I) for p in patterns):
            return label
    return "Other Decision"


def _decision_entities(text: str) -> str:
    ids = re.findall(
        r"\b(?:DEC|DIM|THM|PCL|PMAP|SR\d{1,5}|CD-SR\d{1,5}-\d+)\b(?:-\d+)?",
        _txt(text),
        flags=re.I,
    )
    cleaned = []
    for item in ids:
        item = item.upper()
        if item not in cleaned and not item.startswith("DEC-"):
            cleaned.append(item)
    return "; ".join(cleaned)


def build_audit_trail_events(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a chronological audit trail from 11_Decision_Log, enriched conservatively.

    Calendar dates are used only when an explicit date/timestamp column exists.
    Otherwise DEC numeric sequence is used as analytical chronology.
    """
    log = frames.get("11_Decision_Log", pd.DataFrame()).copy()
    rows = []

    if not log.empty:
        id_col = _first_existing_column(log, ["Decision_ID", "DEC_ID", "Decision"])
        date_col = _first_existing_column(
            log,
            ["Decision_Date", "Date", "Decision_Timestamp", "Timestamp", "Created_Date"],
        )
        title_col = _first_existing_column(
            log,
            ["Decision", "Decision_Title", "Decision_Label", "Title", "Action", "Decision_Type"],
        )
        summary_col = _first_existing_column(
            log,
            ["Impact_on_Analysis", "Decision_Summary", "Summary", "Decision_Description", "Description", "Change_Description"],
        )
        rationale_col = _first_existing_column(
            log,
            ["Reason", "Decision_Rationale", "Rationale", "Audit_Rationale", "Notes", "Decision_Notes"],
        )
        stage_col = _first_existing_column(
            log,
            ["Stage", "Analytical_Stage", "Phase", "Decision_Stage"],
        )

        for pos, (_, r) in enumerate(log.iterrows(), start=1):
            did = _txt(r.get(id_col)) if id_col else f"ROW-{pos}"
            pieces = []
            for col in [title_col, summary_col, rationale_col]:
                if col:
                    value = _txt(r.get(col))
                    if value and value not in pieces:
                        pieces.append(value)
            if not pieces:
                other = [
                    _txt(r.get(col))
                    for col in log.columns
                    if col != id_col and _txt(r.get(col))
                ]
                pieces = other[:3]
            detail = " · ".join(pieces)
            all_text = " ".join([did, detail, " ".join(_txt(r.get(col)) for col in log.columns)])
            seq = _decision_sequence(did, pos)
            raw_date = _txt(r.get(date_col)) if date_col else ""
            parsed_date = pd.to_datetime(raw_date, errors="coerce") if raw_date else pd.NaT
            rows.append({
                "Decision_ID": did,
                "DEC_Sequence": seq,
                "Date": parsed_date,
                "Event_Type": _decision_event_type(all_text),
                "Stage": _txt(r.get(stage_col)) if stage_col else "",
                "Entities": _decision_entities(all_text),
                "Decision_Summary": detail,
                "Evidence_Source": "11_Decision_Log",
                "Chronology_Source": "Calendar date" if pd.notna(parsed_date) else "DEC sequence",
            })

    # Enrich retirement history when a DEC reference is explicitly present in Theme_Status.
    retired = retired_themes(frames)
    if not retired.empty:
        for _, r in retired.iterrows():
            status = _txt(r.get("Theme_Status"))
            m = re.search(r"DEC[-\s]?(\d+)", status, flags=re.I)
            if not m:
                continue
            did = f"DEC-{int(m.group(1))}"
            tid = _txt(r.get("Theme_ID"))
            rows.append({
                "Decision_ID": did,
                "DEC_Sequence": int(m.group(1)),
                "Date": pd.NaT,
                "Event_Type": "Retirement / Withdrawal",
                "Stage": "Theme",
                "Entities": tid,
                "Decision_Summary": status,
                "Evidence_Source": "07_Descriptive_Themes",
                "Chronology_Source": "DEC sequence",
            })

    maps = frames.get("06_DeNovo_Clustering", pd.DataFrame()).copy()
    if not maps.empty and "Mapping_Status" in maps.columns:
        hist = maps[
            maps["Mapping_Status"].fillna("").astype(str).str.contains(
                r"Reassigned|Withdrawn|Re-home|Rehome", case=False, regex=True, na=False
            )
        ].copy()
        for _, r in hist.iterrows():
            status = _txt(r.get("Mapping_Status"))
            text_blob = " ".join(
                _txt(r.get(col))
                for col in ["Mapping_Status", "Mapping_Rationale", "Boundary_Rationale", "Closest_Competing_Cluster"]
                if col in hist.columns
            )
            m = re.search(r"DEC[-\s]?(\d+)", text_blob, flags=re.I)
            if not m:
                continue
            did = f"DEC-{int(m.group(1))}"
            rows.append({
                "Decision_ID": did,
                "DEC_Sequence": int(m.group(1)),
                "Date": pd.NaT,
                "Event_Type": "Reassignment",
                "Stage": "FOC mapping",
                "Entities": "; ".join(
                    x for x in [_txt(r.get("Code_ID")), _txt(r.get("Cluster_ID"))] if x
                ),
                "Decision_Summary": text_blob,
                "Evidence_Source": "06_DeNovo_Clustering",
                "Chronology_Source": "DEC sequence",
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=[
            "Decision_ID", "DEC_Sequence", "Date", "Event_Type", "Stage", "Entities",
            "Decision_Summary", "Evidence_Source", "Chronology_Source",
        ])

    # Prefer Decision_Log rows when the same decision/type is also visible in status metadata.
    out["_priority"] = out["Evidence_Source"].eq("11_Decision_Log").astype(int)
    out = (
        out.sort_values(["DEC_Sequence", "_priority"], ascending=[True, False])
        .drop_duplicates(subset=["Decision_ID", "Event_Type", "Entities"], keep="first")
        .drop(columns="_priority")
        .reset_index(drop=True)
    )
    return out


def build_audit_timeline_figure(events: pd.DataFrame) -> go.Figure:
    if events.empty:
        return go.Figure()

    shown = events.copy()
    has_dates = (
        "Date" in shown.columns
        and shown["Date"].notna().all()
        and len(shown) > 0
    )
    if has_dates:
        plot_df = shown.sort_values("Date").copy()
        x = plot_df["Date"]
        x_title = "Decision date"
    else:
        plot_df = shown.sort_values("DEC_Sequence").copy()
        x = plot_df["DEC_Sequence"]
        x_title = "DEC sequence (analytical chronology)"

    hover = []
    for _, r in plot_df.iterrows():
        hover.append(
            f"{_txt(r.get('Decision_ID'))}<br>"
            f"Type: {_txt(r.get('Event_Type'))}<br>"
            f"Stage: {_txt(r.get('Stage')) or 'Not recorded'}<br>"
            f"Entities: {_txt(r.get('Entities')) or 'Not recorded'}<br>"
            f"{_short(r.get('Decision_Summary'), 180)}"
        )

    fig = go.Figure()
    event_types = plot_df["Event_Type"].fillna("Other Decision").astype(str).drop_duplicates().tolist()
    for event_type in event_types:
        part = plot_df[plot_df["Event_Type"].astype(str).eq(event_type)].copy()
        if has_dates and part["Date"].notna().any():
            px = part["Date"]
        else:
            px = part["DEC_Sequence"]
        phover = [
            f"{_txt(r.get('Decision_ID'))}<br>"
            f"Type: {_txt(r.get('Event_Type'))}<br>"
            f"Stage: {_txt(r.get('Stage')) or 'Not recorded'}<br>"
            f"Entities: {_txt(r.get('Entities')) or 'Not recorded'}<br>"
            f"{_short(r.get('Decision_Summary'), 180)}"
            for _, r in part.iterrows()
        ]
        fig.add_trace(go.Scatter(
            x=px,
            y=[event_type] * len(part),
            mode="markers+text",
            text=part["Decision_ID"].astype(str).tolist(),
            textposition="top center",
            hovertext=phover,
            hoverinfo="text",
            marker=dict(size=13, line=dict(width=1)),
            name=event_type,
        ))

    fig.update_layout(
        title="Analytical Audit-Trail Timeline",
        height=max(520, min(900, 78 * len(event_types) + 220)),
        margin=dict(l=20, r=20, t=70, b=50),
        xaxis_title=x_title,
        yaxis_title="",
        legend_title_text="Decision event",
        hovermode="closest",
    )
    return fig



def _evolution_level(row: pd.Series) -> str:
    """Classify the primary analytical level without letting downstream impact text dominate."""
    stage = _txt(row.get("Stage")).lower()
    decision = _txt(row.get("Decision")).lower()
    affected = _txt(row.get("Affected_Sheets_or_Fields")).lower()
    primary = " ".join([stage, decision, affected])

    stage_sg2 = bool(re.search(r"\bsg2\b", stage))
    stage_sg3 = bool(re.search(r"\bsg3\b", stage))
    stage_sg4 = bool(re.search(r"\bsg4\b", stage))
    stage_hits = sum([stage_sg2, stage_sg3, stage_sg4])

    if stage_hits > 1:
        return "Cross-level / system"
    if stage_sg4:
        return "Theme → Dimension"
    if stage_sg3:
        return "PCL → Theme"
    if stage_sg2:
        return "FOC → PCL"

    has_sg4 = bool(re.search(r"candidate dimension|cross-dimension|higher-order|\bdim-\d+", primary))
    has_sg3 = bool(re.search(r"theme|cluster[- ]to[- ]theme|cross-theme|dissolution|\bthm-\d+", primary))
    has_sg2 = bool(re.search(r"foc|first[- ]order|mapping|reassign|re-home|rehome|\bpcl-\d+", primary))

    if sum([has_sg2, has_sg3, has_sg4]) > 1:
        return "Cross-level / system"
    if has_sg4:
        return "Theme → Dimension"
    if has_sg3:
        return "PCL → Theme"
    if has_sg2:
        return "FOC → PCL"
    return "System / other"


def build_analytical_evolution_story(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Create a presentation-ready evolution story from the decision log."""
    log = frames.get("11_Decision_Log", pd.DataFrame()).copy()
    if log.empty:
        return pd.DataFrame(columns=[
            "Decision_ID", "DEC_Sequence", "Date", "Level", "Event_Type",
            "Decision", "Problem_or_Reason", "Result_or_Impact",
            "Affected_Entities", "Status",
        ])

    rows = []
    for pos, (_, r) in enumerate(log.iterrows(), start=1):
        did = _txt(r.get("Decision_ID")) or f"ROW-{pos}"
        decision = _txt(r.get("Decision"))
        reason = _txt(r.get("Reason"))
        impact = _txt(r.get("Impact_on_Analysis"))
        affected = _txt(r.get("Affected_Sheets_or_Fields"))
        status = _txt(r.get("Status"))
        notes = _txt(r.get("Notes"))
        stage = _txt(r.get("Stage"))
        full_text = " ".join([did, stage, decision, reason, affected, impact, status, notes])
        raw_date = _txt(r.get("Date"))
        parsed_date = pd.to_datetime(raw_date, errors="coerce") if raw_date else pd.NaT
        rows.append({
            "Decision_ID": did,
            "DEC_Sequence": _decision_sequence(did, pos),
            "Date": parsed_date,
            "Level": _evolution_level(r),
            "Event_Type": _decision_event_type(full_text),
            "Decision": decision,
            "Problem_or_Reason": reason,
            "Result_or_Impact": impact,
            "Affected_Entities": _decision_entities(full_text),
            "Affected_Sheets_or_Fields": affected,
            "Status": status,
            "Notes": notes,
        })

    out = pd.DataFrame(rows)
    # Focus this story on analytical evolution rather than routine study closures.
    evolution_mask = out["Event_Type"].isin([
        "Reassignment", "Split", "Merge", "Retirement / Withdrawal",
        "Boundary Review", "Rename", "Creation / Addition", "Audit / Review",
    ])
    evolution_mask |= out["Decision"].fillna("").astype(str).str.contains(
        r"reassign|re-home|rehome|split|merge|retir|dissol|boundary|reconstruct|re-deriv|restart|stabili|cross-theme|cross-dimension",
        case=False, regex=True, na=False,
    )
    return out.loc[evolution_mask].sort_values(["DEC_Sequence", "Decision_ID"]).reset_index(drop=True)


def build_exact_foc_reassignment_history(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Find exact FOC before/after mapping histories retained as multiple rows."""
    maps = frames.get("06_DeNovo_Clustering", pd.DataFrame()).copy()
    if maps.empty or "Code_ID" not in maps.columns:
        return pd.DataFrame()

    maps = maps[maps["Code_ID"].notna()].copy()
    maps["Code_ID"] = maps["Code_ID"].astype(str).str.strip()
    counts = maps["Code_ID"].value_counts()
    repeated = set(counts[counts > 1].index)
    rows = []

    for code_id in sorted(repeated):
        g = maps[maps["Code_ID"].eq(code_id)].copy()
        if "Mapping_Status" not in g.columns:
            continue
        status = g["Mapping_Status"].fillna("").astype(str)
        historical = g[
            status.str.contains(r"Withdrawn|Retired|Reassigned|Historical|Superseded", case=False, regex=True, na=False)
        ]
        current = g[
            status.str.strip().isin(["Stable", "Provisional", "Challenged"])
        ]
        if historical.empty or current.empty:
            continue

        for _, old in historical.iterrows():
            for _, new in current.iterrows():
                rows.append({
                    "Code_ID": code_id,
                    "Study_ID": _txt(new.get("Study_ID")) or _txt(old.get("Study_ID")),
                    "First_Order_Code": _txt(new.get("First_Order_Code")) or _txt(old.get("First_Order_Code")),
                    "Before_PCL": _txt(old.get("Cluster_ID")),
                    "Before_Label": _txt(old.get("Working_Cluster_Label")),
                    "Before_Status": _txt(old.get("Mapping_Status")),
                    "After_PCL": _txt(new.get("Cluster_ID")),
                    "After_Label": _txt(new.get("Working_Cluster_Label")),
                    "After_Status": _txt(new.get("Mapping_Status")),
                    "Why_Changed": _txt(new.get("Boundary_Rationale")) or _txt(new.get("Mapping_Rationale")),
                    "Competing_Cluster": _txt(new.get("Closest_Competing_Cluster")),
                    "Audit_Notes": _txt(new.get("Notes")),
                })
    return pd.DataFrame(rows)


def build_dimension_generation_history(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return named DIM rows that preserve historical/current SG4 generations."""
    dims = frames.get("08_Candidate_Dimensions", pd.DataFrame()).copy()
    if dims.empty or "Dimension_ID" not in dims.columns:
        return pd.DataFrame()
    ids = dims["Dimension_ID"].fillna("").astype(str).str.strip()
    x = dims[ids.str.match(r"^DIM-\d{3}$", case=False, na=False)].copy()
    if x.empty:
        return x
    cols = [
        c for c in [
            "Dimension_ID", "Candidate_Dimension_Name", "Supporting_Theme_IDs",
            "Underlying_Cluster_IDs", "Dimension_Status", "Review_Date", "Notes", "Audit_Notes"
        ] if c in x.columns
    ]
    return x[cols].copy()



def _count_current_pass_focs(frames: Dict[str, pd.DataFrame]) -> int:
    codes = frames.get("05_First_Order_Coding", pd.DataFrame()).copy()
    if codes.empty or "Code_ID" not in codes.columns:
        return 0
    if "Code_Fidelity_Status" in codes.columns:
        status = codes["Code_Fidelity_Status"].fillna("").astype(str).str.strip()
        mask = status.str.match(r"^Pass(?:\s|$|-|–)", case=False, na=False)
        return int(codes.loc[mask, "Code_ID"].dropna().astype(str).nunique())
    return int(codes["Code_ID"].dropna().astype(str).nunique())


def _count_pass_evidence(frames: Dict[str, pd.DataFrame]) -> int:
    ev = frames.get("04_Verbatim_Evidence", pd.DataFrame()).copy()
    if ev.empty or "Evidence_ID" not in ev.columns:
        return 0
    if "PM_Practice_Maturity_Evidence_Gate" in ev.columns:
        gate = ev["PM_Practice_Maturity_Evidence_Gate"].fillna("").astype(str).str.strip()
        return int(ev.loc[gate.eq("Pass"), "Evidence_ID"].dropna().astype(str).nunique())
    return int(ev["Evidence_ID"].dropna().astype(str).nunique())


def _current_mapping_counts(frames: Dict[str, pd.DataFrame]) -> dict:
    cur = current_mapping_rows(frames)
    if cur.empty or "Mapping_Status" not in cur.columns:
        return {"Stable": 0, "Provisional": 0, "Challenged": 0}
    vc = cur["Mapping_Status"].fillna("").astype(str).str.strip().value_counts()
    return {
        "Stable": int(vc.get("Stable", 0)),
        "Provisional": int(vc.get("Provisional", 0)),
        "Challenged": int(vc.get("Challenged", 0)),
    }


def _preferred_decision_story(story: pd.DataFrame, decision_id: str) -> dict | None:
    if story.empty:
        return None
    hit = story[story["Decision_ID"].astype(str).str.upper().eq(decision_id.upper())]
    return hit.iloc[0].to_dict() if not hit.empty else None


def render_supervisor_analytical_journey(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("## Researcher Analytical Journey")
    st.markdown(
        '<div class="note-banner"><b>Supervisor presentation view:</b> '
        'This page explains how the analytical structure was derived, challenged, revised and stabilised. '
        'It is designed to show the research process—not only the final dimensions.</div>',
        unsafe_allow_html=True,
    )

    src = frames.get("01_Source_Register", pd.DataFrame()).copy()
    source_n = (
        int(src["Study_ID"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique())
        if not src.empty and "Study_ID" in src.columns else 0
    )
    pass_evidence = _count_pass_evidence(frames)
    pass_focs = _count_current_pass_focs(frames)
    cluster_n = len(active_cluster_register(frames))
    theme_n = len(active_themes(frames))
    dim_n = len(active_dimensions(frames))
    mapping_counts = _current_mapping_counts(frames)

    st.markdown("### 1 · The analytical chain")
    st.caption(
        "The final dimensions were not generated directly. Each level had to remain traceable to the level below it."
    )
    cols = st.columns(6)
    chain = [
        ("Studies", source_n, "Direct-source corpus"),
        ("Pass evidence", pass_evidence, "Source-grounded units"),
        ("First-Order Codes", pass_focs, "Meaning-preserving codes"),
        ("PCL / Clusters", cluster_n, "Function-first grouping"),
        ("Themes", theme_n, "Higher-order organizing concepts"),
        ("Dimensions", dim_n, "Current inductive structure"),
    ]
    for col, (label, value, note) in zip(cols, chain):
        with col:
            st.metric(label, f"{value:,}")
            st.caption(note)

    st.markdown(
        "**Core message for the supervisor:** every upward step was conditional. "
        "A code could remain Challenged, a cluster could remain unthemed, and a Theme/Dimension could be split, retired or merged "
        "if the boundary test did not support the previous structure."
    )

    st.markdown("---")
    st.markdown("### 2 · One real correction: FOC → PCL")
    exact = build_exact_foc_reassignment_history(frames)
    if not exact.empty:
        preferred = exact[exact["Code_ID"].astype(str).eq("CD-SR068-004")]
        case = preferred.iloc[0] if not preferred.empty else exact.iloc[0]
        st.markdown(f"**Case:** {_txt(case.get('Code_ID'))} · {_txt(case.get('First_Order_Code'))}")
        a, b, c = st.columns([1, 1.25, 1])
        with a:
            st.markdown("#### Initial assignment")
            st.error(
                f"**{_txt(case.get('Before_PCL')) or 'Unassigned'}**\n\n"
                f"{_txt(case.get('Before_Label'))}"
            )
            st.caption(_txt(case.get("Before_Status")))
        with b:
            st.markdown("#### Why it was reopened")
            why = _txt(case.get("Why_Changed"))
            if not why:
                why = (
                    "The full FOC meaning, focal action and managed object were re-compared against the nearest competing clusters. "
                    "The earlier assignment no longer provided the strongest whole-code fit."
                )
            st.warning(why)
            comp = _txt(case.get("Competing_Cluster"))
            if comp:
                st.caption(f"Nearest competing cluster considered: {comp}")
        with c:
            st.markdown("#### Corrected assignment")
            st.success(
                f"**{_txt(case.get('After_PCL')) or 'Challenged'}**\n\n"
                f"{_txt(case.get('After_Label'))}"
            )
            st.caption(_txt(case.get("After_Status")))
        st.info(
            "Why this matters: the earlier row is retained rather than overwritten. "
            "The audit trail therefore shows both the initial analytical judgment and the corrected current judgment."
        )
    else:
        st.info("No exact retained FOC before/after pair was found; use the decision-level stories below.")

    st.markdown("---")
    st.markdown("### 3 · The same logic continued upward")
    story = build_analytical_evolution_story(frames)
    examples = [
        ("PCL → Theme", "DEC-430", "Cross-theme boundary correction"),
        ("Theme → Dimension", "DEC-432", "Delivery-control vs risk split"),
        ("Theme → Dimension", "DEC-433", "Resource capability vs authority/leadership split"),
        ("Theme → Dimension", "DEC-434", "Governance vs multi-project orchestration split"),
        ("Theme → Dimension", "DEC-498", "Higher-order merger after separate validation"),
    ]

    tabs = st.tabs([f"{did} · {label}" for _, did, label in examples])
    for tab, (level, did, label) in zip(tabs, examples):
        with tab:
            row = _preferred_decision_story(story, did)
            if row is None:
                st.info(f"{did} is not available in the current decision history.")
                continue
            st.markdown(f"#### {label}")
            st.caption(f"{level} · {did}")
            x, y, z = st.columns(3)
            with x:
                st.markdown("**What was questioned?**")
                st.write(_txt(row.get("Problem_or_Reason")) or "Not explicitly recorded.")
            with y:
                st.markdown("**What decision was made?**")
                st.write(_txt(row.get("Decision")) or "Not explicitly recorded.")
            with z:
                st.markdown("**What changed?**")
                st.write(_txt(row.get("Result_or_Impact")) or "Not explicitly recorded.")
            if _txt(row.get("Status")):
                st.success(f"Recorded status: {_txt(row.get('Status'))}")

    st.markdown("---")
    st.markdown("### 4 · How the structure evolved across major checkpoints")
    checkpoint_ids = ["DEC-419", "DEC-424", "DEC-425", "DEC-430", "DEC-432", "DEC-433", "DEC-434", "DEC-497", "DEC-498"]
    checkpoint_labels = {
        "DEC-419": "Reset SG4 and restart Theme-to-Dimension derivation",
        "DEC-424": "System-wide cross-Theme consolidation",
        "DEC-425": "Re-adjudicate all Challenged FOCs",
        "DEC-430": "Final whole-system cross-Theme audit",
        "DEC-432": "Split delivery/control from risk",
        "DEC-433": "Split resource lifecycle from authority/leadership",
        "DEC-434": "Split governance from programme/portfolio orchestration",
        "DEC-497": "Validate possible higher-order mergers without executing them",
        "DEC-498": "Execute only the two validated higher-order mergers",
    }
    checkpoints = story[story["Decision_ID"].astype(str).isin(checkpoint_ids)].copy()
    checkpoints["_order"] = checkpoints["Decision_ID"].map({d:i for i,d in enumerate(checkpoint_ids)})
    checkpoints = checkpoints.sort_values("_order")

    if not checkpoints.empty:
        for _, r in checkpoints.iterrows():
            did = _txt(r.get("Decision_ID"))
            with st.expander(f"{did} · {checkpoint_labels.get(did, _txt(r.get('Decision')))}", expanded=False):
                st.markdown(f"**Reason:** {_txt(r.get('Problem_or_Reason'))}")
                st.markdown(f"**Action:** {_txt(r.get('Decision'))}")
                st.markdown(f"**Impact:** {_txt(r.get('Result_or_Impact'))}")
    else:
        st.info("Major checkpoint decisions could not be reconstructed from the current Decision Log.")

    st.markdown("---")
    st.markdown("### 5 · Evidence that the process was not forced")
    unthemed = unthemed_active_clusters(frames)
    retired = retired_themes(frames)
    exact_n = len(exact)
    current_challenged = mapping_counts["Challenged"]

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Current Challenged FOCs", f"{current_challenged:,}")
    q1.caption("Kept unresolved rather than force-fitted")
    q2.metric("Active unthemed clusters", f"{len(unthemed):,}")
    q2.caption("No Theme assigned without a defensible higher-order home")
    q3.metric("Retired Themes retained", f"{len(retired):,}")
    q3.caption("Historical structures preserved for auditability")
    q4.metric("Exact FOC reassignment histories", f"{exact_n:,}")
    q4.caption("Old and corrected mapping rows both retained")

    st.markdown(
        """
**What this demonstrates methodologically**

- **Source fidelity:** codes remain traceable to direct evidence and source wording.
- **Constant comparison:** assignments are tested against nearest competing clusters/themes/dimensions, not accepted by lexical similarity.
- **Negative/deviant handling:** challenged items are retained as challenged instead of being forced into the framework.
- **Boundary testing:** internal homogeneity and external heterogeneity are checked repeatedly at PCL, Theme and Dimension levels.
- **Auditability:** replaced structures and decisions remain visible through DEC records, historical statuses and retained mappings.
        """
    )

    st.markdown("---")
    st.markdown("### 6 · Suggested 90-second explanation to the supervisor")
    st.info(
        "I did not ask the system to generate dimensions directly. I started from source-grounded evidence, "
        "then created First-Order Codes and grouped them progressively. Every assignment was provisional until it survived "
        "comparison with its nearest alternative. When a code, cluster, Theme or Dimension did not fit cleanly, I reopened it, "
        "documented the reason, and either reassigned, split, retired, or—only after separate validation—merged it. "
        "The platform preserves those earlier decisions, so the current dimensions are the result of a documented sequence "
        "of source checks, boundary tests, corrections and stability reviews."
    )
    st.caption(
        "Use this page as the opening supervisor view; then drill into the full Audit-Trail Timeline or Derivation Tree "
        "only when the supervisor asks for evidence behind a specific decision."
    )


def render_analytical_evolution_story(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("### Analytical Evolution Story")
    st.caption(
        "A supervisor-facing narrative of how assignments and higher-order structure were tested, challenged, "
        "corrected and stabilised from First-Order Codes to Candidate Dimensions."
    )
    st.info(
        "Interpretation safeguard: revisions are shown as evidence of constant comparison and boundary testing. "
        "The view distinguishes documented corrections from the current final assignment and does not treat every revision as an error."
    )

    story = build_analytical_evolution_story(frames)
    exact = build_exact_foc_reassignment_history(frames)
    dim_hist = build_dimension_generation_history(frames)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Evolution decisions", len(story))
    c2.metric("FOC→PCL decisions", int((story["Level"] == "FOC → PCL").sum()) if not story.empty else 0)
    c3.metric("PCL→Theme decisions", int((story["Level"] == "PCL → Theme").sum()) if not story.empty else 0)
    c4.metric("Theme→Dimension decisions", int((story["Level"] == "Theme → Dimension").sum()) if not story.empty else 0)

    level_options = [
        "All levels", "FOC → PCL", "PCL → Theme", "Theme → Dimension",
        "Cross-level / system", "System / other",
    ]
    selected_level = st.selectbox(
        "Analytical level",
        level_options,
        key="evolution_story_level",
    )

    shown = story.copy()
    if selected_level != "All levels":
        shown = shown[shown["Level"].eq(selected_level)].copy()

    if shown.empty:
        st.info("No documented evolution decisions are available for the selected level.")
    else:
        event_types = shown["Event_Type"].drop_duplicates().tolist()
        selected_types = st.multiselect(
            "Change types",
            event_types,
            default=event_types,
            key="evolution_story_types",
        )
        shown = shown[shown["Event_Type"].isin(selected_types)].copy()

        st.markdown("#### Evolution timeline")
        timeline = shown.copy()
        timeline["Story_Label"] = timeline["Level"] + " · " + timeline["Event_Type"]
        fig = go.Figure()
        for label in timeline["Story_Label"].drop_duplicates():
            part = timeline[timeline["Story_Label"].eq(label)]
            fig.add_trace(go.Scatter(
                x=part["DEC_Sequence"],
                y=[label] * len(part),
                mode="markers+text",
                text=part["Decision_ID"],
                textposition="top center",
                hovertext=[
                    f"{_txt(r.get('Decision_ID'))}<br>"
                    f"{_txt(r.get('Decision'))}<br>"
                    f"Why: {_short(r.get('Problem_or_Reason'), 220)}<br>"
                    f"After: {_short(r.get('Result_or_Impact'), 220)}"
                    for _, r in part.iterrows()
                ],
                hoverinfo="text",
                name=label,
                marker=dict(size=12),
            ))
        fig.update_layout(
            title="Analytical evolution across FOC → PCL → Theme → Dimension",
            xaxis_title="DEC sequence (analytical chronology)",
            yaxis_title="",
            height=max(520, min(1000, 65 * timeline["Story_Label"].nunique() + 260)),
            margin=dict(l=20, r=20, t=70, b=50),
            hovermode="closest",
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                **PLOT_CONFIG,
                "toImageButtonOptions": {
                    **PLOT_CONFIG["toImageButtonOptions"],
                    "filename": "PMM_Analytical_Evolution_Story",
                },
            },
        )

        st.markdown("#### Before → problem → decision → after")
        display_n = st.slider(
            "Number of decision stories shown",
            min_value=3,
            max_value=min(30, max(3, len(shown))),
            value=min(10, max(3, len(shown))),
            key="evolution_story_n",
        )
        for _, r in shown.sort_values("DEC_Sequence", ascending=False).head(display_n).iterrows():
            title = f"{_txt(r.get('Decision_ID'))} · {_txt(r.get('Level'))} · {_txt(r.get('Event_Type'))}"
            with st.expander(title, expanded=False):
                a, b = st.columns(2)
                with a:
                    st.markdown("**Problem / why the previous state was questioned**")
                    st.write(_txt(r.get("Problem_or_Reason")) or "Not explicitly recorded.")
                    st.markdown("**Decision / correction**")
                    st.write(_txt(r.get("Decision")) or "Not explicitly recorded.")
                with b:
                    st.markdown("**Result / analytical impact**")
                    st.write(_txt(r.get("Result_or_Impact")) or "Not explicitly recorded.")
                    st.markdown("**Affected entities / fields**")
                    st.write(_txt(r.get("Affected_Entities")) or _txt(r.get("Affected_Sheets_or_Fields")) or "Not explicitly recorded.")
                if _txt(r.get("Status")):
                    st.caption(f"Status: {_txt(r.get('Status'))}")

    st.markdown("---")
    st.markdown("#### Exact retained FOC → PCL before/after histories")
    if exact.empty:
        st.info(
            "No FOC has both a retained historical mapping row and a current mapping row in this MASTER. "
            "Broader reassignment history is still available from the Decision Log above."
        )
    else:
        st.dataframe(
            exact,
            use_container_width=True,
            hide_index=True,
            height=min(520, 95 + 72 * len(exact)),
        )
        st.caption(
            "These are exact row-level before/after cases preserved in 06_DeNovo_Clustering, not inferred from narrative text."
        )

    st.markdown("---")
    st.markdown("#### SG4 generation / dimension-history view")
    if dim_hist.empty:
        st.info("No retained Candidate Dimension history rows were found.")
    else:
        status = dim_hist.get("Dimension_Status", pd.Series("", index=dim_hist.index)).fillna("").astype(str)
        history_mask = status.str.contains(
            r"Historical|Superseded|Suspended|Merged|Stable",
            case=False, regex=True, na=False,
        )
        historical_dims = dim_hist[history_mask].copy()
        st.dataframe(
            historical_dims if not historical_dims.empty else dim_hist,
            use_container_width=True,
            hide_index=True,
            height=520,
        )
        st.caption(
            "This table shows retained SG4 generations, including superseded/suspended candidates, stable current constructs, "
            "and merged historical subdomains such as those created under DEC-498."
        )

    st.download_button(
        "Download analytical evolution story (CSV)",
        story.to_csv(index=False).encode("utf-8-sig"),
        "PMM_Analytical_Evolution_Story.csv",
        "text/csv",
        use_container_width=True,
    )


def render_audit_trail_timeline(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("### Audit-Trail Timeline")
    st.caption(
        "Chronology of documented analytical decisions. Explicit calendar dates are used when available; otherwise DEC number provides sequence, not elapsed time."
    )
    events = build_audit_trail_events(frames)
    if events.empty:
        st.info("No audit-trail events could be reconstructed from the current MASTER.")
        return

    types = events["Event_Type"].drop_duplicates().tolist()
    selected_types = st.multiselect(
        "Decision event types",
        types,
        default=types,
        key="qual_audit_timeline_types",
    )
    source_options = events["Evidence_Source"].drop_duplicates().tolist()
    selected_sources = st.multiselect(
        "Evidence sources",
        source_options,
        default=source_options,
        key="qual_audit_timeline_sources",
    )
    shown = events[
        events["Event_Type"].isin(selected_types)
        & events["Evidence_Source"].isin(selected_sources)
    ].copy()

    a, b, c, d = st.columns(4)
    a.metric("Decisions/events", len(shown))
    b.metric("Event types", shown["Event_Type"].nunique())
    c.metric("Earliest DEC", int(shown["DEC_Sequence"].min()) if not shown.empty else 0)
    d.metric("Latest DEC", int(shown["DEC_Sequence"].max()) if not shown.empty else 0)

    fig = build_audit_timeline_figure(shown)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            **PLOT_CONFIG,
            "toImageButtonOptions": {
                **PLOT_CONFIG["toImageButtonOptions"],
                "filename": "PMM_Audit_Trail_Timeline",
            },
        },
    )

    with st.expander("View audit-trail event table", expanded=False):
        st.dataframe(
            shown.sort_values(["DEC_Sequence", "Decision_ID"]),
            use_container_width=True,
            hide_index=True,
            height=520,
        )

    st.download_button(
        "Download audit-trail events (CSV)",
        shown.sort_values(["DEC_Sequence", "Decision_ID"]).to_csv(index=False).encode("utf-8-sig"),
        "PMM_Audit_Trail_Timeline.csv",
        "text/csv",
        use_container_width=True,
    )
    st.info(
        "Interpretation safeguard: the timeline documents the evolution of analytical decisions. "
        "A high number of revisions is not a weakness; merge/split/reassignment/retirement can demonstrate active boundary testing when supported by recorded rationale."
    )


def render_entreq_reporting_audit(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("### ENTREQ Reporting Audit")
    st.caption(
        "ENTREQ = Enhancing Transparency in Reporting the Synthesis of Qualitative Research. "
        "This is a reporting-transparency checklist, not a study-quality score."
    )
    st.info(
        "Source: Tong et al. (2012), BMC Medical Research Methodology 12:181. "
        "The original ENTREQ statement contains 21 items across five domains. "
        "It was developed for qualitative research synthesis; use here is a transparency cross-check for the thesis synthesis."
    )

    base = build_entreq_audit_table(frames)
    if "entreq_audit_editor" not in st.session_state:
        st.session_state["entreq_audit_editor"] = base.copy()

    current = st.session_state["entreq_audit_editor"].copy()
    # Refresh evidence hints from the current MASTER while preserving researcher-entered status/notes.
    refreshed = base.copy()
    if len(current) == len(refreshed):
        refreshed["Status"] = current["Status"].astype(str).tolist()
        refreshed["Thesis location / note"] = current["Thesis location / note"].astype(str).tolist()

    edited = st.data_editor(
        refreshed,
        use_container_width=True,
        hide_index=True,
        height=720,
        disabled=[
            "No.", "Domain", "ENTREQ item", "Reporting expectation",
            "Project evidence hint", "Provisional review", "Review rationale / next action",
            "Where to verify / current evidence",
        ],
        column_config={
            "No.": st.column_config.NumberColumn(width="small"),
            "Domain": st.column_config.TextColumn(width="medium"),
            "ENTREQ item": st.column_config.TextColumn(width="medium"),
            "Reporting expectation": st.column_config.TextColumn(width="large"),
            "Project evidence hint": st.column_config.TextColumn(width="medium"),
            "Provisional review": st.column_config.TextColumn(width="medium"),
            "Review rationale / next action": st.column_config.TextColumn(width="large"),
            "Where to verify / current evidence": st.column_config.TextColumn(width="large"),
            "Status": st.column_config.SelectboxColumn(
                options=["Not assessed", "Covered", "Partial", "Missing", "N/A"],
                required=True,
                width="medium",
            ),
            "Thesis location / note": st.column_config.TextColumn(width="large"),
        },
        key="entreq_reporting_editor_widget",
    )
    st.session_state["entreq_audit_editor"] = edited.copy()

    counts = edited["Status"].value_counts()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Covered", int(counts.get("Covered", 0)))
    c2.metric("Partial", int(counts.get("Partial", 0)))
    c3.metric("Missing", int(counts.get("Missing", 0)))
    c4.metric("Not assessed", int(counts.get("Not assessed", 0)))
    c5.metric("N/A", int(counts.get("N/A", 0)))

    st.download_button(
        "Download ENTREQ audit (CSV)",
        edited.to_csv(index=False).encode("utf-8-sig"),
        "ENTREQ_Reporting_Audit.csv",
        "text/csv",
        use_container_width=True,
    )

    with st.expander("ENTREQ domain summary", expanded=False):
        domain_summary = (
            edited.groupby(["Domain", "Status"]).size()
            .unstack(fill_value=0)
            .reset_index()
        )
        st.dataframe(domain_summary, use_container_width=True, hide_index=True)

    st.warning(
        "Do not interpret the number of Covered items as a methodological quality score. "
        "A status of Covered means the reporting requirement has been located and documented; "
        "it does not independently validate the underlying methodological decision."
    )


def render_qualitative_visuals(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown(
        '<div class="note-banner"><b>Qualitative Visual Outputs:</b> '
        'Thesis-oriented visuals derived from the current analytical structure. '
        'They complement the Derivation Tree and do not modify the MASTER.</div>',
        unsafe_allow_html=True,
    )

    visual = st.radio(
        "Qualitative visual",
        ["Researcher Analytical Journey", "Analytical Sankey", "Analytical Evolution Story", "Theme Boundary Cards", "Negative / Deviant Cases", "ENTREQ Reporting Audit", "Audit-Trail Timeline", "Theme × Study Heatmap", "Theme Co-occurrence Network", "Word Cloud"],
        horizontal=True, key="qualitative_visual_choice"
    )
    st.divider()

    if visual == "Researcher Analytical Journey":
        render_supervisor_analytical_journey(frames)

    elif visual == "Analytical Sankey":
        dims = active_dimensions(frames)
        if dims.empty:
            st.info("No current Candidate Dimensions are available.")
            return
        sankey_mode = st.radio(
            "Sankey scope",
            ["All Dimensions Overview", "One Dimension Deep Dive"],
            horizontal=True,
            key="qual_sankey_scope",
        )

        if sankey_mode == "All Dimensions Overview":
            fig = build_all_dimensions_sankey(frames)
            st.plotly_chart(
                fig, use_container_width=True,
                config={
                    **PLOT_CONFIG,
                    "toImageButtonOptions": {
                        **PLOT_CONFIG["toImageButtonOptions"],
                        "filename": "PMM_Sankey_All_Dimensions_Overview",
                    },
                },
            )
            st.caption(
                "Suggested thesis caption: Overview of the current PMM derivation structure across all active Candidate Dimensions and their Themes."
            )
            st.info(
                "This overview shows all current Dimensions and Themes. Use One Dimension Deep Dive to inspect the downstream PCL/Cluster structure."
            )
        else:
            labels = dict(zip(dims["Dimension_ID"].astype(str), dims["Candidate_Dimension_Name"].astype(str)))
            did = st.selectbox(
                "Candidate Dimension", dims["Dimension_ID"].astype(str).tolist(),
                format_func=lambda x: f"{x} — {labels.get(x, '')}",
                key="qual_sankey_dimension"
            )
            fig = build_dimension_sankey(frames, did)
            st.plotly_chart(
                fig, use_container_width=True,
                config={**PLOT_CONFIG, "toImageButtonOptions": {**PLOT_CONFIG["toImageButtonOptions"], "filename": f"PMM_Sankey_{did}"}}
            )
            st.caption(
                "Suggested thesis caption: Analytical derivation flow from the selected Candidate Dimension "
                "to its supporting Themes and PCL/Clusters. Link widths represent currently mapped First-Order Codes."
            )
            st.info("Interpret this as an analytical derivation structure, not as a causal model.")

    elif visual == "Analytical Evolution Story":
        render_analytical_evolution_story(frames)

    elif visual == "Theme Boundary Cards":
        render_theme_boundary_cards(frames)

    elif visual == "Negative / Deviant Cases":
        render_negative_deviant_cases(frames)

    elif visual == "ENTREQ Reporting Audit":
        render_entreq_reporting_audit(frames)

    elif visual == "Audit-Trail Timeline":
        render_audit_trail_timeline(frames)

    elif visual == "Theme × Study Heatmap":
        c1, c2 = st.columns(2)
        metric = c1.selectbox("Cell metric", ["Evidence count", "FOC count", "Binary study support"], key="qual_heatmap_metric")
        topn = c2.selectbox("Studies displayed", [15, 20, 25, 30, 40], index=2, key="qual_heatmap_topn")
        matrix = build_theme_study_matrix(frames, metric)
        if matrix.empty:
            st.info("No Theme × Study support matrix could be built.")
            return
        fig, shown = build_heatmap_figure(matrix, int(topn))
        st.plotly_chart(
            fig, use_container_width=True,
            config={**PLOT_CONFIG, "toImageButtonOptions": {**PLOT_CONFIG["toImageButtonOptions"], "filename": "PMM_Theme_Study_Heatmap"}}
        )
        st.caption(
            "Suggested thesis caption: Distribution of study support across current descriptive Themes. "
            "Darker cells indicate greater support under the selected metric."
        )
        csv = shown.reset_index().to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "Download heatmap data (CSV)", csv, "PMM_Theme_Study_Heatmap_Data.csv",
            "text/csv", use_container_width=True
        )

    elif visual == "Word Cloud":
        st.markdown("#### Word Cloud Explorer")
        st.info(
            "Descriptive/exploratory visual only: word size represents textual frequency after display-level cleaning; "
            "it does not represent theoretical importance, evidence strength, or causality."
        )

        dimensions = active_dimensions(frames)
        dimension_options = ["All Dimensions"]
        if not dimensions.empty:
            dimension_options += dimensions["Dimension_ID"].astype(str).tolist()
        selected_dimension = st.selectbox(
            "Scope by Dimension",
            dimension_options,
            format_func=lambda x: (
                "All current Dimensions"
                if x == "All Dimensions"
                else f"{x} — {_short(dict(zip(dimensions['Dimension_ID'].astype(str), dimensions['Candidate_Dimension_Name'].astype(str))).get(x, ''))}"
            ),
            key="qual_wordcloud_dimension",
        )

        theme_options = ["All Themes"]
        themes_df = active_themes(frames)
        if not themes_df.empty:
            if selected_dimension != "All Dimensions":
                dmap = dimension_theme_map(frames)
                allowed = set(
                    dmap.loc[
                        dmap["Dimension_ID"].astype(str).str.strip().eq(selected_dimension),
                        "Theme_ID",
                    ].astype(str).str.strip()
                ) if not dmap.empty else set()
                themes_df = themes_df[
                    themes_df["Theme_ID"].astype(str).str.strip().isin(allowed)
                ].copy()
            theme_options += themes_df["Theme_ID"].astype(str).tolist()

        theme_labels = dict(
            zip(
                themes_df["Theme_ID"].astype(str),
                themes_df["Working_Theme_Label"].astype(str),
            )
        ) if not themes_df.empty else {}

        selected_theme = st.selectbox(
            "Scope by Theme",
            theme_options,
            format_func=lambda x: (
                "All current Themes"
                if x == "All Themes"
                else f"{x} — {theme_labels.get(x, '')}"
            ),
            key="qual_wordcloud_theme",
        )

        source = st.radio(
            "Word source",
            ["Original Author Terms", "First-Order Code labels", "Meaning Units / Evidence text"],
            horizontal=True,
            key="qual_wordcloud_source",
        )
        max_words = st.slider("Maximum words", 30, 150, 80, step=10, key="qual_wordcloud_max_words")

        did_filter = None if selected_dimension == "All Dimensions" else selected_dimension
        tid_filter = None if selected_theme == "All Themes" else selected_theme
        frequencies, records = build_wordcloud_frequencies(
            frames,
            source=source,
            dimension_id=did_filter,
            theme_id=tid_filter,
            max_words=max_words,
        )

        if not frequencies:
            st.warning("No usable text is available for the selected scope/source.")
        else:
            image_bytes = build_wordcloud_image(frequencies)
            st.image(image_bytes, use_container_width=True)
            c1, c2, c3 = st.columns(3)
            c1.metric("Unique words shown", len(frequencies))
            c2.metric("Source records", len(records))
            c3.metric("Total token frequency", sum(frequencies.values()))

            freq_df = (
                pd.DataFrame(
                    [{"Word": word, "Frequency": count} for word, count in frequencies.items()]
                )
                .sort_values(["Frequency", "Word"], ascending=[False, True])
            )
            st.download_button(
                "Download Word Cloud PNG",
                image_bytes,
                "PMM_Word_Cloud.png",
                "image/png",
                use_container_width=True,
            )
            st.download_button(
                "Download Word Cloud frequency data (CSV)",
                freq_df.to_csv(index=False).encode("utf-8-sig"),
                "PMM_Word_Cloud_Frequencies.csv",
                "text/csv",
                use_container_width=True,
            )
            with st.expander("View frequency table", expanded=False):
                st.dataframe(freq_df, use_container_width=True, hide_index=True, height=420)

        st.caption(
            "Suggested thesis use: supplementary descriptive figure only. "
            "For substantive claims about Themes or PMM dimensions, rely on the coded evidence, "
            "traceability chain, and formal qualitative synthesis rather than word frequency."
        )

    else:
        threshold = st.slider("Minimum shared studies for an edge", 1, 8, 2, key="qual_network_threshold")
        fig, edges = build_cooccurrence_figure(frames, threshold)
        st.plotly_chart(
            fig, use_container_width=True,
            config={**PLOT_CONFIG, "toImageButtonOptions": {**PLOT_CONFIG["toImageButtonOptions"], "filename": "PMM_Theme_Cooccurrence_Network"}}
        )
        st.caption(
            "Suggested thesis caption: Theme co-occurrence network based on shared contributing studies. "
            "Node size reflects study support; thicker links indicate more studies supporting both Themes."
        )
        st.info(
            "Co-occurrence indicates shared study support, not causation or conceptual equivalence. "
            "Use the threshold control to reduce visual clutter."
        )
        if not edges.empty:
            st.download_button(
                "Download network edge table (CSV)",
                edges.to_csv(index=False).encode("utf-8-sig"),
                "PMM_Theme_Cooccurrence_Edges.csv",
                "text/csv", use_container_width=True
            )
            with st.expander("View network edge table", expanded=False):
                st.dataframe(edges, use_container_width=True, hide_index=True, height=420)
