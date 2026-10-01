
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


def render_qualitative_visuals(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown(
        '<div class="note-banner"><b>Qualitative Visual Outputs:</b> '
        'Thesis-oriented visuals derived from the current analytical structure. '
        'They complement the Derivation Tree and do not modify the MASTER.</div>',
        unsafe_allow_html=True,
    )

    visual = st.radio(
        "Qualitative visual",
        ["Analytical Sankey", "Theme × Study Heatmap", "Theme Co-occurrence Network", "Word Cloud"],
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
