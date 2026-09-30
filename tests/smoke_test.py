from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import gzip
import hashlib

import pandas as pd
from openpyxl import load_workbook

from master_utils import load_master_workbook, master_snapshot, validate_master, active_themes, retired_themes, active_dimensions
from share_utils import supervisor_share_html
from snapshot_utils import load_supervisor_snapshot, nodes_of_type, build_supervisor_snapshot
from tree_utils import build_selected_themes_tree_data
from dimension_export import dimension_trace_workbook_bytes
from researcher_cache import (
    token_matches,
    save_cached_master,
    load_cached_master,
    clear_cached_master,
)


HEADER_ROW = 3


def _sheet(writer, name, columns, rows=None):
    rows = rows or []
    df = pd.DataFrame(rows, columns=columns)
    df.to_excel(writer, sheet_name=name, index=False, startrow=HEADER_ROW)


def build_workbook(version: str = "v99.123", decision: str = "DEC-999") -> bytes:
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        readme = pd.DataFrame([
            [f"PMM DIMENSION DERIVATION MASTER - {version} - TEST"],
            ["Synthetic compatibility workbook"],
            [f"CURRENT {decision}: 1/1 studies (100%); Next action: continue review."],
        ])
        readme.to_excel(writer, sheet_name="00_README", index=False, header=False)

        _sheet(writer, "01_Source_Register", ["Study_ID", "Study_Title"], [["SR001", "Synthetic Study"]])
        _sheet(writer, "02_Capability_Eligibility", ["Study_ID", "Dimension_Formation_Decision"], [["SR001", "Eligible"]])
        _sheet(writer, "03_Study_Profile", ["Study_ID", "Study_Title"], [["SR001", "Synthetic Study"]])
        _sheet(
            writer,
            "04_Verbatim_Evidence",
            [
                "Evidence_ID", "Study_ID", "Meaning_Unit_Verbatim", "Meaning_Unit_Status",
                "PM_Practice_Maturity_Evidence_Gate", "Context_Verbatim", "Original_Author_Term",
                "Author_Parent_Construct", "Author_Defined_Relationship", "Printed_Page",
            ],
            [["EV001", "SR001", "Synthetic evidence", "Approved", "Pass", "Context", "Term", "Parent", "Relation", "1"]],
        )
        _sheet(
            writer,
            "05_First_Order_Coding",
            ["Code_ID", "Evidence_ID", "Study_ID", "First_Order_Code", "Code_Fidelity_Status", "Source_to_Code_Rationale"],
            [["CD-SR001-001", "EV001", "SR001", "Synthetic FOC", "Pass", "Rationale"]],
        )
        _sheet(
            writer,
            "06_DeNovo_Clustering",
            [
                "Mapping_ID", "Code_ID", "Study_ID", "Cluster_ID", "Mapping_Status",
                "Mapping_Rationale", "Boundary_Rationale", "Closest_Competing_Cluster",
            ],
            [["MAP001", "CD-SR001-001", "SR001", "PCL-001", "Stable", "Rationale", "", ""]],
        )
        _sheet(
            writer,
            "06A_Cluster_Register",
            [
                "Cluster_ID", "Working_Cluster_Label", "Cluster_Status", "Core_Organizational_Function",
                "Operational_Definition", "Inclusion_Boundary", "Exclusion_Boundary", "Nearest_Conceptual_Neighbours",
            ],
            [["PCL-001", "Synthetic Cluster", "Stable", "Function", "Definition", "Include", "Exclude", "Neighbour"]],
        )
        _sheet(
            writer,
            "07_Descriptive_Themes",
            [
                "Theme_ID", "Working_Theme_Label", "Included_Cluster_IDs", "Theme_Status",
                "Central_Organizing_Concept", "Theme_Boundary", "Closest_Competing_Theme",
            ],
            [
                ["THM-001", "Synthetic Theme", "PCL-001", "Stable", "Concept", "Boundary", ""],
                ["THM-016", "Embedding sustainability across project-management systems and stakeholder/supply-chain interfaces", "PCL-001", "Retired – DEC-351 functional-boundary refinement", "Historical concept", "Historical boundary", ""],
            ],
        )
        _sheet(
            writer,
            "08_Candidate_Dimensions",
            [
                "Dimension_ID", "Candidate_Dimension_Name", "Supporting_Theme_IDs", "Dimension_Status",
                "Analytical_Definition", "Core_Capability_Logic", "Evidence_Breadth", "Cross_Model_Support",
                "Cross_Context_Support", "Measurement_Evidence_Link", "Contradictory_or_Boundary_Evidence", "Notes",
            ],
            [["DIM-001", "Synthetic Dimension", "THM-001", "Stable", "Definition", "Logic", "Breadth", "", "", "", "", ""]],
        )
        _sheet(writer, "10_Study_Families", ["Study_ID"], [["SR001"]])
        _sheet(writer, "11_Decision_Log", ["Decision_ID"], [[decision]])

    return bio.getvalue()


