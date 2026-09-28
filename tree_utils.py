from __future__ import annotations

import html
import json
from typing import Dict, Any, List

import pandas as pd

from master_utils import active_themes, retired_themes, active_dimensions, cluster_members, split_ids


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _short(value: Any, n: int = 130) -> str:
    s = _text(value)
    return s if len(s) <= n else s[: n - 1] + "…"


def _study_for_row(row: pd.Series) -> str:
    for c in ["Study_ID", "Study_ID_coding", "Study_ID_evidence"]:
        if c in row.index and _text(row.get(c)):
            return _text(row.get(c))
    return ""


def _study_title(frames: Dict[str, pd.DataFrame], study_id: str) -> str:
    """Best-effort lookup of a human-readable study title from the source register/profile."""
    if not study_id:
        return ""
    candidate_cols = [
        "Study_Title", "Title", "Source_Title", "Publication_Title",
        "Article_Title", "Document_Title", "Study_Name"
    ]
    for sheet in ["01_Source_Register", "03_Study_Profile"]:
        df = frames.get(sheet, pd.DataFrame())
        if df.empty or "Study_ID" not in df.columns:
            continue
        hit = df[df["Study_ID"].astype(str).str.strip() == str(study_id).strip()]
        if hit.empty:
            continue
        row = hit.iloc[0]
        for col in candidate_cols:
            if col in row.index and _text(row.get(col)):
                return _text(row.get(col))
    return ""


def _study_node(frames: Dict[str, pd.DataFrame], study_id: str) -> Dict[str, Any]:
    title = _study_title(frames, study_id)
    return {
        "type": "study",
        "id": study_id,
        "label": title or "Original study/source",
        "status": "",
        "meta": {},
        "children": [],
    }


def build_theme_tree_data(frames: Dict[str, pd.DataFrame], theme_id: str) -> Dict[str, Any]:
    themes = frames.get("07_Descriptive_Themes", pd.DataFrame())
    creg = frames.get("06A_Cluster_Register", pd.DataFrame())
    if themes.empty:
        return {}
    match = themes[themes.get("Theme_ID", pd.Series(dtype=str)).astype(str).str.strip() == str(theme_id).strip()]
    if match.empty:
        return {}
    tr = match.iloc[0]
    historical_theme = "retired" in _text(tr.get("Theme_Status")).lower()
    root = {
        "type": "theme",
        "id": _text(tr.get("Theme_ID")),
        "label": _text(tr.get("Working_Theme_Label")),
        "status": _text(tr.get("Theme_Status")),
        "meta": {
            "Central organizing concept": _text(tr.get("Central_Organizing_Concept")),
            "Theme boundary": _text(tr.get("Theme_Boundary")),
            "Closest competing theme": _text(tr.get("Closest_Competing_Theme")),
            "Historical audit only": (
                "Yes — retired Theme; excluded from the current Theme set and Candidate-Dimension logic."
                if "retired" in _text(tr.get("Theme_Status")).lower()
                else ""
            ),
        },
        "children": [],
    }
    for cid in split_ids(tr.get("Included_Cluster_IDs"), "PCL"):
        crs = creg[creg.get("Cluster_ID", pd.Series(dtype=str)).astype(str).str.strip() == cid] if not creg.empty else pd.DataFrame()
        cr = crs.iloc[0] if not crs.empty else pd.Series(dtype=object)
        cnode = {
            "type": "cluster",
            "id": cid,
            "label": _text(cr.get("Working_Cluster_Label")),
            "status": _text(cr.get("Cluster_Status")),
            "meta": {
                "Core function": _text(cr.get("Core_Organizational_Function")),
                "Operational definition": _text(cr.get("Operational_Definition")),
                "Inclusion boundary": _text(cr.get("Inclusion_Boundary")),
                "Exclusion boundary": _text(cr.get("Exclusion_Boundary")),
                "Nearest conceptual neighbours": _text(cr.get("Nearest_Conceptual_Neighbours")),
                "Historical audit note": (
                    "This PCL reference is read from the retired Theme row. "
                    "Current FOC memberships are intentionally not expanded in historical audit mode."
                    if historical_theme else ""
                ),
            },
            "children": [],
        }
        members = pd.DataFrame() if historical_theme else cluster_members(frames, cid)
        if not members.empty:
            # One node per code; if duplicate mappings exist, retain first current row.
            if "Code_ID" in members.columns:
                members = members.drop_duplicates(subset=["Code_ID"], keep="first")
            for _, r in members.iterrows():
                code_id = _text(r.get("Code_ID"))
                study = _study_for_row(r)
                enode = {
                    "type": "evidence",
                    "id": _text(r.get("Evidence_ID")),
                    "label": _text(r.get("Meaning_Unit_Verbatim")),
                    "status": _text(r.get("PM_Practice_Maturity_Evidence_Gate")),
                    "meta": {
                        "Original author term": _text(r.get("Original_Author_Term")),
                        "Author parent construct": _text(r.get("Author_Parent_Construct")),
                        "Author-defined relationship": _text(r.get("Author_Defined_Relationship")),
                        "Printed page": _text(r.get("Printed_Page")),
                    },
                    "children": [_study_node(frames, study)] if study else [],
                }
                code_node = {
                    "type": "code",
                    "id": code_id,
                    "label": _text(r.get("First_Order_Code")),
                    "status": _text(r.get("Code_Fidelity_Status")),
                    "meta": {
                        "Mapping status": _text(r.get("Mapping_Status")),
                        "Mapping rationale": _text(r.get("Mapping_Rationale")),
                        "Boundary rationale": _text(r.get("Boundary_Rationale")),
                        "Closest competing cluster": _text(r.get("Closest_Competing_Cluster")),
                    },
                    "children": [enode],
                }
                cnode["children"].append(code_node)
        root["children"].append(cnode)
    return root


