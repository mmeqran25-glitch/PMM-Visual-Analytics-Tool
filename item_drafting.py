from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from defense_mode import measurement_spec_table
from item_pool_prep import item_pool_anchor_table
from master_utils import active_dimensions

ITEM_DRAFTING_VERSION = "v0.17.3-item-drafting"


TRACE_COLUMNS = [
    "Draft_Item_ID",
    "Dimension_ID",
    "Dimension_Name",
    "Required_Content_Facet",
    "Supporting_PCLs",
    "Supporting_FOCs",
    "Supporting_Studies",
    "Supporting_Evidence_IDs",
    "Source_Anchor_Summary",
    "Item_Referent",
    "Applicability_NA_Control",
    "Exclude_or_Contamination_Rule",
]

EDITABLE_COLUMNS = [
    "Item_Concept",
    "Candidate_Item_EN",
    "Candidate_Item_AR",
    "Response_Format",
    "Draft_Rationale",
    "Boundary_Check",
    "Draft_Status",
]


def _s(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _dimension_name(frames: Dict[str, pd.DataFrame], did: str) -> str:
    dims = active_dimensions(frames)
    if dims.empty or "Dimension_ID" not in dims.columns:
        return ""
    hit = dims[dims["Dimension_ID"].astype(str).str.upper().eq(did.upper())]
    if hit.empty:
        return ""
    return _s(hit.iloc[-1].get("Candidate_Dimension_Name"))


def _measurement_row(frames: Dict[str, pd.DataFrame], did: str) -> pd.Series | None:
    tbl = measurement_spec_table(frames)
    if tbl.empty or "Dimension_ID" not in tbl.columns:
        return None
    hit = tbl[tbl["Dimension_ID"].astype(str).str.upper().eq(did.upper())]
    return None if hit.empty else hit.iloc[-1]


def required_facets(frames: Dict[str, pd.DataFrame], did: str) -> List[str]:
    row = _measurement_row(frames, did)
    if row is None:
        return []
    text = _s(row.get("Required_Content_Facets"))
    if not text:
        return []
    return [x.strip() for x in text.replace("\n", ";").split(";") if x.strip()]


def build_draft_record(
    frames: Dict[str, pd.DataFrame],
    did: str,
    facet: str,
    selected_anchor_rows: pd.DataFrame,
    sequence: int,
) -> Dict[str, str]:
    measurement = _measurement_row(frames, did)
    name = _dimension_name(frames, did)

    def uniq(col: str) -> str:
        if selected_anchor_rows.empty or col not in selected_anchor_rows.columns:
            return ""
        values = []
        for v in selected_anchor_rows[col].dropna().astype(str):
            v = v.strip()
            if v and v not in values:
                values.append(v)
        return "; ".join(values)

    summaries: List[str] = []
    if not selected_anchor_rows.empty:
        for _, r in selected_anchor_rows.iterrows():
            code = _s(r.get("Code_ID"))
            foc = _s(r.get("First_Order_Code"))
            if code or foc:
                summaries.append(f"{code}: {foc}" if code and foc else code or foc)

    return {
        "Draft_Item_ID": f"DRAFT-{did}-{sequence:03d}",
        "Dimension_ID": did,
        "Dimension_Name": name,
        "Required_Content_Facet": facet,
        "Supporting_PCLs": uniq("Cluster_ID"),
        "Supporting_FOCs": uniq("Code_ID"),
        "Supporting_Studies": uniq("Study_ID"),
        "Supporting_Evidence_IDs": uniq("Evidence_ID"),
        "Source_Anchor_Summary": " | ".join(summaries)[:5000],
        "Item_Referent": _s(measurement.get("Item_Referent")) if measurement is not None else "",
        "Applicability_NA_Control": _s(measurement.get("Applicability_NA_Control")) if measurement is not None else "",
        "Exclude_or_Contamination_Rule": _s(measurement.get("Exclude_or_Contamination_Rule")) if measurement is not None else "",
        "Item_Concept": "",
        "Candidate_Item_EN": "",
        "Candidate_Item_AR": "",
        "Response_Format": "",
        "Draft_Rationale": "",
        "Boundary_Check": "",
        "Draft_Status": "Draft",
    }


def _draft_state_key(did: str) -> str:
    return f"item_drafting_rows_{did}"


def _empty_drafts() -> pd.DataFrame:
    return pd.DataFrame(columns=TRACE_COLUMNS + EDITABLE_COLUMNS)


def _next_sequence(df: pd.DataFrame, did: str) -> int:
    if df.empty or "Draft_Item_ID" not in df.columns:
        return 1
    prefix = f"DRAFT-{did}-"
    nums = []
    for value in df["Draft_Item_ID"].dropna().astype(str):
        if not value.startswith(prefix):
            continue
        tail = value[len(prefix):]
        if tail.isdigit():
            nums.append(int(tail))
    return (max(nums) + 1) if nums else 1


def _expert_review_long_template(drafts: pd.DataFrame, expert_count: int) -> pd.DataFrame:
    if drafts.empty:
        return pd.DataFrame()
    rows: List[Dict[str, Any]] = []
    for _, item in drafts.iterrows():
        for expert_no in range(1, expert_count + 1):
            rows.append({
                "Expert_ID": f"EXPERT-{expert_no:02d}",
                "Draft_Item_ID": _s(item.get("Draft_Item_ID")),
                "Dimension_ID": _s(item.get("Dimension_ID")),
                "Required_Content_Facet": _s(item.get("Required_Content_Facet")),
                "Candidate_Item_EN": _s(item.get("Candidate_Item_EN")),
                "Candidate_Item_AR": _s(item.get("Candidate_Item_AR")),
                "Relevance_1_to_4": "",
                "Clarity_1_to_4": "",
                "Representativeness_1_to_4": "",
                "Keep_Revise_Delete": "",
                "Expert_Comment": "",
            })
    return pd.DataFrame(rows)


def _draft_workbook_bytes(
    drafts: pd.DataFrame,
    measurement: pd.Series | None,
    expert_count: int,
) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        instructions = pd.DataFrame([
            ["Purpose", "Human-in-the-loop item drafting and expert content review; this workbook is not the analytical MASTER."],
            ["Traceability rule", "Do not delete or alter source-anchor IDs when revising item wording."],
            ["Relevance rating", "Recommended expert rating field uses 1–4; final CVI calculation should follow the approved thesis protocol."],
            ["Scoring warning", "Do not infer final scale weights, total scores, or reflective-factor structure from this drafting workbook."],
        ], columns=["Field", "Instruction"])
        instructions.to_excel(writer, sheet_name="00_Instructions", index=False)

        drafts.to_excel(writer, sheet_name="01_Draft_Items", index=False)

        if measurement is not None:
            measure_cols = [
                c for c in [
                    "Dimension_ID", "Pre_Item_Measurement_Form", "Required_Content_Facets",
                    "Item_Referent", "Exclude_or_Contamination_Rule", "Applicability_NA_Control",
                    "Aggregation_Control", "Validation_Gate", "Pre_Item_Disposition",
                ] if c in measurement.index
            ]
            pd.DataFrame([{c: measurement.get(c) for c in measure_cols}]).to_excel(
                writer, sheet_name="02_DEC589_Spec", index=False
            )

        ratings = _expert_review_long_template(drafts, expert_count)
        ratings.to_excel(writer, sheet_name="03_Expert_Ratings", index=False)

        summary = drafts[[
            c for c in [
                "Draft_Item_ID", "Dimension_ID", "Required_Content_Facet",
                "Candidate_Item_EN", "Candidate_Item_AR", "Draft_Status",
            ] if c in drafts.columns
        ]].copy()
        summary["I_CVI"] = ""
        summary["Clarity_Agreement"] = ""
        summary["Decision_After_Expert_Review"] = ""
        summary["Revision_Note"] = ""
        summary.to_excel(writer, sheet_name="04_CVI_Summary", index=False)

    return bio.getvalue()


def render_item_drafting_workspace(frames: Dict[str, pd.DataFrame]) -> None:
    st.markdown("### Item Drafting Workspace")
    st.caption(
        f"{ITEM_DRAFTING_VERSION} · Human-in-the-loop questionnaire wording with locked evidence traceability. "
        "Drafts are session-only and never write back to the MASTER."
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
        "Dimension",
        dids,
        format_func=lambda x: f"{x} — {labels.get(x, '')}",
        key="item_drafting_dimension",
    )

    measurement = _measurement_row(frames, did)
    facets = required_facets(frames, did)
    anchors = item_pool_anchor_table(frames, did)

    if measurement is None:
        st.warning("No DEC-589 measurement specification was detected for this Dimension.")
        return
    if not facets:
        st.warning("No Required_Content_Facets were detected for this Dimension.")
        return
    if anchors.empty:
        st.warning("No source-grounded item-pool anchors were detected for this Dimension.")
        return

    st.markdown(f"## {did} — {labels.get(did, '')}")

    m1, m2 = st.columns(2)
    with m1:
        st.markdown("#### Drafting referent")
        st.write(_s(measurement.get("Item_Referent")) or "Not specified")
        st.markdown("#### Applicability / N-A")
        st.write(_s(measurement.get("Applicability_NA_Control")) or "Not specified")
    with m2:
        st.markdown("#### Exclude / contamination")
        st.write(_s(measurement.get("Exclude_or_Contamination_Rule")) or "Not specified")
        st.markdown("#### Validation gate")
        st.write(_s(measurement.get("Validation_Gate")) or "Not specified")

    st.markdown("#### 1. Select the content facet and evidence anchors")
    facet = st.selectbox(
        "Required content facet",
        facets,
        key=f"draft_facet_{did}",
    )

    pcl_values = sorted(
        x for x in anchors.get("Cluster_ID", pd.Series(dtype=str)).dropna().astype(str).unique()
        if x
    )
    pcl_filter = st.selectbox(
        "Limit evidence anchors to one PCL",
        ["All"] + pcl_values,
        key=f"draft_pcl_{did}",
    )

    available = anchors.copy()
    if pcl_filter != "All" and "Cluster_ID" in available.columns:
        available = available[available["Cluster_ID"].astype(str).eq(pcl_filter)]

    code_labels: Dict[str, str] = {}
    if "Code_ID" in available.columns:
        for _, r in available.iterrows():
            code = _s(r.get("Code_ID"))
            if not code:
                continue
            foc = _s(r.get("First_Order_Code"))
            pcl = _s(r.get("Cluster_ID"))
            code_labels[code] = f"{code} — {foc[:125]}" + (f" [{pcl}]" if pcl else "")

    selected_codes = st.multiselect(
        "Supporting FOCs for this draft item",
        list(code_labels.keys()),
        format_func=lambda x: code_labels.get(x, x),
        key=f"draft_codes_{did}",
        help="Choose the minimum evidence set needed to support one candidate item concept. Multiple FOCs may support one item.",
    )

    selected_rows = (
        available[available["Code_ID"].astype(str).isin(selected_codes)].copy()
        if selected_codes and "Code_ID" in available.columns
        else available.iloc[0:0].copy()
    )

    if not selected_rows.empty:
        preview_cols = [
            c for c in [
                "Cluster_ID", "Code_ID", "First_Order_Code", "Study_ID",
                "Original_Author_Term", "Author_Parent_Construct",
                "Author_Defined_Relationship",
            ] if c in selected_rows.columns
        ]
        st.dataframe(selected_rows[preview_cols], use_container_width=True, hide_index=True)

    state_key = _draft_state_key(did)
    if state_key not in st.session_state:
        st.session_state[state_key] = _empty_drafts()

    if st.button(
        "Stage selected anchors as a new draft item",
        key=f"stage_draft_{did}",
        disabled=len(selected_codes) == 0,
        type="primary",
    ):
        drafts = st.session_state[state_key].copy()
        sequence = _next_sequence(drafts, did)
        record = build_draft_record(frames, did, facet, selected_rows, sequence)
        drafts = pd.concat([drafts, pd.DataFrame([record])], ignore_index=True)
        st.session_state[state_key] = drafts
        st.success(f"Created {record['Draft_Item_ID']} with locked traceability to {len(selected_codes)} FOC anchor(s).")

    st.markdown("#### 2. Draft and revise item wording")
    drafts = st.session_state[state_key].copy()
    if drafts.empty:
        st.info("No draft items staged yet for this Dimension.")
        return

    ordered_cols = TRACE_COLUMNS + EDITABLE_COLUMNS
    drafts = drafts[[c for c in ordered_cols if c in drafts.columns]].copy()

    edited = st.data_editor(
        drafts,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=[c for c in TRACE_COLUMNS if c in drafts.columns],
        column_config={
            "Item_Concept": st.column_config.TextColumn("Item concept", width="large"),
            "Candidate_Item_EN": st.column_config.TextColumn("Candidate item — English", width="large"),
            "Candidate_Item_AR": st.column_config.TextColumn("Candidate item — Arabic", width="large"),
            "Response_Format": st.column_config.TextColumn("Response format", width="medium"),
            "Draft_Rationale": st.column_config.TextColumn("Draft rationale", width="large"),
            "Boundary_Check": st.column_config.SelectboxColumn(
                "Boundary check",
                options=["", "Pass", "Revise", "Potential contamination", "Needs source review"],
            ),
            "Draft_Status": st.column_config.SelectboxColumn(
                "Draft status",
                options=["Draft", "Ready for expert review", "Revise", "Hold", "Delete candidate"],
            ),
        },
        key=f"draft_editor_{did}",
        height=520,
    )
    st.session_state[state_key] = edited.copy()

    st.markdown("#### 3. Drafting quality checks")
    quality_rows = []
    for _, r in edited.iterrows():
        item_id = _s(r.get("Draft_Item_ID"))
        en = _s(r.get("Candidate_Item_EN"))
        ar = _s(r.get("Candidate_Item_AR"))
        concept = _s(r.get("Item_Concept"))
        anchors_ok = bool(_s(r.get("Supporting_FOCs")))
        boundary = _s(r.get("Boundary_Check"))
        quality_rows.append({
            "Draft_Item_ID": item_id,
            "Has concept": "Yes" if concept else "No",
            "English wording": "Yes" if en else "No",
            "Arabic wording": "Yes" if ar else "No",
            "Traceability": "Locked" if anchors_ok else "Missing",
            "Boundary check": boundary or "Not reviewed",
            "Expert-review ready": "Yes" if anchors_ok and concept and (en or ar) and boundary == "Pass" else "No",
        })
    st.dataframe(pd.DataFrame(quality_rows), use_container_width=True, hide_index=True)

    st.markdown("#### 4. Export drafting and expert-review package")
    expert_count = st.number_input(
        "Number of experts for the review template",
        min_value=3,
        max_value=15,
        value=5,
        step=1,
        key=f"expert_count_{did}",
        help="This only creates blank rating rows. It does not calculate CVI or assume the final panel size.",
    )

    csv_bytes = edited.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Download current drafts (.csv)",
        data=csv_bytes,
        file_name=f"{did}_draft_items.csv",
        mime="text/csv",
        use_container_width=False,
    )

    xlsx_bytes = _draft_workbook_bytes(edited, measurement, int(expert_count))
    st.download_button(
        "Download Expert Review / CVI preparation workbook (.xlsx)",
        data=xlsx_bytes,
        file_name=f"{did}_expert_review_CVI_preparation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )

    st.caption(
        "The workbook prepares expert-rating fields only. Final I-CVI/S-CVI rules and thresholds must follow the approved thesis protocol; "
        "no content-validity result is inferred here."
    )

    with st.expander("Session draft controls"):
        st.warning("Drafts are session-only. Download them before clearing or closing the session.")
        confirm = st.checkbox(
            "I understand that clearing removes the current session drafts for this Dimension.",
            key=f"clear_drafts_confirm_{did}",
        )
        if st.button(
            "Clear drafts for this Dimension",
            key=f"clear_drafts_{did}",
            disabled=not confirm,
        ):
            st.session_state[state_key] = _empty_drafts()
            st.rerun()
