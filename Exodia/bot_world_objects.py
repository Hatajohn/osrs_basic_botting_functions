"""
World object template detection in the main playspace (outside inventory).

Primary path: find RuneLite **cyan tile markers** via
``bot_spot_verify.locate_cyan_marker_regions``, then match the world icon template
in a padded window around each marker (skips inventory hits and markers with no icon).

Fallback: full playspace template scan when ``EXODIA_WORLD_CYAN_FIRST=0`` or
``EXODIA_WORLD_CYAN_FALLBACK=1`` and the cyan path finds nothing.

No eel/cyan spot verification — template match only. Reuses
``bot_spot_verify.dedupe_spot_candidates`` for near-duplicate suppression.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, TYPE_CHECKING, Tuple

import cv2
import numpy as np

from bot_inventory_detect import draw_inventory_outline_overlay
from bot_search import playspace_search_roi
from bot_spot_verify import (
    CyanMarkerRegion,
    SacredEelSpotCandidate,
    _client_bgr_for_spot_ops,
    dedupe_spot_candidates,
    locate_cyan_marker_regions,
)

if TYPE_CHECKING:
    import bot_eyes as Eyes

_EXODIA_DIR = Path(__file__).resolve().parent

__all__ = [
    "WorldObjectHit",
    "WorldObjectLocateResult",
    "capture_template_path",
    "captures_dir",
    "draw_world_detect_overlay",
    "filter_matches_outside_rect",
    "locate_world_objects",
    "locate_world_objects_from_eyes",
    "world_cyan_first_enabled",
    "world_match_threshold",
    "world_template_names",
    "resolve_world_template_file",
]


def captures_dir() -> Path:
    """Root directory for capture PNGs (``EXODIA_CAPTURES_DIR`` or ``<exodia>/captures``)."""
    raw = os.environ.get("EXODIA_CAPTURES_DIR", "").strip()
    if raw:
        p = Path(raw).expanduser()
        return p if p.is_absolute() else (_EXODIA_DIR / p).resolve()
    return (_EXODIA_DIR / "captures").resolve()


def capture_template_path(name: str) -> Path:
    """Resolve ``captures/<name>.png`` (``.png`` suffix optional on ``name``)."""
    stem = name.strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    return captures_dir() / ("%s.png" % stem)


def resolve_world_template_file(
    template: str,
    template_path: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Resolve template stem and readable PNG path (``images/`` then ``captures/``)."""
    stem = template.strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    if template_path:
        p = Path(template_path).expanduser()
        if p.is_file():
            return stem, str(p.resolve())
    for candidate in (
        _EXODIA_DIR / "images" / template,
        _EXODIA_DIR / "images" / ("%s.png" % stem),
        capture_template_path(stem),
        captures_dir() / template,
    ):
        if candidate.is_file():
            return stem, str(candidate.resolve())
    return stem, None


def _template_file_for_name(
    name: str,
    template_paths: Optional[Dict[str, str]] = None,
) -> Optional[Path]:
    if template_paths and name in template_paths:
        p = Path(template_paths[name]).expanduser()
        if p.is_file():
            return p
    _, path = resolve_world_template_file("%s.png" % name)
    return Path(path) if path else None


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def world_template_names() -> List[str]:
    """Parse comma-separated ``EXODIA_WORLD_TEMPLATES`` (default ``osrs_infernalEel``)."""
    raw = os.environ.get("EXODIA_WORLD_TEMPLATES", "osrs_infernalEel").strip()
    return [t.strip() for t in raw.split(",") if t.strip()]


def world_cyan_first_enabled() -> bool:
    """True when ``EXODIA_WORLD_CYAN_FIRST`` is set (default on)."""
    return _env_bool("EXODIA_WORLD_CYAN_FIRST", True)


def world_match_threshold(explicit: Optional[float] = None) -> float:
    """
    Match threshold for alpha-masked world icons inside a cyan marker window.

    Defaults higher than ``EXODIA_SPOT_THRESHOLD`` — unconstrained playspace scans
    pick up lava glints (~0.45–0.50); cyan-gated windows are tighter.
    """
    if explicit is not None:
        return float(explicit)
    raw = os.environ.get("EXODIA_WORLD_THRESHOLD", "").strip()
    if raw:
        return _env_float("EXODIA_WORLD_THRESHOLD", 0.65)
    return 0.65