def build_cluster_tree_data(frames: Dict[str, pd.DataFrame], cluster_id: str) -> Dict[str, Any]:
    creg = frames.get("06A_Cluster_Register", pd.DataFrame())
    crs = creg[creg.get("Cluster_ID", pd.Series(dtype=str)).astype(str).str.strip() == str(cluster_id).strip()] if not creg.empty else pd.DataFrame()
    if crs.empty:
        return {}
    cr = crs.iloc[0]
    root = {
        "type": "cluster",
        "id": _text(cr.get("Cluster_ID")),
        "label": _text(cr.get("Working_Cluster_Label")),
        "status": _text(cr.get("Cluster_Status")),
        "meta": {
            "Core function": _text(cr.get("Core_Organizational_Function")),
            "Operational definition": _text(cr.get("Operational_Definition")),
            "Inclusion boundary": _text(cr.get("Inclusion_Boundary")),
            "Exclusion boundary": _text(cr.get("Exclusion_Boundary")),
            "Nearest conceptual neighbours": _text(cr.get("Nearest_Conceptual_Neighbours")),
        },
        "children": [],
    }
    members = cluster_members(frames, cluster_id)
    if not members.empty:
        if "Code_ID" in members.columns:
            members = members.drop_duplicates(subset=["Code_ID"], keep="first")
        for _, r in members.iterrows():
            study = _study_for_row(r)
            evidence = {
                "type": "evidence",
                "id": _text(r.get("Evidence_ID")),
                "label": _text(r.get("Meaning_Unit_Verbatim")),
                "status": _text(r.get("PM_Practice_Maturity_Evidence_Gate")),
                "meta": {
                    "Original author term": _text(r.get("Original_Author_Term")),
                    "Author parent construct": _text(r.get("Author_Parent_Construct")),
                    "Author-defined relationship": _text(r.get("Author_Defined_Relationship")),
                    "Printed page": _text(r.get("Printed_Page")),
                },
                "children": [_study_node(frames, study)] if study else [],
            }
            root["children"].append({
                "type": "code",
                "id": _text(r.get("Code_ID")),
                "label": _text(r.get("First_Order_Code")),
                "status": _text(r.get("Code_Fidelity_Status")),
                "meta": {
                    "Mapping status": _text(r.get("Mapping_Status")),
                    "Mapping rationale": _text(r.get("Mapping_Rationale")),
                    "Boundary rationale": _text(r.get("Boundary_Rationale")),
                    "Closest competing cluster": _text(r.get("Closest_Competing_Cluster")),
                },
                "children": [evidence],
            })
    return root



def build_dimension_tree_data(frames: Dict[str, pd.DataFrame], dimension_id: str) -> Dict[str, Any]:
    """Build Dimension → Theme → Cluster → Code → Evidence → Study tree."""
    dims = active_dimensions(frames)
    if dims.empty:
        return {}
    match = dims[dims.get("Dimension_ID", pd.Series(dtype=str)).astype(str).str.strip() == str(dimension_id).strip()]
    if match.empty:
        return {}
    dr = match.iloc[0]
    root = {
        "type": "dimension",
        "id": _text(dr.get("Dimension_ID")),
        "label": _text(dr.get("Candidate_Dimension_Name")),
        "status": _text(dr.get("Dimension_Status")),
        "meta": {
            "Analytical definition": _text(dr.get("Analytical_Definition")),
            "Core capability logic": _text(dr.get("Core_Capability_Logic")),
            "Evidence breadth": _text(dr.get("Evidence_Breadth")),
            "Cross-model support": _text(dr.get("Cross_Model_Support")),
            "Cross-context support": _text(dr.get("Cross_Context_Support")),
            "Measurement evidence": _text(dr.get("Measurement_Evidence_Link")),
            "Boundary / contradictory evidence": _text(dr.get("Contradictory_or_Boundary_Evidence")),
            "Notes": _text(dr.get("Notes")),
        },
        "children": [],
    }
    for tid in split_ids(dr.get("Supporting_Theme_IDs"), "THM"):
        tnode = build_theme_tree_data(frames, tid)
        if tnode:
            root["children"].append(tnode)
    return root


