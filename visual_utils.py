from __future__ import annotations

from typing import Dict, Any, List
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from master_utils import (
    active_dimensions,
    active_themes,
    active_cluster_register,
    cluster_coverage_table,
    theme_cluster_map,
    dimension_theme_map,
    theme_summary_table,
)


def structure_path_table(frames: Dict[str, pd.DataFrame], include_residuals: bool = True) -> pd.DataFrame:
    """Build a presentation hierarchy: Dimension -> Theme -> Cluster.

    Values are current mapped FOC counts per cluster. Residual/unassigned items
    are kept visible rather than force-fitted.
    """
    dims = active_dimensions(frames)
    themes = active_themes(frames)
    clusters = active_cluster_register(frames)
    coverage = cluster_coverage_table(frames)
    tlinks = theme_cluster_map(frames, include_retired=False)
    dlinks = dimension_theme_map(frames)

    dim_labels = {}
    if not dims.empty:
        dim_labels = {
            str(r["Dimension_ID"]): f"{r['Dimension_ID']} — {r.get('Candidate_Dimension_Name','')}"
            for _, r in dims.iterrows()
        }
    theme_labels = {}
    if not themes.empty:
        theme_labels = {
            str(r["Theme_ID"]): f"{r['Theme_ID']} — {r.get('Working_Theme_Label','')}"
            for _, r in themes.iterrows()
        }
    cluster_labels = {}
    if not clusters.empty:
        cluster_labels = {
            str(r["Cluster_ID"]): f"{r['Cluster_ID']} — {r.get('Working_Cluster_Label','')}"
            for _, r in clusters.iterrows()
        }

    fcount = {}
    scount = {}
    if not coverage.empty and "Cluster_ID" in coverage.columns:
        for _, r in coverage.iterrows():
            cid = str(r.get("Cluster_ID", ""))
            fcount[cid] = int(r.get("Codes", 0) or 0)
            scount[cid] = int(r.get("Studies", 0) or 0)

    theme_to_dim: Dict[str, List[str]] = {}
    if not dlinks.empty:
        for tid, g in dlinks.groupby("Theme_ID"):
            theme_to_dim[str(tid)] = sorted(set(g["Dimension_ID"].astype(str)))

    rows = []
    themed_clusters = set()
    if not tlinks.empty:
        for _, r in tlinks.iterrows():
            tid = str(r.get("Theme_ID", ""))
            cid = str(r.get("Cluster_ID", ""))
            if not tid or not cid:
                continue
            themed_clusters.add(cid)
            dids = theme_to_dim.get(tid, [])
            if not dids:
                dids = ["UNASSIGNED"]
            for did in dids:
                rows.append({
                    "Dimension": dim_labels.get(did, "Unassigned active themes" if did == "UNASSIGNED" else did),
                    "Theme": theme_labels.get(tid, tid),
                    "Cluster": cluster_labels.get(cid, cid),
                    "FOCs": max(fcount.get(cid, 0), 1),
                    "Studies": scount.get(cid, 0),
                    "Dimension_ID": did,
                    "Theme_ID": tid,
                    "Cluster_ID": cid,
                })

    if include_residuals and not clusters.empty:
        for _, r in clusters.iterrows():
            cid = str(r.get("Cluster_ID", ""))
            if not cid or cid in themed_clusters:
                continue
            rows.append({
                "Dimension": "Residual / not force-fitted",
                "Theme": "Unthemed active clusters",
                "Cluster": cluster_labels.get(cid, cid),
                "FOCs": max(fcount.get(cid, 0), 1),
                "Studies": scount.get(cid, 0),
                "Dimension_ID": "RESIDUAL",
                "Theme_ID": "UNTHEMED",
                "Cluster_ID": cid,
            })
    return pd.DataFrame(rows)


def structure_sunburst(frames: Dict[str, pd.DataFrame], title: str = "Current inductive structure"):
    df = structure_path_table(frames, include_residuals=True)
    if df.empty:
        return None
    fig = px.sunburst(
        df,
        path=["Dimension", "Theme", "Cluster"],
        values="FOCs",
        hover_data={"Studies": True, "FOCs": True},
        title=title,
    )
    fig.update_layout(margin=dict(t=55, l=10, r=10, b=10), height=700)
    return fig


def dimension_theme_sankey(frames: Dict[str, pd.DataFrame], title: str = "Dimension → Theme evidence flow"):
    ts = theme_summary_table(frames)
    if ts.empty:
        return None
    rows = []
    for _, r in ts.iterrows():
        dims = [x.strip() for x in str(r.get("Dimension_IDs", "")).split(";") if x.strip()]
        if not dims:
            dims = ["UNASSIGNED"]
        for did in dims:
            rows.append({
                "Dimension_ID": did,
                "Theme_ID": str(r.get("Theme_ID", "")),
                "FOCs": int(r.get("FOCs", 0) or 0),
                "Studies": int(r.get("Studies", 0) or 0),
            })
    if not rows:
        return None
    x = pd.DataFrame(rows)
    dims = active_dimensions(frames)
    themes = active_themes(frames)
    dlabel = {str(r["Dimension_ID"]): f"{r['Dimension_ID']} — {r.get('Candidate_Dimension_Name','')}" for _, r in dims.iterrows()} if not dims.empty else {}
    tlabel = {str(r["Theme_ID"]): f"{r['Theme_ID']} — {r.get('Working_Theme_Label','')}" for _, r in themes.iterrows()} if not themes.empty else {}
    dlabel["UNASSIGNED"] = "Unassigned active themes"

    labels = []
    for did in x["Dimension_ID"].drop_duplicates().tolist():
        labels.append(dlabel.get(did, did))
    for tid in x["Theme_ID"].drop_duplicates().tolist():
        labels.append(tlabel.get(tid, tid))
    idx = {label: i for i, label in enumerate(labels)}
    source, target, value, custom = [], [], [], []
    for _, r in x.iterrows():
        dl = dlabel.get(r["Dimension_ID"], r["Dimension_ID"])
        tl = tlabel.get(r["Theme_ID"], r["Theme_ID"])
        source.append(idx[dl])
        target.append(idx[tl])
        value.append(max(int(r["FOCs"]), 1))
        custom.append([int(r["FOCs"]), int(r["Studies"])])

    fig = go.Figure(data=[go.Sankey(
        node=dict(label=labels, pad=12, thickness=16),
        link=dict(
            source=source,
            target=target,
            value=value,
            customdata=custom,
            hovertemplate="FOCs: %{customdata[0]}<br>Studies: %{customdata[1]}<extra></extra>",
        ),
    )])
    fig.update_layout(title_text=title, height=620, margin=dict(t=55, l=10, r=10, b=10))
    return fig


def horizontal_count_bar(df: pd.DataFrame, label_col: str, value_col: str = "Count", title: str = ""):
    if df.empty or label_col not in df.columns or value_col not in df.columns:
        return None
    x = df.copy()
    fig = px.bar(x, x=value_col, y=label_col, orientation="h", title=title, text=value_col)
    fig.update_layout(height=max(280, min(760, 80 + len(x) * 34)), margin=dict(t=55, l=10, r=10, b=10))
    fig.update_yaxes(categoryorder="total ascending")
    return fig