def _icon_search_roi_for_cyan_region(
    region: CyanMarkerRegion,
    *,
    template_w: int,
    template_h: int,
    frame_w: int,
    frame_h: int,
) -> Optional[List[int]]:
    """
    Search window for the spot icon around a cyan tile marker.

    RuneLite markers sit on the clickable tile while the eel sprite can overlap
    the marker from above or to the side when the camera is angled — use generous
    symmetric padding around the cyan rect, not a narrow strip above it only.
    """
    from bot_eyes import _clamp_roi

    rx, ry, rw, rh = (int(region.client_rect[i]) for i in range(4))
    pad_x = _env_int("EXODIA_WORLD_ICON_PAD_X", 30)
    pad_above = _env_int("EXODIA_WORLD_ICON_PAD_ABOVE", 70)
    pad_below = _env_int("EXODIA_WORLD_ICON_PAD_BELOW", 30)
    x = rx - pad_x
    y = ry - pad_above
    w = rw + pad_x * 2
    h = pad_above + rh + pad_below
    sx, sy, sw, sh = _clamp_roi(frame_w, frame_h, [x, y, w, h])
    if sw < template_w or sh < template_h:
        return None
    return [sx, sy, sw, sh]


@dataclass
class WorldObjectHit:
    """One template match for a world object in client and screen coordinates."""

    name: str
    client_xy: List[int]
    screen_xy: List[int]
    score: float


@dataclass
class WorldObjectLocateResult:
    """Aggregate result from ``locate_world_objects`` / ``locate_world_objects_from_eyes``."""

    hits: List[WorldObjectHit]
    search_roi: Optional[List[int]]
    inventory_filtered: int
    cyan_regions: List[CyanMarkerRegion] = field(default_factory=list)
    cyan_rejected: int = 0


def filter_matches_outside_rect(
    matches: Sequence[object],
    rect: Optional[Sequence[int]],
) -> Tuple[List[object], int]:
    """Drop matches whose center falls inside ``rect`` ``[x, y, w, h]``."""
    if rect is None or len(rect) != 4:
        return list(matches), 0
    rx, ry, rw, rh = (int(rect[i]) for i in range(4))
    kept: List[object] = []
    dropped = 0
    for match in matches:
        cx, cy = int(match.client_xy[0]), int(match.client_xy[1])
        if rx <= cx < rx + rw and ry <= cy < ry + rh:
            dropped += 1
        else:
            kept.append(match)
    return kept, dropped


def _hits_as_spot_candidates(hits: Sequence[WorldObjectHit]) -> List[SacredEelSpotCandidate]:
    return [
        SacredEelSpotCandidate(
            screen_xy=h.screen_xy[:],
            client_xy=h.client_xy[:],
            spot_score=h.score,
            eel_score=0.0,
            cyan_ratio=0.0,
            template=h.name,
            verified=True,
            click_xy=h.screen_xy[:],
        )
        for h in hits
    ]


def _spot_candidates_as_hits(candidates: Sequence[SacredEelSpotCandidate]) -> List[WorldObjectHit]:
    return [
        WorldObjectHit(
            name=c.template,
            client_xy=c.client_xy[:],
            screen_xy=c.screen_xy[:],
            score=c.spot_score,
        )
        for c in candidates
    ]


def _ensure_eyes(
    client_bgr: np.ndarray,
    eyes: Optional["Eyes.BotEyes"],
) -> "Eyes.BotEyes":
    if eyes is not None:
        return eyes
    import bot_eyes as EyesMod

    bot_e = EyesMod.BotEyes()
    h0, w0 = client_bgr.shape[:2]
    bot_e.setRect([0, 0, w0, h0], refresh=False)
    bot_e.curr_client = client_bgr
    bot_e.curr_client_unmasked = client_bgr
    return bot_e


def _template_size(tpl_path: Path) -> Tuple[int, int]:
    tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
    if tpl is None or tpl.size == 0:
        return 0, 0
    th, tw = tpl.shape[:2]
    return tw, th