def build_candidate_stage_tree_data(
    frames: Dict[str, pd.DataFrame],
    include_unassigned_themes: bool = True,
    include_unthemed_clusters: bool = True,
) -> Dict[str, Any]:
    """Build a presentation tree rooted at 08_Candidate_Dimensions.

    Current non-retired Candidate Dimensions are shown exactly as recorded in the
    workbook. Active Themes not yet assigned to a current Dimension remain under
    a separate under-review branch. Active clusters not currently assigned to any
    active Theme are also retained explicitly as residual / not force-fitted
    material so no current PCL disappears from the whole-structure view.
    """
    dims = active_dimensions(frames)
    themes = active_themes(frames)

    assigned_theme_ids = set()
    for _, r in dims.iterrows():
        assigned_theme_ids.update(split_ids(r.get("Supporting_Theme_IDs"), "THM"))

    active_theme_ids = set(
        themes.get("Theme_ID", pd.Series(dtype=str)).dropna().astype(str).str.strip()
    ) if not themes.empty else set()
    unassigned = sorted(t for t in active_theme_ids if t and t not in assigned_theme_ids)

    themed_cluster_ids = set()
    if not themes.empty:
        for _, r in themes.iterrows():
            themed_cluster_ids.update(split_ids(r.get("Included_Cluster_IDs"), "PCL"))

    creg = frames.get("06A_Cluster_Register", pd.DataFrame()).copy()
    active_cluster_ids = set()
    if not creg.empty and "Cluster_ID" in creg.columns:
        ids = creg["Cluster_ID"].fillna("").astype(str).str.strip()
        mask = ids.str.match(r"^PCL-\d{3}$", case=False, na=False)
        if "Cluster_Status" in creg.columns:
            mask &= ~creg["Cluster_Status"].fillna("").astype(str).str.contains(
                "Retired|Dissolved", case=False, regex=True
            )
        active_cluster_ids = set(creg.loc[mask, "Cluster_ID"].astype(str).str.strip())

    unthemed = sorted(
        cid for cid in active_cluster_ids
        if cid and cid not in themed_cluster_ids
    )

    root = {
        "type": "stage",
        "id": "08_Candidate_Dimensions",
        "label": "Candidate Dimensions — current recorded structure",
        "status": "READ-ONLY CURRENT STRUCTURE",
        "meta": {
            "Candidate dimensions": str(len(dims)),
            "Active descriptive themes": str(len(themes)),
            "Themes already linked to candidate dimensions": str(len(assigned_theme_ids & active_theme_ids)),
            "Active themes still under review": str(len(unassigned)),
            "Active clusters not yet assigned to a Theme": str(len(unthemed)),
            "Interpretation": (
                "Dimension status is shown exactly as recorded in the MASTER. "
                "Residual Themes and clusters remain visible rather than being force-fitted."
            ),
        },
        "children": [],
    }

    for _, r in dims.iterrows():
        did = _text(r.get("Dimension_ID"))
        dnode = build_dimension_tree_data(frames, did)
        if dnode:
            root["children"].append(dnode)

    if include_unassigned_themes and unassigned:
        group = {
            "type": "group",
            "id": "SG4-UNDER-REVIEW",
            "label": "Active descriptive Themes not yet assigned to a current Dimension",
            "status": "Under review",
            "meta": {
                "Purpose": "Keeps unresolved theme neighbourhoods visible without forcing them into a premature dimension.",
            },
            "children": [],
        }
        for tid in unassigned:
            tnode = build_theme_tree_data(frames, tid)
            if tnode:
                group["children"].append(tnode)
        root["children"].append(group)

    if include_unthemed_clusters and unthemed:
        residual = {
            "type": "group",
            "id": "SG3-UNTHEMED-CLUSTERS",
            "label": "Active clusters not yet assigned to an active Theme",
            "status": "Residual / not force-fitted",
            "meta": {
                "Purpose": (
                    "Preserves active cluster evidence that has not yet passed into a current Theme. "
                    "No higher-order assignment is implied."
                ),
            },
            "children": [],
        }
        for cid in unthemed:
            cnode = build_cluster_tree_data(frames, cid)
            if cnode:
                residual["children"].append(cnode)
        root["children"].append(residual)

    return root


def build_selected_themes_tree_data(
    frames: Dict[str, pd.DataFrame],
    theme_ids: List[str],
    include_retired: bool = False,
) -> Dict[str, Any]:
    """Build a flexible presentation tree for selected Themes.

    By default only current active Themes are eligible. Retired Themes can be
    included explicitly for historical audit review; doing so never promotes
    them back into the current Theme set or Candidate-Dimension logic.
    """
    themes = active_themes(frames)
    available = set(
        themes.get("Theme_ID", pd.Series(dtype=str)).dropna().astype(str).str.strip()
    ) if not themes.empty else set()

    retired_ids = set()
    if include_retired:
        historical = retired_themes(frames)
        retired_ids = set(
            historical.get("Theme_ID", pd.Series(dtype=str)).dropna().astype(str).str.strip()
        ) if not historical.empty else set()
        available |= retired_ids

    selected = []
    seen = set()
    for tid in theme_ids or []:
        tid = _text(tid)
        if tid and tid in available and tid not in seen:
            selected.append(tid)
            seen.add(tid)

    historical_selected = [tid for tid in selected if tid in retired_ids]
    root = {
        "type": "group",
        "id": "SELECTED-THEMES",
        "label": f"Selected descriptive themes ({len(selected)})",
        "status": "Flexible view",
        "meta": {
            "Purpose": "Presentation view for selecting and comparing Themes without implying a new analytical grouping.",
            "Analytical status": "Current Theme definitions are read directly from the uploaded MASTER workbook.",
            "Retired Themes": (
                f"{len(historical_selected)} selected for historical audit only; excluded from current higher-order structure."
                if historical_selected
                else "None selected."
            ),
        },
        "children": [],
    }

    for tid in selected:
        node = build_theme_tree_data(frames, tid)
        if node:
            root["children"].append(node)
    return root

def _count_types(node: Dict[str, Any], counts: Dict[str, int] | None = None) -> Dict[str, int]:
    if counts is None:
        counts = {}
    t = node.get("type", "node")
    counts[t] = counts.get(t, 0) + 1
    for c in node.get("children", []):
        _count_types(c, counts)
    return counts


