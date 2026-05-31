"""
Consolidated OpenCV template locate/score helpers for perception modalities.

World playspace match, inventory watch templates, and dirty slot identification
share ``TemplateFinder`` entry points.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from bot_capture import FrameSnapshot

Rect = List[int]
WorldHitDict = Dict[str, Any]


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _world_cyan_first_for_vision() -> bool:
    """Shape match by default; cyan path only when ``EXODIA_WORLD_CYAN_FIRST=1``."""
    return _env_bool("EXODIA_WORLD_CYAN_FIRST", False)


def _match_to_hit_dict(match: Any, template: str) -> WorldHitDict:
    return {
        "template": template,
        "client_xy": [int(match.client_xy[0]), int(match.client_xy[1])],
        "screen_xy": [int(match.screen_xy[0]), int(match.screen_xy[1])],
        "score": round(float(match.score), 4),
    }


def _hit_dict_from_world_object(hit: Any) -> WorldHitDict:
    return {
        "template": hit.name,
        "client_xy": hit.client_xy[:],
        "screen_xy": hit.screen_xy[:],
        "score": round(float(hit.score), 4),
    }


def _ensure_bot_eyes(
    client_bgr: np.ndarray,
    client_rect: Rect,
    inventory_rect: Optional[Rect],
) -> Any:
    import bot_eyes as EyesMod

    bot_e = EyesMod.BotEyes()
    h0, w0 = client_bgr.shape[:2]
    bot_e.setRect([0, 0, w0, h0], refresh=False)
    bot_e.client_rect = [int(v) for v in client_rect]
    bot_e.curr_client = client_bgr
    bot_e.curr_client_unmasked = client_bgr
    if inventory_rect is not None and len(inventory_rect) == 4:
        bot_e.inventory_rect = [int(v) for v in inventory_rect]
    return bot_e


def _locate_shape_matches(
    client_bgr: np.ndarray,
    client_rect: Rect,
    inventory_rect: Optional[Rect],
    template_names: Sequence[str],
    search_roi: Optional[Rect],
) -> Tuple[List[WorldHitDict], int]:
    """Playspace shape match aligned with ``bot_chain._locate_world_shape_matches``."""
    from bot_shape_match import shape_match_threshold, shape_preprocess_playspace
    from bot_world_objects import filter_matches_outside_rect, resolve_world_template_file

    bot_e = _ensure_bot_eyes(client_bgr, client_rect, inventory_rect)
    hits: List[WorldHitDict] = []
    inventory_filtered = 0
    use_shape = shape_preprocess_playspace()
    threshold = shape_match_threshold()

    for name in template_names:
        stem, tpl_path = resolve_world_template_file(name)
        if not tpl_path:
            continue
        detailed = bot_e.locate_image_detailed(
            inv=False,
            filename=stem,
            threshold=threshold,
            name="World object (shape)",
            search_roi=search_roi,
            template_path=tpl_path,
            frame_bgr=client_bgr,
            shape_preprocess=use_shape,
            shape_playspace=True,
        )
        matches = list(detailed.matches) if detailed.found else []
        filtered, dropped = filter_matches_outside_rect(matches, inventory_rect)
        inventory_filtered += dropped
        for match in filtered:
            hits.append(_match_to_hit_dict(match, stem))

    return hits, inventory_filtered


def _locate_cyan_matches(
    client_bgr: np.ndarray,
    inventory_rect: Optional[Rect],
    template_names: Sequence[str],
) -> Tuple[List[WorldHitDict], Optional[Rect], int, int]:
    from bot_world_objects import locate_world_objects

    result = locate_world_objects(
        client_bgr,
        template_names,
        inventory_rect=inventory_rect,
    )
    hits = [_hit_dict_from_world_object(h) for h in result.hits]
    cyan_count = len(result.cyan_regions)
    inv_filtered = result.inventory_filtered + result.cyan_rejected
    return hits, result.search_roi, cyan_count, inv_filtered


class TemplateFinder:
    """Shared template locate/score entry points for perception modalities."""

    @staticmethod
    def locate_world(
        snap: FrameSnapshot,
        template_names: Sequence[str],
        inventory_rect: Optional[Rect],
        client_rect: Rect,
    ) -> Tuple[List[WorldHitDict], Optional[Rect], int, int]:
        """Locate world templates via shape match or cyan-first path.

        Returns ``(hits, search_roi, cyan_regions, inventory_filtered)``.
        """
        from bot_search import playspace_search_roi

        client_bgr = snap.bgr
        if client_bgr is None or not getattr(client_bgr, "size", 0):
            return [], None, 0, 0

        h0, w0 = client_bgr.shape[:2]
        search_roi = playspace_search_roi(
            w0,
            h0,
            inventory_rect=inventory_rect,
        )

        if _world_cyan_first_for_vision():
            return _locate_cyan_matches(client_bgr, inventory_rect, template_names)

        hits, inv_filtered = _locate_shape_matches(
            client_bgr,
            client_rect,
            inventory_rect,
            template_names,
            search_roi,
        )
        return hits, search_roi, 0, inv_filtered

    @staticmethod
    def locate_inventory_watch(
        snap: FrameSnapshot,
        inv_rect: Sequence[int],
        template_names: Sequence[str],
        slot_items: Optional[Sequence[Sequence[Optional[str]]]] = None,
    ) -> List[Dict[str, Any]]:
        """Locate watched inventory templates via per-slot template match."""
        from bot_template_watchlist import locate_inventory_watch_templates

        client_bgr = snap.bgr
        if client_bgr is None or not getattr(client_bgr, "size", 0):
            return []
        return locate_inventory_watch_templates(
            client_bgr,
            inv_rect,
            snap.client_rect,
            template_names,
            slot_items=slot_items,
        )

    @staticmethod
    def identify_slots_batch(
        snap: FrameSnapshot,
        inv_rect: Sequence[int],
        occupancy: Sequence[Sequence[bool]],
        slot_items: Optional[List[List[Optional[str]]]],
        dirty_coords: Sequence[Tuple[int, int]],
        *,
        frame_buckets: Optional[bool] = None,
    ) -> Tuple[List[List[Optional[str]]], Dict[Tuple[int, int], float]]:
        """Re-identify only ``dirty_coords`` slots; reuse cached labels elsewhere."""
        from bot_inventory_items import identify_inventory_slots_dirty

        client_bgr = snap.bgr
        if client_bgr is None:
            client_bgr = np.array([])
        return identify_inventory_slots_dirty(
            client_bgr,
            inv_rect,
            occupancy,
            slot_items,
            dirty_coords,
            frame_buckets=frame_buckets,
        )


__all__ = [
    "TemplateFinder",
    "WorldHitDict",
]
