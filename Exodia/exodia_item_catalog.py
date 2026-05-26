#!/usr/bin/env python3
"""
List Exodia item catalog entries and resolve a template image to a known item id.

Usage:
  python exodia_item_catalog.py list
  python exodia_item_catalog.py resolve --path /path/to/icon.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

import cv2
import numpy as np

from bot_inventory_count import bgra_to_match_bgr, strip_inventory_plate_background
from bot_match_index import (  # noqa: E402
    SeenItemRegistry,
    _cross_template_score,
    _embed_icon_in_slot_canvas,
    is_temp_item_id,
    items_directory,
    load_named_catalog,
    seen_fingerprints_directory,
    seen_images_directory,
    seen_item_display_label,
    seen_label,
)


def _emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _env_float(key: str, default: float) -> float:
    import os

    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _load_query_bgr(path: Path) -> Optional[np.ndarray]:
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None or raw.size == 0:
        return None
    if raw.ndim == 3 and raw.shape[2] == 4:
        return _embed_icon_in_slot_canvas(bgra_to_match_bgr(raw))
    bgr = raw if raw.ndim == 3 else cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    stripped = strip_inventory_plate_background(bgr)
    if stripped.ndim == 3 and stripped.shape[2] == 4:
        return _embed_icon_in_slot_canvas(bgra_to_match_bgr(stripped))
    return _embed_icon_in_slot_canvas(bgr)


def cmd_list() -> int:
    root = items_directory()
    seen_dir = seen_images_directory(root)
    fp_dir = seen_fingerprints_directory(root)

    named: List[Dict[str, Any]] = []
    if root.is_dir():
        for path in sorted(root.glob("*.png")):
            stem = path.stem.lower()
            if not stem or is_temp_item_id(stem):
                continue
            named.append(
                {
                    "id": stem,
                    "itemId": stem,
                    "displayName": stem,
                    "kind": "named",
                    "templateFile": path.name,
                    "templatePath": str(path.resolve()),
                }
            )

    fingerprints: List[Dict[str, Any]] = []
    if fp_dir.is_dir():
        for json_path in sorted(fp_dir.glob("*.json")):
            tid = json_path.stem.lower()
            if not is_temp_item_id(tid):
                continue
            name = None
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                name = data.get("name")
            except (json.JSONDecodeError, OSError):
                pass
            png = seen_dir / (tid + ".png")
            fingerprints.append(
                {
                    "id": tid,
                    "itemId": seen_label(tid),
                    "displayName": seen_item_display_label(tid, name),
                    "kind": "fingerprint",
                    "templateFile": png.name if png.is_file() else None,
                    "templatePath": str(png.resolve()) if png.is_file() else None,
                }
            )

    _emit({"ok": True, "itemsDir": str(root), "named": named, "fingerprints": fingerprints})
    return 0


def resolve_image_path(
    image_path: Path,
    *,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    from bot_env import inventory_identify_threshold

    thr = threshold if threshold is not None else inventory_identify_threshold()
    if not image_path.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(image_path)}

    query = _load_query_bgr(image_path)
    if query is None:
        return {"ok": False, "error": "could_not_read_image", "path": str(image_path)}

    catalog = load_named_catalog()
    verdict = catalog.match_query(query, strict_gates=False)
    if verdict.accepted and verdict.best_name:
        stem = verdict.best_name
        png = items_directory() / (stem + ".png")
        return {
            "ok": True,
            "matched": True,
            "kind": "named",
            "itemId": stem,
            "displayName": stem,
            "score": round(float(verdict.best_score), 4),
            "templateFile": png.name,
            "templatePath": str(png.resolve()) if png.is_file() else None,
        }

    registry = SeenItemRegistry.load_from_disk()
    best_id: Optional[str] = None
    best_score = 0.0
    best_name: Optional[str] = None
    for entry in registry._entries.values():
        score = _cross_template_score(
            query, entry.template_gray, entry.template_bgr
        )
        if score > best_score:
            best_score = score
            best_id = entry.temp_id
            best_name = entry.name

    if best_id and best_score >= thr:
        png = seen_images_directory() / (best_id + ".png")
        return {
            "ok": True,
            "matched": True,
            "kind": "fingerprint",
            "itemId": seen_label(best_id),
            "displayName": seen_item_display_label(best_id, best_name),
            "score": round(float(best_score), 4),
            "templateFile": png.name if png.is_file() else None,
            "templatePath": str(png.resolve()) if png.is_file() else None,
        }

    return {
        "ok": True,
        "matched": False,
        "bestNamed": verdict.best_name,
        "bestNamedScore": round(float(verdict.best_score), 4) if verdict.best_name else None,
        "bestFingerprintScore": round(float(best_score), 4) if best_id else None,
    }


def cmd_resolve(path: str) -> int:
    result = resolve_image_path(Path(path).expanduser().resolve())
    _emit(result)
    return 0 if result.get("ok") else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Exodia item catalog helpers")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List named items and fingerprints")
    resolve_p = sub.add_parser("resolve", help="Match image to catalog item")
    resolve_p.add_argument("--path", required=True)
    ns = parser.parse_args(argv)
    if ns.command == "list":
        return cmd_list()
    if ns.command == "resolve":
        return cmd_resolve(ns.path)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
