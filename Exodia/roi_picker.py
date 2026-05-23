"""
Interactive ROI selection for calibration (WSL-friendly).

OpenCV in requirements-minimal is ``opencv-python-headless`` (no ``selectROI``).
This module uses tkinter + Pillow instead.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

Rect4 = Tuple[int, int, int, int]  # x, y, width, height in image pixels


def select_roi_bgr(image_bgr: np.ndarray, title: str = "Select region") -> Optional[Rect4]:
    """
    Show *image_bgr* (OpenCV BGR) and let the user drag a rectangle.

    Returns ``(x, y, width, height)`` in full-resolution image coordinates,
    or ``None`` if cancelled.
    """
    try:
        import tkinter as tk
        from PIL import Image, ImageTk
    except ImportError as exc:
        raise RuntimeError(
            "ROI picker needs tkinter and Pillow. Install: sudo apt-get install -y python3-tk"
        ) from exc

    import cv2

    if image_bgr is None or image_bgr.size == 0:
        return None

    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    pil_full = Image.fromarray(rgb)

    max_w, max_h = 1600, 900
    scale = min(1.0, max_w / pil_full.width, max_h / pil_full.height)
    disp_w = max(1, int(pil_full.width * scale))
    disp_h = max(1, int(pil_full.height * scale))
    pil_disp = (
        pil_full.resize((disp_w, disp_h), Image.Resampling.LANCZOS)
        if scale < 1.0
        else pil_full
    )

    root = tk.Tk()
    root.title(title)
    root.attributes("-topmost", True)

    frame = tk.Frame(root)
    frame.pack(padx=8, pady=8)

    hint = tk.Label(
        frame,
        text="Drag a box around the RuneLite client, then click Save (or press Enter). Esc = cancel.",
        wraplength=disp_w,
    )
    hint.pack(anchor="w", pady=(0, 6))

    photo = ImageTk.PhotoImage(pil_disp)
    canvas = tk.Canvas(frame, width=disp_w, height=disp_h, cursor="cross")
    canvas.pack()
    canvas.create_image(0, 0, anchor=tk.NW, image=photo)

    state = {"x0": None, "y0": None, "rect_id": None, "x1": None, "y1": None}
    result: List[Optional[Rect4]] = [None]

    def _delete_rect() -> None:
        if state["rect_id"] is not None:
            canvas.delete(state["rect_id"])
            state["rect_id"] = None

    def on_press(event) -> None:
        state["x0"] = event.x
        state["y0"] = event.y
        state["x1"] = event.x
        state["y1"] = event.y
        _delete_rect()

    def on_drag(event) -> None:
        if state["x0"] is None:
            return
        state["x1"] = event.x
        state["y1"] = event.y
        _delete_rect()
        state["rect_id"] = canvas.create_rectangle(
            state["x0"],
            state["y0"],
            event.x,
            event.y,
            outline="#00ff66",
            width=2,
        )

    def on_release(event) -> None:
        if state["x0"] is None:
            return
        state["x1"] = event.x
        state["y1"] = event.y

    def _selection_disp() -> Optional[Rect4]:
        if state["x0"] is None or state["x1"] is None:
            return None
        x0, y0 = state["x0"], state["y0"]
        x1, y1 = state["x1"], state["y1"]
        left = min(x0, x1)
        top = min(y0, y1)
        w = abs(x1 - x0)
        h = abs(y1 - y0)
        if w < 2 or h < 2:
            return None
        return left, top, w, h

    def _to_image_coords(disp: Rect4) -> Rect4:
        inv = 1.0 / scale if scale > 0 else 1.0
        x, y, w, h = disp
        return (
            int(round(x * inv)),
            int(round(y * inv)),
            int(round(w * inv)),
            int(round(h * inv)),
        )

    def confirm() -> None:
        disp = _selection_disp()
        if disp is None:
            return
        result[0] = _to_image_coords(disp)
        root.destroy()

    def cancel() -> None:
        result[0] = None
        root.destroy()

    btn_row = tk.Frame(frame)
    btn_row.pack(pady=(8, 0))
    tk.Button(btn_row, text="Save", command=confirm, width=10).pack(side=tk.LEFT, padx=4)
    tk.Button(btn_row, text="Cancel", command=cancel, width=10).pack(side=tk.LEFT, padx=4)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Return>", lambda _e: confirm())
    root.bind("<Escape>", lambda _e: cancel())
    root.protocol("WM_DELETE_WINDOW", cancel)

    try:
        root.mainloop()
    except tk.TclError as exc:
        msg = str(exc).lower()
        if "no display" in msg or "display" in msg:
            raise RuntimeError(
                "No graphical display for tkinter. Use WSLg, set DISPLAY=:0, "
                "or pass --rect LEFT,TOP,WIDTH,HEIGHT manually."
            ) from exc
        raise

    return result[0]
