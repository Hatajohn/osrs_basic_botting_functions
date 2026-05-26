#!/usr/bin/env python3
"""
Strip inventory plate background from item template PNGs.

Writes transparent-background BGRA icons (tight-cropped by default).

  python strip_item_backgrounds.py
  python strip_item_backgrounds.py --seen
  python strip_item_backgrounds.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

import cv2

from bot_inventory_count import strip_inventory_plate_background
from bot_match_index import is_temp_item_id, items_directory, seen_images_directory


def _process_paths(
    paths: Iterable[Path],
    *,
    dry_run: bool,
) -> Tuple[int, int, List[str]]:
    changed = 0
    skipped = 0
    lines: List[str] = []
    for path in sorted(paths):
        raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if raw is None or raw.size == 0:
            skipped += 1
            lines.append("skip unreadable: %s" % path)
            continue
        if raw.ndim == 3 and raw.shape[2] == 4:
            alpha = raw[:, :, 3]
            if int((alpha > 0).sum()) >= 16 and int((alpha == 0).sum()) >= 16:
                skipped += 1
                lines.append("skip already stripped: %s" % path.name)
                continue
        bgr = raw[:, :, :3] if raw.ndim == 3 else raw
        out = strip_inventory_plate_background(bgr)
        if out is None or out.size == 0:
            skipped += 1
            lines.append("skip empty result: %s" % path.name)
            continue
        h, w = out.shape[:2]
        alpha_px = int((out[:, :, 3] > 0).sum()) if out.shape[2] == 4 else h * w
        lines.append("strip %s -> %dx%d (%d fg px)" % (path.name, w, h, alpha_px))
        if not dry_run:
            if not cv2.imwrite(str(path), out):
                skipped += 1
                lines[-1] += " [write failed]"
                continue
        changed += 1
    return changed, skipped, lines


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove inventory plate from item PNGs")
    parser.add_argument(
        "--items-dir",
        type=Path,
        default=None,
        help="items/ root (default: EXODIA_ITEMS_DIR or ./items)",
    )
    parser.add_argument(
        "--seen",
        action="store_true",
        help="Also process items/seen/*.png temp-id templates",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing files",
    )
    args = parser.parse_args(argv)

    root = args.items_dir.expanduser().resolve() if args.items_dir else items_directory()
    paths: List[Path] = []
    if root.is_dir():
        for path in sorted(root.glob("*.png")):
            if is_temp_item_id(path.stem):
                continue
            paths.append(path)
    if args.seen:
        seen_dir = seen_images_directory(root)
        if seen_dir.is_dir():
            paths.extend(sorted(seen_dir.glob("*.png")))

    if not paths:
        print("No item PNGs found under %s" % root, file=sys.stderr)
        return 1

    changed, skipped, lines = _process_paths(paths, dry_run=args.dry_run)
    for line in lines:
        print(line)
    print(
        "%s %d file(s), skipped %d"
        % ("would strip" if args.dry_run else "stripped", changed, skipped)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
