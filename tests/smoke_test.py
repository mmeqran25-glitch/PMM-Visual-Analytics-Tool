from __future__ import annotations

from io import BytesIO

import pandas as pd

from master_utils import load_master_workbook, master_snapshot, validate_master
from share_utils import supervisor_share_html


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
            [["THM-001", "Synthetic Theme", "PCL-001", "Stable", "Concept", "Boundary", ""]],
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
