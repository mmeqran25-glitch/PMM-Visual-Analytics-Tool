from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st

from master_utils import active_dimensions, active_themes, current_mapping_rows, split_ids

DEFENSE_MODE_VERSION = "v0.17.1-defense"


def _s(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _decision_log(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = frames.get("11_Decision_Log", pd.DataFrame()).copy()
    if df.empty or "Decision_ID" not in df.columns:
        return pd.DataFrame()
    out = df[df["Decision_ID"].astype(str).str.match(r"^DEC-\d{3}$", case=False, na=False)].copy()
    out["_DecNum"] = pd.to_numeric(out["Decision_ID"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    if "Date" in out.columns:
        out["_DateSort"] = pd.to_datetime(out["Date"], errors="coerce")
    else:
        out["_DateSort"] = pd.NaT
    return out.sort_values(["_DateSort", "_DecNum"], na_position="last")


def _secondary_table(
    frames: Dict[str, pd.DataFrame],
    header_token: str,
    key_pattern: str,
    required_header_tokens: List[str] | None = None,
    max_rows: int = 100,
) -> pd.DataFrame:
    """Recover a secondary table embedded lower in 08_Candidate_Dimensions.

    The MASTER deliberately keeps DEC-588 and DEC-589 audit/specification tables
    inside the existing sheet. This parser respects that design and creates only
    a read-only in-memory view.
    """
    required_header_tokens = required_header_tokens or []
    df = frames.get("08_Candidate_Dimensions", pd.DataFrame())
    if df.empty:
        return pd.DataFrame()

    values = df.reset_index(drop=True)
    for ridx in range(len(values)):
        vals = [_s(v) for v in values.iloc[ridx].tolist()]
        lowered = [v.lower() for v in vals]
        if header_token.lower() not in lowered:
            continue
        if any(tok.lower() not in lowered for tok in required_header_tokens):
            continue

        start = lowered.index(header_token.lower())
        raw_headers = vals[start:]
        headers: List[str] = []
        for h in raw_headers:
            if not h:
                if headers:
                    break
                continue
            headers.append(h)

        if not headers:
            continue

        rows: List[Dict[str, str]] = []
        for j in range(ridx + 1, min(len(values), ridx + 1 + max_rows)):
            rowvals = [_s(v) for v in values.iloc[j].tolist()]
            key = rowvals[start] if start < len(rowvals) else ""
            if not re.match(key_pattern, key, flags=re.IGNORECASE):
                if rows:
                    break
                continue
            rec: Dict[str, str] = {}
            for offset, h in enumerate(headers):
                pos = start + offset
                rec[h] = rowvals[pos] if pos < len(rowvals) else ""
            rows.append(rec)
        if rows:
            return pd.DataFrame(rows)
    return pd.DataFrame()


def measurement_spec_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _secondary_table(
        frames,
        header_token="Dimension_ID",
        key_pattern=r"^DIM-\d{3}$",
        required_header_tokens=["Pre_Item_Measurement_Form", "Required_Content_Facets"],
        max_rows=25,
    )


def pairwise_boundary_table(frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    return _secondary_table(
        frames,
        header_token="Audit_ID",
        key_pattern=r"^D588-\d{2}$",
        required_header_tokens=["Dimension_A", "Dimension_B", "Final_Decision"],
        max_rows=70,
    )


def _dimension_row(frames: Dict[str, pd.DataFrame], did: str) -> pd.Series | None:
    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        return None
    hit = dims[dims["Dimension_ID"].astype(str).str.upper().eq(did.upper())]
    return None if hit.empty else hit.iloc[-1]


def _lineage_sets(frames: Dict[str, pd.DataFrame], did: str) -> Dict[str, set[str]]:
    result = {
        "dimension": {did.upper()},
        "themes": set(),
        "clusters": set(),
        "codes": set(),
        "studies": set(),
        "evidence": set(),
    }

    row = _dimension_row(frames, did)
    if row is None:
        return result

    for tid in split_ids(row.get("Supporting_Theme_IDs"), "THM"):
        result["themes"].add(tid.upper())

    themes = active_themes(frames)
    if not themes.empty and {"Theme_ID", "Included_Cluster_IDs"}.issubset(themes.columns):
        hit = themes[themes["Theme_ID"].astype(str).str.upper().isin(result["themes"])]
        for value in hit["Included_Cluster_IDs"].tolist():
            for pcl in split_ids(value, "PCL"):
                result["clusters"].add(pcl.upper())

    maps = current_mapping_rows(frames)
    if not maps.empty and {"Code_ID", "Cluster_ID"}.issubset(maps.columns):
        hit = maps[maps["Cluster_ID"].astype(str).str.upper().isin(result["clusters"])]
        result["codes"] = set(hit["Code_ID"].dropna().astype(str).str.upper())
        if "Study_ID" in hit.columns:
            result["studies"] |= set(hit["Study_ID"].dropna().astype(str).str.upper())

    coding = frames.get("05_First_Order_Coding", pd.DataFrame())
    if not coding.empty and "Code_ID" in coding.columns:
        hit = coding[coding["Code_ID"].astype(str).str.upper().isin(result["codes"])]
        if "Study_ID" in hit.columns:
            result["studies"] |= set(hit["Study_ID"].dropna().astype(str).str.upper())
        if "Evidence_ID" in hit.columns:
            result["evidence"] |= set(hit["Evidence_ID"].dropna().astype(str).str.upper())

    return result


def _row_text(row: pd.Series, cols: List[str] | None = None) -> str:
    if cols:
        vals = [_s(row.get(c)) for c in cols if c in row.index]
    else:
        vals = [_s(v) for v in row.values]
    return " | ".join(v for v in vals if v)


def _find_matches(text: str, ids: set[str], limit: int = 12) -> List[str]:
    if not text or not ids:
        return []
    found = []
    for entity in sorted(ids):
        pattern = rf"(?<![A-Za-z0-9-]){re.escape(entity)}(?![A-Za-z0-9-])"
        if re.search(pattern, text, flags=re.IGNORECASE):
            found.append(entity)
    return found[:limit]


def _classify_event(text: str) -> str:
    t = text.lower()
    rules = [
        ("Measurement / Item development", ["measurement", "item pool", "psychometric", "scoring", "cvi", "pilot"]),
        ("Cross-dimension boundary", ["pairwise", "cross-dimension", "discriminant", "boundary"]),
        ("Merge / Nesting", ["merge", "merged", "nest", "nested"]),
        ("Split / Separation", ["split", "separate", "separation"]),
        ("Reassignment / Re-home", ["re-home", "rehome", "reassign", "transfer"]),
        ("Evidence exclusion / downgrade", ["withdraw", "supporting only", "downgrade", "exclude"]),
        ("Source / Fidelity", ["source fidelity", "fidelity", "direct source", "source-level"]),
        ("Residual / Challenge", ["challenged", "residual", "no forced", "unassigned"]),
        ("Retention / Closure", ["retain", "retained", "close", "closure", "stable"]),
    ]
    for label, terms in rules:
        if any(term in t for term in terms):
            return label
    return "Other adjudication"


def _decision_events(
    frames: Dict[str, pd.DataFrame],
    lineage: Dict[str, set[str]],
) -> pd.DataFrame:
    dec = _decision_log(frames)
    if dec.empty:
        return pd.DataFrame()

    textcols = [
        c for c in ["Decision_ID", "Stage", "Decision", "Reason", "Affected_Sheets_or_Fields",
                    "Impact_on_Analysis", "Status", "Notes"] if c in dec.columns
    ]

    rows: List[Dict[str, Any]] = []
    for _, row in dec.iterrows():
        text = _row_text(row, textcols)
        direct = _find_matches(text, lineage["dimension"])
        themes = _find_matches(text, lineage["themes"])
        clusters = _find_matches(text, lineage["clusters"])
        codes = _find_matches(text, lineage["codes"], limit=8)
        evidence = _find_matches(text, lineage["evidence"], limit=6)
        studies = _find_matches(text, lineage["studies"], limit=6)

        if direct:
            relevance = "Direct Dimension"
            score = 5
            matched = direct
        elif themes:
            relevance = "Theme-linked"
            score = 4
            matched = themes
        elif clusters:
            relevance = "Cluster-linked"
            score = 3
            matched = clusters
        elif codes or evidence:
            relevance = "FOC/Evidence-linked"
            score = 2
            matched = codes + evidence
        elif studies:
            relevance = "Source-linked"
            score = 1
            matched = studies
        else:
            continue

        rows.append({
            "Decision_ID": _s(row.get("Decision_ID")),
            "Date": _s(row.get("Date")),
            "Stage": _s(row.get("Stage")),
            "Event_Type": _classify_event(text),
            "Relevance": relevance,
            "Matched_Entities": "; ".join(matched[:12]),
            "Decision": _s(row.get("Decision")),
            "Why": _s(row.get("Reason")),
            "Analytical_Effect": _s(row.get("Impact_on_Analysis")),
            "Status": _s(row.get("Status")),
            "_Score": score,
            "_DecNum": row.get("_DecNum"),
        })

    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["_DecNum", "_Score"], ascending=[True, False])


def _archive_events(
    archive_frames: Dict[str, pd.DataFrame] | None,
    lineage: Dict[str, set[str]],
) -> pd.DataFrame:
    if not archive_frames:
        return pd.DataFrame()

    direct_ids = (
        lineage["dimension"] | lineage["themes"] | lineage["clusters"] |
        lineage["codes"] | lineage["evidence"]
    )
    if not direct_ids:
        return pd.DataFrame()

    rows: List[Dict[str, Any]] = []
    for sheet, df in archive_frames.items():
        if sheet == "00_AUDIT_ARCHIVE_INDEX" or df is None or df.empty:
            continue
        for idx, row in df.iterrows():
            text = _row_text(row)
            matched = _find_matches(text, direct_ids, limit=10)
            if not matched:
                continue
            if sheet.startswith("04"):
                category = "Evidence / Source Fidelity"
            elif sheet.startswith("06"):
                category = "SG2 Cluster / Assignment"
            elif sheet.startswith("07"):
                category = "SG3 Theme Audit"
            elif sheet.startswith("08"):
                category = "SG4 Dimension Audit"
            else:
                category = "Historical Control"
            rows.append({
                "Sheet": sheet,
                "Audit_Category": category,
                "Matched_Entities": "; ".join(matched),
                "Context": text[:700],
                "Row": int(idx) + 1 if isinstance(idx, int) else _s(idx),
            })
    return pd.DataFrame(rows)


def _pairwise_for_dimension(frames: Dict[str, pd.DataFrame], did: str) -> pd.DataFrame:
    tbl = pairwise_boundary_table(frames)
    if tbl.empty or not {"Dimension_A", "Dimension_B"}.issubset(tbl.columns):
        return pd.DataFrame()
    mask = (
        tbl["Dimension_A"].astype(str).str.upper().eq(did.upper()) |
        tbl["Dimension_B"].astype(str).str.upper().eq(did.upper())
    )
    return tbl[mask].copy()


def _measurement_for_dimension(frames: Dict[str, pd.DataFrame], did: str) -> pd.Series | None:
    tbl = measurement_spec_table(frames)
    if tbl.empty or "Dimension_ID" not in tbl.columns:
        return None
    hit = tbl[tbl["Dimension_ID"].astype(str).str.upper().eq(did.upper())]
    return None if hit.empty else hit.iloc[-1]


def _dimension_name(frames: Dict[str, pd.DataFrame], did: str) -> str:
    row = _dimension_row(frames, did)
    return _s(row.get("Candidate_Dimension_Name")) if row is not None else ""


def _dimension_definition(frames: Dict[str, pd.DataFrame], did: str) -> str:
    row = _dimension_row(frames, did)
    if row is None:
        return ""
    for col in ["Analytical_Definition", "Construct_Definition", "Definition"]:
        if col in row.index and _s(row.get(col)):
            return _s(row.get(col))
    return ""


def _defense_markdown(
    frames: Dict[str, pd.DataFrame],
    did: str,
    lineage: Dict[str, set[str]],
    events: pd.DataFrame,
    pairwise: pd.DataFrame,
    measurement: pd.Series | None,
) -> str:
    name = _dimension_name(frames, did)
    definition = _dimension_definition(frames, did)
    lines = [
        f"# Defense Brief — {did} — {name}",
        "",
        "## Current construct",
        definition or "No dedicated analytical definition detected.",
        "",
        "## Current evidence footprint",
        f"- Themes: {len(lineage['themes'])}",
        f"- Clusters: {len(lineage['clusters'])}",
        f"- First-order codes: {len(lineage['codes'])}",
        f"- Source records: {len(lineage['studies'])}",
        "",
        "## Current lineage",
        f"- Themes: {', '.join(sorted(lineage['themes'])) or 'None detected'}",
        f"- Clusters: {', '.join(sorted(lineage['clusters'])) or 'None detected'}",
        "",
        "## Decision trail",
    ]
    if events.empty:
        lines.append("- No linked DEC records detected.")
    else:
        for _, r in events.iterrows():
            lines.append(
                f"- {r['Decision_ID']} [{r['Relevance']}; {r['Event_Type']}]: "
                f"{_s(r.get('Decision')) or _s(r.get('Analytical_Effect'))}"
            )

    lines += ["", "## Final pairwise construct boundary"]
    if pairwise.empty:
        lines.append("- No DEC-588 pairwise rows detected.")
    else:
        pass_count = int(pairwise["Final_Decision"].astype(str).str.contains("PASS", case=False, na=False).sum())             if "Final_Decision" in pairwise.columns else 0
        lines.append(f"- Relevant pairwise comparisons: {len(pairwise)}")
        lines.append(f"- PASS decisions: {pass_count}")

    lines += ["", "## DEC-589 pre-item measurement specification"]
    if measurement is None:
        lines.append("- No embedded DEC-589 specification row detected.")
    else:
        for col in [
            "Pre_Item_Measurement_Form", "Required_Content_Facets", "Item_Referent",
            "Exclude_or_Contamination_Rule", "Applicability_NA_Control",
            "Aggregation_Control", "Validation_Gate", "Pre_Item_Disposition",
        ]:
            val = _s(measurement.get(col))
            if val:
                lines.append(f"- **{col}:** {val}")

    lines += [
        "",
        "## Claim boundary",
        "- Can claim: literature-derived and source-traceable content domain with qualitatively adjudicated boundaries.",
        "- Cannot yet claim: validated reflective factor, psychometric validity, final weighting/scoring, or final regression predictor architecture.",
    ]
    return "\n".join(lines)


def render_defense_mode(
    frames: Dict[str, pd.DataFrame],
    archive_frames: Dict[str, pd.DataFrame] | None = None,
) -> None:
    st.markdown("### Supervisor / Viva Defense Mode")
    st.caption(
        f"{DEFENSE_MODE_VERSION} · Reconstructs how each Dimension emerged, what was challenged, "
        "why it was retained, and what is not yet claimed."
    )

    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        st.info("No current Candidate Dimensions are available.")
        return

    names = dict(zip(
        dims["Dimension_ID"].astype(str),
        dims.get("Candidate_Dimension_Name", pd.Series("", index=dims.index)).astype(str),
    ))
    dids = dims["Dimension_ID"].astype(str).tolist()
    did = st.selectbox(
        "Choose a Dimension to defend",
        dids,
        format_func=lambda x: f"{x} — {names.get(x, '')}",
        key="defense_mode_dimension",
    )

    name = names.get(did, "")
    definition = _dimension_definition(frames, did)
    lineage = _lineage_sets(frames, did)
    events = _decision_events(frames, lineage)
    pairwise = _pairwise_for_dimension(frames, did)
    measurement = _measurement_for_dimension(frames, did)
    archive_events = _archive_events(archive_frames, lineage)

    st.markdown(f"## {did} — {name}")
    if definition:
        st.write(definition)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Themes", len(lineage["themes"]))
    c2.metric("Clusters", len(lineage["clusters"]))
    c3.metric("FOCs", len(lineage["codes"]))
    c4.metric("Source records", len(lineage["studies"]))
    c5.metric("Linked DEC records", len(events))

    st.markdown("#### 1. How this construct is currently assembled")
    current = pd.DataFrame({
        "Layer": ["Dimension", "Themes", "Clusters", "FOCs", "Source records"],
        "Count": [1, len(lineage["themes"]), len(lineage["clusters"]), len(lineage["codes"]), len(lineage["studies"])],
        "IDs / note": [
            did,
            "; ".join(sorted(lineage["themes"])),
            "; ".join(sorted(lineage["clusters"])),
            "Source-near FOCs retained in current mapped lineage",
            "; ".join(sorted(lineage["studies"]))[:1200],
        ],
    })
    st.dataframe(current, use_container_width=True, hide_index=True)

    st.markdown("#### 2. Decision history that shaped this Dimension")
    if events.empty:
        st.info("No linked DEC records were detected by the current lineage search.")
    else:
        relevance_options = ["All"] + sorted(events["Relevance"].dropna().unique().tolist())
        selected_rel = st.selectbox("Decision relevance", relevance_options, key="defense_event_relevance")
        shown = events if selected_rel == "All" else events[events["Relevance"].eq(selected_rel)]
        display_cols = [
            c for c in [
                "Decision_ID", "Date", "Stage", "Event_Type", "Relevance",
                "Matched_Entities", "Decision", "Analytical_Effect", "Status",
            ] if c in shown.columns
        ]
        st.dataframe(shown[display_cols].iloc[::-1], use_container_width=True, hide_index=True, height=520)

    st.markdown("#### 3. Final DEC-588 pairwise boundary tests")
    if pairwise.empty:
        st.info("No DEC-588 pairwise table was detected.")
    else:
        pass_count = int(pairwise["Final_Decision"].astype(str).str.contains("PASS", case=False, na=False).sum())             if "Final_Decision" in pairwise.columns else 0
        p1, p2 = st.columns(2)
        p1.metric("Relevant pairwise comparisons", len(pairwise))
        p2.metric("PASS – retain distinct", pass_count)
        cols = [
            c for c in [
                "Audit_ID", "Dimension_A", "Dimension_B", "Shared_Source_Records",
                "Boundary_Risk", "Controlling_Discriminator", "Final_Decision",
                "Pairwise_Rationale", "Measurement_Caution",
            ] if c in pairwise.columns
        ]
        st.dataframe(pairwise[cols], use_container_width=True, hide_index=True, height=470)

    st.markdown("#### 4. DEC-589 measurement-readiness specification")
    if measurement is None:
        st.warning("No embedded DEC-589 measurement specification row was detected for this Dimension.")
    else:
        left, right = st.columns(2)
        with left:
            for label, col in [
                ("Measurement form", "Pre_Item_Measurement_Form"),
                ("Required content facets", "Required_Content_Facets"),
                ("Item referent", "Item_Referent"),
                ("Applicability / N-A control", "Applicability_NA_Control"),
            ]:
                val = _s(measurement.get(col))
                if val:
                    st.markdown(f"**{label}**")
                    st.write(val)
        with right:
            for label, col in [
                ("Exclude / contamination rule", "Exclude_or_Contamination_Rule"),
                ("Aggregation control", "Aggregation_Control"),
                ("Validation gate", "Validation_Gate"),
                ("Pre-item disposition", "Pre_Item_Disposition"),
            ]:
                val = _s(measurement.get(col))
                if val:
                    st.markdown(f"**{label}**")
                    st.write(val)

    st.markdown("#### 5. Historical audit reconstruction")
    if archive_frames is None:
        st.caption("Upload the optional Audit Archive to reconstruct historical audit-sheet appearances.")
    elif archive_events.empty:
        st.caption("No historical archive rows were linked to the current Dimension lineage.")
    else:
        st.dataframe(archive_events, use_container_width=True, hide_index=True, height=420)

    st.markdown("#### 6. What can be defended — and what cannot yet be claimed")
    boundary = pd.DataFrame({
        "Can defend now": [
            "Source-traceable literature-derived content domain",
            "Current FOC → PCL → Theme → Dimension lineage",
            "Documented adjudication / boundary decision trail",
            "DEC-588 qualitative pairwise distinctiveness where detected",
            "DEC-589 pre-item content and applicability specification",
        ],
        "Not yet established": [
            "Reflective unidimensional factor",
            "Psychometric discriminant validity",
            "Final reliability / validity coefficients",
            "Final item weighting or total-score rule",
            "Final regression predictor count from qualitative closure alone",
        ],
    })
    st.dataframe(boundary, use_container_width=True, hide_index=True)

    brief = _defense_markdown(frames, did, lineage, events, pairwise, measurement)
    st.download_button(
        "Download Defense Brief (.md)",
        data=brief.encode("utf-8"),
        file_name=f"{did}_defense_brief.md",
        mime="text/markdown",
        use_container_width=False,
    )


def render_measurement_readiness(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("### Measurement Readiness · DEC-589")
    st.caption(
        "Read-only extraction of the embedded pre-item specification. This is the bridge from "
        "qualitative construct derivation to source-grounded item-pool development."
    )

    tbl = measurement_spec_table(frames)
    if tbl.empty:
        st.warning("The embedded DEC-589 measurement specification table could not be detected.")
        return

    required = [
        "Dimension_ID", "Pre_Item_Measurement_Form", "Required_Content_Facets",
        "Item_Referent", "Exclude_or_Contamination_Rule", "Applicability_NA_Control",
        "Aggregation_Control", "Validation_Gate", "Pre_Item_Disposition",
    ]
    show = [c for c in required if c in tbl.columns]

    k1, k2, k3 = st.columns(3)
    k1.metric("Specified Dimensions", int(tbl["Dimension_ID"].nunique()) if "Dimension_ID" in tbl.columns else len(tbl))
    k2.metric(
        "Item-pool next",
        int(tbl.get("Pre_Item_Disposition", pd.Series(dtype=str)).astype(str).str.contains("ITEM|POOL|LOCK", case=False, na=False).sum()),
    )
    k3.metric("Current status", "Pre-item architecture locked")

    st.dataframe(tbl[show], use_container_width=True, hide_index=True, height=520)

    if "Dimension_ID" in tbl.columns:
        dids = tbl["Dimension_ID"].astype(str).tolist()
        did = st.selectbox("Open one measurement specification", dids, key="measurement_ready_dim")
        row = tbl[tbl["Dimension_ID"].astype(str).eq(did)].iloc[-1]
        st.markdown(f"#### {did} — {_dimension_name(frames, did)}")

        for label, col in [
            ("Measurement form", "Pre_Item_Measurement_Form"),
            ("Required content facets", "Required_Content_Facets"),
            ("Item referent", "Item_Referent"),
            ("Exclude / contamination", "Exclude_or_Contamination_Rule"),
            ("Applicability / N-A", "Applicability_NA_Control"),
            ("Aggregation control", "Aggregation_Control"),
            ("Validation gate", "Validation_Gate"),
            ("Disposition", "Pre_Item_Disposition"),
        ]:
            val = _s(row.get(col))
            if val:
                st.markdown(f"**{label}:** {val}")

        st.markdown("#### Item-development gate")
        st.info(
            "Next analytical action: build candidate item concepts within the required content facets, "
            "retain the stated referent and exclusion boundary, use N/A controls where required, then "
            "take the pool through expert content validity/CVI, pilot clarity/reliability, and empirical "
            "dimensionality/discriminant assessment before scoring."
        )
