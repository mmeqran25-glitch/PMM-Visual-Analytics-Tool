# PMM Visual Analytics & Presentation Tool v0.9.1

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

## v0.9.1 interaction improvements

- View and Scope choices are shown as bordered interactive cards instead of plain radio rows.
- Theme filtering uses square checkbox cards in a two-column grid.
- Includes Select all / Clear all controls and a live selected-Theme count.
- The same interaction model is used in Researcher and Supervisor views.

## Workbook compatibility

The application is intentionally **version-agnostic**. It is not tied to a specific MASTER filename, version number, decision number, or fixed analytical counts.

At runtime it:
- reads the workbook that the researcher uploads for that session;
- validates the required PMM analytical sheets/columns;
- recomputes live counts and higher-order structure from the uploaded workbook;
- reads checkpoint/version metadata from `00_README` when available;
- keeps the original workbook outside the supervisor-facing presentation output.

As the MASTER evolves, upload the latest compatible workbook and the application will rebuild the current view from that file. No application release is required merely because the workbook version number changes.

## Public supervisor vs researcher workflow

The deployed application now separates the two use cases:

- **Default/public link**: supervisor presentation only. No Excel upload control is shown. The app reads a sanitized published snapshot containing Candidate Dimensions, Themes, active Clusters and First-Order Codes.
- **Researcher workspace**: open the same app with `?view=researcher`. Upload any current compatible MASTER workbook. The workbook filename/version can change freely.
- **Private refresh-safe researcher link**: use `?view=researcher&key=<private-key>`. After a workbook passes validation, the app stores a temporary private server-side copy outside GitHub so browser Refresh can reuse it. The cached MASTER can be cleared with **Forget cached MASTER** and may also disappear automatically when Streamlit restarts or redeploys.

The published supervisor snapshot intentionally excludes:
- the original XLSX workbook and workbook filename;
- Meaning Unit verbatim text and Context verbatim text;
- Study/source nodes and Evidence IDs;
- any write-back capability.

Residual active clusters that are not yet assigned to an active Theme remain visible under an explicit **Residual / not force-fitted** branch, so the presentation does not hide unresolved structure or force premature higher-order assignments.

When the MASTER changes, regenerate/publish a new sanitized snapshot. The application code itself does not need to change merely because the workbook filename, version number, decision number, counts or memberships change.

### Researcher cache privacy

The refresh-safe researcher cache is intentionally separate from the public supervisor snapshot:
- only a URL containing the private researcher key may read/write the cached MASTER;
- only the SHA-256 hash of that key is committed to GitHub;
- the original XLSX is stored only in temporary server storage, never in the repository;
- invalid uploads never replace the previous validated cached MASTER;
- the cache is temporary rather than archival storage and should not be treated as a backup.

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