def tree_html(tree: Dict[str, Any], title: str = "Code & Evidence Tree", standalone: bool = False) -> str:
    if not tree:
        return "<p>No tree data available.</p>"
    data = json.dumps(tree, ensure_ascii=False)
    counts = _count_types(tree)
    counts_text = " · ".join(f"{k}: {v}" for k, v in counts.items())
    body = f'''
<div id="pmmTree" class="pmm-tree-app">
  <div class="tree-toolbar">
    <div>
      <div class="tree-kicker">TRACEABLE ANALYTICAL HIERARCHY</div>
      <div class="tree-title">{html.escape(title)}</div>
      <div class="tree-counts">{html.escape(counts_text)}</div>
    </div>
    <div class="tree-actions">
      <button type="button" id="expandAll">Expand all</button>
      <button type="button" id="collapseAll">Collapse all</button>
    </div>
  </div>
  <label class="search-label" for="treeSearch">Search IDs or text</label>
  <input id="treeSearch" class="tree-search" placeholder="e.g., PCL-038, DIM-002, THM-004, lessons learned" />
  <div id="treeMessage" class="tree-message" aria-live="polite"></div>
  <div id="treeHost" class="tree-host"></div>
</div>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin:0; font-family: Inter, Segoe UI, Arial, sans-serif; background:#fff; color:#17324d; }}
  .pmm-tree-app {{ padding:10px 14px 18px; }}
  .tree-toolbar {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-end; padding:14px 16px; border:1px solid #d9e4ef; border-radius:14px; background:#f8fbfe; }}
  .tree-kicker {{ font-size:11px; letter-spacing:.11em; font-weight:800; color:#5f7892; }}
  .tree-title {{ font-size:22px; font-weight:800; color:#12385e; margin-top:3px; }}
  .tree-counts {{ font-size:12px; color:#687d91; margin-top:5px; }}
  .tree-actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
  button {{ border:1px solid #b9cadb; background:white; border-radius:9px; padding:8px 11px; color:#173c61; font-weight:650; cursor:pointer; }}
  button:hover {{ background:#edf5fb; }}
  .search-label {{ display:block; font-size:12px; color:#61758a; font-weight:700; margin:14px 0 5px; }}
  .tree-search {{ box-sizing:border-box; width:100%; border:1px solid #cbd9e6; border-radius:10px; padding:10px 12px; font-size:14px; outline:none; }}
  .tree-search:focus {{ border-color:#5d89b7; box-shadow:0 0 0 3px rgba(93,137,183,.13); }}
  .tree-message {{ min-height:20px; color:#6b7d90; font-size:12px; padding:5px 2px; }}
  .tree-host {{ margin-top:4px; }}
  .tree-node {{ position:relative; margin-left:18px; padding-left:18px; }}
  .tree-node::before {{ content:""; position:absolute; left:3px; top:0; bottom:0; width:1px; background:#d4e0ea; }}
  .tree-node:last-child::before {{ bottom:22px; }}
  .tree-node::after {{ content:""; position:absolute; left:3px; top:22px; width:14px; height:1px; background:#d4e0ea; }}
  details {{ margin:5px 0; }}
  summary {{ list-style:none; cursor:pointer; display:flex; gap:9px; align-items:flex-start; padding:9px 10px; border:1px solid #dde6ee; border-radius:11px; background:white; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary:hover {{ background:#f8fbfd; }}
  .toggle {{ width:18px; height:18px; flex:0 0 18px; border-radius:4px; display:grid; place-items:center; background:#edf3f8; color:#315b80; font-weight:900; margin-top:1px; }}
  details[open] > summary .toggle::before {{ content:"−"; }}
  details:not([open]) > summary .toggle::before {{ content:"+"; }}
  .leaf .toggle::before {{ content:"•" !important; }}
  .node-main {{ min-width:0; flex:1; }}
  .node-top {{ display:flex; gap:7px; align-items:center; flex-wrap:wrap; }}
  .node-id {{ font-weight:850; color:#173f66; }}
  .node-sep {{ color:#7d8fa1; font-weight:700; }}
  .node-label {{ color:#263f57; line-height:1.32; font-weight:650; }}
  .badge {{ font-size:10px; font-weight:800; border-radius:999px; padding:3px 7px; background:#edf2f7; color:#52687d; }}
  .type-stage {{ border-left:6px solid #12385e; background:#f3f8fd; }}
  .type-dimension {{ border-left:6px solid #e58b2a; background:#fffaf3; }}
  .type-group {{ border-left:6px solid #9aa9b7; background:#fafbfc; }}
  .type-theme {{ border-left:5px solid #7a5ab7; }}
  .type-cluster {{ border-left:5px solid #2c8c78; }}
  .type-code {{ border-left:5px solid #2e74b5; }}
  .type-evidence {{ border-left:5px solid #c58a21; }}
  .type-study {{ border-left:5px solid #76889a; }}
  .node-meta {{ margin:4px 0 8px 38px; padding:8px 10px; border-left:2px solid #e3eaf1; color:#52677b; font-size:12px; line-height:1.45; }}
  .meta-row {{ margin:3px 0; }}
  .meta-key {{ font-weight:800; color:#40596f; }}
  .children {{ margin-left:4px; }}
  .match > summary {{ box-shadow:0 0 0 2px #f2c94c inset; background:#fffdf1; }}
  .hidden-by-search {{ display:none !important; }}
  @media (max-width: 700px) {{ .tree-toolbar {{ align-items:flex-start; flex-direction:column; }} .tree-title {{ font-size:18px; }} .tree-node {{ margin-left:8px; padding-left:12px; }} .node-meta {{ margin-left:20px; }} }}
</style>
<script>
(() => {{
  const root = document.getElementById('pmmTree');
  if (!root || root.dataset.ready === '1') return;
  root.dataset.ready = '1';
  const tree = {data};
  const host = root.querySelector('#treeHost');
  const esc = s => String(s ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
  function nodeHTML(n, depth=0) {{
    const kids = Array.isArray(n.children) ? n.children : [];
    const meta = n.meta || {{}};
    const status = n.status ? `<span class="badge">${{esc(n.status)}}</span>` : '';
    const searchable = [n.id,n.label,n.status,...Object.values(meta)].join(' ').toLowerCase();
    const metaRows = Object.entries(meta).filter(([,v]) => String(v||'').trim()).map(([k,v]) => `<div class="meta-row"><span class="meta-key">${{esc(k)}}:</span> ${{esc(v)}}</div>`).join('');
    const isLeaf = kids.length === 0;
    return `<div class="tree-node" data-search="${{esc(searchable)}}">
      <details ${{depth < 2 ? 'open' : ''}}>
        <summary class="type-${{esc(n.type||'node')}} ${{isLeaf ? 'leaf' : ''}}">
          <span class="toggle"></span>
          <span class="node-main"><span class="node-top"><span class="node-id">${{esc(n.id||n.type)}}</span><span class="node-sep">—</span><span class="node-label">${{esc(n.label||'')}}</span>${{status}}</span></span>
        </summary>
        ${{metaRows ? `<div class="node-meta">${{metaRows}}</div>` : ''}}
        ${{kids.length ? `<div class="children">${{kids.map(c => nodeHTML(c, depth+1)).join('')}}</div>` : ''}}
      </details>
    </div>`;
  }}
  host.innerHTML = nodeHTML(tree);
  const allDetails = () => [...host.querySelectorAll('details')];
  root.querySelector('#expandAll').addEventListener('click', () => allDetails().forEach(d => d.open = true));
  root.querySelector('#collapseAll').addEventListener('click', () => {{ allDetails().forEach(d => d.open = false); const first=host.querySelector('details'); if(first) first.open=true; }});
  const search = root.querySelector('#treeSearch');
  const msg = root.querySelector('#treeMessage');
  search.addEventListener('input', () => {{
    const q = search.value.trim().toLowerCase();
    const nodes = [...host.querySelectorAll('.tree-node')];
    nodes.forEach(n => n.classList.remove('match','hidden-by-search'));
    if (!q) {{ msg.textContent=''; return; }}
    let matched = 0;
    nodes.forEach(n => {{
      if ((n.dataset.search||'').includes(q)) {{
        n.classList.add('match'); matched++;
        let p=n.parentElement;
        while(p && p!==host) {{ if(p.tagName==='DETAILS') p.open=true; p=p.parentElement; }}
      }}
    }});
    msg.textContent = matched ? `${{matched}} matching node(s); matching branches were expanded.` : 'No matching nodes.';
  }});
}})();
</script>
'''
    if standalone:
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title></head><body>{body}</body></html>"
    return body



