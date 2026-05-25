#!/usr/bin/env python3
"""
Interactive inventory item labeler — turn ``?`` / ``tmp:`` slots into named templates.

Usage:
  cd Exodia && .venv/bin/python3 label_inventory_item.py

Non-interactive (save one template and exit):
  python label_inventory_item.py --name flax --slot 0,0
  python label_inventory_item.py --name flax --bucket tmp:a1b2c3d4
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

from bot_eyes import INV_ROWS, inventory_grid_cell_xywh
from bot_inventory_detect import inventory_occupancy_from_client
from bot_inventory_items import (
    bucket_slots_for_label,
    crop_inventory_slot_bgr,
    draw_inventory_item_identify_overlay,
    frame_bucket_id_from_label,
    identify_inventory_slot_items,
    is_frame_bucket_label,
    normalize_item_template_name,
    save_named_item_template,
    slot_at_client_point,
    slot_label_bucket_counts,
)
from tests.inventory_test_common import capture_client_bgr, locate_inventory_rect

_SIDEBAR_W = 280
_MAX_CANVAS_W = 1200
_MAX_CANVAS_H = 900
_ZOOM_MIN = 0.5
_ZOOM_MAX = 8.0
_ZOOM_STEP = 1.15


def _ensure_defaults() -> None:
    ps = Path("/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    if ps.is_file() and not os.environ.get("EXODIA_CAPTURE_BACKEND"):
        os.environ["EXODIA_CAPTURE_BACKEND"] = "wsl_ps"
    os.environ.setdefault("EXODIA_INV_FRAME_BUCKETS", "1")
    os.environ.setdefault("EXODIA_BUCKET_USE_SEEN_LOOSE", "1")


def _bucket_display_label(label: str) -> str:
    tid = frame_bucket_id_from_label(label)
    if tid:
        return tid[:8]
    if label.startswith("unknown:"):
        return label.split(":", 1)[-1][:8]
    return label


def _bucket_color_bgr(label: str) -> Tuple[int, int, int]:
    # OpenCV HSV hue is 0–179 (not 0–360).
    h = abs(hash(label)) % 180
    hsv = np.uint8([[[h, 200, 255]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return int(bgr[0]), int(bgr[1]), int(bgr[2])


class LabelSession:
    """Capture + identify state shared by GUI and CLI."""

    def __init__(self) -> None:
        self.client_bgr: Optional[np.ndarray] = None
        self.inv_rect: Optional[List[int]] = None
        self.occupancy: Optional[List[List[bool]]] = None
        self.slot_items: Optional[List[List[Optional[str]]]] = None
        self.error: Optional[str] = None

    def capture(self) -> bool:
        """Grab a new client frame and run full detect + identify."""
        client, err = capture_client_bgr()
        if client is None:
            self.error = err or "capture failed"
            return False
        rect, _outline, _grid = locate_inventory_rect(client)
        if rect is None:
            self.error = "inventory panel not found"
            return False
        occ, _count, _proto = inventory_occupancy_from_client(client, rect)
        if occ is None:
            self.error = "occupancy grid failed"
            return False
        self.client_bgr = client
        self.inv_rect = list(rect)
        self.occupancy = occ
        return self.reidentify()

    def reidentify(self) -> bool:
        """Re-run item identify on the current frame (no new screenshot)."""
        if self.client_bgr is None or self.inv_rect is None or self.occupancy is None:
            self.error = "no capture loaded"
            return False
        grid, _scores, _diag = identify_inventory_slot_items(
            self.client_bgr,
            self.inv_rect,
            self.occupancy,
            frame_buckets=True,
        )
        self.slot_items = grid
        self.error = None
        return True

    def refresh(self) -> bool:
        """Alias for ``capture()``."""
        return self.capture()

    def overlay_bgr(self) -> Optional[np.ndarray]:
        if self.client_bgr is None or self.inv_rect is None or self.slot_items is None:
            return None
        return draw_inventory_item_identify_overlay(
            self.client_bgr,
            self.inv_rect,
            self.slot_items,
            self.occupancy,
        )


def _parse_slot(raw: str) -> Tuple[int, int]:
    parts = [p.strip() for p in raw.replace(" ", "").split(",")]
    if len(parts) != 2:
        raise ValueError("slot must be row,col")
    row, col = int(parts[0]), int(parts[1])
    if not (0 <= row < INV_ROWS and 0 <= col < INV_COLS):
        raise ValueError("slot out of range")
    return row, col


def _label_slots(
    session: LabelSession,
    name: str,
    slots: List[Tuple[int, int]],
    *,
    overwrite: bool = False,
) -> Path:
    if session.client_bgr is None or session.inv_rect is None:
        raise RuntimeError("no capture loaded")
    if not slots:
        raise ValueError("no slots to label")
    row, col = slots[0]
    crop = crop_inventory_slot_bgr(session.client_bgr, session.inv_rect, row, col)
    if crop is None:
        raise RuntimeError("failed to crop slot (%d,%d)" % (row, col))
    return save_named_item_template(crop, name, overwrite=overwrite)


def _run_cli(args: argparse.Namespace) -> int:
    session = LabelSession()
    if not session.refresh():
        print(session.error or "refresh failed", file=sys.stderr)
        return 1
    assert session.slot_items is not None and session.occupancy is not None

    slots: List[Tuple[int, int]] = []
    if args.slot:
        slots = [_parse_slot(args.slot)]
    elif args.bucket:
        label = args.bucket.strip()
        if not label.startswith("tmp:"):
            label = "tmp:" + label.strip().lower()
        slots = bucket_slots_for_label(session.slot_items, session.occupancy, label)
        if not slots:
            print("no slots for bucket %r" % label, file=sys.stderr)
            return 1
    else:
        print("provide --slot or --bucket", file=sys.stderr)
        return 1

    try:
        path = _label_slots(session, args.name, slots, overwrite=args.overwrite)
    except FileExistsError as exc:
        print("%s (use --overwrite)" % exc, file=sys.stderr)
        return 1
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    session.reidentify()
    print("saved", path)
    return 0


def _run_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog
        from PIL import Image, ImageTk
    except ImportError as exc:
        print(
            "GUI needs tkinter and Pillow. Install: sudo apt-get install -y python3-tk",
            file=sys.stderr,
        )
        return 1

    session = LabelSession()
    if not session.capture():
        print(session.error or "initial capture failed", file=sys.stderr)
        return 1

    root = tk.Tk()
    root.title("Inventory item labeler")
    root.attributes("-topmost", True)

    main = tk.Frame(root)
    main.pack(padx=8, pady=8)

    canvas_frame = tk.Frame(main)
    canvas_frame.pack(side=tk.LEFT)

    sidebar = tk.Frame(main, width=_SIDEBAR_W)
    sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
    sidebar.pack_propagate(False)
    sidebar.grid_columnconfigure(0, weight=1, minsize=_SIDEBAR_W - 16)
    sidebar.grid_rowconfigure(3, weight=1)
    sidebar.grid_rowconfigure(6, weight=1)

    state: Dict[str, Any] = {
        "scale": 1.0,
        "base_scale": 1.0,
        "zoom": 1.0,
        "img_w": 0,
        "img_h": 0,
        "disp_w": 0,
        "disp_h": 0,
        "pil_full": None,
        "photo": None,
        "selected": None,
        "selected_label": None,
        "bucket_labels": [],
        "highlight_ids": [],
    }

    status_var = tk.StringVar(value="Click a slot or select a bucket.")
    policy_var = tk.StringVar(value="Grouping: fingerprint + template slide")

    _row = 0
    tk.Label(sidebar, text="Status", font=("", 10, "bold")).grid(
        row=_row, column=0, sticky="w"
    )
    _row += 1
    tk.Label(
        sidebar,
        textvariable=status_var,
        wraplength=_SIDEBAR_W - 8,
        justify=tk.LEFT,
    ).grid(row=_row, column=0, sticky="ew", pady=(0, 8))
    _row += 1

    tk.Label(sidebar, text="Fingerprint buckets", font=("", 10, "bold")).grid(
        row=_row, column=0, sticky="w"
    )
    _row += 1
    bucket_list = tk.Listbox(sidebar, height=8, exportselection=False)
    bucket_list.grid(row=_row, column=0, sticky="nsew", pady=(0, 4))
    _row += 1
    tk.Label(
        sidebar,
        textvariable=policy_var,
        font=("", 8),
        fg="#666",
        wraplength=_SIDEBAR_W - 8,
    ).grid(row=_row, column=0, sticky="ew", pady=(0, 8))
    _row += 1

    tk.Label(sidebar, text="Slots in bucket", font=("", 10, "bold")).grid(
        row=_row, column=0, sticky="w"
    )
    _row += 1
    slot_list = tk.Listbox(sidebar, height=6, exportselection=False)
    slot_list.grid(row=_row, column=0, sticky="nsew", pady=(0, 4))
    _actions_row = _row + 1

    _view_w = max(400, _MAX_CANVAS_W - _SIDEBAR_W - 32)
    _view_h = _MAX_CANVAS_H

    canvas_outer = tk.Frame(canvas_frame)
    canvas_outer.pack()

    zoom_bar = tk.Frame(canvas_outer)
    zoom_bar.pack(fill=tk.X, pady=(0, 4))
    zoom_var = tk.StringVar(value="100%")
    tk.Label(zoom_bar, text="Zoom").pack(side=tk.LEFT)
    tk.Label(zoom_bar, textvariable=zoom_var, width=5).pack(side=tk.LEFT, padx=(4, 8))

    viewport = tk.Frame(canvas_outer)
    viewport.pack()
    viewport.grid_rowconfigure(0, weight=1)
    viewport.grid_columnconfigure(0, weight=1)

    canvas = tk.Canvas(
        viewport,
        cursor="cross",
        highlightthickness=0,
        width=_view_w,
        height=_view_h,
    )
    vsb = tk.Scrollbar(viewport, orient=tk.VERTICAL, command=canvas.yview)
    hsb = tk.Scrollbar(viewport, orient=tk.HORIZONTAL, command=canvas.xview)
    canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")

    def _display_scale(img_w: int, img_h: int) -> float:
        return min(1.0, _view_w / img_w, _view_h / img_h)

    def _effective_scale() -> float:
        return state["base_scale"] * state["zoom"]

    def _canvas_to_client(x_canvas: float, y_canvas: float) -> Tuple[int, int]:
        inv = 1.0 / state["scale"] if state["scale"] > 0 else 1.0
        return int(round(x_canvas * inv)), int(round(y_canvas * inv))

    def _scroll_to_canvas_point(
        frac_x: float, frac_y: float, widget_x: float, widget_y: float
    ) -> None:
        disp_w = state["disp_w"]
        disp_h = state["disp_h"]
        target_x = frac_x * disp_w - widget_x
        target_y = frac_y * disp_h - widget_y
        max_x = max(0, disp_w - _view_w)
        max_y = max(0, disp_h - _view_h)
        if max_x > 0:
            canvas.xview_moveto(max(0.0, min(1.0, target_x / max_x)))
        if max_y > 0:
            canvas.yview_moveto(max(0.0, min(1.0, target_y / max_y)))

    def _update_overlay_image() -> None:
        overlay = session.overlay_bgr()
        if overlay is None:
            return
        rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
        pil_full = Image.fromarray(rgb)
        state["pil_full"] = pil_full
        state["img_w"], state["img_h"] = pil_full.size
        state["base_scale"] = _display_scale(state["img_w"], state["img_h"])

    def _render_view(
        focus_x: Optional[float] = None, focus_y: Optional[float] = None
    ) -> None:
        pil = state.get("pil_full")
        if pil is None:
            return

        old_disp_w = state.get("disp_w") or 1
        old_disp_h = state.get("disp_h") or 1
        frac_x: Optional[float] = None
        frac_y: Optional[float] = None
        if focus_x is not None and focus_y is not None:
            canvas_x = canvas.canvasx(focus_x)
            canvas_y = canvas.canvasy(focus_y)
            frac_x = canvas_x / old_disp_w
            frac_y = canvas_y / old_disp_h

        scale = _effective_scale()
        state["scale"] = scale
        disp_w = max(1, int(round(state["img_w"] * scale)))
        disp_h = max(1, int(round(state["img_h"] * scale)))
        state["disp_w"] = disp_w
        state["disp_h"] = disp_h

        pil_disp = (
            pil.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
            if (disp_w, disp_h) != pil.size
            else pil
        )
        state["photo"] = ImageTk.PhotoImage(pil_disp)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor=tk.NW, image=state["photo"], tags="image")
        canvas.config(scrollregion=(0, 0, disp_w, disp_h))
        zoom_var.set("%d%%" % int(round(state["zoom"] * 100)))

        if frac_x is not None and frac_y is not None:
            _scroll_to_canvas_point(frac_x, frac_y, focus_x, focus_y)

        state["highlight_ids"] = []
        sel_label = state.get("selected_label")
        if sel_label:
            _draw_highlights(sel_label)

    def _zoom_by(factor: float, focus_x: Optional[float] = None, focus_y: Optional[float] = None) -> None:
        new_zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, state["zoom"] * factor))
        if abs(new_zoom - state["zoom"]) < 1e-6:
            return
        state["zoom"] = new_zoom
        _render_view(focus_x, focus_y)

    def _zoom_reset() -> None:
        state["zoom"] = 1.0
        _render_view()
        canvas.xview_moveto(0)
        canvas.yview_moveto(0)

    tk.Button(zoom_bar, text="−", width=2, command=lambda: _zoom_by(1.0 / _ZOOM_STEP)).pack(
        side=tk.LEFT, padx=(0, 2)
    )
    tk.Button(zoom_bar, text="+", width=2, command=lambda: _zoom_by(_ZOOM_STEP)).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    tk.Button(zoom_bar, text="Reset", command=_zoom_reset).pack(side=tk.LEFT)
    tk.Label(
        zoom_bar,
        text="Wheel = zoom · middle-drag = pan",
        font=("", 8),
        fg="#666",
    ).pack(side=tk.LEFT, padx=(8, 0))

    def _cell_disp_rect(row: int, col: int) -> Optional[Tuple[int, int, int, int]]:
        if session.inv_rect is None:
            return None
        cell = inventory_grid_cell_xywh(tuple(session.inv_rect), row, col, 0)
        if cell is None:
            return None
        x, y, w, h = cell
        s = state["scale"]
        return int(x * s), int(y * s), max(1, int(w * s)), max(1, int(h * s))

    def _rebuild_bucket_list() -> None:
        bucket_list.delete(0, tk.END)
        state["bucket_labels"] = []
        if session.slot_items is None or session.occupancy is None:
            return
        counts = slot_label_bucket_counts(session.slot_items, session.occupancy)
        for label, n in counts:
            short = _bucket_display_label(label)
            bucket_list.insert(tk.END, "%s x%d" % (short, n))
            state["bucket_labels"].append(label)

    def _fill_slot_list(label: Optional[str]) -> None:
        slot_list.delete(0, tk.END)
        if label is None or session.slot_items is None or session.occupancy is None:
            return
        for row, col in bucket_slots_for_label(
            session.slot_items, session.occupancy, label
        ):
            slot_list.insert(tk.END, "(%d,%d)" % (row, col))

    def _update_status(row: Optional[int], col: Optional[int]) -> None:
        if row is None or col is None or session.slot_items is None:
            status_var.set("Click a slot or select a bucket.")
            return
        label = session.slot_items[row][col]
        crop = None
        if session.client_bgr is not None and session.inv_rect is not None:
            crop = crop_inventory_slot_bgr(session.client_bgr, session.inv_rect, row, col)
        size = "%dx%d" % (crop.shape[1], crop.shape[0]) if crop is not None else "?"
        status_var.set("(%d,%d)  label=%s  crop=%s" % (row, col, label or "?", size))

    def _clear_highlights() -> None:
        for rid in state["highlight_ids"]:
            canvas.delete(rid)
        state["highlight_ids"] = []

    def _draw_highlights(label: Optional[str]) -> None:
        _clear_highlights()
        if label is None or session.slot_items is None or session.occupancy is None:
            return
        color = _bucket_color_bgr(label)
        hex_color = "#%02x%02x%02x" % (color[2], color[1], color[0])
        for row, col in bucket_slots_for_label(
            session.slot_items, session.occupancy, label
        ):
            rect = _cell_disp_rect(row, col)
            if rect is None:
                continue
            x, y, w, h = rect
            rid = canvas.create_rectangle(
                x, y, x + w, y + h, outline=hex_color, width=2
            )
            state["highlight_ids"].append(rid)

    def _select_label(label: Optional[str], row: Optional[int] = None, col: Optional[int] = None) -> None:
        state["selected_label"] = label
        if row is not None and col is not None:
            state["selected"] = (row, col)
        _fill_slot_list(label)
        _draw_highlights(label)
        _update_status(
            row if row is not None else (state["selected"][0] if state["selected"] else None),
            col if col is not None else (state["selected"][1] if state["selected"] else None),
        )
        if label is not None:
            for i, bl in enumerate(state["bucket_labels"]):
                if bl == label:
                    bucket_list.selection_clear(0, tk.END)
                    bucket_list.selection_set(i)
                    bucket_list.see(i)
                    break

    def _refresh_canvas(*, reset_zoom: bool = False) -> None:
        if reset_zoom:
            state["zoom"] = 1.0
        _update_overlay_image()
        _render_view()
        if reset_zoom:
            canvas.xview_moveto(0)
            canvas.yview_moveto(0)

    def _sync_ui_after_identify(*, reset_zoom: bool = False) -> None:
        _rebuild_bucket_list()
        sel = state.get("selected")
        if sel and session.slot_items is not None:
            row, col = sel
            if row < len(session.slot_items) and col < len(session.slot_items[row]):
                _select_label(session.slot_items[row][col], row, col)
            else:
                _select_label(None)
        elif state.get("selected_label"):
            _select_label(state["selected_label"])
        _refresh_canvas(reset_zoom=reset_zoom)

    def _refresh_all() -> None:
        if not session.capture():
            messagebox.showerror("Capture failed", session.error or "unknown error")
            return
        _sync_ui_after_identify(reset_zoom=True)

    def _ask_name(initial: str = "") -> Optional[str]:
        raw = simpledialog.askstring("Item name", "Template name (items/<name>.png):", initialvalue=initial)
        if raw is None:
            return None
        stem = normalize_item_template_name(raw)
        if stem is None:
            messagebox.showerror("Invalid name", "Use letters, numbers, underscores only.")
            return _ask_name(raw)
        return stem

    def _confirm_overwrite(path: Path) -> bool:
        return messagebox.askyesno(
            "Overwrite?",
            "%s already exists.\nOverwrite?" % path.name,
            default=messagebox.NO,
        )

    def _do_label(slots: List[Tuple[int, int]]) -> None:
        if not slots or session.slot_items is None:
            return
        row, col = slots[0]
        existing = session.slot_items[row][col]
        initial = ""
        if existing and not is_frame_bucket_label(existing) and existing != "?":
            if not messagebox.askyesno(
                "Already labeled",
                "Slot (%d,%d) is already %r.\nSave under a new name anyway?"
                % (row, col, existing),
                default=messagebox.NO,
            ):
                return
            initial = existing if not existing.startswith("unknown:") else ""

        name = _ask_name(initial)
        if name is None:
            return
        path = _EXODIA / "items" / ("%s.png" % name)
        overwrite = False
        if path.is_file() and not _confirm_overwrite(path):
            return
        if path.is_file():
            overwrite = True
        try:
            saved = _label_slots(session, name, slots, overwrite=overwrite)
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        messagebox.showinfo("Saved", "Wrote %s" % saved.name)
        if not session.reidentify():
            messagebox.showerror("Re-identify failed", session.error or "unknown error")
            return
        _sync_ui_after_identify()

    def on_canvas_click(event) -> None:
        if session.inv_rect is None:
            return
        cx, cy = _canvas_to_client(canvas.canvasx(event.x), canvas.canvasy(event.y))
        hit = slot_at_client_point(cx, cy, session.inv_rect, occupancy=session.occupancy)
        if hit is None:
            return
        row, col = hit
        label = session.slot_items[row][col] if session.slot_items else None
        state["selected"] = (row, col)
        _select_label(label, row, col)

    def on_wheel(event) -> None:
        if hasattr(event, "delta") and event.delta:
            factor = _ZOOM_STEP if event.delta > 0 else 1.0 / _ZOOM_STEP
        elif getattr(event, "num", None) == 4:
            factor = _ZOOM_STEP
        elif getattr(event, "num", None) == 5:
            factor = 1.0 / _ZOOM_STEP
        else:
            return
        _zoom_by(factor, event.x, event.y)

    def on_pan_start(event) -> None:
        canvas.scan_mark(event.x, event.y)

    def on_pan_move(event) -> None:
        canvas.scan_dragto(event.x, event.y, gain=1)

    def on_bucket_select(_event=None) -> None:
        sel = bucket_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(state["bucket_labels"]):
            return
        label = state["bucket_labels"][idx]
        slots = bucket_slots_for_label(
            session.slot_items or [], session.occupancy or [], label
        )
        row, col = slots[0] if slots else (None, None)
        state["selected"] = (row, col) if row is not None else None
        _select_label(label, row, col)

    def on_slot_select(_event=None) -> None:
        sel = slot_list.curselection()
        if not sel:
            return
        text = slot_list.get(int(sel[0]))
        try:
            inner = text.strip("()")
            row_s, col_s = inner.split(",")
            row, col = int(row_s), int(col_s)
        except (ValueError, AttributeError):
            return
        state["selected"] = (row, col)
        label = session.slot_items[row][col] if session.slot_items else None
        _select_label(label, row, col)

    def label_bucket() -> None:
        label = state.get("selected_label")
        if label is None or session.slot_items is None or session.occupancy is None:
            messagebox.showinfo("Select bucket", "Select a bucket or slot first.")
            return
        slots = bucket_slots_for_label(session.slot_items, session.occupancy, label)
        _do_label(slots)

    def label_slot() -> None:
        sel = state.get("selected")
        if sel is None:
            messagebox.showinfo("Select slot", "Click a slot on the canvas.")
            return
        _do_label([sel])

    btn_row = tk.Frame(sidebar)
    btn_row.grid(row=_actions_row, column=0, sticky="ew", pady=(8, 0))
    btn_row.grid_columnconfigure(0, weight=1)
    _btn_ipady = 6
    tk.Button(btn_row, text="Label bucket…", command=label_bucket).grid(
        row=0, column=0, sticky="ew", pady=2, ipady=_btn_ipady
    )
    tk.Button(btn_row, text="Label slot…", command=label_slot).grid(
        row=1, column=0, sticky="ew", pady=2, ipady=_btn_ipady
    )
    tk.Button(btn_row, text="Refresh capture", command=_refresh_all).grid(
        row=2, column=0, sticky="ew", pady=2, ipady=_btn_ipady
    )
    tk.Button(btn_row, text="Quit", command=root.destroy).grid(
        row=3, column=0, sticky="ew", pady=2, ipady=_btn_ipady
    )

    bucket_list.bind("<<ListboxSelect>>", on_bucket_select)
    slot_list.bind("<ButtonRelease-1>", on_slot_select)
    canvas.bind("<ButtonPress-1>", on_canvas_click)
    canvas.bind("<MouseWheel>", on_wheel)
    canvas.bind("<Button-4>", on_wheel)
    canvas.bind("<Button-5>", on_wheel)
    canvas.bind("<ButtonPress-2>", on_pan_start)
    canvas.bind("<B2-Motion>", on_pan_move)
    canvas.bind("<Control-MouseWheel>", lambda e: _zoom_reset())
    canvas.focus_set()

    _rebuild_bucket_list()
    _refresh_canvas()

    try:
        root.mainloop()
    except tk.TclError as exc:
        msg = str(exc).lower()
        if "no display" in msg or "display" in msg:
            print(
                "No graphical display for tkinter. Use WSLg, set DISPLAY=:0, "
                "or use --name / --slot for non-interactive labeling.",
                file=sys.stderr,
            )
            return 1
        raise
    return 0


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Label inventory item templates")
    p.add_argument("--name", metavar="NAME", help="Template stem (non-interactive)")
    p.add_argument("--slot", metavar="ROW,COL", help="Label from one slot")
    p.add_argument("--bucket", metavar="TMP_ID", help="Label from tmp bucket (tmp:… or hex id)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing items/<name>.png")
    return p.parse_args(argv)


def main(argv=None) -> int:
    os.chdir(_EXODIA)
    _ensure_defaults()
    args = _parse_args(argv)
    if args.name and (args.slot or args.bucket):
        return _run_cli(args)
    if args.name or args.slot or args.bucket:
        print("Non-interactive mode requires --name and (--slot or --bucket)", file=sys.stderr)
        return 1
    return _run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