def _locate_via_cyan_markers(
    client_bgr: np.ndarray,
    template_names: Sequence[str],
    *,
    search_roi: Optional[List[int]],
    inventory_rect: Optional[Sequence[int]],
    match_threshold: float,
    bot_e: "Eyes.BotEyes",
    template_paths: Optional[Dict[str, str]] = None,
) -> Tuple[List[WorldObjectHit], List[CyanMarkerRegion], int]:
    """Match each template inside the icon window above every cyan tile marker."""
    regions = locate_cyan_marker_regions(client_bgr, search_roi)
    h0, w0 = client_bgr.shape[:2]
    raw_hits: List[WorldObjectHit] = []
    rejected = 0

    for region in regions:
        if inventory_rect is not None and len(inventory_rect) == 4:
            cx, cy = region.client_center
            rx, ry, rw, rh = (int(inventory_rect[i]) for i in range(4))
            if rx <= cx < rx + rw and ry <= cy < ry + rh:
                rejected += 1
                continue

        matched_region = False
        for name in template_names:
            tpl_path = _template_file_for_name(name, template_paths)
            if tpl_path is None:
                continue
            tw, th = _template_size(tpl_path)
            if tw <= 0 or th <= 0:
                continue
            icon_roi = _icon_search_roi_for_cyan_region(
                region,
                template_w=tw,
                template_h=th,
                frame_w=w0,
                frame_h=h0,
            )
            if icon_roi is None:
                continue
            detailed = bot_e.locate_image_detailed(
                inv=False,
                filename="%s.png" % name,
                threshold=match_threshold,
                name="World object (cyan)",
                search_roi=icon_roi,
                template_path=str(tpl_path),
                frame_bgr=client_bgr,
                max_peaks=1,
            )
            if not detailed.matches:
                continue
            best = max(detailed.matches, key=lambda m: m.score)
            raw_hits.append(
                WorldObjectHit(
                    name=name,
                    client_xy=best.client_xy[:],
                    screen_xy=best.screen_xy[:],
                    score=float(best.score),
                )
            )
            matched_region = True
            break

        if not matched_region:
            rejected += 1

    return raw_hits, regions, rejected


def _locate_via_playspace_scan(
    client_bgr: np.ndarray,
    template_names: Sequence[str],
    *,
    search_roi: Optional[List[int]],
    inventory_rect: Optional[Sequence[int]],
    match_threshold: float,
    bot_e: "Eyes.BotEyes",
    template_paths: Optional[Dict[str, str]] = None,
) -> Tuple[List[WorldObjectHit], int]:
    raw_hits: List[WorldObjectHit] = []
    inventory_filtered = 0
    for name in template_names:
        tpl_path = _template_file_for_name(name, template_paths)
        if tpl_path is None:
            continue
        detailed = bot_e.locate_image_detailed(
            inv=False,
            filename=tpl_path.name,
            threshold=match_threshold,
            name="World object",
            search_roi=search_roi,
            template_path=str(tpl_path),
            frame_bgr=client_bgr,
        )
        filtered, dropped = filter_matches_outside_rect(detailed.matches, inventory_rect)
        inventory_filtered += dropped
        for match in filtered:
            raw_hits.append(
                WorldObjectHit(
                    name=name,
                    client_xy=match.client_xy[:],
                    screen_xy=match.screen_xy[:],
                    score=float(match.score),
                )
            )
    return raw_hits, inventory_filtered


def locate_world_objects(
    client_bgr: np.ndarray,
    template_names: Sequence[str],
    *,
    inventory_rect: Optional[Sequence[int]] = None,
    chat_rect: Optional[Sequence[int]] = None,
    threshold: Optional[float] = None,
    dedupe_radius_px: Optional[int] = None,
    eyes: Optional["Eyes.BotEyes"] = None,
    template_paths: Optional[Dict[str, str]] = None,
) -> WorldObjectLocateResult:
    """
    Find world objects on a client BGR frame.

    Cyan-first path: ``locate_cyan_marker_regions`` → template match in icon window per
    marker → dedupe. Falls back to full playspace scan when disabled or empty (see env).

    Returns hits plus diagnostic fields (search ROI, cyan regions, filter counts).
    """
    if client_bgr is None or client_bgr.size == 0:
        return WorldObjectLocateResult([], None, 0)

    match_threshold = world_match_threshold(threshold)
    dedupe_radius = (
        int(dedupe_radius_px)
        if dedupe_radius_px is not None
        else _env_int("EXODIA_SPOT_DEDUPE_RADIUS", 28)
    )

    bot_e = _ensure_eyes(client_bgr, eyes)
    h0, w0 = client_bgr.shape[:2]
    search_roi = playspace_search_roi(
        w0,
        h0,
        inventory_rect=inventory_rect,
        chat_rect=chat_rect,
    )

    cyan_regions: List[CyanMarkerRegion] = []
    cyan_rejected = 0
    inventory_filtered = 0
    raw_hits: List[WorldObjectHit] = []

    if world_cyan_first_enabled() and search_roi is not None:
        raw_hits, cyan_regions, cyan_rejected = _locate_via_cyan_markers(
            client_bgr,
            template_names,
            search_roi=search_roi,
            inventory_rect=inventory_rect,
            match_threshold=match_threshold,
            bot_e=bot_e,
            template_paths=template_paths,
        )

    if not raw_hits and (
        not world_cyan_first_enabled()
        or _env_bool("EXODIA_WORLD_CYAN_FALLBACK", False)
    ):
        raw_hits, inventory_filtered = _locate_via_playspace_scan(
            client_bgr,
            template_names,
            search_roi=search_roi,
            inventory_rect=inventory_rect,
            match_threshold=match_threshold,
            bot_e=bot_e,
            template_paths=template_paths,
        )

    deduped = _spot_candidates_as_hits(
        dedupe_spot_candidates(_hits_as_spot_candidates(raw_hits), dedupe_radius)
    )
    return WorldObjectLocateResult(
        hits=deduped,
        search_roi=search_roi,
        inventory_filtered=inventory_filtered,
        cyan_regions=cyan_regions,
        cyan_rejected=cyan_rejected,
    )


