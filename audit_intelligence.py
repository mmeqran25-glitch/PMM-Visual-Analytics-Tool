from __future__ import annotations

from io import BytesIO
import re
from typing import Any, Dict, List, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from defense_mode import render_defense_mode, render_measurement_readiness
from item_pool_prep import render_item_pool_preparation
from item_drafting import render_item_drafting_workspace

from master_utils import (
    active_dimensions,
    active_themes,
    current_mapping_rows,
    split_ids,
)

AUDIT_INTELLIGENCE_VERSION = "v0.17.3-audit"

_ID_RE = re.compile(r"\b(?:(?:DIM|THM|PCL|PMAP|CD|EV)-[A-Za-z0-9-]+|SR\d{3,})\b", re.IGNORECASE)
_DEC_RE = re.compile(r"\bDEC-\d{3}\b", re.IGNORECASE)


def _s(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _exact_id_pattern(entity: str) -> str:
    return rf"(?<![A-Za-z0-9-]){re.escape(entity)}(?![A-Za-z0-9-])"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy().dropna(how="all")
    out.columns = [_s(c) for c in out.columns]
    return out


def _guess_header(raw: pd.DataFrame, max_rows: int = 18) -> int:
    """Choose a likely table header row for historical audit sheets."""
    if raw.empty:
        return 0
    tokens = {
        "decision_id", "audit_id", "code_id", "evidence_id", "study_id",
        "cluster_id", "theme_id", "dimension_id", "original_position",
        "archived_sheet", "mapping_id", "status", "decision", "date",
    }
    best_i, best_score = 0, -1.0
    for i in range(min(max_rows, len(raw))):
        vals = [_s(v) for v in raw.iloc[i].tolist()]
        nonempty = [v for v in vals if v]
        if not nonempty:
            continue
        normalized = {re.sub(r"[^a-z0-9]+", "_", v.lower()).strip("_") for v in nonempty}
        hits = len(tokens & normalized)
        unique = len(set(nonempty))
        score = len(nonempty) + hits * 8 + unique * 0.05
        if score > best_score:
            best_i, best_score = i, score
    return best_i


def load_audit_archive(file_bytes: bytes) -> Tuple[Dict[str, pd.DataFrame], List[Dict[str, Any]]]:
    """Load the optional historical Audit Archive read-only."""
    xls = pd.ExcelFile(BytesIO(file_bytes), engine="openpyxl")
    frames: Dict[str, pd.DataFrame] = {}
    structure: List[Dict[str, Any]] = []
    for sheet in xls.sheet_names:
        try:
            raw = pd.read_excel(xls, sheet_name=sheet, header=None)
            header_i = _guess_header(raw)
            if header_i >= len(raw):
                df = pd.DataFrame()
            else:
                header = [_s(v) or f"Unnamed_{j}" for j, v in enumerate(raw.iloc[header_i].tolist())]
                df = raw.iloc[header_i + 1 :].copy()
                df.columns = header
                df = _clean(df)
            frames[sheet] = df
            structure.append({"Sheet": sheet, "Rows": int(len(df)), "Header_Row": int(header_i + 1)})
        except Exception as exc:
            frames[sheet] = pd.DataFrame()
            structure.append({"Sheet": sheet, "Rows": 0, "Header_Row": None, "Error": str(exc)})
    return frames, structure


def _decision_log(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = _clean(frames.get("11_Decision_Log", pd.DataFrame()))
    if df.empty:
        return df
    if "Decision_ID" not in df.columns:
        for c in df.columns:
            if _s(c).lower() == "decision_id":
                df = df.rename(columns={c: "Decision_ID"})
                break
    if "Decision_ID" not in df.columns:
        return pd.DataFrame()
    out = df[df["Decision_ID"].astype(str).str.match(r"^DEC-\d{3}$", case=False, na=False)].copy()
    if "Date" in out.columns:
        out["_DateSort"] = pd.to_datetime(out["Date"], errors="coerce")
    else:
        out["_DateSort"] = pd.NaT
    out["_DecNum"] = pd.to_numeric(out["Decision_ID"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    return out.sort_values(["_DateSort", "_DecNum"], na_position="last")


def _latest_decision_id(frames: Dict[str, pd.DataFrame]) -> str:
    d = _decision_log(frames)
    if d.empty:
        return "Not detected"
    return _s(d.iloc[-1]["Decision_ID"])


def _archive_index(archive_frames: Dict[str, pd.DataFrame] | None) -> pd.DataFrame:
    if not archive_frames:
        return pd.DataFrame()
    return _clean(archive_frames.get("00_AUDIT_ARCHIVE_INDEX", pd.DataFrame()))


def _find_entity_occurrences(
    frames: Dict[str, pd.DataFrame] | None,
    entity_id: str,
    source: str,
) -> pd.DataFrame:
    if not frames or not entity_id:
        return pd.DataFrame(columns=["Source", "Sheet", "Row", "Matched_Columns", "Context"])
    entity = entity_id.strip().upper()
    pattern = _exact_id_pattern(entity)
    rows: List[Dict[str, Any]] = []
    for sheet, df in frames.items():
        if sheet.startswith("__") or df is None or df.empty:
            continue
        text_df = df.astype(str)
        try:
            hitmask = text_df.apply(
                lambda col: col.str.contains(pattern, case=False, na=False, regex=True)
            ).any(axis=1)
        except Exception:
            continue
        for idx in df.index[hitmask]:
            matched_cols = []
            context_parts = []
            for col in df.columns:
                val = _s(df.at[idx, col])
                if re.search(pattern, val, flags=re.IGNORECASE):
                    matched_cols.append(_s(col))
                if val and len(context_parts) < 4:
                    context_parts.append(f"{_s(col)}: {val[:220]}")
            rows.append({
                "Source": source,
                "Sheet": sheet,
                "Row": int(idx) + 1 if isinstance(idx, (int, float)) and not pd.isna(idx) else _s(idx),
                "Matched_Columns": ", ".join(matched_cols),
                "Context": " | ".join(context_parts),
            })
    return pd.DataFrame(rows)


def _extract_entity_ids(frames: Dict[str, pd.DataFrame]) -> List[str]:
    found: List[str] = []
    preferred = [
        ("08_Candidate_Dimensions", "Dimension_ID"),
        ("07_Descriptive_Themes", "Theme_ID"),
        ("06A_Cluster_Register", "Cluster_ID"),
        ("05_First_Order_Coding", "Code_ID"),
        ("04_Verbatim_Evidence", "Evidence_ID"),
        ("01_Source_Register", "Study_ID"),
    ]
    for sheet, col in preferred:
        df = frames.get(sheet, pd.DataFrame())
        if not df.empty and col in df.columns:
            for value in df[col].dropna().astype(str):
                for m in _ID_RE.findall(value):
                    if m.upper() not in found:
                        found.append(m.upper())
    return found


def _entity_type(entity_id: str) -> str:
    x = entity_id.upper()
    if x.startswith("DIM-"):
        return "Dimension"
    if x.startswith("THM-"):
        return "Theme"
    if x.startswith("PCL-"):
        return "Cluster"
    if x.startswith("PMAP-") or x.startswith("CD-"):
        return "First-Order Code / Coding record"
    if x.startswith("EV-"):
        return "Evidence"
    if re.match(r"^SR\d{3,}$", x):
        return "Source / Study record"
    return "Entity"


def _edge_rows(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    edges: List[Dict[str, str]] = []

    maps = current_mapping_rows(frames)
    if not maps.empty and {"Code_ID", "Cluster_ID"}.issubset(maps.columns):
        for _, r in maps.iterrows():
            code, pcl = _s(r.get("Code_ID")), _s(r.get("Cluster_ID"))
            if code and pcl:
                edges.append({"From": code, "To": pcl, "Relationship": "FOC → Cluster"})

    themes = active_themes(frames)
    if not themes.empty and {"Theme_ID", "Included_Cluster_IDs"}.issubset(themes.columns):
        for _, r in themes.iterrows():
            tid = _s(r.get("Theme_ID"))
            for pcl in split_ids(r.get("Included_Cluster_IDs"), "PCL"):
                edges.append({"From": pcl, "To": tid, "Relationship": "Cluster → Theme"})

    dims = active_dimensions(frames)
    if not dims.empty and {"Dimension_ID", "Supporting_Theme_IDs"}.issubset(dims.columns):
        for _, r in dims.iterrows():
            did = _s(r.get("Dimension_ID"))
            for tid in split_ids(r.get("Supporting_Theme_IDs"), "THM"):
                edges.append({"From": tid, "To": did, "Relationship": "Theme → Dimension"})

    return pd.DataFrame(edges).drop_duplicates() if edges else pd.DataFrame(
        columns=["From", "To", "Relationship"]
    )


def _lineage_neighborhood(edges: pd.DataFrame, entity_id: str) -> pd.DataFrame:
    if edges.empty or not entity_id:
        return edges.iloc[0:0].copy()
    selected = {entity_id.upper()}
    work = edges.copy()
    work["FromU"] = work["From"].astype(str).str.upper()
    work["ToU"] = work["To"].astype(str).str.upper()
    for _ in range(4):
        mask = work["FromU"].isin(selected) | work["ToU"].isin(selected)
        near = work.loc[mask]
        grown = selected | set(near["FromU"]) | set(near["ToU"])
        if grown == selected:
            break
        selected = grown
    out = work[work["FromU"].isin(selected) & work["ToU"].isin(selected)].copy()
    return out[["From", "To", "Relationship"]].drop_duplicates()


def _sankey(edges: pd.DataFrame, focus: str) -> go.Figure | None:
    if edges.empty:
        return None
    nodes = list(dict.fromkeys(
        edges["From"].astype(str).tolist() + edges["To"].astype(str).tolist()
    ))
    if len(nodes) > 120:
        return None
    idx = {n: i for i, n in enumerate(nodes)}
    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(label=nodes, pad=14, thickness=16),
            link=dict(
                source=[idx[x] for x in edges["From"].astype(str)],
                target=[idx[x] for x in edges["To"].astype(str)],
                value=[1] * len(edges),
                label=edges["Relationship"].astype(str).tolist(),
            ),
        )
    )
    fig.update_layout(
        title=f"Structural lineage around {focus}",
        height=max(520, min(900, 420 + len(nodes) * 5)),
    )
    return fig


def _dimension_record(
    frames: Dict[str, pd.DataFrame],
    dimension_id: str,
) -> pd.Series | None:
    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        return None
    rows = dims[dims["Dimension_ID"].astype(str).str.upper().eq(dimension_id.upper())]
    if rows.empty:
        return None
    return rows.iloc[-1]


def _find_col(
    row: pd.Series,
    candidates: List[str],
    contains: List[str] | None = None,
) -> str:
    contains = contains or []
    for c in candidates:
        if c in row.index and _s(row.get(c)):
            return _s(row.get(c))
    for c in row.index:
        cl = _s(c).lower()
        if any(token.lower() in cl for token in contains) and _s(row.get(c)):
            return _s(row.get(c))
    return ""


def _dimension_evidence_counts(
    frames: Dict[str, pd.DataFrame],
    dimension_id: str,
) -> Dict[str, int]:
    edges = _edge_rows(frames)
    if edges.empty:
        return {"themes": 0, "clusters": 0, "focs": 0, "sources": 0}
    near = _lineage_neighborhood(edges, dimension_id)
    themes = set(
        near.loc[
            near["To"].astype(str).str.upper().eq(dimension_id.upper()), "From"
        ].astype(str)
    )
    clusters = set(near.loc[near["To"].isin(themes), "From"].astype(str)) if themes else set()
    focs = set(near.loc[near["To"].isin(clusters), "From"].astype(str)) if clusters else set()
    sources: set[str] = set()
    coding = frames.get("05_First_Order_Coding", pd.DataFrame())
    if (
        not coding.empty
        and {"Code_ID", "Study_ID"}.issubset(coding.columns)
        and focs
    ):
        hit = coding[coding["Code_ID"].astype(str).isin(focs)]
        sources = set(hit["Study_ID"].dropna().astype(str))
    return {
        "themes": len(themes),
        "clusters": len(clusters),
        "focs": len(focs),
        "sources": len(sources),
    }


def _render_overview(
    frames: Dict[str, pd.DataFrame],
    archive_frames: Dict[str, pd.DataFrame] | None,
) -> None:
    dec = _decision_log(frames)
    idx = _archive_index(archive_frames)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current decision", _latest_decision_id(frames))
    c2.metric("Decision-log records", len(dec))
    c3.metric(
        "Historical audit sheets",
        max(
            0,
            len(archive_frames or {})
            - (1 if archive_frames and "00_AUDIT_ARCHIVE_INDEX" in archive_frames else 0),
        ),
    )
    c4.metric("Archive link", "Connected" if archive_frames else "Optional")

    st.markdown(
        '<div class="note-banner"><b>Source-of-truth rule:</b> Current analytical state is read from the operational MASTER. '
        'The Audit Archive is used only to reconstruct historical adjudications and does not create a new analytical vote.</div>',
        unsafe_allow_html=True,
    )

    st.markdown("#### Audit coverage by historical category")
    if not idx.empty and "Archive_Category" in idx.columns:
        cov = (
            idx["Archive_Category"]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
            .rename_axis("Audit category")
            .reset_index(name="Archived sheets")
        )
        st.dataframe(cov, use_container_width=True, hide_index=True)
    elif archive_frames:
        cats = []
        for name in archive_frames:
            if name == "00_AUDIT_ARCHIVE_INDEX":
                continue
            if name.startswith("04"):
                cat = "Evidence / source fidelity"
            elif name.startswith("06"):
                cat = "SG2 clustering / assignment"
            elif name.startswith("07"):
                cat = "SG3 theme audit"
            elif name.startswith("08"):
                cat = "SG4 dimension / higher-order"
            else:
                cat = "Other historical control"
            cats.append(cat)
        cov = (
            pd.Series(cats)
            .value_counts()
            .rename_axis("Audit category")
            .reset_index(name="Archived sheets")
        )
        st.dataframe(cov, use_container_width=True, hide_index=True)
    else:
        st.info(
            "Upload the optional Audit Archive in the sidebar to add historical "
            "audit-sheet coverage and occurrence tracing."
        )

    st.markdown("#### Current methodological boundary")
    st.write(
        "The current platform can document construct derivation, boundary adjudication, "
        "evidence provenance, and pre-item measurement readiness. It must not present "
        "qualitative closure as psychometric validation or a validated reflective factor structure."
    )


def _render_timeline(frames: Dict[str, pd.DataFrame]) -> None:
    dec = _decision_log(frames)
    if dec.empty:
        st.warning("No parseable Decision Log was found in the current MASTER.")
        return

    st.markdown("#### Decision Intelligence Timeline")
    stages = sorted([
        x for x in dec.get("Stage", pd.Series(dtype=str)).dropna().astype(str).unique() if x
    ])
    c1, c2 = st.columns([2, 1])
    query = c1.text_input(
        "Search decisions",
        placeholder="DEC-589, boundary, merge, source fidelity ...",
        key="audit_dec_search",
    )
    stage = c2.selectbox("Stage", ["All"] + stages, key="audit_dec_stage")

    shown = dec.copy()
    if stage != "All" and "Stage" in shown.columns:
        shown = shown[shown["Stage"].astype(str).eq(stage)]
    if query:
        q = re.escape(query.strip())
        textcols = [
            c for c in [
                "Decision_ID", "Stage", "Decision", "Reason",
                "Impact_on_Analysis", "Status", "Notes",
            ] if c in shown.columns
        ]
        if textcols:
            mask = shown[textcols].astype(str).apply(
                lambda col: col.str.contains(q, case=False, na=False)
            ).any(axis=1)
            shown = shown[mask]

    display = [
        c for c in [
            "Decision_ID", "Date", "Stage", "Decision", "Reason",
            "Impact_on_Analysis", "Status", "Notes",
        ] if c in shown.columns
    ]
    st.dataframe(shown[display].iloc[::-1], use_container_width=True, hide_index=True, height=520)

    ids = shown["Decision_ID"].astype(str).tolist()
    if ids:
        selected = st.selectbox("Open one decision", ids[::-1], key="audit_dec_open")
        row = shown[shown["Decision_ID"].astype(str).eq(selected)].iloc[-1]
        st.markdown(f"### {selected}")
        for label, col in [
            ("Stage", "Stage"),
            ("Decision", "Decision"),
            ("Why it mattered", "Reason"),
            ("Analytical effect", "Impact_on_Analysis"),
            ("Status", "Status"),
            ("Notes", "Notes"),
        ]:
            value = _s(row.get(col))
            if value:
                st.markdown(f"**{label}:** {value}")


def _render_entity_history(
    frames: Dict[str, pd.DataFrame],
    archive_frames: Dict[str, pd.DataFrame] | None,
) -> None:
    ids = _extract_entity_ids(frames)
    if not ids:
        st.info("No traceable entity IDs were detected.")
        return

    c1, c2 = st.columns([1.2, 2.8])
    prefix = c1.selectbox(
        "Entity family",
        ["All", "DIM", "THM", "PCL", "PMAP/CD", "EV", "SR"],
        key="audit_entity_family",
    )
    filtered = ids
    if prefix == "PMAP/CD":
        filtered = [x for x in ids if x.startswith("PMAP-") or x.startswith("CD-")]
    elif prefix == "SR":
        filtered = [x for x in ids if re.match(r"^SR\d{3,}$", x)]
    elif prefix != "All":
        filtered = [x for x in ids if x.startswith(prefix + "-")]

    entity = c2.selectbox("Entity", filtered, key="audit_entity_select") if filtered else ""
    if not entity:
        return

    st.markdown(f"### {entity} · {_entity_type(entity)}")
    cur = _find_entity_occurrences(frames, entity, "Current MASTER")
    hist = (
        _find_entity_occurrences(archive_frames, entity, "Audit Archive")
        if archive_frames else pd.DataFrame()
    )
    occ = pd.concat([cur, hist], ignore_index=True) if not hist.empty else cur

    k1, k2, k3 = st.columns(3)
    k1.metric("Current MASTER occurrences", len(cur))
    k2.metric("Historical archive occurrences", len(hist))
    k3.metric("Sheets touched", int(occ["Sheet"].nunique()) if not occ.empty else 0)

    if not occ.empty:
        st.dataframe(occ, use_container_width=True, hide_index=True, height=430)
    else:
        st.info("No occurrences were found beyond the entity register itself.")

    dec = _decision_log(frames)
    if not dec.empty:
        textcols = [c for c in dec.columns if not c.startswith("_")]
        mask = dec[textcols].astype(str).apply(
            lambda col: col.str.contains(_exact_id_pattern(entity), case=False, na=False, regex=True)
        ).any(axis=1)
        linked = dec[mask]
        st.markdown("#### Linked DEC records")
        if linked.empty:
            st.caption(
                "No Decision Log row names this entity explicitly. Structural lineage below "
                "can still show its current placement."
            )
        else:
            cols = [
                c for c in [
                    "Decision_ID", "Date", "Stage", "Decision",
                    "Impact_on_Analysis", "Status",
                ] if c in linked.columns
            ]
            st.dataframe(linked[cols], use_container_width=True, hide_index=True)

    st.markdown("#### Current structural lineage")
    edges = _edge_rows(frames)
    near = _lineage_neighborhood(edges, entity)
    if near.empty:
        st.caption(
            "This entity does not participate in the current FOC → PCL → Theme → Dimension "
            "edge set, or its link is intentionally unresolved."
        )
    else:
        fig = _sankey(near, entity)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(near, use_container_width=True, hide_index=True)


def _render_dimension_defense(frames: Dict[str, pd.DataFrame]) -> None:
    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        st.info("No current Candidate Dimensions are available.")
        return

    names = (
        dims["Candidate_Dimension_Name"]
        if "Candidate_Dimension_Name" in dims.columns
        else pd.Series("", index=dims.index)
    )
    labels = dict(zip(dims["Dimension_ID"].astype(str), names.astype(str)))
    dids = dims["Dimension_ID"].astype(str).tolist()
    did = st.selectbox(
        "Dimension",
        dids,
        format_func=lambda x: f"{x} — {labels.get(x, '')}",
        key="audit_dim_defense",
    )
    row = _dimension_record(frames, did)
    if row is None:
        return

    name = _s(row.get("Candidate_Dimension_Name"))
    st.markdown(f"### {did} — {name}")
    counts = _dimension_evidence_counts(frames, did)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Themes", counts["themes"])
    c2.metric("Clusters", counts["clusters"])
    c3.metric("FOCs", counts["focs"])
    c4.metric("Source records", counts["sources"])

    definition = _find_col(
        row,
        ["Analytical_Definition", "Construct_Definition", "Definition"],
        ["definition"],
    )
    required = _find_col(
        row,
        ["Required_Facets", "Required_Facets_DEC589", "Measurement_Required_Facets"],
        ["required", "facet"],
    )
    exclusions = _find_col(
        row,
        ["Exclusions", "Exclusion_Boundary", "Exclude_Contamination", "Contamination_Risks"],
        ["exclu", "contamin"],
    )
    applicability = _find_col(
        row,
        ["Applicability_Rule", "Applicability", "Measurement_Applicability"],
        ["applicab"],
    )
    measurement = _find_col(
        row,
        ["Measurement_Form", "Measurement_Architecture", "Construct_Form"],
        ["measurement", "composite"],
    )
    refs = " ".join(_DEC_RE.findall(" | ".join(_s(v) for v in row.values)))

    if definition:
        st.markdown("#### Construct definition")
        st.write(definition)

    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown("#### Required / included content")
        st.write(
            required
            or _s(row.get("Supporting_Theme_IDs"))
            or "Not explicitly recorded in a dedicated field."
        )
        st.markdown("#### Applicability rule")
        st.write(
            applicability
            or "Use the current source-grounded inclusion boundary recorded for this Dimension."
        )

    with c_right:
        st.markdown("#### Exclusions / contamination boundary")
        st.write(
            exclusions
            or "No dedicated exclusion field detected; inspect linked boundary decisions "
               "and current Theme/PCL membership."
        )
        st.markdown("#### Measurement form")
        st.write(
            measurement
            or "Pre-item content-domain specification; do not infer psychometric factor "
               "structure from qualitative closure."
        )

    if refs:
        st.caption(f"Decision references detected on this record: {refs}")

    st.markdown("#### Claim boundary")
    claims = pd.DataFrame({
        "Can claim now": [
            "Literature-derived content domain",
            "Traceable FOC → PCL → Theme → Dimension provenance",
            "Qualitatively adjudicated construct boundary",
            "Pre-item measurement content specification when recorded",
        ],
        "Cannot claim yet": [
            "Validated latent/reflexive factor",
            "Psychometric validity or reliability",
            "Final item weights or scoring formula",
            "Final regression predictor count solely from qualitative closure",
        ],
    })
    st.dataframe(claims, use_container_width=True, hide_index=True)


def _render_current_vs_historical(
    frames: Dict[str, pd.DataFrame],
    archive_frames: Dict[str, pd.DataFrame] | None,
) -> None:
    st.markdown("#### Current vs Historical State")
    current = pd.DataFrame([
        {
            "Layer": "Decision Log",
            "Current source": "11_Decision_Log",
            "Current state": _latest_decision_id(frames),
        },
        {
            "Layer": "FOC → Cluster mapping",
            "Current source": "06_DeNovo_Clustering",
            "Current state": "Operational MASTER",
        },
        {
            "Layer": "Cluster register",
            "Current source": "06A_Cluster_Register",
            "Current state": "Operational MASTER",
        },
        {
            "Layer": "Themes",
            "Current source": "07_Descriptive_Themes",
            "Current state": "Operational MASTER",
        },
        {
            "Layer": "Candidate Dimensions",
            "Current source": "08_Candidate_Dimensions",
            "Current state": "Operational MASTER",
        },
    ])
    st.dataframe(current, use_container_width=True, hide_index=True)

    if not archive_frames:
        st.info("Upload the Audit Archive to inspect historical audit-sheet counterparts.")
        return

    idx = _archive_index(archive_frames)
    if idx.empty:
        st.caption(
            "Archive connected, but its index table could not be parsed. Entity History "
            "can still search the archived sheets directly."
        )
        return

    cols = [
        c for c in [
            "Archived_Sheet", "Archive_Category", "Why_Archived",
            "Final/Core_Counterpart", "Retention_Status",
            "Analytical_Effect", "DEC553_Note",
        ] if c in idx.columns
    ]
    if cols:
        st.dataframe(idx[cols], use_container_width=True, hide_index=True, height=540)


def render_audit_intelligence(
    frames: Dict[str, pd.DataFrame],
    archive_frames: Dict[str, pd.DataFrame] | None = None,
    archive_name: str | None = None,
) -> None:
    st.subheader("Audit Intelligence Center")
    st.caption(
        f"{AUDIT_INTELLIGENCE_VERSION} · Explainable qualitative provenance, "
        "decision history, construct defense, and historical reconstruction."
    )
    if archive_frames:
        st.success(f"Historical Audit Archive connected: {archive_name or 'uploaded archive'}")
    else:
        st.caption(
            "Audit Archive is optional. Current-state views remain available from "
            "the operational MASTER."
        )

    tabs = st.tabs([
        "Overview",
        "Decision Timeline",
        "Entity History",
        "Defense Mode",
        "Measurement Readiness",
        "Item-Pool Prep",
        "Item Drafting",
        "Current vs Historical",
    ])
    with tabs[0]:
        _render_overview(frames, archive_frames)
    with tabs[1]:
        _render_timeline(frames)
    with tabs[2]:
        _render_entity_history(frames, archive_frames)
    with tabs[3]:
        render_defense_mode(frames, archive_frames=archive_frames)
    with tabs[4]:
        render_measurement_readiness(frames)
    with tabs[5]:
        render_item_pool_preparation(frames)
    with tabs[6]:
        render_item_drafting_workspace(frames)
    with tabs[7]:
        _render_current_vs_historical(frames, archive_frames)
