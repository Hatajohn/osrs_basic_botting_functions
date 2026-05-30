"""
Client-side perception diff — consecutive ``PerceptionTick`` → change events.

Each event carries a ``data`` dict with the relevant JSON-shaped payload for
logging (JSONL) and FSM predicates. Typed fields mirror ``data`` for pattern
matching without dict access.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from bot_perception_types import (
    INV_SLOT_COUNT,
    ActionSnapshot,
    InventorySnapshot,
    InventorySlot,
    PerceptionTick,
    WorldHit,
    WorldSnapshot,
    WorldTrack,
    action_snapshot_to_dict,
    inventory_slot_to_dict,
    inventory_snapshot_to_dict,
    world_hit_to_dict,
    world_snapshot_to_dict,
    world_track_to_dict,
)

_UNKNOWN_LABEL = "?"


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


DEFAULT_WORLD_MOVE_THRESHOLD_PX = _env_float("EXODIA_WORLD_TRACK_MOVE_THRESHOLD_PX", 8.0)
DEFAULT_STALE_THRESHOLD_MS = _env_float("EXODIA_PERCEPTION_STALE_MS", 2000.0)


# --- Inventory events ---


@dataclass(frozen=True)
class InventorySnapshotInitial:
    kind: str = field(default="inventory_snapshot_initial", init=False)
    inventory: InventorySnapshot
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventorySlotOccupied:
    kind: str = field(default="inventory_slot_occupied", init=False)
    row: int
    col: int
    label: Optional[str]
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventorySlotCleared:
    kind: str = field(default="inventory_slot_cleared", init=False)
    row: int
    col: int
    old_label: Optional[str]
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryLabelChanged:
    kind: str = field(default="inventory_label_changed", init=False)
    row: int
    col: int
    old_label: Optional[str]
    new_label: Optional[str]
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryLabelResolved:
    kind: str = field(default="inventory_label_resolved", init=False)
    row: int
    col: int
    label: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryCountChanged:
    kind: str = field(default="inventory_count_changed", init=False)
    label: str
    old_count: int
    new_count: int
    delta: int
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryFull:
    kind: str = field(default="inventory_full", init=False)
    occupied: int
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryNoLongerFull:
    kind: str = field(default="inventory_no_longer_full", init=False)
    occupied: int
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InventoryUnknownIncreased:
    kind: str = field(default="inventory_unknown_increased", init=False)
    old_unknown: int
    new_unknown: int
    delta: int
    data: Dict[str, Any] = field(default_factory=dict)


# --- World events ---


@dataclass(frozen=True)
class WorldSnapshotInitial:
    kind: str = field(default="world_snapshot_initial", init=False)
    world: WorldSnapshot
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldTrackAppeared:
    kind: str = field(default="world_track_appeared", init=False)
    track: WorldTrack
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldTrackMoved:
    kind: str = field(default="world_track_moved", init=False)
    track_id: int
    template: str
    client_xy: Tuple[int, int]
    screen_xy: Tuple[int, int]
    velocity_xy: Tuple[float, float]
    prev_client_xy: Tuple[int, int]
    prev_screen_xy: Tuple[int, int]
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldTrackLost:
    kind: str = field(default="world_track_lost", init=False)
    track_id: int
    template: str
    last_client_xy: Tuple[int, int]
    last_screen_xy: Tuple[int, int]
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldTrackStabilized:
    kind: str = field(default="world_track_stabilized", init=False)
    track: WorldTrack
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldHitAppeared:
    kind: str = field(default="world_hit_appeared", init=False)
    hit: WorldHit
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldHitLost:
    kind: str = field(default="world_hit_lost", init=False)
    hit: WorldHit
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorldTemplateScanChanged:
    kind: str = field(default="world_template_scan_changed", init=False)
    old_templates: Tuple[str, ...]
    new_templates: Tuple[str, ...]
    data: Dict[str, Any] = field(default_factory=dict)


# --- Action strip events ---


@dataclass(frozen=True)
class ActionSnapshotInitial:
    kind: str = field(default="action_snapshot_initial", init=False)
    action: ActionSnapshot
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionStateChanged:
    kind: str = field(default="action_state_changed", init=False)
    before_code: int
    after_code: int
    action: ActionSnapshot
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionStripAppeared:
    kind: str = field(default="action_strip_appeared", init=False)
    action: ActionSnapshot
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionStripHidden:
    kind: str = field(default="action_strip_hidden", init=False)
    action: ActionSnapshot
    data: Dict[str, Any] = field(default_factory=dict)


# --- Meta events ---


@dataclass(frozen=True)
class CaptureSeqAdvanced:
    kind: str = field(default="capture_seq_advanced", init=False)
    old_seq: int
    new_seq: int
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PerceptionStale:
    kind: str = field(default="perception_stale", init=False)
    frame_age_ms: float
    threshold_ms: float
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PerceptionFresh:
    kind: str = field(default="perception_fresh", init=False)
    frame_age_ms: float
    threshold_ms: float
    data: Dict[str, Any] = field(default_factory=dict)


PerceptionEvent = Union[
    ActionSnapshotInitial,
    ActionStateChanged,
    ActionStripAppeared,
    ActionStripHidden,
    InventorySnapshotInitial,
    InventorySlotOccupied,
    InventorySlotCleared,
    InventoryLabelChanged,
    InventoryLabelResolved,
    InventoryCountChanged,
    InventoryFull,
    InventoryNoLongerFull,
    InventoryUnknownIncreased,
    WorldSnapshotInitial,
    WorldTrackAppeared,
    WorldTrackMoved,
    WorldTrackLost,
    WorldTrackStabilized,
    WorldHitAppeared,
    WorldHitLost,
    WorldTemplateScanChanged,
    CaptureSeqAdvanced,
    PerceptionStale,
    PerceptionFresh,
]


def perception_event_to_dict(event: PerceptionEvent) -> Dict[str, Any]:
    """Serialize an event for JSONL logging (``kind`` + ``data`` payload)."""
    return {"kind": event.kind, "data": dict(event.data)}


def _client_distance(a: Tuple[int, int], b: Tuple[int, int]) -> float:
    return math.hypot(float(a[0] - b[0]), float(a[1] - b[1]))


def _labels_equal(a: Optional[str], b: Optional[str]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a == b


def _slot_event_data(slot: InventorySlot, **extra: Any) -> Dict[str, Any]:
    payload = {"slot": inventory_slot_to_dict(slot)}
    payload.update(extra)
    return payload


def diff_inventory(
    prev: Optional[InventorySnapshot],
    curr: InventorySnapshot,
) -> List[PerceptionEvent]:
    """Diff consecutive inventory snapshots and emit slot / aggregate events."""
    events: List[PerceptionEvent] = []
    curr_data = inventory_snapshot_to_dict(curr)

    if prev is None:
        events.append(
            InventorySnapshotInitial(
                inventory=curr,
                data={"inventory": curr_data},
            )
        )
        for slot in curr.slots:
            if slot.occupied:
                events.append(
                    InventorySlotOccupied(
                        row=slot.row,
                        col=slot.col,
                        label=slot.label,
                        data=_slot_event_data(slot, label=slot.label),
                    )
                )
        if curr.is_full():
            events.append(
                InventoryFull(
                    occupied=curr.occupied,
                    data={"occupied": curr.occupied, "inventory": curr_data},
                )
            )
        return events

    prev_slots = {(s.row, s.col): s for s in prev.slots}
    curr_slots = {(s.row, s.col): s for s in curr.slots}

    for key, slot in curr_slots.items():
        old = prev_slots.get(key)
        if old is None:
            continue
        if not old.occupied and slot.occupied:
            events.append(
                InventorySlotOccupied(
                    row=slot.row,
                    col=slot.col,
                    label=slot.label,
                    data=_slot_event_data(slot, label=slot.label),
                )
            )
        elif old.occupied and not slot.occupied:
            events.append(
                InventorySlotCleared(
                    row=slot.row,
                    col=slot.col,
                    old_label=old.label,
                    data=_slot_event_data(slot, old_label=old.label),
                )
            )
        elif old.occupied and slot.occupied and not _labels_equal(old.label, slot.label):
            events.append(
                InventoryLabelChanged(
                    row=slot.row,
                    col=slot.col,
                    old_label=old.label,
                    new_label=slot.label,
                    data=_slot_event_data(
                        slot,
                        old_label=old.label,
                        new_label=slot.label,
                    ),
                )
            )
            if old.label == _UNKNOWN_LABEL and slot.label not in (None, _UNKNOWN_LABEL):
                events.append(
                    InventoryLabelResolved(
                        row=slot.row,
                        col=slot.col,
                        label=slot.label,
                        data=_slot_event_data(slot, label=slot.label),
                    )
                )

    prev_counts = prev.label_counts()
    curr_counts = curr.label_counts()
    all_labels = set(prev_counts) | set(curr_counts)
    for label in sorted(all_labels):
        old_count = prev_counts.get(label, 0)
        new_count = curr_counts.get(label, 0)
        if old_count != new_count:
            events.append(
                InventoryCountChanged(
                    label=label,
                    old_count=old_count,
                    new_count=new_count,
                    delta=new_count - old_count,
                    data={
                        "label": label,
                        "old_count": old_count,
                        "new_count": new_count,
                        "delta": new_count - old_count,
                    },
                )
            )

    if not prev.is_full() and curr.is_full():
        events.append(
            InventoryFull(
                occupied=curr.occupied,
                data={
                    "occupied": curr.occupied,
                    "capacity": INV_SLOT_COUNT,
                    "inventory": curr_data,
                },
            )
        )
    elif prev.is_full() and not curr.is_full():
        events.append(
            InventoryNoLongerFull(
                occupied=curr.occupied,
                data={
                    "occupied": curr.occupied,
                    "capacity": INV_SLOT_COUNT,
                    "inventory": curr_data,
                },
            )
        )

    if curr.unknown > prev.unknown:
        events.append(
            InventoryUnknownIncreased(
                old_unknown=prev.unknown,
                new_unknown=curr.unknown,
                delta=curr.unknown - prev.unknown,
                data={
                    "old_unknown": prev.unknown,
                    "new_unknown": curr.unknown,
                    "delta": curr.unknown - prev.unknown,
                    "inventory": curr_data,
                },
            )
        )

    return events


def _tracks_by_id(world: WorldSnapshot) -> dict[int, WorldTrack]:
    return {t.track_id: t for t in world.tracks}


def _match_hits(
    prev_hits: Sequence[WorldHit],
    curr_hits: Sequence[WorldHit],
    *,
    move_threshold_px: float,
) -> Tuple[List[Tuple[WorldHit, WorldHit]], List[WorldHit], List[WorldHit]]:
    """Greedy match hits by template + client distance."""
    unmatched_prev = list(prev_hits)
    unmatched_curr = list(curr_hits)
    matched: List[Tuple[WorldHit, WorldHit]] = []

    for curr_hit in list(unmatched_curr):
        best_idx = -1
        best_dist = move_threshold_px
        for idx, prev_hit in enumerate(unmatched_prev):
            if prev_hit.template != curr_hit.template:
                continue
            dist = _client_distance(prev_hit.client_xy, curr_hit.client_xy)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx >= 0:
            matched.append((unmatched_prev.pop(best_idx), curr_hit))
            unmatched_curr.remove(curr_hit)

    return matched, unmatched_prev, unmatched_curr


def diff_world_tracks(
    prev: Optional[WorldSnapshot],
    curr: WorldSnapshot,
    *,
    move_threshold_px: float = DEFAULT_WORLD_MOVE_THRESHOLD_PX,
) -> List[PerceptionEvent]:
    """Diff consecutive world snapshots and emit track lifecycle events."""
    events: List[PerceptionEvent] = []
    curr_data = world_snapshot_to_dict(curr)

    if prev is None:
        events.append(
            WorldSnapshotInitial(
                world=curr,
                data={"world": curr_data},
            )
        )
        for track in curr.tracks:
            track_data = world_track_to_dict(track)
            events.append(
                WorldTrackAppeared(
                    track=track,
                    data={"track": track_data},
                )
            )
            if track.stable:
                events.append(
                    WorldTrackStabilized(
                        track=track,
                        data={"track": track_data},
                    )
                )
        return events

    prev_map = _tracks_by_id(prev)
    curr_map = _tracks_by_id(curr)

    for track_id, track in curr_map.items():
        track_data = world_track_to_dict(track)
        if track_id not in prev_map:
            events.append(
                WorldTrackAppeared(
                    track=track,
                    data={"track": track_data},
                )
            )
        else:
            old = prev_map[track_id]
            if _client_distance(old.client_xy, track.client_xy) >= move_threshold_px:
                events.append(
                    WorldTrackMoved(
                        track_id=track.track_id,
                        template=track.template,
                        client_xy=track.client_xy,
                        screen_xy=track.screen_xy,
                        velocity_xy=track.velocity_xy,
                        prev_client_xy=old.client_xy,
                        prev_screen_xy=old.screen_xy,
                        data={
                            "track": track_data,
                            "prev_client_xy": [old.client_xy[0], old.client_xy[1]],
                            "prev_screen_xy": [old.screen_xy[0], old.screen_xy[1]],
                        },
                    )
                )
            if track.stable and not old.stable:
                events.append(
                    WorldTrackStabilized(
                        track=track,
                        data={"track": track_data},
                    )
                )

    for track_id, old in prev_map.items():
        if track_id not in curr_map:
            events.append(
                WorldTrackLost(
                    track_id=old.track_id,
                    template=old.template,
                    last_client_xy=old.client_xy,
                    last_screen_xy=old.screen_xy,
                    data={"track": world_track_to_dict(old)},
                )
            )

    return events


def diff_world_hits(
    prev: Optional[WorldSnapshot],
    curr: WorldSnapshot,
    *,
    move_threshold_px: float = DEFAULT_WORLD_MOVE_THRESHOLD_PX,
) -> List[PerceptionEvent]:
    """Diff ephemeral world hits (legacy fallback)."""
    if prev is None:
        return []

    events: List[PerceptionEvent] = []
    _, lost, appeared = _match_hits(prev.hits, curr.hits, move_threshold_px=move_threshold_px)

    for hit in appeared:
        hit_data = world_hit_to_dict(hit)
        events.append(
            WorldHitAppeared(
                hit=hit,
                data={"hit": hit_data},
            )
        )
    for hit in lost:
        hit_data = world_hit_to_dict(hit)
        events.append(
            WorldHitLost(
                hit=hit,
                data={"hit": hit_data},
            )
        )
    return events


def diff_world_templates(
    prev: Optional[WorldSnapshot],
    curr: WorldSnapshot,
) -> List[PerceptionEvent]:
    if prev is None:
        return []
    if prev.templates_scanned == curr.templates_scanned:
        return []
    return [
        WorldTemplateScanChanged(
            old_templates=prev.templates_scanned,
            new_templates=curr.templates_scanned,
            data={
                "old_templates": list(prev.templates_scanned),
                "new_templates": list(curr.templates_scanned),
            },
        )
    ]


def diff_action(
    prev: Optional[ActionSnapshot],
    curr: ActionSnapshot,
) -> List[PerceptionEvent]:
    """Diff consecutive action-strip snapshots."""
    events: List[PerceptionEvent] = []
    curr_data = action_snapshot_to_dict(curr)

    if prev is None:
        events.append(
            ActionSnapshotInitial(
                action=curr,
                data={"action": curr_data},
            )
        )
        if curr.strip_visible:
            events.append(
                ActionStripAppeared(
                    action=curr,
                    data={"action": curr_data},
                )
            )
        return events

    if prev.action_code != curr.action_code:
        events.append(
            ActionStateChanged(
                before_code=prev.action_code,
                after_code=curr.action_code,
                action=curr,
                data={
                    "before_code": prev.action_code,
                    "after_code": curr.action_code,
                    "action": curr_data,
                },
            )
        )

    if not prev.strip_visible and curr.strip_visible:
        events.append(
            ActionStripAppeared(
                action=curr,
                data={"action": curr_data},
            )
        )
    elif prev.strip_visible and not curr.strip_visible:
        events.append(
            ActionStripHidden(
                action=curr,
                data={"action": curr_data},
            )
        )

    return events


def diff_frame_age(
    prev_age_ms: float,
    curr_age_ms: float,
    *,
    stale_threshold_ms: float = DEFAULT_STALE_THRESHOLD_MS,
) -> List[PerceptionEvent]:
    events: List[PerceptionEvent] = []
    prev_stale = prev_age_ms >= stale_threshold_ms
    curr_stale = curr_age_ms >= stale_threshold_ms
    if not prev_stale and curr_stale:
        events.append(
            PerceptionStale(
                frame_age_ms=curr_age_ms,
                threshold_ms=stale_threshold_ms,
                data={
                    "frame_age_ms": curr_age_ms,
                    "threshold_ms": stale_threshold_ms,
                    "prev_frame_age_ms": prev_age_ms,
                },
            )
        )
    elif prev_stale and not curr_stale:
        events.append(
            PerceptionFresh(
                frame_age_ms=curr_age_ms,
                threshold_ms=stale_threshold_ms,
                data={
                    "frame_age_ms": curr_age_ms,
                    "threshold_ms": stale_threshold_ms,
                    "prev_frame_age_ms": prev_age_ms,
                },
            )
        )
    return events


def diff_perception(
    prev: Optional[PerceptionTick],
    curr: PerceptionTick,
    *,
    move_threshold_px: float = DEFAULT_WORLD_MOVE_THRESHOLD_PX,
    stale_threshold_ms: float = DEFAULT_STALE_THRESHOLD_MS,
) -> List[PerceptionEvent]:
    """Diff consecutive perception ticks into inventory, world, and meta events."""
    prev_inv = prev.inventory if prev is not None else None
    prev_world = prev.world if prev is not None else None
    prev_action = prev.action if prev is not None else None

    events: List[PerceptionEvent] = []
    events.extend(diff_action(prev_action, curr.action))
    events.extend(diff_inventory(prev_inv, curr.inventory))
    events.extend(
        diff_world_tracks(prev_world, curr.world, move_threshold_px=move_threshold_px)
    )
    events.extend(
        diff_world_hits(prev_world, curr.world, move_threshold_px=move_threshold_px)
    )
    events.extend(diff_world_templates(prev_world, curr.world))

    if prev is not None:
        if curr.capture_seq != prev.capture_seq:
            events.append(
                CaptureSeqAdvanced(
                    old_seq=prev.capture_seq,
                    new_seq=curr.capture_seq,
                    data={
                        "old_seq": prev.capture_seq,
                        "new_seq": curr.capture_seq,
                        "frame_age_ms": curr.frame_age_ms,
                    },
                )
            )
        events.extend(
            diff_frame_age(
                prev.frame_age_ms,
                curr.frame_age_ms,
                stale_threshold_ms=stale_threshold_ms,
            )
        )

    return events


__all__ = [
    "DEFAULT_STALE_THRESHOLD_MS",
    "DEFAULT_WORLD_MOVE_THRESHOLD_PX",
    "ActionSnapshotInitial",
    "ActionStateChanged",
    "ActionStripAppeared",
    "ActionStripHidden",
    "CaptureSeqAdvanced",
    "InventoryCountChanged",
    "InventoryFull",
    "InventoryLabelChanged",
    "InventoryLabelResolved",
    "InventoryNoLongerFull",
    "InventorySlotCleared",
    "InventorySlotOccupied",
    "InventorySnapshotInitial",
    "InventoryUnknownIncreased",
    "PerceptionEvent",
    "PerceptionFresh",
    "PerceptionStale",
    "WorldHitAppeared",
    "WorldHitLost",
    "WorldSnapshotInitial",
    "WorldTemplateScanChanged",
    "WorldTrackAppeared",
    "WorldTrackLost",
    "WorldTrackMoved",
    "WorldTrackStabilized",
    "diff_action",
    "diff_frame_age",
    "diff_inventory",
    "diff_perception",
    "diff_world_hits",
    "diff_world_templates",
    "diff_world_tracks",
    "perception_event_to_dict",
]
