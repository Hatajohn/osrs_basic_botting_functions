"""
Sacred eel fishing-spot verification (template + eel icon + cyan outline).

Coarse candidates come from playspace template matching; each hit is confirmed by:

1. **Eel icon** — small template over the spot (grey eel sprite above the tile).
2. **Cyan outline** — RuneLite object-marker diamond on the clickable tile below the icon.

Reusable pieces work on any ``client_bgr`` crop and anchor point, not only the sacred eel FSM.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING, Union

import cv2
import numpy as np

from bot_eyes import _clamp_roi, _load_template_gray, _match_template_peaks
from bot_search import playspace_search_roi

if TYPE_CHECKING:
    import bot_eyes as Eyes

Point = List[int]

__all__ = [
    "SacredEelSpotCandidate",
    "SpotVerifyConfig",
    "cyan_marker_ratio",
    "default_spot_verify_config",
    "dedupe_spot_candidates",
    "eel_icon_score_at",
    "filter_sacred_eel_spots",
    "locate_sacred_eel_spots",
    "spot_template_trust_threshold",
    "template_trust_fallback",
    "verify_spot_at_client_xy",
]


@dataclass(frozen=True)
class SpotVerifyConfig:
    """Thresholds and geometry for post-template verification."""

    eel_icon_file: str = "osrs_sacredEelSpot_icon.png"
    eel_threshold: float = 0.42
    eel_search_half_w: int = 42
    eel_search_above_h: int = 40
    cyan_hsv_lower: Tuple[int, int, int] = (85, 80, 120)
    cyan_hsv_upper: Tuple[int, int, int] = (105, 255, 255)
    cyan_min_ratio: float = 0.018
    cyan_search_half_w: int = 36
    cyan_search_below_h: int = 44
    require_eel_icon: bool = True
    require_cyan_outline: bool = True
    enabled: bool = True
    dedupe_radius_px: int = 28


@dataclass
class SacredEelSpotCandidate:
    """One fishing-spot hit with verification scores."""

    screen_xy: List[int]
    client_xy: List[int]
    spot_score: float
    eel_score: float
    cyan_ratio: float
    template: str
    verified: bool
    click_xy: List[int]  # screen coords — cyan centroid when found, else template center

    def to_dict(self) -> Dict[str, Any]:
        return {
            "screen_xy": self.screen_xy,
            "client_xy": self.client_xy,
            "spot_score": self.spot_score,
            "eel_score": self.eel_score,
            "cyan_ratio": self.cyan_ratio,
            "template": self.template,
            "verified": self.verified,
            "click_xy": self.click_xy,
        }


def _env_bool(key: str, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def default_spot_verify_config() -> SpotVerifyConfig:
    icon_file = os.environ.get("EXODIA_SPOT_EEL_ICON", "osrs_sacredEelSpot_icon.png")
    cfg = SpotVerifyConfig(
        eel_icon_file=icon_file,
        eel_threshold=float(os.environ.get("EXODIA_SPOT_EEL_THRESHOLD", "0.38")),
        cyan_min_ratio=float(os.environ.get("EXODIA_SPOT_CYAN_MIN_RATIO", "0.012")),
        require_eel_icon=_env_bool("EXODIA_SPOT_REQUIRE_EEL", True),
        require_cyan_outline=_env_bool("EXODIA_SPOT_REQUIRE_CYAN", True),
        enabled=_env_bool("EXODIA_SPOT_VERIFY", True),
        dedupe_radius_px=int(os.environ.get("EXODIA_SPOT_DEDUPE_RADIUS", "28")),
    )
    if cfg.require_eel_icon and not (Path(os.getcwd()) / "images" / icon_file).is_file():
        print(
            "WARN: spot eel icon missing (images/%s) — eel verification disabled"
            % icon_file
        )
        cfg = replace(cfg, require_eel_icon=False)
    return cfg


def spot_template_trust_threshold(match_threshold: float) -> float:
    """
    Strong template scores can be clicked when eel/cyan checks fail (RuneLite variance).

    Override with ``EXODIA_SPOT_TRUST_TEMPLATE`` (0 = disable fallback).
    """
    raw = (os.environ.get("EXODIA_SPOT_TRUST_TEMPLATE") or "").strip()
    if raw:
        return max(0.0, float(raw))
    return max(float(match_threshold) + 0.03, 0.48)


def _client_bgr_for_spot_ops(eyes: "Eyes.BotEyes") -> Optional[np.ndarray]:
    """Prefer unmasked client capture so cyan markers are not blacked out."""
    unmasked = getattr(eyes, "curr_client_unmasked", None)
    if unmasked is not None and getattr(unmasked, "size", 0) > 0:
        return unmasked
    return eyes.curr_client


def template_trust_fallback(
    raw_hits: Sequence[SacredEelSpotCandidate],
    verified: Sequence[SacredEelSpotCandidate],
    *,
    trust_threshold: float,
    dedupe_radius_px: int,
) -> List[SacredEelSpotCandidate]:
    """
    When strict verify rejects every template peak, keep the best strong template match.
    """
    if verified or trust_threshold <= 0.0:
        return list(verified)
    strong = [h for h in raw_hits if h.spot_score >= trust_threshold]
    if not strong:
        return list(verified)
    best = max(strong, key=lambda c: c.spot_score)
    trusted = replace(best, verified=True)
    print(
        "Spot verify: template-trusted fallback (score=%.2f eel=%.2f cyan=%.3f tpl=%s)"
        % (trusted.spot_score, trusted.eel_score, trusted.cyan_ratio, trusted.template)
    )
    return dedupe_spot_candidates([trusted], dedupe_radius_px)


def _crop_client(bgr: np.ndarray, rect: Sequence[int]) -> Optional[np.ndarray]:
    if bgr is None or bgr.size == 0 or len(rect) != 4:
        return None
    h0, w0 = bgr.shape[:2]
    sx, sy, sw, sh = _clamp_roi(w0, h0, rect)
    if sw <= 0 or sh <= 0:
        return None
    return bgr[sy : sy + sh, sx : sx + sw]


def cyan_marker_ratio(
    bgr_patch: np.ndarray,
    *,
    hsv_lower: Tuple[int, int, int] = (85, 80, 120),
    hsv_upper: Tuple[int, int, int] = (105, 255, 255),
) -> Tuple[float, Optional[List[int]]]:
    """
    Fraction of pixels in the cyan HSV band and optional BGR centroid ``[x, y]`` in patch coords.
    """
    if bgr_patch is None or bgr_patch.size == 0:
        return 0.0, None
    hsv = cv2.cvtColor(bgr_patch, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.array(hsv_lower, dtype=np.uint8),
        np.array(hsv_upper, dtype=np.uint8),
    )
    total = mask.size
    if total == 0:
        return 0.0, None
    count = int(cv2.countNonZero(mask))
    ratio = count / float(total)
    if count < 4:
        return ratio, None
    m = cv2.moments(mask)
    if m["m00"] <= 0:
        return ratio, None
    cx = int(m["m10"] / m["m00"])
    cy = int(m["m01"] / m["m00"])
    return ratio, [cx, cy]


def eel_icon_score_at(
    client_bgr: np.ndarray,
    client_xy: Sequence[int],
    icon_path: str,
    *,
    half_w: int = 42,
    above_h: int = 40,
    threshold: float = 0.42,
) -> float:
    """
    Best ``TM_CCOEFF_NORMED`` score for the eel icon in a window **above** ``client_xy``.
    """
    if client_bgr is None or client_bgr.size == 0:
        return 0.0
    template = _load_template_gray(os.path.join(os.getcwd(), "images", icon_path))
    if template is None:
        return 0.0
    th, tw = template.shape[:2]
    cx, cy = int(client_xy[0]), int(client_xy[1])
    h0, w0 = client_bgr.shape[:2]
    # Eel sprite sits above the clickable tile / template anchor.
    roi = [
        cx - half_w,
        cy - above_h - th,
        half_w * 2 + tw,
        above_h + th,
    ]
    patch = _crop_client(client_bgr, roi)
    if patch is None:
        return 0.0
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    if gray.shape[0] < th or gray.shape[1] < tw:
        return 0.0
    res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    peaks = _match_template_peaks(res, tw, th, threshold, max_peaks=1)
    if peaks:
        return peaks[0][2]
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return float(max_val) if max_val >= threshold else 0.0


def verify_spot_at_client_xy(
    client_bgr: np.ndarray,
    client_xy: Sequence[int],
    cfg: SpotVerifyConfig,
    *,
    client_rect: Optional[Sequence[int]] = None,
) -> Tuple[bool, float, float, List[int]]:
    """
    Verify one anchor in client-local coordinates.

    Returns ``(verified, eel_score, cyan_ratio, click_xy_client)``.
    ``click_xy_client`` prefers the cyan-marker centroid on the tile (below the icon).
    """
    cx, cy = int(client_xy[0]), int(client_xy[1])
    click = [cx, cy]
    eel_score = 0.0
    cyan_ratio = 0.0

    if cfg.require_eel_icon or cfg.enabled:
        eel_score = eel_icon_score_at(
            client_bgr,
            (cx, cy),
            cfg.eel_icon_file,
            half_w=cfg.eel_search_half_w,
            above_h=cfg.eel_search_above_h,
            threshold=cfg.eel_threshold,
        )

    cyan_centroid: Optional[List[int]] = None
    if cfg.require_cyan_outline or cfg.enabled:
        h0, w0 = client_bgr.shape[:2]
        cyan_roi = [
            cx - cfg.cyan_search_half_w,
            cy,
            cfg.cyan_search_half_w * 2,
            cfg.cyan_search_below_h,
        ]
        patch = _crop_client(client_bgr, cyan_roi)
        if patch is not None:
            cyan_ratio, cyan_centroid = cyan_marker_ratio(
                patch,
                hsv_lower=cfg.cyan_hsv_lower,
                hsv_upper=cfg.cyan_hsv_upper,
            )
            if cyan_centroid is not None:
                click = [
                    cyan_roi[0] + cyan_centroid[0],
                    cyan_roi[1] + cyan_centroid[1],
                ]

    if not cfg.enabled:
        return True, eel_score, cyan_ratio, click

    eel_ok = (not cfg.require_eel_icon) or (eel_score >= cfg.eel_threshold)
    cyan_ok = (not cfg.require_cyan_outline) or (cyan_ratio >= cfg.cyan_min_ratio)
    return eel_ok and cyan_ok, eel_score, cyan_ratio, click


def dedupe_spot_candidates(
    candidates: Sequence[SacredEelSpotCandidate],
    radius_px: int,
) -> List[SacredEelSpotCandidate]:
    """Keep highest ``spot_score`` hit within ``radius_px`` of an existing pick."""
    radius_px = max(1, int(radius_px))
    ranked = sorted(candidates, key=lambda c: -c.spot_score)
    kept: List[SacredEelSpotCandidate] = []
    for cand in ranked:
        if all(
            math.hypot(cand.screen_xy[0] - k.screen_xy[0], cand.screen_xy[1] - k.screen_xy[1])
            >= radius_px
            for k in kept
        ):
            kept.append(cand)
    return kept


def filter_sacred_eel_spots(
    raw_hits: Sequence[SacredEelSpotCandidate],
    cfg: Optional[SpotVerifyConfig] = None,
    *,
    on_reject: Optional[Callable[[SacredEelSpotCandidate], None]] = None,
    return_rejects: bool = False,
) -> Union[
    List[SacredEelSpotCandidate],
    Tuple[List[SacredEelSpotCandidate], List[SacredEelSpotCandidate]],
]:
    """
    Apply verification flags and drop failures; dedupe survivors.

    When ``on_reject`` is set, it is invoked once per candidate that fails
    verification while ``cfg.enabled`` is true (before dedupe).

    Pass ``return_rejects=True`` to receive ``(verified, rejected)`` instead of
    only the verified list. ``rejected`` holds verification failures only, not
    dedupe drops.
    """
    cfg = cfg or default_spot_verify_config()
    verified: List[SacredEelSpotCandidate] = []
    rejected: List[SacredEelSpotCandidate] = []
    for hit in raw_hits:
        if hit.verified or not cfg.enabled:
            verified.append(hit)
        else:
            rejected.append(hit)
            if on_reject is not None:
                on_reject(hit)
    deduped = dedupe_spot_candidates(verified, cfg.dedupe_radius_px)
    if return_rejects:
        return deduped, rejected
    return deduped


def locate_sacred_eel_spots(
    eyes: "Eyes.BotEyes",
    spot_templates: Sequence[str],
    *,
    threshold: float,
    verify_cfg: Optional[SpotVerifyConfig] = None,
    on_reject: Optional[Callable[[SacredEelSpotCandidate], None]] = None,
    return_rejects: bool = False,
) -> Union[
    List[SacredEelSpotCandidate],
    Tuple[List[SacredEelSpotCandidate], List[SacredEelSpotCandidate]],
]:
    """
    Template-match spot images in the playspace, then verify eel icon + cyan outline.

    Returns structured candidates (use ``.click_xy`` for clicks — tile outline when found).

    Optional ``on_reject`` / ``return_rejects`` behave as in ``filter_sacred_eel_spots``.
    """
    cfg = verify_cfg or default_spot_verify_config()
    client_bgr = _client_bgr_for_spot_ops(eyes)
    if client_bgr is None or client_bgr.size == 0:
        return []

    h0, w0 = client_bgr.shape[:2]
    search_roi = playspace_search_roi(w0, h0)
    client_rect = eyes.client_rect or [0, 0, w0, h0]
    ox = int(client_rect[0])
    oy = int(client_rect[1])

    raw: List[SacredEelSpotCandidate] = []
    for template in spot_templates:
        detailed = eyes.locate_image_detailed(
            filename=template,
            inv=False,
            threshold=threshold,
            name="Sacred eel spot",
            search_roi=search_roi,
        )
        for match in detailed.matches:
            ok, eel_s, cyan_r, click_client = verify_spot_at_client_xy(
                client_bgr,
                match.client_xy,
                cfg,
            )
            click_screen = [int(click_client[0]) + ox, int(click_client[1]) + oy]
            raw.append(
                SacredEelSpotCandidate(
                    screen_xy=match.screen_xy[:],
                    client_xy=match.client_xy[:],
                    spot_score=float(match.score),
                    eel_score=eel_s,
                    cyan_ratio=cyan_r,
                    template=template,
                    verified=ok,
                    click_xy=click_screen,
                )
            )

    filtered = filter_sacred_eel_spots(
        raw, cfg, on_reject=on_reject, return_rejects=return_rejects
    )
    if return_rejects:
        verified, rejected_hits = filtered
    else:
        verified = filtered
        rejected_hits = [h for h in raw if cfg.enabled and not h.verified]
    trust_thr = spot_template_trust_threshold(threshold)
    verified = template_trust_fallback(
        raw,
        verified,
        trust_threshold=trust_thr,
        dedupe_radius_px=cfg.dedupe_radius_px,
    )
    if cfg.enabled and raw:
        reject_count = len(rejected_hits)
        if reject_count or _env_bool("EXODIA_SPOT_VERIFY_DEBUG", False):
            print(
                "Spot verify: %d/%d passed (eel>=%.2f cyan>=%.3f trust>=%.2f)"
                % (
                    len(verified),
                    len(raw),
                    cfg.eel_threshold,
                    cfg.cyan_min_ratio,
                    trust_thr,
                )
            )
    if return_rejects:
        return verified, rejected_hits
    return verified


def sacred_eel_spot_click_points(candidates: Sequence[SacredEelSpotCandidate]) -> List[Point]:
    """Screen click coordinates from verified candidates."""
    return [c.click_xy[:] for c in candidates]
