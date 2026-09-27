from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from master_utils import master_snapshot
from tree_utils import build_candidate_stage_tree_data


SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT_PATH = "supervisor_snapshot.json"


def _prune_tree(node: Dict[str, Any]) -> Dict[str, Any] | None:
    """Keep presentation structure only; remove source-near evidence/study nodes."""
    if not node:
        return None

    node_type = str(node.get("type", "")).strip()
    if node_type in {"evidence", "study"}:
        return None

    kept = {
        "type": node_type,
        "id": node.get("id", ""),
        "label": node.get("label", ""),
        "status": node.get("status", ""),
        "meta": node.get("meta", {}) or {},
        "children": [],
    }

    for child in node.get("children", []) or []:
        pruned = _prune_tree(child)
        if pruned is not None:
            kept["children"].append(pruned)

    # First-order codes remain visible, but never carry Meaning Unit / Study children.
    if node_type == "code":
        kept["children"] = []

    return kept


def build_supervisor_snapshot(frames: Dict[str, Any]) -> Dict[str, Any]:
    """Build a sanitized, version-agnostic presentation snapshot.

    The snapshot contains the higher-order derivation structure down to FOC level.
    It intentionally excludes the original workbook bytes, workbook filename,
    Meaning Unit verbatim text, contextual verbatim text, and study/source nodes.
    """
    live = master_snapshot(frames)
    tree = build_candidate_stage_tree_data(frames, include_unassigned_themes=True)
    clean_tree = _prune_tree(tree) or {}

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "kind": "PMM_SUPERVISOR_PRESENTATION_SNAPSHOT",
        "source_policy": {
            "workbook_included": False,
            "workbook_filename_included": False,
            "meaning_units_included": False,
            "context_verbatim_included": False,
            "study_nodes_included": False,
            "lowest_visible_level": "First-Order Code",
        },
        "snapshot": live,
        "tree": clean_tree,
    }


def snapshot_bytes(frames: Dict[str, Any]) -> bytes:
    payload = build_supervisor_snapshot(frames)
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def load_supervisor_snapshot(path: str | Path = DEFAULT_SNAPSHOT_PATH) -> Dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return None
    if data.get("kind") != "PMM_SUPERVISOR_PRESENTATION_SNAPSHOT":
        return None
    if int(data.get("schema_version", 0) or 0) != SNAPSHOT_SCHEMA_VERSION:
        return None
    if not isinstance(data.get("tree"), dict):
        return None
    if not isinstance(data.get("snapshot"), dict):
        return None
    return data


def walk_tree(node: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if not node:
        return
    yield node
    for child in node.get("children", []) or []:
        yield from walk_tree(child)


def nodes_of_type(tree: Dict[str, Any], node_type: str) -> List[Dict[str, Any]]:
    return [n for n in walk_tree(tree) if n.get("type") == node_type]


def subtree_by_id(tree: Dict[str, Any], node_id: str) -> Dict[str, Any] | None:
    target = str(node_id).strip()
    for node in walk_tree(tree):
        if str(node.get("id", "")).strip() == target:
            return node
    return None


def selected_nodes_tree(
    tree: Dict[str, Any],
    node_ids: List[str],
    node_type: str,
    label: str,
) -> Dict[str, Any]:
    wanted = {str(x).strip() for x in node_ids if str(x).strip()}
    children = [
        n for n in walk_tree(tree)
        if n.get("type") == node_type and str(n.get("id", "")).strip() in wanted
    ]
    return {
        "type": "group",
        "id": f"SELECTED-{node_type.upper()}S",
        "label": label,
        "status": "Presentation view",
        "meta": {
            "Privacy": "Sanitized presentation snapshot; original Excel workbook is not included.",
        },
        "children": children,
    }


def descendant_counts(node: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in walk_tree(node):
        t = str(item.get("type", "node"))
        out[t] = out.get(t, 0) + 1
    return out


def dimension_summary(tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for dim in nodes_of_type(tree, "dimension"):
        counts = descendant_counts(dim)
        rows.append({
            "Dimension_ID": dim.get("id", ""),
            "Candidate_Dimension_Name": dim.get("label", ""),
            "Dimension_Status": dim.get("status", ""),
            "Themes": counts.get("theme", 0),
            "Clusters": counts.get("cluster", 0),
            "FOCs": counts.get("code", 0),
        })
    return rows
