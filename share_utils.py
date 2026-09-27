from __future__ import annotations

import html
from typing import Any, Dict

import pandas as pd

from master_utils import current_dimension_evidence_summary, master_snapshot
from tree_utils import build_candidate_stage_tree_data, tree_html


def _safe(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return html.escape(str(value))


def _metric_card(label: str, value: Any, note: str = "") -> str:
    note_html = f'<div class="share-note">{_safe(note)}</div>' if note else ""
    return (
        '<div class="share-card">'
        f'<div class="share-value">{_safe(value)}</div>'
        f'<div class="share-label">{_safe(label)}</div>'
        f'{note_html}'
        '</div>'
    )


def _dimension_table(frames: Dict[str, pd.DataFrame]) -> str:
    df = current_dimension_evidence_summary(frames)
    if df.empty:
        return '<p class="share-muted">No current candidate dimensions are recorded.</p>'

    cols = [
        c for c in [
            "Dimension_ID",
            "Candidate_Dimension_Name",
            "Dimension_Status",
            "Themes",
            "Clusters",
            "FOCs",
            "Studies",
        ]
        if c in df.columns
    ]
    view = df[cols].copy()
    headers = "".join(f"<th>{_safe(c.replace('_', ' '))}</th>" for c in cols)
    rows = []
    for _, row in view.iterrows():
        cells = "".join(f"<td>{_safe(row.get(c, ''))}</td>" for c in cols)
        rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="share-table-wrap"><table class="share-table">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def supervisor_share_html(
    frames: Dict[str, pd.DataFrame],
    snapshot: Dict[str, Any] | None = None,
) -> str:
    """Create a self-contained, read-only supervisor presentation.

    The exported HTML contains only the presentation data rendered by the app.
    It does not contain the original XLSX workbook and it performs no write-back.
    """
    snapshot = snapshot or master_snapshot(frames)
    tree = build_candidate_stage_tree_data(frames, include_unassigned_themes=True)
    title = "PMM Dimension-Derivation Supervisor Presentation"
    if snapshot.get("version"):
        title += f" - {snapshot['version']}"

    metrics = [
        _metric_card("Active FOCs", snapshot.get("active_focs", 0), f"{snapshot.get('mapped_focs', 0)} mapped"),
        _metric_card("Challenged FOCs", snapshot.get("challenged_focs", 0)),
        _metric_card("Active Clusters", snapshot.get("active_clusters", 0), f"{snapshot.get('provisional_clusters', 0)} provisional"),
        _metric_card("Active Themes", snapshot.get("active_themes", 0), f"{snapshot.get('stable_themes', 0)} stable"),
        _metric_card("Current Dimensions", snapshot.get("active_dimensions", 0), f"{snapshot.get('stable_dimensions', 0)} stable"),
    ]

    corpus = ""
    if snapshot.get("completed") is not None and snapshot.get("target"):
        corpus = (
            f"<p><b>Corpus checkpoint:</b> {_safe(snapshot.get('completed'))} / "
            f"{_safe(snapshot.get('target'))}"
            + (
                f" ({float(snapshot.get('percent')):.1f}%)"
                if snapshot.get("percent") is not None
                else ""
            )
            + "</p>"
        )

    decision = ""
    if snapshot.get("decision"):
        decision = f"<p><b>Current decision:</b> {_safe(snapshot.get('decision'))}</p>"

    next_action = ""
    if snapshot.get("next_action"):
        next_action = (
            '<div class="share-callout"><b>Workbook next action:</b> '
            f"{_safe(snapshot.get('next_action'))}</div>"
        )

    tree_body = tree_html(tree, title="Interactive Traceable Derivation Tree", standalone=False)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_safe(title)}</title>
<style>
html, body {{ margin:0; background:#fff; color:#17324d; font-family:Inter,Segoe UI,Arial,sans-serif; }}
.share-shell {{ max-width:1500px; margin:0 auto; padding:24px 22px 50px; }}
.share-kicker {{ font-size:11px; font-weight:800; letter-spacing:.11em; text-transform:uppercase; color:#5f7892; }}
.share-title {{ font-size:30px; line-height:1.2; font-weight:850; color:#12385e; margin:5px 0 8px; }}
.share-sub {{ color:#62778c; line-height:1.5; }}
.share-privacy {{ margin:16px 0; padding:11px 13px; border-left:5px solid #238636; border-radius:9px; background:#f1fbf4; }}
.share-metrics {{ display:grid; grid-template-columns:repeat(5,minmax(150px,1fr)); gap:10px; margin:18px 0 24px; }}
.share-card {{ border:1px solid #d8e4ef; background:#fbfdff; border-radius:14px; padding:14px; min-height:84px; }}
.share-value {{ font-size:25px; font-weight:850; color:#12385e; }}
.share-label {{ font-size:12px; color:#5f7489; font-weight:750; margin-top:4px; }}
.share-note {{ font-size:11px; color:#7a8c9e; margin-top:4px; }}
.share-section {{ margin-top:28px; }}
.share-section h2 {{ color:#12385e; margin-bottom:8px; }}
.share-muted {{ color:#6c7f91; }}
.share-callout {{ padding:11px 13px; border-left:5px solid #4c83b6; background:#f5f9fd; border-radius:9px; margin:14px 0; }}
.share-table-wrap {{ overflow:auto; border:1px solid #dbe5ef; border-radius:12px; }}
.share-table {{ width:100%; border-collapse:collapse; font-size:13px; }}
.share-table th {{ text-align:left; background:#f3f7fb; color:#36536e; padding:10px; border-bottom:1px solid #dbe5ef; }}
.share-table td {{ padding:10px; border-bottom:1px solid #edf2f6; vertical-align:top; }}
.share-table tr:last-child td {{ border-bottom:none; }}
@media (max-width:900px) {{
  .share-metrics {{ grid-template-columns:repeat(2,minmax(150px,1fr)); }}
  .share-title {{ font-size:24px; }}
}}
</style>
</head>
<body>
<div class="share-shell">
  <div class="share-kicker">Supervisor presentation - read only</div>
  <div class="share-title">{_safe(title)}</div>
  <div class="share-sub">
    Traceable presentation of the current PMM dimension-derivation structure.
    This export is generated from the researcher's current MASTER but is not the MASTER workbook.
  </div>
  <div class="share-privacy">
    <b>Privacy:</b> this HTML file does not contain the original Excel workbook and cannot modify it.
    It contains the evidence and analytical fields required for this presentation view only.
  </div>
  {corpus}
  {decision}
  <div class="share-metrics">{''.join(metrics)}</div>
  {next_action}
  <div class="share-section">
    <h2>Current Candidate Dimensions</h2>
    {_dimension_table(frames)}
  </div>
  <div class="share-section">
    <h2>Interactive Derivation Tree</h2>
    <p class="share-muted">Search by IDs such as PCL-038, THM-008, DIM-001, or by evidence text. Expand branches to trace Dimension -> Theme -> Cluster -> FOC -> Meaning Unit -> Study.</p>
    {tree_body}
  </div>
</div>
</body>
</html>
"""
