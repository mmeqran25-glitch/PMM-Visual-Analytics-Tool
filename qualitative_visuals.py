
from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from master_utils import active_dimensions, active_themes, cluster_members, dimension_theme_map, split_ids

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


def render_qualitative_visuals(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown(
        '<div class="note-banner"><b>Qualitative Visual Outputs:</b> '
        'Thesis-oriented visuals derived from the current analytical structure. '
        'They complement the Derivation Tree and do not modify the MASTER.</div>',
        unsafe_allow_html=True,
    )

    visual = st.radio(
        "Qualitative visual",
        ["Analytical Sankey", "Theme × Study Heatmap", "Theme Co-occurrence Network"],
        horizontal=True, key="qualitative_visual_choice"
    )
    st.divider()

    if visual == "Analytical Sankey":
        dims = active_dimensions(frames)
        if dims.empty:
            st.info("No current Candidate Dimensions are available.")
            return
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
