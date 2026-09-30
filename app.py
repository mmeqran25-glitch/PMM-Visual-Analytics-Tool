from __future__ import annotations

import html
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from tree_utils import (
    build_candidate_stage_tree_data,
    build_selected_themes_tree_data,
    build_dimension_tree_data,
    build_theme_tree_data,
    build_cluster_tree_data,
    tree_html,
    org_chart_html,
)
from master_utils import (
    load_master_workbook,
    validate_master,
    status_counts,
    active_cluster_register,
    active_themes,
    retired_themes,
    active_dimensions,
    theme_lineage,
    cluster_members,
    cluster_coverage_table,
    traceability_checks,
    split_ids,
    current_mapping_rows,
    challenged_dimensions,
    structural_status_summary,
    stability_audit_rows,
    unthemed_active_clusters,
    unassigned_active_themes,
    dimension_theme_map,
    master_snapshot,
    theme_summary_table,
    challenged_foc_table,
    provisional_cluster_summary,
    mu_context_audit_summary,
    current_dimension_evidence_summary,
)
from visual_utils import structure_sunburst, dimension_theme_sankey, horizontal_count_bar
from share_utils import supervisor_share_html
from snapshot_utils import (
    build_supervisor_snapshot,
    load_supervisor_snapshot,
    snapshot_bytes,
    nodes_of_type,
    subtree_by_id,
    selected_nodes_tree,
    dimension_summary,
)
from researcher_cache import (
    token_matches,
    save_cached_master,
    load_cached_master,
    clear_cached_master,
)


