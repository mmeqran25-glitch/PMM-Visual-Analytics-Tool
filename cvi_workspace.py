from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Tuple

import pandas as pd
import streamlit as st

CVI_WORKSPACE_VERSION = "v0.17.4-cvi"

REQUIRED_RATING_COLUMNS = [
    "Expert_ID",
    "Draft_Item_ID",
    "Dimension_ID",
    "Required_Content_Facet",
    "Candidate_Item_EN",
    "Candidate_Item_AR",
    "Relevance_1_to_4",
]


def _s(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def load_expert_review_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(".csv"):
        return pd.read_csv(BytesIO(file_bytes))
    xls = pd.ExcelFile(BytesIO(file_bytes), engine="openpyxl")
    preferred = "03_Expert_Ratings"
    sheet = preferred if preferred in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)


def validate_rating_table(ratings: pd.DataFrame) -> list[str]:
    issues = []
    missing = [c for c in REQUIRED_RATING_COLUMNS if c not in ratings.columns]
    if missing:
        issues.append("Missing required columns: " + ", ".join(missing))
        return issues

    if ratings.empty:
        issues.append("The rating table is empty.")
        return issues

    pairs = ratings[["Expert_ID", "Draft_Item_ID"]].astype(str)
    dup = pairs.duplicated(keep=False)
    if dup.any():
        issues.append(
            f"Duplicate Expert_ID × Draft_Item_ID pairs detected: {int(dup.sum())} rows. "
            "Resolve duplicates before treating the output as final."
        )

    numeric = pd.to_numeric(ratings["Relevance_1_to_4"], errors="coerce")
    invalid = ratings["Relevance_1_to_4"].notna() & numeric.isna()
    if invalid.any():
        issues.append(f"Non-numeric relevance ratings detected: {int(invalid.sum())} rows.")

    out_of_range = numeric.notna() & ~numeric.between(1, 4)
    if out_of_range.any():
        issues.append(f"Relevance ratings outside 1–4 detected: {int(out_of_range.sum())} rows.")

    return issues


def calculate_cvi(
    ratings: pd.DataFrame,
    threshold: float = 0.78,
) -> Tuple[pd.DataFrame, Dict[str, Any], pd.DataFrame]:
    if ratings.empty:
        return pd.DataFrame(), {}, pd.DataFrame()

    work = ratings.copy()
    work["Expert_ID"] = work["Expert_ID"].astype(str).str.strip()
    work["Draft_Item_ID"] = work["Draft_Item_ID"].astype(str).str.strip()
    work["Relevance_Numeric"] = pd.to_numeric(work["Relevance_1_to_4"], errors="coerce")
    work.loc[~work["Relevance_Numeric"].between(1, 4), "Relevance_Numeric"] = pd.NA

    duplicate_mask = work.duplicated(subset=["Expert_ID", "Draft_Item_ID"], keep=False)
    quality_rows = []
    if duplicate_mask.any():
        for _, r in work.loc[duplicate_mask].iterrows():
            quality_rows.append({
                "Issue": "Duplicate expert-item pair",
                "Expert_ID": _s(r.get("Expert_ID")),
                "Draft_Item_ID": _s(r.get("Draft_Item_ID")),
                "Detail": "Only the last row is used for provisional calculation; resolve before final reporting.",
            })

    # Provisional calculation uses the last row per expert-item pair so the workspace
    # remains usable, while the quality table makes the duplication explicit.
    dedup = work.drop_duplicates(subset=["Expert_ID", "Draft_Item_ID"], keep="last").copy()

    for _, r in dedup[dedup["Relevance_Numeric"].isna()].iterrows():
        quality_rows.append({
            "Issue": "Missing/invalid relevance rating",
            "Expert_ID": _s(r.get("Expert_ID")),
            "Draft_Item_ID": _s(r.get("Draft_Item_ID")),
            "Detail": "Excluded from the item denominator.",
        })

    rows = []
    for item_id, g in dedup.groupby("Draft_Item_ID", dropna=False):
        valid = g[g["Relevance_Numeric"].notna()].copy()
        favorable = valid[valid["Relevance_Numeric"].ge(3)]
        first = g.iloc[-1]

        valid_n = int(valid["Expert_ID"].nunique())
        favorable_n = int(favorable["Expert_ID"].nunique())
        i_cvi = (favorable_n / valid_n) if valid_n else None

        rows.append({
            "Draft_Item_ID": _s(item_id),
            "Dimension_ID": _s(first.get("Dimension_ID")),
            "Required_Content_Facet": _s(first.get("Required_Content_Facet")),
            "Candidate_Item_EN": _s(first.get("Candidate_Item_EN")),
            "Candidate_Item_AR": _s(first.get("Candidate_Item_AR")),
            "Valid_Expert_Ratings": valid_n,
            "Favorable_Ratings_3_or_4": favorable_n,
            "I_CVI": i_cvi,
            "Threshold": float(threshold),
            "CVI_Decision": (
                "Meets threshold"
                if i_cvi is not None and i_cvi >= threshold
                else "Review"
            ),
        })

    item_results = pd.DataFrame(rows)
    cvi_values = pd.to_numeric(item_results.get("I_CVI"), errors="coerce").dropna()
    panel_experts = int(dedup["Expert_ID"].replace("", pd.NA).dropna().nunique())
    summary = {
        "Items": int(item_results["Draft_Item_ID"].nunique()) if not item_results.empty else 0,
        "Experts_Detected": panel_experts,
        "S_CVI_Ave": float(cvi_values.mean()) if not cvi_values.empty else None,
        "Items_Meeting_Threshold": int(item_results["CVI_Decision"].eq("Meets threshold").sum()) if not item_results.empty else 0,
        "Items_For_Review": int(item_results["CVI_Decision"].eq("Review").sum()) if not item_results.empty else 0,
        "Threshold": float(threshold),
    }
    quality = pd.DataFrame(quality_rows)
    return item_results, summary, quality