def _descendant_counts(node: Dict[str, Any]) -> Dict[str, int]:
    counts = {}
    def walk(n: Dict[str, Any]):
        t = n.get("type", "node")
        counts[t] = counts.get(t, 0) + 1
        for c in n.get("children", []) or []:
            walk(c)
    walk(node)
    return counts


def _descendant_studies(node: Dict[str, Any]) -> List[str]:
    studies: List[str] = []
    seen = set()
    def walk(n: Dict[str, Any]):
        if n.get("type") == "study":
            sid = _text(n.get("id"))
            if sid and sid not in seen:
                seen.add(sid)
                studies.append(sid)
        for c in n.get("children", []) or []:
            walk(c)
    walk(node)
    return studies


def org_chart_html(tree: Dict[str, Any], title: str = "Presentation Org Chart", max_depth: int = 99, standalone: bool = False) -> str:
    if not tree:
        return "<p>No org-chart data available.</p>"

    type_names = {
        "stage": "Current stage",
        "dimension": "Candidate Dimension",
        "group": "Review group",
        "theme": "Descriptive Theme",
        "cluster": "De Novo Cluster",
        "code": "First-Order Code",
        "evidence": "Evidence Unit",
        "study": "Study",
    }

    def stats_text(n: Dict[str, Any]) -> str:
        counts = _descendant_counts(n)
        studies = len(_descendant_studies(n))
        t = n.get("type", "")
        if t == "stage":
            return f"{counts.get('dimension', 0)} dimensions - {counts.get('theme', 0)} themes"
        if t == "dimension":
            return f"{counts.get('theme', 0)} themes - {counts.get('cluster', 0)} clusters"
        if t == "group":
            return f"{counts.get('theme', 0)} themes under review"
        if t == "theme":
            return f"{counts.get('cluster', 0)} clusters - {counts.get('code', 0)} FOCs"
        if t == "cluster":
            parts = [f"{counts.get('code', 0)} FOCs"]
            if studies:
                parts.append(f"{studies} studies")
            return " - ".join(parts)
        if t == "code":
            return f"{counts.get('evidence', 0)} evidence unit"
        if t == "evidence":
            return f"{studies} study" if studies else "Source-traceable"
        return ""

    def node_html(n: Dict[str, Any], depth: int = 0) -> str:
        t = _text(n.get("type") or "node")
        children = n.get("children", []) or []
        if depth >= max_depth:
            children = []
        badge = type_names.get(t, t.title())
        nid = _text(n.get("id"))
        label = _short(n.get("label"), 135)
        status = _text(n.get("status"))
        stats = stats_text(n)
        has_children = bool(children)
        expanded = depth == 0 or t == "stage"
        status_html = f'<div class="oc-status">{html.escape(status)}</div>' if status else ''
        stats_html = f'<div class="oc-stats">{html.escape(stats)}</div>' if stats else ''
        kids_html = ''.join(node_html(c, depth + 1) for c in children)
        node_type = html.escape(t)
        if has_children:
            toggle = f'<button class="oc-toggle" type="button" aria-expanded="{"true" if expanded else "false"}">{"-" if expanded else "+"}</button>'
        else:
            toggle = '<span class="oc-toggle oc-toggle-empty">&#8226;</span>'
        child_html = f'<ul class="oc-children"{"" if expanded else " style=\"display:none\""}>{kids_html}</ul>' if kids_html else ''
        clickable = ' oc-clickable' if has_children else ''
        return (
            f'<li data-depth="{depth}">'
            f'<div class="oc-card oc-{node_type}{clickable}" data-has-children="{str(has_children).lower()}">'
            f'{toggle}'
            f'<div class="oc-badge">{html.escape(badge)}</div>'
            f'<div class="oc-id">{html.escape(nid)}</div>'
            f'<div class="oc-label">{html.escape(label)}</div>'
            f'{stats_html}{status_html}'
            f'</div>'
            f'{child_html}'
            f'</li>'
        )

    counts = _descendant_counts(tree)
    counts_text = ' - '.join(f"{k}: {v}" for k, v in counts.items() if v)
    body = f'''
<div class="orgwrap" id="orgWrap">
  <div class="org-toolbar">
    <div class="org-heading">
      <div class="org-kicker">Supervisor presentation</div>
      <div class="org-title">{html.escape(title)}</div>
      <div class="org-sub">Interactive traceability chart - {html.escape(counts_text)}</div>
    </div>
    <div class="org-note">Click a card to drill down: Dimension - Theme - Cluster - FOC - Evidence Unit - Study</div>
  </div>
  <div class="org-controls" aria-label="Chart display controls">
    <button type="button" id="ocFit">Fit to screen</button>
    <button type="button" id="ocCenter">Center view</button>
    <button type="button" id="ocActual">100%</button>
    <button type="button" id="ocZoomOut" aria-label="Zoom out">-</button>
    <span id="ocZoomLabel" class="zoom-label">100%</span>
    <button type="button" id="ocZoomIn" aria-label="Zoom in">+</button>
    <span class="control-sep"></span>
    <button type="button" id="ocExpand">Expand all</button>
    <button type="button" id="ocCollapse">Collapse all</button>
  </div>
  <div class="org-scroll" id="orgViewport">
    <div class="org-tree" id="orgTree">
      <ul>{node_html(tree, 0)}</ul>
    </div>
  </div>
</div>
<style>
:root {{ color-scheme: light; }}
html, body {{ margin:0; width:100%; font-family:Inter, Segoe UI, Arial, sans-serif; color:#17324d; background:#fff; }}
.orgwrap {{ box-sizing:border-box; width:100%; padding:8px 8px 20px; }}
.org-toolbar {{ display:flex; justify-content:space-between; gap:14px; align-items:flex-end; padding:12px 14px; border:1px solid #d9e4ef; border-radius:14px; background:#f8fbfe; margin-bottom:10px; }}
.org-heading {{ min-width:0; }}
.org-kicker {{ font-size:10px; letter-spacing:.1em; font-weight:800; color:#5f7892; text-transform:uppercase; }}
.org-title {{ font-size:20px; font-weight:800; color:#12385e; margin-top:3px; line-height:1.25; }}
.org-sub {{ font-size:11px; color:#687d91; margin-top:4px; }}
.org-note {{ max-width:520px; font-size:11px; color:#4c6a85; background:#eef5fb; border:1px solid #d7e4ef; border-radius:12px; padding:7px 10px; line-height:1.35; }}
.org-controls {{ display:flex; align-items:center; flex-wrap:wrap; gap:7px; margin:0 0 8px 0; }}
.org-controls button {{ min-height:34px; border:1px solid #b9cadb; background:white; border-radius:9px; padding:6px 10px; color:#173c61; font-weight:700; cursor:pointer; }}
.org-controls button:hover {{ background:#edf5fb; }}
.zoom-label {{ min-width:48px; text-align:center; font-size:12px; font-weight:800; color:#425d76; }}
.control-sep {{ width:1px; height:28px; background:#d9e4ef; margin:0 3px; }}
.org-scroll {{ width:100%; box-sizing:border-box; overflow:auto; padding:8px 8px 22px; scroll-behavior:smooth; border-top:1px solid #edf1f5; min-height:640px; cursor:grab; overscroll-behavior-x:contain; scrollbar-gutter:stable both-edges; }}
.org-scroll.oc-dragging {{ cursor:grabbing; scroll-behavior:auto; user-select:none; }}
.org-tree {{ width:max-content; min-width:100%; margin:0 auto; transform-origin:top center; }}
.org-tree ul {{ box-sizing:border-box; padding:20px 0 0 0; margin:0 auto; position:relative; display:flex; justify-content:center; flex-wrap:nowrap; width:max-content; min-width:100%; }}
/* Center every descendant row beneath its parent card, even when the row is wider than the viewport. */
.org-tree ul.oc-children {{ left:50%; transform:translateX(-50%); min-width:max-content; }}
.org-tree li {{ list-style-type:none; text-align:center; position:relative; padding:20px 6px 0 6px; }}
.org-tree li::before, .org-tree li::after {{ content:''; position:absolute; top:0; right:50%; border-top:2px solid #cfd9e4; width:50%; height:20px; }}
.org-tree li::after {{ right:auto; left:50%; border-left:2px solid #cfd9e4; }}
.org-tree li:only-child::after, .org-tree li:only-child::before {{ display:none; }}
.org-tree li:only-child {{ padding-top:0; }}
.org-tree li:first-child::before, .org-tree li:last-child::after {{ border:none; }}
.org-tree li:last-child::before {{ border-right:2px solid #cfd9e4; border-radius:0 6px 0 0; }}
.org-tree li:first-child::after {{ border-radius:6px 0 0 0; }}
.org-tree ul ul::before {{ content:''; position:absolute; top:0; left:50%; border-left:2px solid #cfd9e4; width:0; height:20px; }}
.oc-card {{ box-sizing:border-box; width:238px; min-height:128px; background:#fff; border:1px solid #dbe5ef; border-radius:16px; padding:13px 14px; box-shadow:0 7px 18px rgba(16,40,67,.075); position:relative; display:flex; flex-direction:column; justify-content:center; align-items:center; }}
.oc-dimension {{ width:260px; min-height:148px; background:#fffaf3; border-color:#f0d7b5; }}
.oc-theme {{ width:255px; min-height:145px; background:#faf7ff; border-color:#dfd1f3; }}
.oc-cluster {{ width:245px; min-height:138px; background:#f3fbf8; border-color:#cfe8e0; }}
.oc-code {{ width:238px; min-height:132px; background:#f5faff; border-color:#d4e6f6; }}
.oc-evidence {{ width:260px; min-height:142px; background:#fff9f1; border-color:#eddab8; }}
.oc-study {{ width:245px; min-height:126px; background:#fafbfc; border-color:#dfe5ea; }}
.oc-stage {{ width:275px; background:#f3f8fd; border-color:#cfe0f2; }}
.oc-clickable {{ cursor:pointer; transition:transform .12s ease, box-shadow .12s ease, border-color .12s ease; }}
.oc-clickable:hover {{ transform:translateY(-1px); box-shadow:0 10px 23px rgba(16,40,67,.11); border-color:#aebfd0; }}
.oc-toggle {{ position:absolute; top:9px; right:10px; width:28px; height:28px; border-radius:999px; border:1px solid #d3deea; background:#fff; color:#315b80; font-size:17px; line-height:24px; font-weight:800; cursor:pointer; display:grid; place-items:center; padding:0; }}
.oc-toggle-empty {{ border:none; background:transparent; cursor:default; color:#8396a9; font-size:18px; }}
.oc-badge {{ display:inline-block; font-size:9px; font-weight:800; letter-spacing:.035em; text-transform:uppercase; padding:4px 8px; border-radius:999px; background:#eaf1f8; color:#58718a; margin-bottom:8px; }}
.oc-id {{ font-size:14px; font-weight:850; color:#173f66; margin-bottom:5px; }}
.oc-label {{ font-size:13px; line-height:1.3; font-weight:650; color:#243f58; overflow-wrap:anywhere; }}
.oc-stats {{ font-size:11px; color:#61758a; margin-top:7px; }}
.oc-status {{ margin-top:7px; display:inline-block; font-size:10px; font-weight:750; color:#345; background:#f6f8fb; border-radius:999px; padding:4px 8px; max-width:95%; }}
@media (max-width:900px) {{
  .org-toolbar {{ align-items:flex-start; flex-direction:column; }}
  .org-note {{ max-width:none; }}
  .oc-card {{ width:220px; }}
  .oc-dimension, .oc-theme, .oc-evidence {{ width:235px; }}
}}
</style>
<script>
(() => {{
  const root = document.getElementById('orgTree');
  const viewport = document.getElementById('orgViewport');
  if (!root || !viewport || root.dataset.ready === '1') return;
  root.dataset.ready = '1';

  const zoomLabel = document.getElementById('ocZoomLabel');
  const fitBtn = document.getElementById('ocFit');
  const centerBtn = document.getElementById('ocCenter');
  const actualBtn = document.getElementById('ocActual');
  const zinBtn = document.getElementById('ocZoomIn');
  const zoutBtn = document.getElementById('ocZoomOut');
  const expandBtn = document.getElementById('ocExpand');
  const collapseBtn = document.getElementById('ocCollapse');
  let zoom = 1;
  let autoFit = true;
  let focusedCard = null;
  const minZoom = 0.42;
  const maxZoom = 1.25;

  function clamp(v, lo, hi) {{ return Math.max(lo, Math.min(hi, v)); }}

  function updateZoomLabel() {{
    if (zoomLabel) zoomLabel.textContent = Math.round(zoom * 100) + '%';
    if (fitBtn) fitBtn.style.background = autoFit ? '#eaf3fb' : '#fff';
  }}

  function applyZoom(value, manual=false) {{
    zoom = clamp(value, minZoom, maxZoom);
    root.style.zoom = String(zoom);
    if (manual) autoFit = false;
    updateZoomLabel();
  }}

  function centerTree() {{
    requestAnimationFrame(() => {{
      const target = Math.max(0, (viewport.scrollWidth - viewport.clientWidth) / 2);
      viewport.scrollTo({{ left: target, behavior: 'smooth' }});
    }});
  }}

  function fitTree(anchorCard=null) {{
    autoFit = true;
    if (anchorCard) focusedCard = anchorCard;
    root.style.zoom = '1';
    requestAnimationFrame(() => {{
      const natural = Math.max(root.scrollWidth, root.getBoundingClientRect().width || 0);
      const available = Math.max(320, viewport.clientWidth - 24);
      const target = natural > 0 ? clamp(available / natural, minZoom, 1) : 1;
      zoom = target;
      root.style.zoom = String(zoom);
      updateZoomLabel();
      requestAnimationFrame(() => {{
        if (focusedCard && document.body.contains(focusedCard)) centerCard(focusedCard);
        else centerTree();
      }});
    }});
  }}

  function centerCard(card) {{
    if (!card) return;
    requestAnimationFrame(() => {{
      const cardRect = card.getBoundingClientRect();
      const viewRect = viewport.getBoundingClientRect();
      const delta = (cardRect.left + cardRect.width / 2) - (viewRect.left + viewRect.width / 2);
      viewport.scrollLeft += delta;
    }});
  }}

  function afterStructureChange(card) {{
    if (card) focusedCard = card;
    setTimeout(() => {{
      if (autoFit) fitTree(card);
      else centerCard(card);
    }}, 30);
  }}

  function setExpanded(card, expanded, relayout=true) {{
    const li = card.closest('li');
    const child = li ? li.querySelector(':scope > ul.oc-children') : null;
    const btn = card.querySelector(':scope > .oc-toggle');
    if (!child || !btn) return;
    child.style.display = expanded ? '' : 'none';
    btn.textContent = expanded ? '-' : '+';
    btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    if (relayout) afterStructureChange(card);
  }}

  root.querySelectorAll('.oc-card[data-has-children="true"]').forEach(card => {{
    card.addEventListener('click', (e) => {{
      if (e.target.closest('.oc-toggle')) e.preventDefault();
      const btn = card.querySelector(':scope > .oc-toggle');
      const expanded = btn && btn.getAttribute('aria-expanded') === 'true';
      setExpanded(card, !expanded, true);
    }});
  }});

  if (fitBtn) fitBtn.addEventListener('click', () => fitTree(focusedCard));
  if (centerBtn) centerBtn.addEventListener('click', () => {{
    if (focusedCard && document.body.contains(focusedCard)) centerCard(focusedCard);
    else centerTree();
  }});
  if (actualBtn) actualBtn.addEventListener('click', () => {{
    autoFit = false;
    applyZoom(1, false);
    if (focusedCard && document.body.contains(focusedCard)) centerCard(focusedCard);
    else centerTree();
  }});
  if (zinBtn) zinBtn.addEventListener('click', () => {{
    applyZoom(zoom + 0.1, true);
    if (focusedCard && document.body.contains(focusedCard)) centerCard(focusedCard);
    else centerTree();
  }});
  if (zoutBtn) zoutBtn.addEventListener('click', () => {{
    applyZoom(zoom - 0.1, true);
    if (focusedCard && document.body.contains(focusedCard)) centerCard(focusedCard);
    else centerTree();
  }});

  if (expandBtn) expandBtn.addEventListener('click', () => {{
    root.querySelectorAll('.oc-card[data-has-children="true"]').forEach(card => setExpanded(card, true, false));
    const anchor = focusedCard || root.querySelector('.oc-card');
    afterStructureChange(anchor);
  }});

  if (collapseBtn) collapseBtn.addEventListener('click', () => {{
    root.querySelectorAll('.oc-card[data-has-children="true"]').forEach((card, idx) => setExpanded(card, idx === 0, false));
    focusedCard = root.querySelector('.oc-card');
    afterStructureChange(focusedCard);
  }});

  // Mouse/touchpad-friendly horizontal browsing: drag anywhere in the chart background.
  let dragging = false;
  let dragStartX = 0;
  let dragStartScroll = 0;

  viewport.addEventListener('pointerdown', (e) => {{
    if (e.button !== 0 || e.target.closest('button, .oc-card')) return;
    dragging = true;
    dragStartX = e.clientX;
    dragStartScroll = viewport.scrollLeft;
    viewport.classList.add('oc-dragging');
    viewport.setPointerCapture?.(e.pointerId);
  }});

  viewport.addEventListener('pointermove', (e) => {{
    if (!dragging) return;
    viewport.scrollLeft = dragStartScroll - (e.clientX - dragStartX);
  }});

  function stopDragging(e) {{
    if (!dragging) return;
    dragging = false;
    viewport.classList.remove('oc-dragging');
    try {{ viewport.releasePointerCapture?.(e.pointerId); }} catch (_) {{}}
  }}
  viewport.addEventListener('pointerup', stopDragging);
  viewport.addEventListener('pointercancel', stopDragging);
  viewport.addEventListener('pointerleave', (e) => {{ if (dragging && e.buttons === 0) stopDragging(e); }});

  // A normal mouse wheel browses a wide row horizontally when vertical movement is not needed.
  viewport.addEventListener('wheel', (e) => {{
    const canBrowseHorizontally = viewport.scrollWidth > viewport.clientWidth + 4;
    if (!canBrowseHorizontally) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && !e.ctrlKey) {{
      viewport.scrollLeft += e.deltaY;
      e.preventDefault();
    }}
  }}, {{ passive:false }});

  if (typeof ResizeObserver !== 'undefined') {{
    const ro = new ResizeObserver(() => {{ if (autoFit) fitTree(focusedCard); }});
    ro.observe(viewport);
  }}

  requestAnimationFrame(() => {{
    focusedCard = root.querySelector('.oc-card');
    fitTree(focusedCard);
  }});
}})();
</script>'''
    if standalone:
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title></head><body>{body}</body></html>"
    return body
