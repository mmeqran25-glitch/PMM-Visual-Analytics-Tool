# PMM Visual Analytics & Presentation Tool v0.7.0

A local Streamlit companion for the PMM dimension-derivation MASTER workbook.

## Locked workflow

**Excel MASTER is the source of truth.**

Use Excel for:
- Meaning Unit review and corrections
- First-Order Code wording/fidelity
- FOC -> Cluster decisions
- Cluster boundary / merge / split / rename decisions
- Theme and Candidate-Dimension decisions
- decision log and audit trail

Use this Python/Streamlit tool for:
- read-only visualization
- current-state metrics
- challenged/residual workload display
- structural/status summaries
- traceability demonstrations
- presentation to the supervisor/doctor
- structural/data-quality checks

The application does **not** code, reassign, merge, split, or write analytical decisions back to Excel.

## v0.7 screens

### Supervisor Presentation
1. **Executive Snapshot**
   - latest corpus checkpoint from `00_README`
   - active/mapped/challenged FOCs
   - Stable/Provisional clusters
   - active Themes
   - current Stable Candidate Dimensions
   - abstraction chain and evidence-breadth summary
2. **Derivation Tree**
   - whole structure, one Dimension, or selected Themes
   - Dimension -> Theme -> Cluster -> FOC -> Meaning Unit -> Study
   - interactive tree or org-chart presentation
   - standalone HTML export
3. **Structure Visuals**
   - interactive Sunburst
   - Dimension -> Theme Sankey flow
   - residual/unassigned structure remains visible
4. **Traceability**
   - select Dimension -> Theme -> Cluster -> FOC
   - view exact Meaning Unit, context, author term/parent construct, study/page and mapping rationale
5. **Open Decisions**
   - Challenged FOCs
   - Provisional clusters
   - unthemed active clusters
   - active Themes not assigned to a current Dimension

### Researcher Visual Analytics
Adds:
- **SG2 Review** read-only workload view
- **Themes & Dimensions** structural analysis
- **Evidence Integrity** using `04A_MU_Context_Audit` when present
- **Stability** recorded audit results
- **Data Quality** structural traceability checks

## Current-workbook compatibility

v0.7 is tested against the current `v12.98_MU_CONTEXT_RESTORATION_DEC398` structure:
- 80/132 live corpus checkpoint
- 1427 active FOCs
- 1277 mapped + 150 Challenged
- 77 active clusters (63 Stable + 14 Provisional)
- 13 Stable Themes
- 4 Stable Candidate Dimensions

These values are not hardcoded; the application recomputes analytical counts from the uploaded workbook and reads the current checkpoint/version from `00_README`.

## Windows startup

1. Extract this ZIP to a normal folder.
2. Double-click `setup_and_run_windows.bat`.
3. On first run it creates a local `.venv` and installs the required packages.
4. The browser normally opens at `http://localhost:8501`.
5. Upload the latest PMM MASTER `.xlsx` from the sidebar.
6. Choose `Supervisor Presentation` or `Researcher Visual Analytics`.

## Requirements

- Python 3
- streamlit >= 1.37
- pandas >= 2.0
- openpyxl >= 3.1
- plotly >= 5.24

## Methodological safeguards

- No write-back to the MASTER.
- Evidence breadth is descriptive, not an importance weight.
- Stable / Provisional / Challenged are analytical statuses, not validity coefficients.
- Residual and unassigned evidence is shown explicitly rather than force-fitted.
- Python visualizations never substitute for researcher judgment or Excel-recorded decisions.