def _cvi_export_bytes(
    item_results: pd.DataFrame,
    summary: Dict[str, Any],
    ratings: pd.DataFrame,
    quality: pd.DataFrame,
) -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pd.DataFrame([
            ["Items", summary.get("Items")],
            ["Experts detected", summary.get("Experts_Detected")],
            ["S-CVI/Ave", summary.get("S_CVI_Ave")],
            ["Decision threshold", summary.get("Threshold")],
            ["Items meeting threshold", summary.get("Items_Meeting_Threshold")],
            ["Items for review", summary.get("Items_For_Review")],
            ["Method note", "I-CVI = experts rating relevance 3 or 4 divided by valid expert relevance ratings for that item."],
            ["Guardrail", "Threshold is researcher-controlled and must match the approved thesis protocol."],
        ], columns=["Metric", "Value"]).to_excel(writer, sheet_name="00_CVI_Summary", index=False)

        item_results.to_excel(writer, sheet_name="01_Item_CVI", index=False)
        ratings.to_excel(writer, sheet_name="02_Ratings_Input", index=False)
        quality.to_excel(writer, sheet_name="03_Quality_Issues", index=False)

    return bio.getvalue()


def render_cvi_workspace() -> None:
    st.markdown("### Expert Review / CVI Workspace")
    st.caption(
        f"{CVI_WORKSPACE_VERSION} · Calculates content-validity agreement from completed expert relevance ratings. "
        "No rating is written to the analytical MASTER."
    )

    st.markdown(
        '<div class="note-banner"><b>Method boundary:</b> This workspace calculates I-CVI and S-CVI/Ave from relevance ratings only. '
        'It does not establish construct validity, factor structure, reliability, or final scale scoring.</div>',
        unsafe_allow_html=True,
    )

    upload = st.file_uploader(
        "Upload completed Expert Review workbook (.xlsx) or ratings CSV",
        type=["xlsx", "csv"],
        key="cvi_review_upload",
    )
    if upload is None:
        st.info(
            "Use the workbook exported from Item Drafting, collect expert ratings, then upload the completed file here."
        )
        return

    try:
        ratings = load_expert_review_file(upload.getvalue(), upload.name)
    except Exception as exc:
        st.error(f"Could not read expert review file: {exc}")
        return

    issues = validate_rating_table(ratings)
    fatal_missing = any(x.startswith("Missing required columns") for x in issues)
    if fatal_missing:
        for issue in issues:
            st.error(issue)
        return

    if issues:
        st.warning("Data-quality checks found issues. Calculations below are provisional until they are resolved.")
        for issue in issues:
            st.write(f"- {issue}")
    else:
        st.success("Rating table passed structural and range checks.")

    threshold = st.slider(
        "I-CVI decision threshold",
        min_value=0.50,
        max_value=1.00,
        value=0.78,
        step=0.01,
        key="cvi_threshold",
        help="Researcher-controlled. Confirm the final threshold in the approved methodology/protocol.",
    )

    item_results, summary, quality = calculate_cvi(ratings, threshold=float(threshold))
    if item_results.empty:
        st.warning("No analyzable item ratings were found.")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Items", summary.get("Items", 0))
    c2.metric("Experts detected", summary.get("Experts_Detected", 0))
    scvi = summary.get("S_CVI_Ave")
    c3.metric("S-CVI/Ave", f"{scvi:.3f}" if isinstance(scvi, float) else "N/A")
    c4.metric("Meet threshold", summary.get("Items_Meeting_Threshold", 0))
    c5.metric("Review", summary.get("Items_For_Review", 0))

    st.markdown("#### Item-level CVI")
    st.dataframe(
        item_results,
        use_container_width=True,
        hide_index=True,
        height=500,
        column_config={
            "I_CVI": st.column_config.NumberColumn("I-CVI", format="%.3f"),
            "Threshold": st.column_config.NumberColumn("Threshold", format="%.2f"),
        },
    )

    st.markdown("#### Rating completeness by item")
    panel = max(1, summary.get("Experts_Detected", 0))
    completeness = item_results[[
        "Draft_Item_ID", "Valid_Expert_Ratings", "Favorable_Ratings_3_or_4", "I_CVI"
    ]].copy()
    completeness["Panel_Experts_Detected"] = panel
    completeness["Rating_Completeness"] = completeness["Valid_Expert_Ratings"] / panel
    st.dataframe(
        completeness,
        use_container_width=True,
        hide_index=True,
        column_config={
            "I_CVI": st.column_config.NumberColumn("I-CVI", format="%.3f"),
            "Rating_Completeness": st.column_config.ProgressColumn(
                "Rating completeness", min_value=0.0, max_value=1.0, format="%.0%%"
            ),
        },
    )

    if not quality.empty:
        st.markdown("#### Data-quality issues")
        st.dataframe(quality, use_container_width=True, hide_index=True)

    st.markdown("#### Interpretation guardrail")
    st.write(
        "A high I-CVI means experts agreed that an item is relevant to its intended content domain under the chosen rating rule. "
        "It does not by itself prove that the item is unidimensional, reliable, discriminant, or suitable for a final aggregate score."
    )

    export_bytes = _cvi_export_bytes(item_results, summary, ratings, quality)
    st.download_button(
        "Download CVI analysis workbook (.xlsx)",
        data=export_bytes,
        file_name="CVI_analysis_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
    )