APP_VERSION = "v0.9.4"
st.set_page_config(page_title=f"PMM Visual Analytics Tool {APP_VERSION}", page_icon="📊", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.15rem; padding-bottom: 2.5rem;}
.kicker {font-size:.78rem; font-weight:800; letter-spacing:.08em; text-transform:uppercase; color:#5b7187; margin-bottom:.2rem;}
.readonly-banner {border-left:5px solid #238636; background:#f1fbf4; border-radius:9px; padding:11px 14px; margin:.3rem 0 1rem 0;}
.review-banner {border-left:5px solid #d29922; background:#fff9e8; border-radius:9px; padding:11px 14px; margin:.3rem 0 1rem 0;}
.note-banner {border-left:5px solid #4c83b6; background:#f5f9fd; border-radius:9px; padding:11px 14px; margin:.3rem 0 1rem 0;}
.flow-step {border:1px solid #d7e2ee; border-radius:14px; padding:14px 10px; text-align:center; background:#fbfdff; min-height:96px;}
.flow-step .n {font-size:1.42rem; font-weight:850; color:#12385e;}
.flow-step .t {font-size:.82rem; color:#60758a; margin-top:4px;}
.flow-arrow {font-size:1.55rem; text-align:center; color:#4c83b6; padding-top:31px;}
.lineage-box {border:1px solid #d7e2ee; border-radius:13px; padding:12px 14px; background:#fbfdff; min-height:110px;}
.lineage-title {font-weight:800; color:#12385e; margin-bottom:5px;}
.small-muted {color:#657789; font-size:.86rem;}
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def cached_master_load(file_bytes: bytes):
    return load_master_workbook(file_bytes)


@st.cache_data(show_spinner=False)
def cached_supervisor_snapshot_bytes(file_bytes: bytes) -> bytes:
    """Build the sanitized supervisor snapshot once per workbook, not on every UI click."""
    frames, _ = cached_master_load(file_bytes)
    return snapshot_bytes(frames)


def prune_tree_depth(node: dict, max_depth: int, depth: int = 0) -> dict:
    """Copy only the hierarchy needed by the current visual scope.

    This keeps large Evidence/Study subtrees out of the browser DOM while leaving
    the analytical MASTER untouched.
    """
    if not node:
        return {}
    out = {k: v for k, v in node.items() if k != "children"}
    children = node.get("children", []) or []
    if depth >= max_depth:
        out["children"] = []
    else:
        out["children"] = [
            prune_tree_depth(child, max_depth, depth + 1)
            for child in children
            if child
        ]
    return out


def clipped(value, n=220):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value)
    return text if len(text) <= n else text[: n - 1] + "…"


def current_dimension_status_counts(frames: dict) -> pd.DataFrame:
    dims = active_dimensions(frames)
    return status_counts(dims, "Dimension_Status") if not dims.empty else pd.DataFrame()


def card_choice(
    title: str,
    options: list[str],
    key: str,
    descriptions: dict[str, str] | None = None,
    default_index: int = 0,
) -> str:
    """Render a small set of mutually exclusive choices as interactive cards."""
    descriptions = descriptions or {}
    if key not in st.session_state or st.session_state.get(key) not in options:
        st.session_state[key] = options[min(max(default_index, 0), len(options) - 1)]

    st.markdown(f"**{html.escape(title)}**")
    cols = st.columns(len(options))
    current = st.session_state[key]

    for idx, option in enumerate(options):
        selected = current == option
        with cols[idx]:
            with st.container(border=True):
                st.markdown(
                    f"<div style='font-weight:800;font-size:.98rem;margin-bottom:.2rem;'>"
                    f"{'✓ ' if selected else ''}{html.escape(option)}</div>",
                    unsafe_allow_html=True,
                )
                if descriptions.get(option):
                    st.caption(descriptions[option])
                if st.button(
                    "Selected" if selected else "Choose",
                    key=f"{key}__option_{idx}",
                    use_container_width=True,
                    type="primary" if selected else "secondary",
                ):
                    st.session_state[key] = option
                    st.rerun()

    return st.session_state[key]


def theme_dropdown_selector(
    ids: list[str],
    labels: dict[str, str],
    key_prefix: str,
    statuses: dict[str, str] | None = None,
    default_selected: list[str] | None = None,
    retired_ids: list[str] | None = None,
    retired_labels: dict[str, str] | None = None,
    retired_statuses: dict[str, str] | None = None,
) -> tuple[list[str], list[str], bool]:
    """Compact dropdown checklist for current and optional retired Themes."""
    statuses = statuses or {}
    default_selected = default_selected or []
    retired_ids = retired_ids or []
    retired_labels = retired_labels or {}
    retired_statuses = retired_statuses or {}

    valid_ids = [str(x) for x in ids if str(x)]
    valid_retired = [str(x) for x in retired_ids if str(x)]

    for tid in valid_ids:
        state_key = f"{key_prefix}__current__{tid}"
        if state_key not in st.session_state:
            st.session_state[state_key] = tid in default_selected

    selected_before = [
        tid for tid in valid_ids
        if st.session_state.get(f"{key_prefix}__current__{tid}", False)
    ]
    retired_before = [
        tid for tid in valid_retired
        if st.session_state.get(f"{key_prefix}__retired__{tid}", False)
    ]
    total_before = len(selected_before) + len(retired_before)

    with st.popover(
        f"Themes ▾  ·  {total_before} selected",
        use_container_width=True,
    ):
        st.markdown("**Current Themes**")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Select all current", key=f"{key_prefix}__all_current", use_container_width=True):
                for tid in valid_ids:
                    st.session_state[f"{key_prefix}__current__{tid}"] = True
                st.rerun()
        with b2:
            if st.button("Clear current", key=f"{key_prefix}__clear_current", use_container_width=True):
                for tid in valid_ids:
                    st.session_state[f"{key_prefix}__current__{tid}"] = False
                st.rerun()

        selected_current: list[str] = []
        for tid in valid_ids:
            checked = st.checkbox(
                f"{tid} — {labels.get(tid, '')}",
                key=f"{key_prefix}__current__{tid}",
                help=f"Status: {statuses.get(tid, '')}" if statuses.get(tid, "") else None,
            )
            if checked:
                selected_current.append(tid)

        show_retired = False
        selected_retired: list[str] = []
        if valid_retired:
            st.divider()
            retired_toggle_key = f"{key_prefix}__show_retired"
            if retired_toggle_key not in st.session_state:
                st.session_state[retired_toggle_key] = False
            show_retired = st.checkbox(
                "Show retired Themes — audit history",
                key=retired_toggle_key,
                help=(
                    "Historical audit only. Retired Themes remain excluded from "
                    "current Theme counts and Candidate-Dimension logic."
                ),
            )
            if show_retired:
                st.caption("Historical audit only — selecting these does not reactivate them.")
                r1, r2 = st.columns(2)
                with r1:
                    if st.button("Select all retired", key=f"{key_prefix}__all_retired", use_container_width=True):
                        for tid in valid_retired:
                            st.session_state[f"{key_prefix}__retired__{tid}"] = True
                        st.rerun()
                with r2:
                    if st.button("Clear retired", key=f"{key_prefix}__clear_retired", use_container_width=True):
                        for tid in valid_retired:
                            st.session_state[f"{key_prefix}__retired__{tid}"] = False
                        st.rerun()

                for tid in valid_retired:
                    checked = st.checkbox(
                        f"[RETIRED] {tid} — {retired_labels.get(tid, '')}",
                        key=f"{key_prefix}__retired__{tid}",
                        help=(
                            f"Historical status: {retired_statuses.get(tid, '')}"
                            if retired_statuses.get(tid, "") else "Retired Theme — audit history only."
                        ),
                    )
                    if checked:
                        selected_retired.append(tid)
            else:
                selected_retired = []

    selected_current = [
        tid for tid in valid_ids
        if st.session_state.get(f"{key_prefix}__current__{tid}", False)
    ]
    if show_retired:
        selected_retired = [
            tid for tid in valid_retired
            if st.session_state.get(f"{key_prefix}__retired__{tid}", False)
        ]

    selected_names = selected_current + selected_retired
    if selected_names:
        preview = ", ".join(selected_names[:6])
        if len(selected_names) > 6:
            preview += f" … +{len(selected_names) - 6}"
        st.caption(f"Selected: {preview}")
    else:
        st.caption("No Themes selected.")

    return selected_current, selected_retired, show_retired


def render_flow(snapshot: dict):
    items = [
        (snapshot.get("active_focs", 0), "Active FOCs"),
        (snapshot.get("mapped_focs", 0), "Mapped FOCs"),
        (snapshot.get("active_clusters", 0), "Active Clusters"),
        (snapshot.get("active_themes", 0), "Active Themes"),
        (snapshot.get("active_dimensions", 0), "Current Dimensions"),
    ]
    widths = []
    for i in range(len(items)):
        widths.append(1)
        if i < len(items) - 1:
            widths.append(.13)
    cols = st.columns(widths)
    pos = 0
    for i, (n, label) in enumerate(items):
        with cols[pos]:
            st.markdown(
                f'<div class="flow-step"><div class="n">{n}</div><div class="t">{html.escape(label)}</div></div>',
                unsafe_allow_html=True,
            )
        pos += 1
        if i < len(items) - 1:
            with cols[pos]:
                st.markdown('<div class="flow-arrow">→</div>', unsafe_allow_html=True)
            pos += 1


def render_snapshot_header(snapshot: dict, filename: str | None = None, show_filename: bool = False):
    st.markdown('<div class="kicker">Excel MASTER → Python visual analytics</div>', unsafe_allow_html=True)
    title = snapshot.get("version") or "Current MASTER"
    decision = snapshot.get("decision")
    st.title(f"PMM Visual Analytics & Presentation Tool — {APP_VERSION}")

    parts = []
    if show_filename and filename:
        parts.append(f"Loaded: {filename}")
    if title:
        parts.append(str(title))
    if decision:
        parts.append(str(decision))
    if parts:
        st.caption(" · ".join(parts))

    st.markdown(
        '<div class="readonly-banner"><b>Read-only rule:</b> Excel MASTER is the only source of truth. '
        'This application reads the workbook only for the current analysis session and does not write analytical decisions back to it. '
        'Supervisor-facing presentation output does not include or expose the original Excel file.</div>',
        unsafe_allow_html=True,
    )


def render_executive_snapshot(frames: dict, snapshot: dict):
    st.subheader("Current Analytical Checkpoint")
    c1, c2, c3, c4 = st.columns(4)
    if snapshot.get("completed") is not None and snapshot.get("target"):
        c1.metric("Corpus checkpoint", f"{snapshot['completed']} / {snapshot['target']}", f"{snapshot['percent']:.1f}%")
    else:
        c1.metric("Corpus checkpoint", "Not recorded")
    c2.metric("Active FOCs", snapshot.get("active_focs", 0), f"{snapshot.get('mapped_focs',0)} mapped")
    c3.metric("Challenged FOCs", snapshot.get("challenged_focs", 0))
    c4.metric("Current dimensions", snapshot.get("active_dimensions", 0), f"{snapshot.get('stable_dimensions',0)} stable")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Active clusters", snapshot.get("active_clusters", 0), f"{snapshot.get('provisional_clusters',0)} provisional")
    c6.metric("Active themes", snapshot.get("active_themes", 0), f"{snapshot.get('stable_themes',0)} stable")
    c7.metric("Unthemed clusters", len(unthemed_active_clusters(frames)))
    c8.metric("Unassigned themes", len(unassigned_active_themes(frames, provisional_only=False)))

    st.markdown("#### Progressive abstraction")
    render_flow(snapshot)
    st.caption("This is an abstraction pathway, not a reduction score or an importance ranking. Challenged and residual evidence remains visible rather than being force-fitted.")

    st.markdown("#### Mapping and structural status")
    s1, s2 = st.columns(2)
    with s1:
        cur = current_mapping_rows(frames)
        if not cur.empty:
            fig = horizontal_count_bar(status_counts(cur, "Mapping_Status"), "Mapping_Status", title="FOC → Cluster mapping status")
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
    with s2:
        clusters = active_cluster_register(frames)
        fig = horizontal_count_bar(status_counts(clusters, "Cluster_Status"), "Cluster_Status", title="Active cluster status")
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Evidence breadth of current dimensions")
    breadth = current_dimension_evidence_summary(frames)
    if not breadth.empty:
        show = [c for c in ["Dimension_ID", "Candidate_Dimension_Name", "Dimension_Status", "Themes", "Clusters", "FOCs", "Studies"] if c in breadth.columns]
        st.dataframe(breadth[show], use_container_width=True, hide_index=True)
        st.caption("Evidence breadth is descriptive only. A larger number of studies, codes or clusters is not a validity coefficient and does not make one dimension more important than another.")

    if snapshot.get("next_action"):
        st.markdown(f'<div class="note-banner"><b>Workbook next action:</b> {html.escape(snapshot["next_action"])}</div>', unsafe_allow_html=True)


def render_structure_visuals(frames: dict):
    st.subheader("Higher-Order Structure")
    st.caption("Use these views for presentation. They visualize only structures already recorded in the Excel MASTER.")
    v1, v2 = st.tabs(["Sunburst", "Dimension → Theme flow"])
    with v1:
        fig = structure_sunburst(frames)
        if fig is None:
            st.info("No current hierarchy is available.")
        else:
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Residual/unassigned material is shown explicitly instead of being forced into a current dimension.")
    with v2:
        fig = dimension_theme_sankey(frames)
        if fig is None:
            st.info("No current Dimension → Theme links are available.")
        else:
            st.plotly_chart(fig, use_container_width=True)
            st.caption("Link width reflects current mapped FOC breadth only. It is not an importance weight.")

    st.markdown("#### Theme summary")
    ts = theme_summary_table(frames)
    if not ts.empty:
        st.dataframe(ts, use_container_width=True, hide_index=True, height=460)


def render_derivation_tree(frames: dict, supervisor: bool = True):
    st.subheader("Interactive Derivation Tree")
    st.caption("Click and expand the analytical chain without changing Excel: Dimension → Theme → Cluster → FOC → Meaning Unit → Study.")

    style = card_choice(
        "View",
        ["Interactive evidence tree", "Org-chart presentation"],
        key=f"tree_style_card_{supervisor}",
        descriptions={
            "Interactive evidence tree": "Compact expandable evidence view.",
            "Org-chart presentation": "Visual hierarchy with interactive cards and drill-down.",
        },
        default_index=1,
    )

    scope = card_choice(
        "Scope",
        ["Whole current structure", "One current Dimension", "Selected Themes"],
        key=f"tree_scope_card_{supervisor}",
        descriptions={
            "Whole current structure": "Display the complete current hierarchy.",
            "One current Dimension": "Focus on a single Candidate Dimension.",
            "Selected Themes": "Tick one or more Themes from a checkbox grid.",
        },
        default_index=0,
    )

    tree_data = None
    title = ""
    if scope == "Whole current structure":
        tree_data = build_candidate_stage_tree_data(frames, include_unassigned_themes=True)
        title = "Current PMM Dimension-Derivation Structure"
    elif scope == "One current Dimension":
        dims = active_dimensions(frames)
        if dims.empty:
            st.info("No current dimensions are recorded.")
            return
        ids = dims["Dimension_ID"].astype(str).tolist()
        labels = dict(zip(dims["Dimension_ID"].astype(str), dims["Candidate_Dimension_Name"].astype(str)))
        did = st.selectbox("Dimension", ids, format_func=lambda x: f"{x} — {labels.get(x,'')}", key=f"tree_dim_{supervisor}")
        tree_data = build_dimension_tree_data(frames, did)
        title = f"{did} — {labels.get(did,'')}"
    else:
        themes = active_themes(frames)
        if themes.empty:
            st.info("No active themes are recorded.")
            return

        ids = themes["Theme_ID"].astype(str).tolist()
        labels = dict(zip(themes["Theme_ID"].astype(str), themes["Working_Theme_Label"].astype(str)))
        statuses = dict(zip(themes["Theme_ID"].astype(str), themes["Theme_Status"].astype(str))) if "Theme_Status" in themes.columns else {}

        historical = retired_themes(frames)
        retired_ids = historical["Theme_ID"].astype(str).tolist() if not historical.empty else []
        retired_labels = (
            dict(zip(historical["Theme_ID"].astype(str), historical["Working_Theme_Label"].astype(str)))
            if not historical.empty else {}
        )
        retired_statuses = (
            dict(zip(historical["Theme_ID"].astype(str), historical["Theme_Status"].astype(str)))
            if not historical.empty and "Theme_Status" in historical.columns else {}
        )

        st.markdown("#### Themes")
        st.caption("Open the dropdown, then tick ✓ the Themes you want to display.")
        selected_current, selected_retired, show_retired = theme_dropdown_selector(
            ids,
            labels,
            key_prefix=f"theme_dropdown_{supervisor}",
            statuses=statuses,
            default_selected=ids[:1],
            retired_ids=retired_ids,
            retired_labels=retired_labels,
            retired_statuses=retired_statuses,
        )

        selected = selected_current + selected_retired
        if not selected:
            st.info("Tick at least one current or retired Theme to display the tree.")
            return

        tree_data = build_selected_themes_tree_data(
            frames,
            selected,
            include_retired=show_retired,
        )
        current_n = len(selected_current)
        retired_n = len(selected_retired)
        title = f"Selected Themes ({len(selected)} total · {current_n} current · {retired_n} retired audit)"

    if not tree_data:
        st.info("No tree data available for this scope.")
        return

    if style == "Interactive evidence tree":
        chart_html = tree_html(tree_data, title)
        components.html(chart_html, height=900, scrolling=True)
        with st.expander("Export this evidence tree"):
            if st.checkbox("Prepare downloadable HTML", key=f"prepare_evidence_export_{supervisor}"):
                data = tree_html(tree_data, title, standalone=True).encode("utf-8")
                st.download_button(
                    "Download this evidence tree as HTML",
                    data=data,
                    file_name="PMM_Evidence_Tree.html",
                    mime="text/html",
                )
    else:
        # Keep the browser DOM intentionally small. The whole-structure view is
        # an overview down to PCL; focused Dimension/Theme views go down to FOC.
        # Full Evidence → Study traceability remains available in the evidence tree.
        depth_limit = 3
        if scope == "Whole current structure":
            depth_limit = 3  # stage → dimension → theme → cluster
        elif scope in {"One current Dimension", "Selected Themes"}:
            depth_limit = 3  # root → theme → cluster → FOC (or dimension equivalent)

        display_tree = prune_tree_depth(tree_data, depth_limit)
        chart_html = org_chart_html(display_tree, title, max_depth=depth_limit)
        components.html(chart_html, height=900, scrolling=True)
        st.caption(
            "Performance mode: Org-chart renders only the hierarchy needed for this scope. "
            "Use Interactive evidence tree for Meaning Unit and Study-level drill-down."
        )
        with st.expander("Export this org chart"):
            if st.checkbox("Prepare downloadable HTML", key=f"prepare_org_export_{supervisor}"):
                data = org_chart_html(
                    display_tree,
                    title,
                    max_depth=depth_limit,
                    standalone=True,
                ).encode("utf-8")
                st.download_button(
                    "Download this org chart as HTML",
                    data=data,
                    file_name="PMM_Org_Chart.html",
                    mime="text/html",
                )


def render_traceability(frames: dict):
    st.subheader("Backward Traceability")
    st.caption("Demonstrate that every higher-order construct can be traced back to the exact source-verbatim Meaning Unit.")
    dims = active_dimensions(frames)
    themes = active_themes(frames)
    clusters = active_cluster_register(frames)
    if dims.empty or themes.empty or clusters.empty:
        st.info("The current workbook does not yet contain a complete higher-order chain.")
        return

    dlabels = dict(zip(dims["Dimension_ID"].astype(str), dims["Candidate_Dimension_Name"].astype(str)))
    did = st.selectbox("1. Dimension", dims["Dimension_ID"].astype(str).tolist(), format_func=lambda x: f"{x} — {dlabels.get(x,'')}", key="trace_dim")
    dmap = dimension_theme_map(frames)
    tids = dmap.loc[dmap["Dimension_ID"].astype(str).eq(did), "Theme_ID"].astype(str).tolist() if not dmap.empty else []
    if not tids:
        st.info("No Themes are linked to this dimension in the current MASTER.")
        return
    tlabels = dict(zip(themes["Theme_ID"].astype(str), themes["Working_Theme_Label"].astype(str)))
    tid = st.selectbox("2. Theme", tids, format_func=lambda x: f"{x} — {tlabels.get(x,'')}", key="trace_theme")
    trow = themes[themes["Theme_ID"].astype(str).eq(tid)].iloc[0]
    cids = split_ids(trow.get("Included_Cluster_IDs"), "PCL")
    clabels = dict(zip(clusters["Cluster_ID"].astype(str), clusters["Working_Cluster_Label"].astype(str)))
    cid = st.selectbox("3. Cluster", cids, format_func=lambda x: f"{x} — {clabels.get(x,'')}", key="trace_cluster")
    members = cluster_members(frames, cid)
    if members.empty:
        st.info("No current member records are linked to this cluster.")
        return
    code_ids = members["Code_ID"].dropna().astype(str).unique().tolist()
    code_label = dict(zip(members["Code_ID"].astype(str), members.get("First_Order_Code", pd.Series(dtype=str)).fillna("").astype(str)))
    code_id = st.selectbox("4. First-Order Code", code_ids, format_func=lambda x: f"{x} — {clipped(code_label.get(x,''), 105)}", key="trace_code")
    row = members[members["Code_ID"].astype(str).eq(code_id)].iloc[0]

    cols = st.columns(5)
    items = [
        ("Dimension", did, dlabels.get(did, "")),
        ("Theme", tid, tlabels.get(tid, "")),
        ("Cluster", cid, clabels.get(cid, "")),
        ("FOC", code_id, row.get("First_Order_Code", "")),
        ("Meaning Unit", row.get("Evidence_ID", ""), row.get("Meaning_Unit_Verbatim", "")),
    ]
    for c, (label, ident, text) in zip(cols, items):
        with c:
            st.markdown(f'<div class="lineage-box"><div class="lineage-title">{html.escape(label)}</div><b>{html.escape(str(ident))}</b><br><span class="small-muted">{html.escape(clipped(text, 180))}</span></div>', unsafe_allow_html=True)

    st.markdown("#### Source-near evidence")
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("**Meaning_Unit_Verbatim**")
        st.write(row.get("Meaning_Unit_Verbatim", ""))
        st.markdown("**Context_Verbatim**")
        st.write(row.get("Context_Verbatim", ""))
        st.markdown("**Original Author Term**")
        st.write(row.get("Original_Author_Term", ""))
    with e2:
        st.markdown("**Author Parent Construct**")
        st.write(row.get("Author_Parent_Construct", ""))
        st.markdown("**Author-defined relationship**")
        st.write(row.get("Author_Defined_Relationship", ""))
        st.markdown("**Study / page**")
        st.write(f"{row.get('Study_ID','')} · page {row.get('Printed_Page','')}")
        st.markdown("**Mapping rationale**")
        st.write(row.get("Mapping_Rationale", ""))


def render_open_decisions(frames: dict, compact: bool = False):
    st.subheader("Open / Residual Decisions")
    st.markdown(
        '<div class="review-banner"><b>Action rule:</b> Use this page to identify what still needs review. '
        'Make every analytical change in Excel MASTER, then reload the updated workbook here.</div>',
        unsafe_allow_html=True,
    )

    challenged = challenged_foc_table(frames)
    provisional = provisional_cluster_summary(frames)
    unthemed = unthemed_active_clusters(frames)
    unassigned = unassigned_active_themes(frames, provisional_only=False)
    cdims = challenged_dimensions(frames)

    a, b, c, d = st.columns(4)
    a.metric("Challenged FOCs", len(challenged))
    b.metric("Provisional clusters", len(provisional))
    c.metric("Unthemed clusters", len(unthemed))
    d.metric("Unassigned themes", len(unassigned))

    if not challenged.empty:
        st.markdown("#### Challenged FOCs")
        filters = st.columns(2)
        studies = sorted(challenged["Study_ID"].dropna().astype(str).unique().tolist()) if "Study_ID" in challenged.columns else []
        selected_study = filters[0].selectbox("Study filter", ["All"] + studies, key=f"open_study_{compact}")
        competitor_col = "Closest_Competing_Cluster" if "Closest_Competing_Cluster" in challenged.columns else None
        competitors = sorted(challenged[competitor_col].dropna().astype(str).unique().tolist()) if competitor_col else []
        selected_comp = filters[1].selectbox("Closest-cluster filter", ["All"] + competitors, key=f"open_comp_{compact}") if competitor_col else "All"
        shown = challenged.copy()
        if selected_study != "All":
            shown = shown[shown["Study_ID"].astype(str).eq(selected_study)]
        if competitor_col and selected_comp != "All":
            shown = shown[shown[competitor_col].astype(str).eq(selected_comp)]
        display_cols = [c for c in ["Code_ID", "Study_ID", "First_Order_Code", "Meaning_Unit_Verbatim", "Closest_Competing_Cluster", "Boundary_Rationale"] if c in shown.columns]
        st.dataframe(shown[display_cols], use_container_width=True, hide_index=True, height=340 if compact else 480)

    if not provisional.empty:
        st.markdown("#### Provisional clusters")
        show = [c for c in ["Cluster_ID", "Working_Cluster_Label", "Codes", "Studies", "Theme_IDs", "Audit_Sensitivity_Flag", "Audit_Disposition"] if c in provisional.columns]
        st.dataframe(provisional[show], use_container_width=True, hide_index=True)

    if not unassigned.empty:
        st.markdown("#### Active Themes not currently assigned to a Dimension")
        show = [c for c in ["Theme_ID", "Working_Theme_Label", "Included_Cluster_IDs", "Theme_Status", "Closest_Competing_Theme"] if c in unassigned.columns]
        st.dataframe(unassigned[show], use_container_width=True, hide_index=True)

    if not unthemed.empty:
        st.markdown("#### Active clusters not currently assigned to a Theme")
        show = [c for c in ["Cluster_ID", "Working_Cluster_Label", "Cluster_Status", "Codes", "Studies"] if c in unthemed.columns]
        st.dataframe(unthemed[show], use_container_width=True, hide_index=True)

    if not cdims.empty:
        st.markdown("#### Challenged / reopened dimensions")
        show = [c for c in ["Dimension_ID", "Candidate_Dimension_Name", "Supporting_Theme_IDs", "Dimension_Status"] if c in cdims.columns]
        st.dataframe(cdims[show], use_container_width=True, hide_index=True)


def render_sg2_review(frames: dict):
    st.subheader("SG2 Review Workload")
    st.caption("Read-only visual support for Excel-based FOC → Cluster review. It does not recommend or apply reassignments.")
    challenged = challenged_foc_table(frames)
    provisional = provisional_cluster_summary(frames)
    cur = current_mapping_rows(frames)

    k1, k2, k3 = st.columns(3)
    k1.metric("Current challenged FOCs", len(challenged))
    k2.metric("Current provisional clusters", len(provisional))
    k3.metric("Current mapped FOCs", int(cur.loc[cur["Mapping_Status"].isin(["Stable", "Provisional"]), "Code_ID"].nunique()) if not cur.empty else 0)

    c1, c2 = st.columns(2)
    with c1:
        if not cur.empty:
            fig = horizontal_count_bar(status_counts(cur, "Mapping_Status"), "Mapping_Status", title="Current mapping status")
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
    with c2:
        if not provisional.empty and "Codes" in provisional.columns:
            x = provisional[["Cluster_ID", "Codes"]].sort_values("Codes", ascending=False)
            fig = horizontal_count_bar(x.rename(columns={"Codes": "Count"}), "Cluster_ID", title="Provisional cluster size (mapped FOCs)")
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)

    render_open_decisions(frames, compact=False)


def render_higher_order_review(frames: dict):
    render_structure_visuals(frames)
    st.markdown("#### Current dimensions")
    dims = current_dimension_evidence_summary(frames)
    if not dims.empty:
        st.dataframe(dims, use_container_width=True, hide_index=True)
    st.markdown("#### Residual higher-order material")
    unassigned = unassigned_active_themes(frames, provisional_only=False)
    unthemed = unthemed_active_clusters(frames)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Unassigned active Themes**")
        if unassigned.empty:
            st.success("None")
        else:
            show = [c for c in ["Theme_ID", "Working_Theme_Label", "Theme_Status"] if c in unassigned.columns]
            st.dataframe(unassigned[show], use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**Unthemed active Clusters**")
        if unthemed.empty:
            st.success("None")
        else:
            show = [c for c in ["Cluster_ID", "Working_Cluster_Label", "Cluster_Status", "Codes", "Studies"] if c in unthemed.columns]
            st.dataframe(unthemed[show], use_container_width=True, hide_index=True)


def render_evidence_integrity(frames: dict):
    st.subheader("Evidence Integrity & MU Context Audit")
    audit = mu_context_audit_summary(frames)
    if not audit.get("total"):
        st.info("No 04A_MU_Context_Audit sheet was detected. This view is available in newer MASTER versions.")
        return
    total = audit["total"]
    changed_mu = audit["changed_mu"]
    changed_foc = audit["changed_foc"]
    q1, q2, q3 = st.columns(3)
    q1.metric("Audited active MUs", total)
    q2.metric("MU text changed/restored", len(changed_mu))
    q3.metric("FOC wording changed", len(changed_foc))

    c1, c2 = st.columns(2)
    with c1:
        fig = horizontal_count_bar(audit["risk"], "Risk_Tier", title="MU audit risk tier")
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
    with c2:
        dec = audit["decisions"].head(12)
        fig = horizontal_count_bar(dec, "Audit_Decision", title="Most frequent audit decisions")
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)

    if not changed_mu.empty:
        st.markdown("#### Meaning Units changed/restored by the current audit")
        show = [c for c in ["Audit_ID", "Code_ID", "Study_ID", "Risk_Tier", "Audit_Decision", "Pre_Audit_Meaning_Unit", "Post_Audit_Meaning_Unit", "Context_Action", "Audit_Rationale"] if c in changed_mu.columns]
        st.dataframe(changed_mu[show], use_container_width=True, hide_index=True, height=420)
    if not changed_foc.empty:
        st.markdown("#### FOC wording refinements")
        show = [c for c in ["Audit_ID", "Code_ID", "Study_ID", "Pre_Audit_First_Order_Code", "Post_Audit_First_Order_Code", "FOC_Impact", "SG2_Impact"] if c in changed_foc.columns]
        st.dataframe(changed_foc[show], use_container_width=True, hide_index=True)

    codes = frames.get("05_First_Order_Coding", pd.DataFrame())
    if not codes.empty and "Code_Fidelity_Status" in codes.columns:
        st.markdown("#### Code-fidelity status")
        fig = horizontal_count_bar(status_counts(codes, "Code_Fidelity_Status"), "Code_Fidelity_Status", title="First-order-code fidelity")
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)


def render_results_stability(frames: dict):
    st.subheader("Structural Stability & Recorded Audits")
    summary = structural_status_summary(frames)
    if not summary.empty:
        st.dataframe(summary, use_container_width=True, hide_index=True)
    audits = stability_audit_rows(frames)
    if audits.empty:
        st.info("No STAB40 audit rows were detected.")
    else:
        for _, r in audits.iterrows():
            with st.expander(f"{r.get('Audit_ID','')} — {r.get('Test','')}"):
                st.markdown(f"**Observed result:** {r.get('Observed_Result','')}")
                st.markdown(f"**Decision / interpretation:** {r.get('Decision_Interpretation','')}")
    st.caption("These are recorded workbook audit decisions. The visual tool does not turn them into statistical/psychometric validity scores.")


def render_data_quality(frames: dict, structure: list):
    st.subheader("Traceability & Data Quality Checks")
    checks = traceability_checks(frames)
    if not checks.empty:
        issue_total = int(checks["Issues"].sum())
        ok = int((checks["Issues"] == 0).sum())
        a, b = st.columns(2)
        a.metric("Checks with no detected issue", ok)
        b.metric("Total flagged structural links / IDs", issue_total)
        st.dataframe(checks, use_container_width=True, hide_index=True)
        st.caption("These checks are structural only. Zero flags does not prove semantic correctness of a code-to-cluster assignment.")
    with st.expander("Workbook structure"):
        st.dataframe(pd.DataFrame(structure), use_container_width=True, hide_index=True)


def render_published_supervisor(package: dict):
    snapshot = package.get("snapshot", {})
    tree = package.get("tree", {})
    retired_snapshot_themes = package.get("retired_themes", []) or []

    st.markdown('<div class="kicker">Supervisor presentation · sanitized snapshot</div>', unsafe_allow_html=True)
    st.title(f"PMM Visual Analytics & Presentation Tool — {APP_VERSION}")

    parts = []
    if snapshot.get("version"):
        parts.append(str(snapshot.get("version")))
    if snapshot.get("decision"):
        parts.append(str(snapshot.get("decision")))
    if parts:
        st.caption(" · ".join(parts))

    st.markdown(
        '<div class="readonly-banner"><b>Supervisor privacy rule:</b> This view does not contain the original Excel MASTER, '
        'its filename, Meaning Unit verbatim text, context verbatim text, or study/source nodes. '
        'It shows only the sanitized presentation structure down to First-Order Code level.</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["Overview", "Derivation Tree", "Dimensions"])

    with tabs[0]:
        st.subheader("Current Analytical Checkpoint")
        c1, c2, c3, c4 = st.columns(4)
        if snapshot.get("completed") is not None and snapshot.get("target"):
            pct = snapshot.get("percent")
            delta = f"{pct:.1f}%" if isinstance(pct, (int, float)) else None
            c1.metric("Corpus checkpoint", f"{snapshot['completed']} / {snapshot['target']}", delta)
        else:
            c1.metric("Corpus checkpoint", "Not recorded")
        c2.metric("Active FOCs", snapshot.get("active_focs", 0), f"{snapshot.get('mapped_focs', 0)} mapped")
        c3.metric("Active clusters", snapshot.get("active_clusters", 0), f"{snapshot.get('provisional_clusters', 0)} provisional")
        c4.metric("Current dimensions", snapshot.get("active_dimensions", 0), f"{snapshot.get('stable_dimensions', 0)} stable")

        c5, c6, c7 = st.columns(3)
        c5.metric("Challenged FOCs", snapshot.get("challenged_focs", 0))
        c6.metric("Active themes", snapshot.get("active_themes", 0), f"{snapshot.get('stable_themes', 0)} stable")
        c7.metric("Snapshot privacy", "Sanitized", "No Excel")

        st.markdown("#### Progressive abstraction")
        render_flow(snapshot)
        st.caption(
            "The presentation snapshot is refreshed from the researcher's latest compatible MASTER. "
            "The application is not tied to a workbook filename or version number."
        )

    with tabs[1]:
        st.subheader("Interactive Derivation Tree")
        st.caption("Presentation hierarchy: Candidate Dimension → Theme → Cluster → First-Order Code.")

        style = card_choice(
            "View",
            ["Interactive evidence tree", "Org-chart presentation"],
            key="published_tree_style_card",
            descriptions={
                "Interactive evidence tree": "Compact expandable evidence view.",
                "Org-chart presentation": "Visual hierarchy with interactive cards and drill-down.",
            },
            default_index=1,
        )
        scope = card_choice(
            "Scope",
            ["Whole current structure", "One current Dimension", "Selected Themes"],
            key="published_tree_scope_card",
            descriptions={
                "Whole current structure": "Display the complete published hierarchy.",
                "One current Dimension": "Focus on one Candidate Dimension.",
                "Selected Themes": "Tick one or more Themes from a checkbox grid.",
            },
            default_index=0,
        )

        chosen_tree = tree
        title = "Current PMM Dimension-Derivation Structure"

        if scope == "One current Dimension":
            dims = nodes_of_type(tree, "dimension")
            if not dims:
                st.info("No current dimensions are available in the published snapshot.")
                return
            ids = [str(d.get("id", "")) for d in dims]
            labels = {str(d.get("id", "")): str(d.get("label", "")) for d in dims}
            did = st.selectbox(
                "Dimension",
                ids,
                format_func=lambda x: f"{x} — {labels.get(x, '')}",
                key="published_dim",
            )
            chosen_tree = subtree_by_id(tree, did) or tree
            title = f"{did} — {labels.get(did, '')}"

        elif scope == "Selected Themes":
            themes = nodes_of_type(tree, "theme")
            if not themes:
                st.info("No themes are available in the published snapshot.")
                return

            ids = [str(t.get("id", "")) for t in themes]
            labels = {str(t.get("id", "")): str(t.get("label", "")) for t in themes}
            statuses = {str(t.get("id", "")): str(t.get("status", "")) for t in themes}

            rids = [str(t.get("id", "")) for t in retired_snapshot_themes]
            rlabels = {
                str(t.get("id", "")): str(t.get("label", ""))
                for t in retired_snapshot_themes
            }
            rstatuses = {
                str(t.get("id", "")): str(t.get("status", ""))
                for t in retired_snapshot_themes
            }

            st.markdown("#### Themes")
            st.caption("Open the dropdown, then tick ✓ the Themes you want to display.")
            selected_current, selected_retired, show_retired = theme_dropdown_selector(
                ids,
                labels,
                key_prefix="published_theme_dropdown",
                statuses=statuses,
                default_selected=ids[:1],
                retired_ids=rids,
                retired_labels=rlabels,
                retired_statuses=rstatuses,
            )

            selected = selected_current + selected_retired
            if not selected:
                st.info("Tick at least one current or retired Theme to display the tree.")
                return

            chosen_tree = selected_nodes_tree(
                tree,
                selected_current,
                "theme",
                f"Selected descriptive themes ({len(selected)})",
            )
            if selected_retired:
                retired_lookup = {
                    str(t.get("id", "")): t for t in retired_snapshot_themes
                }
                chosen_tree["children"].extend(
                    retired_lookup[tid] for tid in selected_retired if tid in retired_lookup
                )
                chosen_tree["meta"]["Historical audit"] = (
                    f"{len(selected_retired)} retired Theme(s) shown for audit history only."
                )

            title = (
                f"Selected Themes ({len(selected)} total · "
                f"{len(selected_current)} current · {len(selected_retired)} retired audit)"
            )

        if style == "Interactive evidence tree":
            components.html(tree_html(chosen_tree, title), height=900, scrolling=True)
        else:
            components.html(org_chart_html(chosen_tree, title, max_depth=99), height=900, scrolling=True)

        st.caption(
            "Search by IDs such as PCL-038, THM-008 or DIM-001. "
            "Source-near Meaning Units are intentionally excluded from this supervisor snapshot."
        )

    with tabs[2]:
        st.subheader("Current Candidate Dimensions")
        rows = dimension_summary(tree)
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No current dimensions are available in the published snapshot.")


def render_supervisor_mode(frames: dict, snapshot: dict):
    share_html = supervisor_share_html(frames, snapshot).encode("utf-8")
    st.download_button(
        "Download Doctor/Supervisor Share HTML (no Excel)",
        data=share_html,
        file_name="PMM_Supervisor_Presentation.html",
        mime="text/html",
        help="Creates a self-contained read-only presentation file. The original Excel MASTER is not included.",
        use_container_width=False,
    )
    st.caption(
        "Safe sharing option: send this HTML file to the supervisor/doctor instead of the Excel MASTER. "
        "The file is read-only and includes only the presentation evidence rendered by the application."
    )
    tabs = st.tabs(["Executive Snapshot", "Derivation Tree", "Structure Visuals", "Traceability", "Open Decisions"])
    with tabs[0]:
        render_executive_snapshot(frames, snapshot)
    with tabs[1]:
        render_derivation_tree(frames, supervisor=True)
    with tabs[2]:
        render_structure_visuals(frames)
    with tabs[3]:
        render_traceability(frames)
    with tabs[4]:
        render_open_decisions(frames, compact=True)


def render_researcher_mode(frames: dict, snapshot: dict, structure: list):
    """Render only the active researcher section.

    Streamlit tabs execute every tab body on every rerun. With a large MASTER
    that made a Theme click recompute all eight analytical pages. A single
    horizontal section selector keeps the familiar navigation while executing
    only the page the researcher is actually viewing.
    """
    sections = [
        "Current State",
        "SG2 Review",
        "Themes & Dimensions",
        "Evidence Integrity",
        "Derivation Tree",
        "Traceability",
        "Stability",
        "Data Quality",
    ]
    section = st.radio(
        "Researcher section",
        sections,
        horizontal=True,
        key="researcher_active_section",
        label_visibility="collapsed",
    )
    st.divider()

    if section == "Current State":
        render_executive_snapshot(frames, snapshot)
    elif section == "SG2 Review":
        render_sg2_review(frames)
    elif section == "Themes & Dimensions":
        render_higher_order_review(frames)
    elif section == "Evidence Integrity":
        render_evidence_integrity(frames)
    elif section == "Derivation Tree":
        render_derivation_tree(frames, supervisor=False)
    elif section == "Traceability":
        render_traceability(frames)
    elif section == "Stability":
        render_results_stability(frames)
    else:
        render_data_quality(frames, structure)


def _query_param(name: str, default: str = "") -> str:
    value = st.query_params.get(name, default)
    if isinstance(value, list):
        value = value[0] if value else default
    return str(value or default)


def main():
    view = _query_param("view", "supervisor").strip().lower()
    researcher_access = view == "researcher"

    if not researcher_access:
        with st.sidebar:
            st.markdown("## PMM Visual Tool")
            st.caption(APP_VERSION)
            st.success("Supervisor view")
            st.caption("Sanitized presentation only · no Excel upload or workbook access")

        package = load_supervisor_snapshot()
        if package is None:
            st.title(f"PMM Visual Analytics & Presentation Tool — {APP_VERSION}")
            st.info("No supervisor presentation snapshot has been published yet.")
            return

        render_published_supervisor(package)
        return

    private_key = _query_param("key", "")
    persistence_enabled = token_matches(private_key)
    uploader_version = int(st.session_state.get("master_uploader_version", 0))
    cached_entry = load_cached_master() if persistence_enabled else None

    with st.sidebar:
        st.markdown("## PMM Visual Tool")
        st.caption(APP_VERSION)
        st.info("Researcher workspace")

        if persistence_enabled:
            st.success("Private refresh-safe cache enabled")
            st.caption(
                "The latest validated MASTER can survive browser Refresh temporarily. "
                "It is stored outside GitHub and is never exposed in Supervisor view."
            )
        else:
            st.caption(
                "Standard researcher link: manual upload works normally, but the MASTER is not retained after browser Refresh."
            )

        master_upload = st.file_uploader(
            "Upload current Excel MASTER (.xlsx)",
            type=["xlsx"],
            key=f"master_xlsx_{uploader_version}",
        )

        if persistence_enabled and cached_entry is not None:
            cached_name, _, cached_meta = cached_entry
            size_mb = float(cached_meta.get("size_bytes", 0)) / (1024 * 1024)
            st.success(f"Cached MASTER: {cached_name}")
            st.caption(f"Temporary private cache · {size_mb:.1f} MB · not stored in GitHub")
            if st.button("Forget cached MASTER", use_container_width=True, type="secondary"):
                clear_cached_master()
                st.session_state["master_uploader_version"] = uploader_version + 1
                cached_master_load.clear()
                st.rerun()

        display_mode = st.radio(
            "Display mode",
            ["Researcher Visual Analytics", "Supervisor Preview"],
            index=0,
        )
        st.markdown("---")
        st.success("Read-only: no write-back to Excel")
        st.caption("Upload any current compatible MASTER. The app is not tied to a filename or version.")

    master_name = None
    master_bytes = None
    uploaded_now = master_upload is not None

    if uploaded_now:
        master_name = master_upload.name
        master_bytes = master_upload.getvalue()
    elif persistence_enabled and cached_entry is not None:
        master_name, master_bytes, _ = cached_entry

    if master_bytes is None:
        st.title(f"PMM Visual Analytics & Presentation Tool — {APP_VERSION}")
        st.markdown(
            '<div class="readonly-banner"><b>Flexible researcher workflow:</b> Excel MASTER remains the analytical source of truth. '
            'Upload the latest compatible MASTER here; its filename and version may change freely.</div>',
            unsafe_allow_html=True,
        )
        if persistence_enabled:
            st.info(
                "Upload the current PMM MASTER once. After it passes validation, browser Refresh will reuse the temporary private copy."
            )
        else:
            st.info("Upload the current PMM MASTER workbook from the sidebar to begin.")
        return

    try:
        frames, structure = cached_master_load(master_bytes)
    except Exception as exc:
        st.error(f"Could not read workbook: {exc}")
        return

    issues = validate_master(frames)
    if issues:
        st.error("This workbook does not match the expected PMM MASTER structure.")
        for issue in issues:
            st.write(f"- {issue}")
        if uploaded_now and persistence_enabled and cached_entry is not None:
            st.info("The previously cached validated MASTER was not replaced.")
        return

    if uploaded_now and persistence_enabled:
        meta = save_cached_master(master_name, master_bytes)
        cached_entry = (master_name, master_bytes, meta)

    snapshot = master_snapshot(frames)
    render_snapshot_header(
        snapshot,
        master_name,
        show_filename=True,
    )

    if persistence_enabled:
        st.caption(
            "Refresh-safe researcher session is active. This temporary server cache may be cleared by a Streamlit restart/redeploy or by the Forget cached MASTER button."
        )

    sanitized = cached_supervisor_snapshot_bytes(master_bytes)
    with st.sidebar:
        st.download_button(
            "Download sanitized supervisor snapshot",
            data=sanitized,
            file_name="supervisor_snapshot.json",
            mime="application/json",
            help="Contains presentation structure only; no Excel file, filename, Meaning Units, context verbatim, or study/source nodes.",
            use_container_width=True,
        )

    if display_mode == "Supervisor Preview":
        package = build_supervisor_snapshot(frames)
        render_published_supervisor(package)
    else:
        render_researcher_mode(frames, snapshot, structure)


if __name__ == "__main__":
    main()
