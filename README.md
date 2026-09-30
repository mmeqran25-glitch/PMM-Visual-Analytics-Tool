# PMM Visual Analytics & Presentation Tool v0.12.2

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

## v0.9.2 retired Theme audit history

- Current Themes remain the default and continue to drive all current counts and Candidate-Dimension logic.
- A **Show retired Themes — audit history** checkbox reveals historical retired Themes in a separate section.
- Retired Themes are clearly labelled **[RETIRED]** and **Historical audit only**.
- Selecting a retired Theme does not reactivate it or include it in the current analytical structure.
- Historical Theme views stop at the Theme → PCL reference level so current FOC memberships are not misrepresented as historical memberships.

## v0.9.3 compact Theme dropdown

- Theme selection now uses one compact dropdown/popover instead of displaying every Theme as a full-page card.
- Open the dropdown and tick ✓ the required Themes; the page remains compact when the dropdown is closed.
- Includes Select all current / Clear current controls and a selected-Theme count.
- Retired Themes remain inside the same dropdown under the optional **Show retired Themes — audit history** section.
- The same compact Theme selector is used in Researcher and Supervisor views.

## v0.9.4 performance and current-structure fixes

- Researcher navigation now executes only the section being viewed instead of recalculating all eight pages on every Streamlit rerun.
- Sanitized supervisor snapshot generation is cached per workbook instead of being rebuilt after every Theme/filter click.
- Org-chart rendering is depth-limited by scope: the whole-structure view stops at Cluster/PCL, while focused Dimension/Theme views continue to First-Order Code. Meaning Unit and Study drill-down remains available in the interactive evidence tree.
- Downloadable HTML is generated only when explicitly requested, avoiding a second full chart build on every rerun.
- Supervisor Preview uses the same cached package and single-section navigation.
- Candidate-dimension selection excludes Historical/Superseded/Suspended rows and can recover the latest audited working SG4 candidate set when a workbook retains older dimension generations for audit history.

## v0.10.0 Dimension traceability Excel export

- The Traceability page can export any selected current Candidate Dimension to a standalone XLSX workbook.
- Export lineage: **Dimension → Theme → PCL/Cluster → First-Order Code → Meaning Unit → Study**.
- The workbook contains: Export Info, Full Trace, Themes, Clusters/PCLs, FOCs, Studies and a hierarchical Tree Index.
- The export is generated on demand and never writes back to the analytical MASTER.
- Long verbatim evidence is Excel-safe and the workbook preserves current mapping/status fields for audit review.

## v0.11.0 Research Evidence BI Dashboard

Adds a dedicated researcher-only BI workspace that describes the evidence corpus rather than the Dimension hierarchy.

### Research Corpus Overview
- separates Source records, Profiled Studies, Evidence Contributors and Pass Contributors;
- analytical funnel from current filter → Eligible → Evidence contributors → Pass contributors;
- study-profile metadata completeness;
- publication-year and sector-context summaries.

### Time & Context Explorer
- studies by year and cumulative corpus growth;
- methodological-family trends over time;
- top country and sector contexts;
- Country × Sector coverage matrix;
- explicit warnings when context metadata are incomplete.

### Evidence & Quality
- study-level eligibility distribution;
- evidence-level Pass / Supporting / Architecture gate distribution;
- top Pass-evidence contributors;
- Pareto contribution view;
- QA score × evidence contribution scatter.

### Novelty & Stability
- study-level novelty/reinforcement events over extraction order;
- New FOC / New Cluster / Boundary Change / Split-Merge / Reinforcement tracking;
- cumulative structural novelty;
- explicit safeguard that the view is not an automatic saturation claim.

### BI safeguards
- Dashboard filters include Study Universe, year, country, sector, methodology and publication grouping.
- Drill-through tables expose the studies behind every current filter.
- BI methodology/publication groupings are display categories only; original workbook wording remains unchanged.
- The dashboard never writes back to the MASTER.

## v0.12.0 Academic thesis identity and interface polish

- Adds a shared academic identity header to Researcher and Supervisor views.
- Main Arabic title: **رسالة ماجستير للباحث – معاذ عبدالقوي عباس مقران**.
- Uses the official Sana'a University and Faculty of Engineering logo assets hosted on the university domain.
- Adds a responsive academic header with research-purpose badges, current workspace mode and app version.
- Adds a compact researcher identity card in the sidebar and an academic footer.
- Replaces repeated large application titles with compact workspace strips to preserve vertical space for charts and derivation trees.
- Restyles KPI cards, sidebar, expanders and controls with a restrained academic visual system.
- Responsive layout keeps both logos and the thesis identity readable on narrower screens.
- The interface explicitly presents itself as a thesis/research workspace and does not imply that the application is an official university administrative system.

## v0.12.1 Branding render fix

- Fixes the academic header being interpreted as a Markdown code block and showing raw `<div>` / `<img>` markup.
- Renders header, sidebar identity and footer as compact uninterrupted HTML fragments.
- Adds graceful logo fallbacks so a temporary external image failure shows a clean university/faculty label instead of a broken-image icon.
- Preserves the v0.12 academic identity, responsive layout and researcher/supervisor separation.

## v0.12.2 Resilient academic logo tiles

- Replaces external `<img>` tags with CSS background-image tiles so a failed remote image never produces a broken-image icon or alt-text clutter.
- Uses a Wikimedia-hosted Sana'a University logo for reliable public rendering and the current official Sana'a University Faculty of Engineering image path.
- Keeps visible bilingual captions under both logo areas even if an image source is temporarily unavailable.
- Preserves the responsive academic header and all v0.12 branding.

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