def locate_world_objects_from_eyes(
    eyes: "Eyes.BotEyes",
    template_names: Sequence[str],
    **kwargs: object,
) -> WorldObjectLocateResult:
    """
    ``locate_world_objects`` using ``BotEyes`` capture and panel rects.

    Uses unmasked client BGR when available so cyan markers are visible.
    """
    client_bgr = _client_bgr_for_spot_ops(eyes)
    if client_bgr is None or client_bgr.size == 0:
        return WorldObjectLocateResult([], None, 0)
    inventory_rect = kwargs.pop("inventory_rect", None) or eyes.inventory_rect
    chat_rect = kwargs.pop("chat_rect", None) or eyes.chat_rect
    return locate_world_objects(
        client_bgr,
        template_names,
        inventory_rect=inventory_rect,
        chat_rect=chat_rect,
        eyes=eyes,
        **kwargs,
    )


def draw_world_detect_overlay(
    client_bgr: np.ndarray,
    hits: Sequence[WorldObjectHit],
    *,
    inventory_rect: Optional[Sequence[int]] = None,
    search_roi: Optional[Sequence[int]] = None,
    cyan_regions: Optional[Sequence[CyanMarkerRegion]] = None,
) -> np.ndarray:
    """Annotate playspace ROI, cyan markers, inventory outline, and hit markers."""
    vis = client_bgr.copy()

    if search_roi is not None and len(search_roi) == 4:
        sx, sy, sw, sh = (int(search_roi[i]) for i in range(4))
        x2, y2 = sx + sw, sy + sh
        tint = np.array((255, 255, 0), dtype=np.float32)
        alpha = 0.15
        patch = vis[sy:y2, sx:x2].astype(np.float32)
        vis[sy:y2, sx:x2] = np.clip(patch * (1.0 - alpha) + tint * alpha, 0, 255).astype(np.uint8)
        cv2.rectangle(vis, (sx, sy), (x2, y2), (255, 255, 0), 2)

    if cyan_regions:
        for region in cyan_regions:
            rx, ry, rw, rh = (int(v) for v in region.client_rect[:4])
            cv2.rectangle(vis, (rx, ry), (rx + rw, ry + rh), (255, 128, 0), 2)

    if inventory_rect is not None and len(inventory_rect) == 4:
        vis = draw_inventory_outline_overlay(vis, inventory_rect, draw_grid=False)

    for hit in hits:
        cx, cy = int(hit.client_xy[0]), int(hit.client_xy[1])
        tpl_path = capture_template_path(hit.name)
        half_w, half_h = 14, 14
        if tpl_path.is_file():
            tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
            if tpl is not None and tpl.size > 0:
                th, tw = tpl.shape[:2]
                half_w, half_h = tw // 2, th // 2
                cv2.rectangle(
                    vis,
                    (cx - half_w, cy - half_h),
                    (cx + half_w, cy + half_h),
                    (0, 255, 255),
                    2,
                )
        cv2.circle(vis, (cx, cy), 4, (0, 255, 255), -1)
        label = "%s score=%.2f" % (hit.name, hit.score)
        cv2.putText(
            vis,
            label,
            (cx + half_w + 4, cy + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

    return vis
