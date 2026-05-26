#!/usr/bin/env python3
"""
Save template images for ExodiaBotUI and catalog lookup.

  python exodia_save_template.py inventory --name flax --slot 0,3
  python exodia_save_template.py world --name my_spot --rect 120,80,72,72
  python exodia_save_template.py import --kind images --name osrs_mySpot --path /path/to.png
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

import cv2
import numpy as np

from bot_inventory_items import (  # noqa: E402
    crop_inventory_slot_bgr,
    normalize_item_template_name,
    save_named_item_template,
)
from bot_match_index import (  # noqa: E402
    _embed_icon_in_slot_canvas,
    items_directory,
    is_temp_item_id,
)
from tests.inventory_test_common import capture_client_bgr, locate_inventory_rect  # noqa: E402

_NAME_SAFE_RE = re.compile(r"[^a-z0-9_]+")


def _emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def _ensure_capture_env() -> None:
    import os

    ps_path = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps_path.is_file():
        if not os.environ.get("EXODIA_CAPTURE_BACKEND"):
            os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
    os.environ.setdefault("EXODIA_INV_FRAME_BUCKETS", "1")


def images_directory() -> Path:
    import os

    raw = os.environ.get("EXODIA_IMAGES_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_EXODIA / "images").resolve()


def normalize_world_template_name(raw: str) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    name = str(raw).strip().lower().replace(" ", "_")
    name = _NAME_SAFE_RE.sub("", name)
    name = name.strip("_")
    if not name or is_temp_item_id(name):
        return None
    return name


def _parse_slot(text: str) -> Optional[Tuple[int, int]]:
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _parse_rect(text: str) -> Optional[List[int]]:
    parts = [p.strip() for p in str(text).split(",")]
    if len(parts) != 4:
        return None
    try:
        return [int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])]
    except ValueError:
        return None


def _clamp_rect(frame_w: int, frame_h: int, rect: Sequence[int]) -> Optional[Tuple[int, int, int, int]]:
    if len(rect) != 4:
        return None
    x, y, w, h = (int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
    if w < 4 or h < 4:
        return None
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    w = min(w, frame_w - x)
    h = min(h, frame_h - y)
    if w < 4 or h < 4:
        return None
    return x, y, w, h


def _default_world_crop_size() -> Tuple[int, int]:
    import os

    raw = os.environ.get("EXODIA_SAVE_WORLD_CROP_SIZE", "80,80").strip()
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) == 2:
        try:
            return max(16, int(parts[0])), max(16, int(parts[1]))
        except ValueError:
            pass
    return 80, 80


def rect_centered_on(cx: int, cy: int, *, width: int, height: int) -> List[int]:
    return [int(cx - width // 2), int(cy - height // 2), int(width), int(height)]


def save_inventory_slot(
    name: str,
    row: int,
    col: int,
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    _ensure_capture_env()
    stem = normalize_item_template_name(name)
    if stem is None:
        return {"ok": False, "error": "invalid_name", "name": name}

    client, err = capture_client_bgr()
    if client is None:
        return {"ok": False, "error": err or "capture_failed"}

    inv_rect = locate_inventory_rect(client)
    if not inv_rect or len(inv_rect) != 4:
        return {"ok": False, "error": "inventory_not_found", "hint": "open inventory in RuneLite"}

    crop = crop_inventory_slot_bgr(client, inv_rect, row, col)
    if crop is None or crop.size == 0:
        return {"ok": False, "error": "slot_crop_failed", "slot": [row, col]}

    try:
        path = save_named_item_template(crop, stem, overwrite=overwrite)
    except FileExistsError:
        return {"ok": False, "error": "file_exists", "templatePath": str(items_directory() / ("%s.png" % stem))}
    except (ValueError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "kind": "inventory",
        "dest": "items",
        "itemId": stem,
        "displayName": stem,
        "templateFile": path.name,
        "templatePath": str(path.resolve()),
        "slot": [row, col],
    }


def save_world_crop(
    name: str,
    rect: Sequence[int],
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    _ensure_capture_env()
    stem = normalize_world_template_name(name)
    if stem is None:
        return {"ok": False, "error": "invalid_name", "name": name}

    client, err = capture_client_bgr()
    if client is None:
        return {"ok": False, "error": err or "capture_failed"}

    h0, w0 = client.shape[:2]
    clamped = _clamp_rect(w0, h0, rect)
    if clamped is None:
        return {"ok": False, "error": "invalid_rect", "rect": list(rect)}

    x, y, w, h = clamped
    crop = client[y : y + h, x : x + w].copy()
    if crop.size == 0:
        return {"ok": False, "error": "empty_crop"}

    root = images_directory()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("%s.png" % stem)
    if path.is_file() and not overwrite:
        return {"ok": False, "error": "file_exists", "templatePath": str(path)}

    if not cv2.imwrite(str(path), crop):
        return {"ok": False, "error": "write_failed", "templatePath": str(path)}

    return {
        "ok": True,
        "kind": "world",
        "dest": "images",
        "itemId": stem,
        "displayName": stem,
        "templateFile": path.name,
        "templatePath": str(path.resolve()),
        "rect": [x, y, w, h],
    }


def import_template_file(
    kind: str,
    name: str,
    source_path: Path,
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    kind = (kind or "").strip().lower()
    if kind not in ("items", "inventory", "images", "world"):
        return {"ok": False, "error": "invalid_kind", "kind": kind}

    if not source_path.is_file():
        return {"ok": False, "error": "file_not_found", "path": str(source_path)}

    bgr = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        return {"ok": False, "error": "unreadable_image", "path": str(source_path)}

    is_inventory = kind in ("items", "inventory")
    if is_inventory:
        stem = normalize_item_template_name(name)
        if stem is None:
            return {"ok": False, "error": "invalid_name", "name": name}
        try:
            path = save_named_item_template(bgr, stem, overwrite=overwrite)
        except FileExistsError:
            return {"ok": False, "error": "file_exists"}
        except (ValueError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "kind": "inventory",
            "dest": "items",
            "itemId": stem,
            "displayName": stem,
            "templateFile": path.name,
            "templatePath": str(path.resolve()),
            "importedFrom": str(source_path.resolve()),
        }

    stem = normalize_world_template_name(name)
    if stem is None:
        return {"ok": False, "error": "invalid_name", "name": name}
    root = images_directory()
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("%s.png" % stem)
    if path.is_file() and not overwrite:
        return {"ok": False, "error": "file_exists", "templatePath": str(path)}
    if not cv2.imwrite(str(path), bgr):
        return {"ok": False, "error": "write_failed"}
    return {
        "ok": True,
        "kind": "world",
        "dest": "images",
        "itemId": stem,
        "displayName": stem,
        "templateFile": path.name,
        "templatePath": str(path.resolve()),
        "importedFrom": str(source_path.resolve()),
    }


def cmd_inventory(args: argparse.Namespace) -> int:
    slot = _parse_slot(args.slot)
    if slot is None:
        _emit({"ok": False, "error": "invalid_slot", "slot": args.slot})
        return 1
    row, col = slot
    result = save_inventory_slot(args.name, row, col, overwrite=bool(args.overwrite))
    _emit(result)
    return 0 if result.get("ok") else 1


def cmd_world(args: argparse.Namespace) -> int:
    rect: Optional[List[int]] = None
    if args.rect:
        rect = _parse_rect(args.rect)
    elif args.center:
        center = _parse_rect(args.center)
        if center and len(center) >= 2:
            w, h = _default_world_crop_size()
            rect = rect_centered_on(center[0], center[1], width=w, height=h)
    if rect is None:
        _emit({"ok": False, "error": "missing_rect", "hint": "use --rect x,y,w,h or --center cx,cy"})
        return 1
    result = save_world_crop(args.name, rect, overwrite=bool(args.overwrite))
    _emit(result)
    return 0 if result.get("ok") else 1


def cmd_import(args: argparse.Namespace) -> int:
    result = import_template_file(
        args.kind,
        args.name,
        Path(args.path).expanduser().resolve(),
        overwrite=bool(args.overwrite),
    )
    _emit(result)
    return 0 if result.get("ok") else 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Save Exodia template images")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="Crop inventory slot from live capture → items/<name>.png")
    inv.add_argument("--name", required=True)
    inv.add_argument("--slot", required=True, help="row,col (0-based)")
    inv.add_argument("--overwrite", action="store_true")

    world = sub.add_parser("world", help="Crop client playspace rect → images/<name>.png")
    world.add_argument("--name", required=True)
    world.add_argument("--rect", help="x,y,width,height in client pixels")
    world.add_argument("--center", help="cx,cy — crop centered using EXODIA_SAVE_WORLD_CROP_SIZE")
    world.add_argument("--overwrite", action="store_true")

    imp = sub.add_parser("import", help="Copy image file into items/ or images/")
    imp.add_argument("--kind", required=True, choices=["items", "inventory", "images", "world"])
    imp.add_argument("--name", required=True)
    imp.add_argument("--path", required=True)
    imp.add_argument("--overwrite", action="store_true")

    ns = parser.parse_args(argv)
    if ns.command == "inventory":
        return cmd_inventory(ns)
    if ns.command == "world":
        return cmd_world(ns)
    if ns.command == "import":
        return cmd_import(ns)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