def main():
    arbitrary_filename = "THIS_NAME_CAN_CHANGE_EVERY_DAY_v2045.xlsx"
    payload = build_workbook()

    frames, structure = load_master_workbook(payload)
    assert validate_master(frames) == [], validate_master(frames)

    snap = master_snapshot(frames)
    assert snap["version"] == "v99.123", snap
    assert snap["decision"] == "DEC-999", snap
    assert snap["active_focs"] == 1, snap
    assert snap["mapped_focs"] == 1, snap
    assert snap["active_clusters"] == 1, snap
    assert snap["active_themes"] == 1, snap
    assert snap["active_dimensions"] == 1, snap

    page = supervisor_share_html(frames, snap)
    assert "Synthetic Dimension" in page
    assert "PCL-001" in page
    assert "Synthetic FOC" in page
    assert "Synthetic evidence" in page

    # The presentation generator never receives a workbook filename.
    assert arbitrary_filename not in page
    assert ".xlsx" not in page.lower()

    # Retired Themes remain excluded from current-state logic but can be opened explicitly for audit history.
    current_themes = active_themes(frames)
    history_themes = retired_themes(frames)
    assert current_themes["Theme_ID"].astype(str).tolist() == ["THM-001"]
    assert history_themes["Theme_ID"].astype(str).tolist() == ["THM-016"]

    current_only_tree = build_selected_themes_tree_data(frames, ["THM-016"], include_retired=False)
    assert len(current_only_tree["children"]) == 0

    audit_tree = build_selected_themes_tree_data(frames, ["THM-016"], include_retired=True)
    assert len(audit_tree["children"]) == 1
    retired_node = audit_tree["children"][0]
    assert retired_node["id"] == "THM-016"
    assert "retired" in retired_node["status"].lower()
    assert len(nodes_of_type(retired_node, "cluster")) == 1
    assert len(nodes_of_type(retired_node, "code")) == 0

    live_supervisor = build_supervisor_snapshot(frames)
    assert len(live_supervisor.get("retired_themes", [])) == 1
    assert live_supervisor["retired_themes"][0]["id"] == "THM-016"

    # Current-dimension selection must ignore retained historical/suspended rows
    # and prefer a later audited working set when canonical current statuses are absent.
    dim_test = pd.DataFrame([
        {
            "Dimension_ID": "DIM-001",
            "Candidate_Dimension_Name": "Old historical label",
            "Supporting_Theme_IDs": "THM-001; THM-002",
            "Underlying_Cluster_IDs": "PCL-001; PCL-002",
            "Dimension_Status": "Historical / Superseded – excluded from fresh SG4 derivation",
            "Analytical_Definition": "Old definition",
            "Core_Capability_Logic": "Old logic",
        },
        {
            "Dimension_ID": "DIM-007",
            "Candidate_Dimension_Name": "Suspended exploratory candidate",
            "Supporting_Theme_IDs": "THM-003",
            "Underlying_Cluster_IDs": "PCL-003",
            "Dimension_Status": "SUSPENDED – SG4 FROZEN PENDING SG2/SG3 BOUNDARY REPAIR",
            "Analytical_Definition": "Suspended definition",
            "Core_Capability_Logic": "Suspended",
        },
        {
            "Dimension_ID": "DIM-001",
            "Candidate_Dimension_Name": "Current working governance dimension",
            "Supporting_Theme_IDs": "Strategic alignment; authorization; priority decisions",
            "Underlying_Cluster_IDs": "Not listed in the working audit block",
            "Dimension_Status": "",
            "Analytical_Definition": "Set organizational direction and formal project-choice decisions.",
            "Core_Capability_Logic": "PASS – PROVISIONAL",
        },
        {
            "Dimension_ID": "DIM-001",
            "Candidate_Dimension_Name": "Boundary challenge narrative only",
            "Supporting_Theme_IDs": "",
            "Underlying_Cluster_IDs": "",
            "Dimension_Status": "",
            "Analytical_Definition": "",
            "Core_Capability_Logic": "",
        },
    ])
    dim_frames = {"08_Candidate_Dimensions": dim_test}
    current_dims = active_dimensions(dim_frames)
    assert len(current_dims) == 1
    assert current_dims.iloc[0]["Candidate_Dimension_Name"] == "Current working governance dimension"
    assert current_dims.iloc[0]["Dimension_Status"] == "PASS – PROVISIONAL"
    assert current_dims.iloc[0]["Supporting_Theme_IDs"] == "THM-001; THM-002"
    assert current_dims.iloc[0]["Underlying_Cluster_IDs"] == "PCL-001; PCL-002"

    # Selected Dimension can be exported as a complete Excel traceability package.
    export_bytes, export_summary = dimension_trace_workbook_bytes(frames, "DIM-001")
    assert export_summary["Dimension_ID"] == "DIM-001"
    assert export_summary["Theme_Count"] == 1
    assert export_summary["Cluster_Count"] == 1
    assert export_summary["FOC_Count"] == 1
    assert export_summary["Evidence_Count"] == 1
    assert export_summary["Study_Count"] == 1

    export_wb = load_workbook(BytesIO(export_bytes), read_only=True, data_only=False)
    assert export_wb.sheetnames == [
        "00_Export_Info",
        "01_Full_Trace",
        "02_Themes",
        "03_Clusters",
        "04_FOCs",
        "05_Studies",
        "06_Tree_Index",
    ]
    trace_ws = export_wb["01_Full_Trace"]
    headers = [cell.value for cell in next(trace_ws.iter_rows(min_row=1, max_row=1))]
    first_row = [cell.value for cell in next(trace_ws.iter_rows(min_row=2, max_row=2))]
    trace = dict(zip(headers, first_row))
    assert trace["Dimension_ID"] == "DIM-001"
    assert trace["Theme_ID"] == "THM-001"
    assert trace["Cluster_ID"] == "PCL-001"
    assert trace["Code_ID"] == "CD-SR001-001"
    assert trace["Evidence_ID"] == "EV001"
    assert trace["Study_ID"] == "SR001"
    assert trace["Meaning_Unit_Verbatim"] == "Synthetic evidence"

    tree_ws = export_wb["06_Tree_Index"]
    tree_values = list(tree_ws.iter_rows(min_row=2, values_only=True))
    tree_types = {row[1] for row in tree_values}
    assert {"Dimension", "Theme", "Cluster", "First-Order Code", "Meaning Unit", "Study"}.issubset(tree_types)

    # Published supervisor snapshot must load from the repository without any Excel file.
    published = load_supervisor_snapshot()
    assert published is not None
    tree = published["tree"]
    assert len(nodes_of_type(tree, "dimension")) == 4
    assert len(nodes_of_type(tree, "theme")) == 13
    assert len(nodes_of_type(tree, "cluster")) == 77
    assert len(nodes_of_type(tree, "code")) == 1277
    assert len(nodes_of_type(tree, "evidence")) == 0
    assert len(nodes_of_type(tree, "study")) == 0

    # The committed compact payload itself must not contain source-near fields or workbook references.
    parts = sorted(Path("supervisor_snapshot_chunks").glob("part*.b64"))
    assert parts
    encoded = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    compact_text = gzip.decompress(base64.b64decode(encoded)).decode("utf-8")
    for forbidden in [".xlsx", "Meaning_Unit_Verbatim", "Context_Verbatim", "Study_ID", "Evidence_ID"]:
        assert forbidden not in compact_text, forbidden

    # Researcher workbook cache persists independently of a Streamlit browser session.
    with TemporaryDirectory() as td:
        saved = save_cached_master("changing_name_v99.xlsx", payload, cache_root=td)
        assert saved["filename"] == "changing_name_v99.xlsx"
        cached = load_cached_master(cache_root=td)
        assert cached is not None
        cached_name, cached_bytes, cached_meta = cached
        assert cached_name == "changing_name_v99.xlsx"
        assert cached_bytes == payload
        assert cached_meta["sha256"] == hashlib.sha256(payload).hexdigest()
        clear_cached_master(cache_root=td)
        assert load_cached_master(cache_root=td) is None

    # Token verification is hash-based; tests never require the production raw researcher key.
    unit_secret = "unit-test-secret"
    unit_hash = hashlib.sha256(unit_secret.encode("utf-8")).hexdigest()
    assert token_matches(unit_secret, expected_hash=unit_hash)
    assert not token_matches("wrong-secret", expected_hash=unit_hash)

    # Workbook evolution is data-driven: changing metadata does not require code changes.
    frames2, _ = load_master_workbook(build_workbook(version="v2045.7", decision="DEC-2045"))
    snap2 = master_snapshot(frames2)
    assert snap2["version"] == "v2045.7", snap2
    assert snap2["decision"] == "DEC-2045", snap2

    print("SMOKE TEST PASSED")
    print(f"Sheets loaded: {len(structure)}")
    print(f"Snapshot: {snap}")
    print(f"Future snapshot: {snap2}")


if __name__ == "__main__":
    main()
