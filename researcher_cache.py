from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Optional, Tuple


# Only the SHA-256 hash is stored in the public repository.
# The raw access key is never committed to GitHub.
RESEARCHER_ACCESS_SHA256 = "0c940cfae170d5a5a0337324a66a086d597a5db419814700ce7d9e9bb8dd2672"
DEFAULT_CACHE_ROOT = Path(tempfile.gettempdir()) / "pmm_visual_analytics_researcher"


def token_matches(token: str, expected_hash: str = RESEARCHER_ACCESS_SHA256) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_hash)


def _cache_dir(cache_root: Path | str | None = None) -> Path:
    root = Path(cache_root) if cache_root is not None else DEFAULT_CACHE_ROOT
    # Namespace by access hash so unrelated future researcher keys do not share cache.
    path = root / RESEARCHER_ACCESS_SHA256[:16]
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _named_paths(
    stem: str,
    cache_root: Path | str | None = None,
) -> Tuple[Path, Path]:
    d = _cache_dir(cache_root)
    safe_stem = "".join(ch for ch in str(stem) if ch.isalnum() or ch in {"_", "-"}) or "workbook"
    return d / f"{safe_stem}.xlsx", d / f"{safe_stem}.json"


def _paths(cache_root: Path | str | None = None) -> Tuple[Path, Path]:
    return _named_paths("current_master", cache_root)


def save_cached_master(
    filename: str,
    data: bytes,
    cache_root: Path | str | None = None,
) -> dict:
    workbook_path, meta_path = _paths(cache_root)
    safe_name = Path(str(filename or "current_master.xlsx")).name
    payload = bytes(data)
    digest = hashlib.sha256(payload).hexdigest()

    tmp_workbook = workbook_path.with_suffix(".xlsx.tmp")
    tmp_meta = meta_path.with_suffix(".json.tmp")

    tmp_workbook.write_bytes(payload)
    tmp_meta.write_text(
        json.dumps(
            {
                "filename": safe_name,
                "sha256": digest,
                "size_bytes": len(payload),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    tmp_workbook.replace(workbook_path)
    tmp_meta.replace(meta_path)

    for path in (workbook_path, meta_path):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    return {
        "filename": safe_name,
        "sha256": digest,
        "size_bytes": len(payload),
    }


def load_cached_master(
    cache_root: Path | str | None = None,
) -> Optional[Tuple[str, bytes, dict]]:
    workbook_path, meta_path = _paths(cache_root)
    if not workbook_path.exists() or not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        data = workbook_path.read_bytes()
    except Exception:
        return None

    digest = hashlib.sha256(data).hexdigest()
    if digest != str(meta.get("sha256", "")):
        return None

    filename = Path(str(meta.get("filename") or "current_master.xlsx")).name
    return filename, data, meta


def clear_cached_master(cache_root: Path | str | None = None) -> None:
    workbook_path, meta_path = _paths(cache_root)
    for path in (workbook_path, meta_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass



def _save_named_workbook(
    stem: str,
    filename: str,
    data: bytes,
    cache_root: Path | str | None = None,
) -> dict:
    workbook_path, meta_path = _named_paths(stem, cache_root)
    safe_name = Path(str(filename or f"{stem}.xlsx")).name
    payload = bytes(data)
    digest = hashlib.sha256(payload).hexdigest()

    tmp_workbook = workbook_path.with_suffix(".xlsx.tmp")
    tmp_meta = meta_path.with_suffix(".json.tmp")

    tmp_workbook.write_bytes(payload)
    tmp_meta.write_text(
        json.dumps(
            {
                "filename": safe_name,
                "sha256": digest,
                "size_bytes": len(payload),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    tmp_workbook.replace(workbook_path)
    tmp_meta.replace(meta_path)

    for path in (workbook_path, meta_path):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    return {
        "filename": safe_name,
        "sha256": digest,
        "size_bytes": len(payload),
    }


def _load_named_workbook(
    stem: str,
    cache_root: Path | str | None = None,
) -> Optional[Tuple[str, bytes, dict]]:
    workbook_path, meta_path = _named_paths(stem, cache_root)
    if not workbook_path.exists() or not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        data = workbook_path.read_bytes()
    except Exception:
        return None

    digest = hashlib.sha256(data).hexdigest()
    if digest != str(meta.get("sha256", "")):
        return None

    filename = Path(str(meta.get("filename") or f"{stem}.xlsx")).name
    return filename, data, meta


def _clear_named_workbook(
    stem: str,
    cache_root: Path | str | None = None,
) -> None:
    workbook_path, meta_path = _named_paths(stem, cache_root)
    for path in (workbook_path, meta_path):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def save_cached_prisma(
    filename: str,
    data: bytes,
    cache_root: Path | str | None = None,
) -> dict:
    return _save_named_workbook("current_prisma_screening", filename, data, cache_root)


def load_cached_prisma(
    cache_root: Path | str | None = None,
) -> Optional[Tuple[str, bytes, dict]]:
    return _load_named_workbook("current_prisma_screening", cache_root)


def clear_cached_prisma(cache_root: Path | str | None = None) -> None:
    _clear_named_workbook("current_prisma_screening", cache_root)
