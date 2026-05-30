#!/usr/bin/env python3
"""
One-shot Eyes capture of the RuneLite client window → PNG + optional **UI breakdown**.

Imports only ``ClientWindow`` + ``BotEyes`` (not ``bot_actions``), so PyAutoGUI / Xauthority
are not loaded — capture works in minimal X/WSL setups where importing ``pyautogui`` fails.

**Breakdown (default on):** uses ``BotEyes`` geometry — template-based **inventory** detection
(``images/ui_icons.png``), fixed **chat strip** from ``setRect``, and the **action** ROI
(``ACTION_STRIP_ROI_CLIENT_LOCAL``). Writes crops next to ``-o`` and a JSON manifest.

Minimal venv deps (approx.):

  pip install numpy opencv-python-headless mss Pillow pytesseract scipy scikit-learn PyAutoGUI

**Capture workspace:** outputs default to ``Exodia/captures/`` (see ``--captures-root``).
That directory is **emptied at startup** every run (only paths under ``Exodia/`` are allowed).
Sidecars stay beside ``-o``; default ``-o`` lives inside this workspace.
On **WSLg**, Python ``mss`` often produces an **all-black** image — set
``EXODIA_CAPTURE_BACKEND=wsl_ps`` (or pass ``--capture-backend wsl_ps``) to capture via Windows
PowerShell GDI (**Win32 coordinates**).

Default mode: ``xdotool`` + RuneLite window title (substring ``RuneLite``).
Use ``--full-primary`` for the primary display, or ``--rect L,T,W,H`` when you already know coords.

See ``window_tool.linux_activate_move_resize`` for Linux client-window snapping.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_EXODIA_DIR = Path(__file__).resolve().parent


def _path_within_exodia(path: Path) -> bool:
    """Allow only paths nested under ``Exodia/``."""
    rp = path.resolve()
    try:
        rp.relative_to(_EXODIA_DIR.resolve())
        return True
    except ValueError:
        return False


def wipe_capture_workspace(root: Path) -> Path:
    """
    Empty ``root`` recursively (preserve the directory itself). Only runs if ``root``
    resolves under ``Exodia/``.
    """
    root = root.resolve()
    if not _path_within_exodia(root):
        raise ValueError(
            "Refusing to wipe captures directory outside Exodia/: %s" % root,
        )
    root.mkdir(parents=True, exist_ok=True)
    for entry in list(root.iterdir()):
        try:
            if entry.is_symlink():
                entry.unlink(missing_ok=True)
            elif entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        except FileNotFoundError:
            continue
    return root


def _apply_capture_backend_argv() -> None:
    """Set ``EXODIA_CAPTURE_BACKEND`` from ``--capture-backend X`` before ``bot_env`` import."""
    for i, tok in enumerate(sys.argv[:-1]):
        if tok == "--capture-backend":
            raw = sys.argv[i + 1].strip()
            if raw:
                os.environ["EXODIA_CAPTURE_BACKEND"] = raw.lower()
            break


_apply_capture_backend_argv()

import bot_client as Client
import bot_env as Env
import bot_eyes as Eyes
from bot_capture import FrameSnapshot
from bot_client_text import ClientTextSnapshot, ColoredTextSpan, TextFinder
from bot_frames import safe_imwrite, write_breakdown_sidecars
from bot_runtime import ensure_logs_dir, write_json_atomic

_EXODIA_LOGS_DIAG = _EXODIA_DIR / "logs" / "diag"

_TEXT_COLOR_BGR = {
    "green": (0, 255, 0),
    "red": (0, 0, 255),
    "yellow": (0, 255, 255),
    "cyan": (255, 255, 0),
    "orange": (0, 165, 255),
    "white": (255, 255, 255),
    "unknown": (128, 128, 128),
}


def _span_to_dict(span: ColoredTextSpan) -> dict:
    return {
        "text": span.text,
        "color": span.color,
        "bbox": list(span.bbox),
        "conf": round(span.conf, 1),
        "source": span.source,
    }


def _text_snapshot_to_dict(snap: ClientTextSnapshot) -> dict:
    return {
        "processed_seq": snap.processed_seq,
        "capture_seq": snap.capture_seq,
        "client_size": list(snap.client_size),
        "elapsed_ms": round(snap.elapsed_ms, 1),
        "span_count": len(snap.spans),
        "spans": [_span_to_dict(s) for s in snap.spans],
    }


def _draw_text_span_overlay(client_bgr, spans: tuple) -> "object":
    import cv2  # noqa: PLC0415

    vis = client_bgr.copy()
    for span in spans:
        x, y, w, h = (int(v) for v in span.bbox)
        color = _TEXT_COLOR_BGR.get(span.color.lower(), _TEXT_COLOR_BGR["unknown"])
        cv2.rectangle(vis, (x, y), (x + w, y + h), color, 1)
        label = "%s:%s" % (span.color[:1].upper(), span.text[:24])
        ty = max(y - 4, 10)
        cv2.putText(
            vis,
            label,
            (x, ty),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            color,
            1,
            cv2.LINE_AA,
        )
    return vis


def write_text_dump(
    client_bgr,
    *,
    client_rect: list,
    overlay: bool = False,
) -> dict:
    """Run ``TextFinder.scan`` on client crop; write JSON (+ optional overlay) under logs/diag/."""
    ensure_logs_dir()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = _EXODIA_LOGS_DIAG / ("text_dump_%s" % stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    snap = FrameSnapshot(
        bgr=client_bgr,
        seq=1,
        ts=time.monotonic(),
        client_rect=list(client_rect),
        age_ms=0.0,
    )
    result = TextFinder.scan(snap)
    payload = _text_snapshot_to_dict(result)
    payload["client_rect"] = list(client_rect)
    json_path = out_dir / "text_spans.json"
    write_json_atomic(json_path, payload)

    paths = {"json": str(json_path.resolve()), "dir": str(out_dir.resolve())}
    if overlay:
        overlay_bgr = _draw_text_span_overlay(client_bgr, result.spans)
        overlay_path = out_dir / "text_overlay.png"
        if safe_imwrite(overlay_path, overlay_bgr):
            paths["overlay"] = str(overlay_path.resolve())
    return paths


def main() -> int:
    p = argparse.ArgumentParser(description="Capture RuneLite via BotEyes to a PNG file.")
    p.add_argument(
        "--captures-root",
        default="captures",
        metavar="DIR",
        help="Directory relative to Exodia/ (must stay under Exodia/). Wiped empty at startup. Default: captures",
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="PATH",
        help="Primary PNG path (default: <captures-root>/runelite_capture.png).",
    )
    p.add_argument("--debug", action="store_true", help="Eyes/debug views (opencv windows).")
    p.add_argument(
        "--capture-backend",
        metavar="NAME",
        help="Forwarded to bot_env capture backend (parsed early): mss | pil | wsl_ps. WSL/WSLg: use wsl_ps if captures are black.",
    )
    p.add_argument(
        "--segments",
        dest="segments",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write crops + perception JSON next to -o (default: on).",
    )
    p.add_argument(
        "--ocr",
        action="store_true",
        help="Run Tesseract on action + chat strips (requires tesseract on PATH or EXODIA_TESSERACT_CMD).",
    )
    p.add_argument(
        "--annotate",
        action="store_true",
        help="Write *_ui_rois_overlay.png with inventory/chat/action rectangles.",
    )
    p.add_argument(
        "--annotate-inventory",
        action="store_true",
        help="Save *_inventory_grid_debug.png when inventory_rect exists (occupied vs empty overlay).",
    )
    p.add_argument(
        "--write-masked",
        action="store_true",
        help="Also save *_masked.png (post update() black bars — matches legacy BotEyes.curr_client).",
    )
    p.add_argument(
        "--text-dump",
        action="store_true",
        help="Run TextFinder.scan on client crop; write JSON spans to logs/diag/.",
    )
    p.add_argument(
        "--text-dump-overlay",
        action="store_true",
        help="With --text-dump, also write text_overlay.png with colored span boxes.",
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--full-primary",
        action="store_true",
        help="Skip window lookup — capture primary monitor (under WSLg use --capture-backend wsl_ps if mss is black).",
    )
    src.add_argument(
        "--rect",
        metavar="L,T,W,H",
        help="Explicit screen rectangle; skip ClientWindow / xdotool (comma-separated ints).",
    )
    args = p.parse_args()

    cap_arg = Path(args.captures_root)
    captures_root = cap_arg if cap_arg.is_absolute() else (_EXODIA_DIR / cap_arg).resolve()
    try:
        wipe_capture_workspace(captures_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.output is None:
        out_path = (captures_root / "runelite_capture.png").resolve()
    else:
        out_opt = Path(os.path.expanduser(args.output)).expanduser()
        out_path = out_opt.resolve() if out_opt.is_absolute() else (Path.cwd() / out_opt).resolve()

    print("capture_workspace_cleared:", str(captures_root.resolve()))

    if args.full_primary:
        eyes = Eyes.BotEyes(DEBUG=args.debug)
        eyes.setRect(Env.primary_monitor_rect())
    elif args.rect:
        parts = [int(x.strip()) for x in args.rect.replace(" ", "").split(",")]
        if len(parts) != 4:
            print("Expected --rect L,T,W,H (four integers).", file=sys.stderr)
            return 2
        eyes = Eyes.BotEyes(DEBUG=args.debug)
        eyes.setRect(parts)
    else:
        client = Client.ClientWindow(DEBUG=args.debug)
        eyes = Eyes.BotEyes(DEBUG=args.debug)
        eyes.setRect(client.win_rect)
        client.update()
        eyes.setRect(client.win_rect)

    primary_bgr = eyes.curr_client_unmasked if eyes.curr_client_unmasked is not None else eyes.curr_client
    if primary_bgr is None:
        print("eyes.curr_client_unmasked / curr_client is None — capture failed.", file=sys.stderr)
        return 1

    if not safe_imwrite(out_path, primary_bgr):
        print("cv2.imwrite failed for %r" % str(out_path), file=sys.stderr)
        return 1

    print("Saved (unmasked client):", str(out_path))
    print("Shape (H,W,C):", primary_bgr.shape)
    print("client_rect screen [L,T,W,H]:", list(eyes.client_rect))
    if eyes.perception_envelope:
        print("capture_backend:", eyes.perception_envelope.get("capture_backend"))
        print("inventory_rect (client-local):", eyes.perception_envelope.get("inventory_rect_client_local"))

    if args.segments:
        side = write_breakdown_sidecars(
            eyes,
            out_path,
            ocr=args.ocr,
            annotate=args.annotate,
            annotate_inventory=args.annotate_inventory,
            write_masked_copy=args.write_masked,
        )
        print("Sidecars:", ", ".join("%s=%s" % (k, v) for k, v in sorted(side.items())))

    if args.text_dump:
        try:
            dump_paths = write_text_dump(
                primary_bgr,
                client_rect=list(eyes.client_rect),
                overlay=args.text_dump_overlay,
            )
            print("Text dump:", dump_paths.get("json"))
            if dump_paths.get("overlay"):
                print("Text overlay:", dump_paths["overlay"])
        except Exception as exc:
            print("Text dump failed:", exc, file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
