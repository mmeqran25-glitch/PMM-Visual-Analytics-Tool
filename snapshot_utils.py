from __future__ import annotations

import json
import base64
import gzip
from pathlib import Path
from typing import Any, Dict, Iterable, List

from master_utils import master_snapshot, retired_themes
from tree_utils import build_candidate_stage_tree_data, build_theme_tree_data


SNAPSHOT_SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT_PATH = "supervisor_snapshot.json"
DEFAULT_CHUNK_DIR = "supervisor_snapshot_chunks"


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

    historical_nodes = []
    historical = retired_themes(frames)
    if not historical.empty:
        for tid in historical["Theme_ID"].dropna().astype(str).str.strip():
            node = build_theme_tree_data(frames, tid)
            clean = _prune_tree(node) if node else None
            if clean is not None:
                historical_nodes.append(clean)

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
        "retired_themes": historical_nodes,
    }


def snapshot_bytes(frames: Dict[str, Any]) -> bytes:
    payload = build_supervisor_snapshot(frames)
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _expand_compact_snapshot(data: Dict[str, Any]) -> Dict[str, Any] | None:
    if data.get("kind") != "PMM_SUPERVISOR_COMPACT_SNAPSHOT":
        return None
    if int(data.get("schema_version", 0) or 0) != 2:
        return None

    snapshot = data.get("snapshot")
    dimensions = data.get("dimensions")
    themes = data.get("themes")
    clusters = data.get("clusters")
    if not isinstance(snapshot, dict) or not isinstance(dimensions, list) or not isinstance(themes, list) or not isinstance(clusters, list):
        return None

    cluster_map = {}
    for item in clusters:
        if not isinstance(item, list) or len(item) < 4:
            continue
        cid, label, status, codes = item[:4]
        code_nodes = []
        for code in codes or []:
            if not isinstance(code, list) or len(code) < 3:
                continue
            code_nodes.append({
                "type": "code",
                "id": code[0],
                "label": code[1],
                "status": code[2],
                "meta": {},
                "children": [],
            })
        cluster_map[str(cid)] = {
            "type": "cluster",
            "id": cid,
            "label": label,
            "status": status,
            "meta": {},
            "children": code_nodes,
        }

    theme_map = {}
    themed_cluster_ids = set()
    for item in themes:
        if not isinstance(item, list) or len(item) < 4:
            continue
        tid, label, status, cluster_ids = item[:4]
        cluster_ids = [str(x) for x in (cluster_ids or [])]
        themed_cluster_ids.update(cluster_ids)
        theme_map[str(tid)] = {
            "type": "theme",
            "id": tid,
            "label": label,
            "status": status,
            "meta": {},
            "children": [cluster_map[cid] for cid in cluster_ids if cid in cluster_map],
        }

    root = {
        "type": "stage",
        "id": "08_Candidate_Dimensions",
        "label": "Candidate Dimensions — current recorded structure",
        "status": "READ-ONLY CURRENT STRUCTURE",
        "meta": {},
        "children": [],
    }

    assigned_theme_ids = set()
    for item in dimensions:
        if not isinstance(item, list) or len(item) < 4:
            continue
        did, label, status, theme_ids = item[:4]
        theme_ids = [str(x) for x in (theme_ids or [])]
        assigned_theme_ids.update(theme_ids)
        root["children"].append({
            "type": "dimension",
            "id": did,
            "label": label,
            "status": status,
            "meta": {},
            "children": [theme_map[tid] for tid in theme_ids if tid in theme_map],
        })

    unassigned_theme_ids = sorted(set(theme_map) - assigned_theme_ids)
    if unassigned_theme_ids:
        root["children"].append({
            "type": "group",
            "id": "SG4-UNDER-REVIEW",
            "label": "Active descriptive Themes not yet assigned to a current Dimension",
            "status": "Under review",
            "meta": {},
            "children": [theme_map[tid] for tid in unassigned_theme_ids],
        })

    unthemed_cluster_ids = sorted(set(cluster_map) - themed_cluster_ids)
    if unthemed_cluster_ids:
        root["children"].append({
            "type": "group",
            "id": "SG3-UNTHEMED-CLUSTERS",
            "label": "Active clusters not yet assigned to an active Theme",
            "status": "Residual / not force-fitted",
            "meta": {},
            "children": [cluster_map[cid] for cid in unthemed_cluster_ids],
        })

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
        "snapshot": snapshot,
        "tree": root,
    }


def _validate_snapshot(data: Any) -> Dict[str, Any] | None:
    if not isinstance(data, dict):
        return None

    compact = _expand_compact_snapshot(data)
    if compact is not None:
        return compact

    if data.get("kind") != "PMM_SUPERVISOR_PRESENTATION_SNAPSHOT":
        return None
    if int(data.get("schema_version", 0) or 0) != SNAPSHOT_SCHEMA_VERSION:
        return None
    if not isinstance(data.get("tree"), dict):
        return None
    if not isinstance(data.get("snapshot"), dict):
        return None
    return data


def load_supervisor_snapshot(
    path: str | Path = DEFAULT_SNAPSHOT_PATH,
    chunk_dir: str | Path = DEFAULT_CHUNK_DIR,
) -> Dict[str, Any] | None:
    """Load a sanitized snapshot from JSON or compressed chunk files.

    The chunked form is intended for deployed/public presentation builds. It
    contains only the sanitized snapshot payload, never the original workbook.
    """
    p = Path(path)
    if p.exists():
        try:
            with p.open("r", encoding="utf-8") as fh:
                return _validate_snapshot(json.load(fh))
        except Exception:
            return None

    d = Path(chunk_dir)
    parts = sorted(d.glob("part*.b64")) if d.exists() else []
    if not parts:
        return None

    try:
        encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
        raw = gzip.decompress(base64.b64decode(encoded))
        data = json.loads(raw.decode("utf-8"))
        return _validate_snapshot(data)
    except Exception:
        return None


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
