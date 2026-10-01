
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

from master_utils import (active_cluster_register, active_dimensions, active_themes, challenged_foc_table, cluster_members, current_mapping_rows, dimension_theme_map, provisional_cluster_summary, retired_themes, split_ids)

QUAL_VIS_VERSION = "v0.14.2"

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


def build_entreq_audit_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for no, domain, item, guide in ENTREQ_ITEMS:
        evidence_level, hint = _entreq_evidence_hint(frames, no)
        rows.append({
            "No.": no,
            "Domain": domain,
            "ENTREQ item": item,
            "Reporting expectation": guide,
            "Project evidence hint": evidence_level,
            "Where to verify / current evidence": hint,
            "Status": "Not assessed",
            "Thesis location / note": "",
        })
    return pd.DataFrame(rows)


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
            "Project evidence hint", "Where to verify / current evidence",
        ],
        column_config={
            "No.": st.column_config.NumberColumn(width="small"),
            "Domain": st.column_config.TextColumn(width="medium"),
            "ENTREQ item": st.column_config.TextColumn(width="medium"),
            "Reporting expectation": st.column_config.TextColumn(width="large"),
            "Project evidence hint": st.column_config.TextColumn(width="medium"),
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
        ["Analytical Sankey", "Theme Boundary Cards", "Negative / Deviant Cases", "ENTREQ Reporting Audit", "Theme × Study Heatmap", "Theme Co-occurrence Network", "Word Cloud"],
        horizontal=True, key="qualitative_visual_choice"
    )
    st.divider()

    if visual == "Analytical Sankey":
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

    elif visual == "Theme Boundary Cards":
        render_theme_boundary_cards(frames)

    elif visual == "Negative / Deviant Cases":
        render_negative_deviant_cases(frames)

    elif visual == "ENTREQ Reporting Audit":
        render_entreq_reporting_audit(frames)

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
