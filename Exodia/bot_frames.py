"""
Frame sidecar writer for Exodia perception crops.

Extracts PNG breakdown logic shared by ``capture_runelite_once.py`` and optional
session recording. Writes masked world view, UI strips, inventory, and perception JSON.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import bot_eyes as Eyes

__all__ = [
    "safe_imwrite",
    "annotate_regions",
    "build_manifest",
    "write_tick_frames",
    "write_breakdown_sidecars",
]


def safe_imwrite(path: Path, image) -> bool:
    import cv2  # noqa: PLC0415

    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(path), image))


def annotate_regions(eyes: "Eyes.BotEyes") -> Optional[Any]:
    """BGR image with inventory / chat / action ROIs outlined (client-local coords)."""
    import cv2  # noqa: PLC0415

    base = eyes.curr_client_unmasked
    if base is None:
        return None
    vis = base.copy()
    envp = eyes.perception_envelope or {}
    inv = envp.get("inventory_rect_client_local")
    if inv and len(inv) == 4:
        x, y, w, h = [int(v) for v in inv]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 200, 0), 2)
    if eyes.chat_rect and len(eyes.chat_rect) == 4:
        x, y, w, h = [int(v) for v in eyes.chat_rect]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (255, 128, 0), 2)
    ar = envp.get("action_strip_roi_client_local")
    if ar and len(ar) == 4:
        x, y, w, h = [int(v) for v in ar]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (200, 0, 255), 2)
    return vis


def build_manifest(eyes: "Eyes.BotEyes", ocr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    pe = dict(eyes.perception_envelope) if eyes.perception_envelope else {}
    inv = bool(pe.get("inventory_rect_client_local"))
    return {
        "perception_envelope": pe,
        "inventory_template_match": inv,
        "files_note": (
            "Inventory uses template images/ui_icons.png; omit or fail leaves inventory_* absent."
        ),
        "ocr": ocr,
    }


def write_breakdown_sidecars(
    eyes: "Eyes.BotEyes",
    primary_out: Path,
    *,
    ocr: bool,
    annotate: bool,
    annotate_inventory: bool,
    write_masked_copy: bool,
) -> Dict[str, str]:
    """Write segment PNGs + JSON manifest; return logical name -> path."""
    import bot_eyes as Eyes  # noqa: PLC0415

    stem = primary_out.stem
    directory = primary_out.parent
    sidecars: Dict[str, str] = {}

    if write_masked_copy and eyes.curr_client is not None:
        p_masked = directory / ("%s_masked.png" % stem)
        if safe_imwrite(p_masked, eyes.curr_client):
            sidecars["world_masked"] = str(p_masked)

    unmasked = eyes.curr_client_unmasked
    if annotate:
        overlay = annotate_regions(eyes)
        if overlay is not None:
            p_ann = directory / ("%s_ui_rois_overlay.png" % stem)
            if safe_imwrite(p_ann, overlay):
                sidecars["ui_rois_overlay"] = str(p_ann)

    if unmasked is not None and eyes.chat_rect and len(eyes.chat_rect) == 4:
        ch = eyes.crop_client_local(list(eyes.chat_rect))
        if ch is not None and ch.size:
            pc = directory / ("%s_chat_strip.png" % stem)
            if safe_imwrite(pc, ch):
                sidecars["chat_strip"] = str(pc)

    crop_a = eyes.crop_client_local(list(Eyes.ACTION_STRIP_ROI_CLIENT_LOCAL))
    if crop_a is not None and crop_a.size:
        pa = directory / ("%s_action_strip.png" % stem)
        if safe_imwrite(pa, crop_a):
            sidecars["action_strip"] = str(pa)

    inv = getattr(eyes, "curr_inventory", None)
    if inv is not None and inv.size:
        pi = directory / ("%s_inventory.png" % stem)
        if safe_imwrite(pi, inv):
            sidecars["inventory"] = str(pi)

    if annotate_inventory:
        inv_dbg = eyes.draw_inventory_grid_debug()
        if inv_dbg is not None:
            pname = directory / ("%s_inventory_grid_debug.png" % stem)
            if safe_imwrite(pname, inv_dbg):
                sidecars["inventory_grid_debug"] = str(pname)

    ocr_meta: Optional[Dict[str, Any]] = None
    if ocr:
        ocr_meta = {
            "action_strip": eyes.ocr_action_text_roi(),
            "dialogue_chat_strip": eyes.ocr_dialogue_roi(),
        }

    pj = directory / ("%s_perception.json" % stem)
    sidecars["perception_json"] = str(pj)
    manifest = build_manifest(eyes, ocr_meta)
    manifest["sidecars"] = dict(sidecars)
    pj.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return sidecars


def write_tick_frames(
    eyes: "Eyes.BotEyes",
    out_dir: Path,
    stem: str,
    *,
    ocr: bool = True,
    annotate: bool = False,
    annotate_inventory: bool = False,
) -> Dict[str, str]:
    """
    Write per-tick frame sidecars under ``out_dir`` with logical crop keys.

    Returns logical name -> absolute path (``world_masked``, ``action_strip``, etc.).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    primary = out_dir / ("%s.png" % stem)
    unmasked = eyes.curr_client_unmasked if eyes.curr_client_unmasked is not None else eyes.curr_client
    if unmasked is not None:
        safe_imwrite(primary, unmasked)
    return write_breakdown_sidecars(
        eyes,
        primary,
        ocr=ocr,
        annotate=annotate,
        annotate_inventory=annotate_inventory,
        write_masked_copy=True,
    )
