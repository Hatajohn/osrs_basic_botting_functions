"""
Typed perception snapshots parsed from stream ``/meta`` JSON.

World ``tracks[]`` with ``best_track`` / ``stable_tracks`` helpers; inventory
grid parsing for event diff consumers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Match ``bot_eyes.INV_ROWS`` / ``INV_COLS`` (7×4 grid) without importing cv2.
INV_ROWS = 7
INV_COLS = 4
INV_SLOT_COUNT = INV_ROWS * INV_COLS
_UNKNOWN_LABEL = "?"


class InventorySlotCountError(ValueError):
    """Occupied inventory slots exceed the OSRS grid size (28)."""


def _normalize_template_stem(template: str) -> str:
    stem = (template or "").strip()
    if stem.lower().endswith(".png"):
        stem = stem[:-4]
    return stem


def _pair_xy(raw: Any, *, fallback: Tuple[int, int] = (0, 0)) -> Tuple[int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return fallback
    try:
        return int(raw[0]), int(raw[1])
    except (TypeError, ValueError):
        return fallback


def _float_pair(raw: Any, *, fallback: Tuple[float, float] = (0.0, 0.0)) -> Tuple[float, float]:
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return fallback
    try:
        return float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return fallback


def _rect4(raw: Any) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        return int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3])
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class InventorySlot:
    row: int
    col: int
    occupied: bool
    label: Optional[str]


@dataclass(frozen=True)
class InventorySnapshot:
    rect: Optional[Tuple[int, int, int, int]]
    slots: Tuple[InventorySlot, ...]
    occupied: int
    unknown: int
    tmp_count: int
    calibrated: bool
    seq: int

    def slot_at(self, row: int, col: int) -> Optional[InventorySlot]:
        for slot in self.slots:
            if slot.row == row and slot.col == col:
                return slot
        return None

    def slots_with_label(self, name: str) -> Tuple[InventorySlot, ...]:
        stem = _normalize_template_stem(name)
        if not stem:
            return ()
        return tuple(
            s
            for s in self.slots
            if s.occupied and s.label is not None and _normalize_template_stem(s.label) == stem
        )

    def count_label(self, name: str) -> int:
        return len(self.slots_with_label(name))

    def occupied_from_grid(self) -> int:
        """Occupied slots from the parsed 7×4 occupancy grid."""
        return sum(1 for slot in self.slots if slot.occupied)

    def empty_slot_count(self) -> int:
        """Unoccupied inventory slots (0 = full, ready to crack)."""
        return max(0, INV_SLOT_COUNT - self.occupied_from_grid())

    def is_full(self) -> bool:
        return self.empty_slot_count() == 0

    def validate_slot_counts(self) -> None:
        """Raise when occupied counts exceed the 28-slot grid."""
        grid_occupied = self.occupied_from_grid()
        if grid_occupied > INV_SLOT_COUNT:
            raise InventorySlotCountError(
                "inventory grid reports %d occupied slots (max %d)"
                % (grid_occupied, INV_SLOT_COUNT)
            )
        if self.occupied > INV_SLOT_COUNT:
            raise InventorySlotCountError(
                "inventory meta occupied=%d exceeds max %d (grid=%d)"
                % (self.occupied, INV_SLOT_COUNT, grid_occupied)
            )

    def label_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for slot in self.slots:
            if not slot.occupied or slot.label is None or slot.label == _UNKNOWN_LABEL:
                continue
            stem = _normalize_template_stem(slot.label)
            if stem:
                counts[stem] = counts.get(stem, 0) + 1
        return counts


@dataclass(frozen=True)
class WorldHit:
    """Ephemeral single-frame template detection (legacy fallback)."""

    template: str
    client_xy: Tuple[int, int]
    screen_xy: Tuple[int, int]
    score: float


@dataclass(frozen=True)
class WorldTrack:
    """Persistent world-object track from ``WorldObjectTracker``."""

    track_id: int
    template: str
    client_xy: Tuple[int, int]
    screen_xy: Tuple[int, int]
    velocity_xy: Tuple[float, float]
    score: float
    age_frames: int
    missed_frames: int
    stable: bool


@dataclass(frozen=True)
class WorldSnapshot:
    tracks: Tuple[WorldTrack, ...]
    hits: Tuple[WorldHit, ...]
    templates_scanned: Tuple[str, ...]
    seq: int

    def best_track(self, template: str) -> Optional[WorldTrack]:
        """Highest-score track for ``template``; prefers ``stable`` tracks."""
        stem = _normalize_template_stem(template)
        if not stem:
            return None
        matches = [t for t in self.tracks if _normalize_template_stem(t.template) == stem]
        if not matches:
            return None
        stable = [t for t in matches if t.stable]
        pool = stable if stable else matches
        return max(pool, key=lambda t: (t.stable, t.score, -t.missed_frames))

    def stable_tracks(self, template: str) -> Tuple[WorldTrack, ...]:
        stem = _normalize_template_stem(template)
        if not stem:
            return ()
        return tuple(
            t
            for t in self.tracks
            if t.stable and _normalize_template_stem(t.template) == stem
        )


@dataclass(frozen=True)
class TextSpan:
    text: str
    color: str
    bbox: Tuple[int, int, int, int]
    conf: float


@dataclass(frozen=True)
class TextSnapshot:
    """Colored OCR spans from stream ``perception.text``."""

    spans: Tuple[TextSpan, ...]
    span_count: int
    client_size: Tuple[int, int]
    scan_ms: float
    vision_fps: float
    seq: int
    capture_seq: int


@dataclass(frozen=True)
class ActionSnapshot:
    """Action-strip tri-state from stream ``perception.action``."""

    action_code: int
    fishing_visible: bool
    not_fishing_visible: bool
    strip_visible: bool
    action_strip_rect: Optional[Tuple[int, int, int, int]]
    fish_template_score: float
    not_fish_template_score: float
    seq: int
    action_line_text: Optional[str] = None
    action_line_color: Optional[str] = None
    detection_source: Optional[str] = None

    def is_fishing(self) -> bool:
        """Green active skilling (code ``0``)."""
        return self.action_code == 0

    def is_idle_at_spot(self) -> bool:
        """Confident NOT fishing line after a session (code ``1``)."""
        return self.action_code == 1

    def is_strip_hidden(self) -> bool:
        """No confident fishing or NOT fishing line (code ``2``)."""
        return self.action_code == 2


@dataclass(frozen=True)
class PerceptionTick:
    """Parsed ``/meta`` tick for stream-first bot consumers."""

    capture_seq: int
    frame_age_ms: float
    client_rect: Optional[Tuple[int, int, int, int]]
    inventory: InventorySnapshot
    world: WorldSnapshot
    action: ActionSnapshot
    text: TextSnapshot
    ts: float = 0.0


def inventory_slot_to_dict(slot: InventorySlot) -> Dict[str, Any]:
    return {
        "row": slot.row,
        "col": slot.col,
        "occupied": slot.occupied,
        "label": slot.label,
    }


def inventory_snapshot_to_dict(snap: InventorySnapshot) -> Dict[str, Any]:
    return {
        "inventory_rect": list(snap.rect) if snap.rect is not None else None,
        "occupied": snap.occupied,
        "unknown": snap.unknown,
        "tmp_count": snap.tmp_count,
        "inventory_calibrated": snap.calibrated,
        "seq": snap.seq,
        "slots": [inventory_slot_to_dict(s) for s in snap.slots],
    }


def world_hit_to_dict(hit: WorldHit) -> Dict[str, Any]:
    return {
        "template": hit.template,
        "client_xy": [hit.client_xy[0], hit.client_xy[1]],
        "screen_xy": [hit.screen_xy[0], hit.screen_xy[1]],
        "score": hit.score,
    }


def world_track_to_dict(track: WorldTrack) -> Dict[str, Any]:
    return {
        "track_id": track.track_id,
        "template": track.template,
        "client_xy": [track.client_xy[0], track.client_xy[1]],
        "screen_xy": [track.screen_xy[0], track.screen_xy[1]],
        "velocity_xy": [track.velocity_xy[0], track.velocity_xy[1]],
        "score": track.score,
        "age_frames": track.age_frames,
        "missed_frames": track.missed_frames,
        "stable": track.stable,
    }


def world_snapshot_to_dict(snap: WorldSnapshot) -> Dict[str, Any]:
    return {
        "seq": snap.seq,
        "templates_scanned": list(snap.templates_scanned),
        "tracks": [world_track_to_dict(t) for t in snap.tracks],
        "hits": [world_hit_to_dict(h) for h in snap.hits],
    }


def _coerce_bool_grid(raw: Any, *, rows: int, cols: int) -> List[List[bool]]:
    grid = [[False] * cols for _ in range(rows)]
    if not isinstance(raw, list):
        return grid
    for row in range(min(rows, len(raw))):
        row_raw = raw[row]
        if not isinstance(row_raw, list):
            continue
        for col in range(min(cols, len(row_raw))):
            grid[row][col] = bool(row_raw[col])
    return grid


def _coerce_label_grid(raw: Any, *, rows: int, cols: int) -> List[List[Optional[str]]]:
    grid: List[List[Optional[str]]] = [[None] * cols for _ in range(rows)]
    if not isinstance(raw, list):
        return grid
    for row in range(min(rows, len(raw))):
        row_raw = raw[row]
        if not isinstance(row_raw, list):
            continue
        for col in range(min(cols, len(row_raw))):
            cell = row_raw[col]
            if cell is None:
                grid[row][col] = None
            else:
                text = str(cell).strip()
                grid[row][col] = text if text else None
    return grid


def _build_inventory_slots(
    occupancy: Sequence[Sequence[bool]],
    slot_items: Sequence[Sequence[Optional[str]]],
) -> Tuple[InventorySlot, ...]:
    slots: List[InventorySlot] = []
    for row in range(INV_ROWS):
        for col in range(INV_COLS):
            occupied = (
                bool(occupancy[row][col])
                if row < len(occupancy) and col < len(occupancy[row])
                else False
            )
            label: Optional[str] = None
            if row < len(slot_items) and col < len(slot_items[row]):
                label = slot_items[row][col]
            if not occupied:
                label = None
            slots.append(InventorySlot(row=row, col=col, occupied=occupied, label=label))
    return tuple(slots)


def empty_action_snapshot(*, seq: int = 0) -> ActionSnapshot:
    return ActionSnapshot(
        action_code=2,
        fishing_visible=False,
        not_fishing_visible=False,
        strip_visible=False,
        action_strip_rect=None,
        fish_template_score=0.0,
        not_fish_template_score=0.0,
        seq=seq,
        action_line_text=None,
        action_line_color=None,
        detection_source=None,
    )


def empty_text_snapshot(*, seq: int = 0) -> TextSnapshot:
    return TextSnapshot(
        spans=(),
        span_count=0,
        client_size=(0, 0),
        scan_ms=0.0,
        vision_fps=0.0,
        seq=seq,
        capture_seq=seq,
    )


def text_span_to_dict(span: TextSpan) -> Dict[str, Any]:
    return {
        "text": span.text,
        "color": span.color,
        "bbox": [span.bbox[0], span.bbox[1], span.bbox[2], span.bbox[3]],
        "conf": span.conf,
    }


def text_snapshot_to_dict(snap: TextSnapshot) -> Dict[str, Any]:
    return {
        "processed_seq": snap.seq,
        "capture_seq": snap.capture_seq,
        "span_count": snap.span_count,
        "client_w": snap.client_size[0],
        "client_h": snap.client_size[1],
        "scan_ms": snap.scan_ms,
        "vision_fps": snap.vision_fps,
        "spans": [text_span_to_dict(s) for s in snap.spans],
    }


def action_snapshot_to_dict(snap: ActionSnapshot) -> Dict[str, Any]:
    return {
        "action_code": snap.action_code,
        "fishing_visible": snap.fishing_visible,
        "not_fishing_visible": snap.not_fishing_visible,
        "strip_visible": snap.strip_visible,
        "action_strip_rect": list(snap.action_strip_rect) if snap.action_strip_rect else None,
        "fish_template_score": snap.fish_template_score,
        "not_fish_template_score": snap.not_fish_template_score,
        "seq": snap.seq,
        "action_line_text": snap.action_line_text,
        "action_line_color": snap.action_line_color,
        "detection_source": snap.detection_source,
    }


def parse_action_meta(action: Optional[Mapping[str, Any]], *, seq: int = 0) -> ActionSnapshot:
    """Parse ``perception.action`` slice from ``/meta``."""
    root = action if isinstance(action, Mapping) else {}
    try:
        action_code = int(root.get("action_code", 2))
    except (TypeError, ValueError):
        action_code = 2
    fishing_visible = bool(root.get("fishing_visible"))
    not_fishing_visible = bool(root.get("not_fishing_visible"))
    strip_visible = bool(root.get("strip_visible"))
    rect = _rect4(root.get("action_strip_rect"))
    try:
        fish_score = float(root.get("fish_template_score", 0.0))
    except (TypeError, ValueError):
        fish_score = 0.0
    try:
        idle_score = float(root.get("not_fish_template_score", 0.0))
    except (TypeError, ValueError):
        idle_score = 0.0
    try:
        snap_seq = int(root.get("processed_seq", root.get("capture_seq", seq)))
    except (TypeError, ValueError):
        snap_seq = seq
    action_line_text = root.get("action_line_text")
    if action_line_text is not None:
        action_line_text = str(action_line_text).strip() or None
    action_line_color = root.get("action_line_color")
    if action_line_color is not None:
        action_line_color = str(action_line_color).strip() or None
    detection_source = root.get("detection_source")
    if detection_source is not None:
        detection_source = str(detection_source).strip() or None
    return ActionSnapshot(
        action_code=action_code,
        fishing_visible=fishing_visible,
        not_fishing_visible=not_fishing_visible,
        strip_visible=strip_visible,
        action_strip_rect=rect,
        fish_template_score=fish_score,
        not_fish_template_score=idle_score,
        seq=snap_seq,
        action_line_text=action_line_text,
        action_line_color=action_line_color,
        detection_source=detection_source,
    )


def empty_inventory_snapshot(*, seq: int = 0) -> InventorySnapshot:
    occ = _coerce_bool_grid(None, rows=INV_ROWS, cols=INV_COLS)
    items = _coerce_label_grid(None, rows=INV_ROWS, cols=INV_COLS)
    return InventorySnapshot(
        rect=None,
        slots=_build_inventory_slots(occ, items),
        occupied=0,
        unknown=0,
        tmp_count=0,
        calibrated=False,
        seq=seq,
    )


def parse_inventory_meta(inventory: Optional[Mapping[str, Any]], *, seq: int = 0) -> InventorySnapshot:
    """Parse ``perception.inventory`` slice from ``/meta``."""
    root = inventory if isinstance(inventory, Mapping) else {}
    occupancy = _coerce_bool_grid(root.get("occupancy"), rows=INV_ROWS, cols=INV_COLS)
    slot_items = _coerce_label_grid(root.get("slot_items"), rows=INV_ROWS, cols=INV_COLS)
    rect = _rect4(root.get("inventory_rect"))

    try:
        occupied = int(root.get("occupied", sum(1 for row in occupancy for cell in row if cell)))
    except (TypeError, ValueError):
        occupied = sum(1 for row in occupancy for cell in row if cell)
    try:
        unknown = int(root.get("unknown", 0))
    except (TypeError, ValueError):
        unknown = 0
    try:
        tmp_count = int(root.get("tmp_count", 0))
    except (TypeError, ValueError):
        tmp_count = 0

    calibrated = bool(root.get("inventory_calibrated"))
    if not calibrated and rect is not None:
        calibrated = True

    try:
        snap_seq = int(root.get("processed_seq", root.get("capture_seq", seq)))
    except (TypeError, ValueError):
        snap_seq = seq

    return InventorySnapshot(
        rect=rect,
        slots=_build_inventory_slots(occupancy, slot_items),
        occupied=occupied,
        unknown=unknown,
        tmp_count=tmp_count,
        calibrated=calibrated,
        seq=snap_seq,
    )


def _parse_world_hit(raw: Dict[str, Any]) -> Optional[WorldHit]:
    template = _normalize_template_stem(str(raw.get("template") or raw.get("name") or ""))
    if not template:
        return None
    client_xy = _pair_xy(raw.get("client_xy"))
    screen_xy = _pair_xy(raw.get("screen_xy"), fallback=client_xy)
    try:
        score = float(raw.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return WorldHit(template=template, client_xy=client_xy, screen_xy=screen_xy, score=score)


def _parse_world_track(raw: Dict[str, Any]) -> Optional[WorldTrack]:
    template = _normalize_template_stem(str(raw.get("template") or ""))
    if not template:
        return None
    try:
        track_id = int(raw.get("track_id", -1))
    except (TypeError, ValueError):
        return None
    if track_id < 0:
        return None
    client_xy = _pair_xy(raw.get("client_xy"))
    screen_xy = _pair_xy(raw.get("screen_xy"), fallback=client_xy)
    velocity_xy = _float_pair(raw.get("velocity_xy"))
    try:
        score = float(raw.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    try:
        age_frames = int(raw.get("age_frames", 0))
    except (TypeError, ValueError):
        age_frames = 0
    try:
        missed_frames = int(raw.get("missed_frames", 0))
    except (TypeError, ValueError):
        missed_frames = 0
    stable = bool(raw.get("stable"))
    return WorldTrack(
        track_id=track_id,
        template=template,
        client_xy=client_xy,
        screen_xy=screen_xy,
        velocity_xy=velocity_xy,
        score=score,
        age_frames=age_frames,
        missed_frames=missed_frames,
        stable=stable,
    )


def parse_world_meta(world: Optional[Dict[str, Any]], *, seq: int = 0) -> WorldSnapshot:
    """Parse ``perception.world`` slice from ``/meta``."""
    root = world if isinstance(world, dict) else {}
    hits: Tuple[WorldHit, ...] = ()
    raw_hits = root.get("hits")
    if isinstance(raw_hits, list):
        parsed_hits = [_parse_world_hit(h) for h in raw_hits if isinstance(h, dict)]
        hits = tuple(h for h in parsed_hits if h is not None)

    tracks: Tuple[WorldTrack, ...] = ()
    raw_tracks = root.get("tracks")
    if isinstance(raw_tracks, list):
        parsed_tracks = [_parse_world_track(t) for t in raw_tracks if isinstance(t, dict)]
        tracks = tuple(t for t in parsed_tracks if t is not None)

    templates: Tuple[str, ...] = ()
    raw_templates = root.get("templates_scanned")
    if isinstance(raw_templates, list):
        templates = tuple(
            _normalize_template_stem(str(t))
            for t in raw_templates
            if _normalize_template_stem(str(t))
        )

    try:
        snap_seq = int(root.get("processed_seq", root.get("seq", seq)))
    except (TypeError, ValueError):
        snap_seq = seq

    return WorldSnapshot(
        tracks=tracks,
        hits=hits,
        templates_scanned=templates,
        seq=snap_seq,
    )


def _parse_text_span(raw: Dict[str, Any]) -> Optional[TextSpan]:
    text = str(raw.get("text") or "").strip()
    if not text:
        return None
    color = str(raw.get("color") or "unknown").strip() or "unknown"
    bbox = _rect4(raw.get("bbox"))
    if bbox is None:
        return None
    try:
        conf = float(raw.get("conf", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return TextSpan(text=text, color=color, bbox=bbox, conf=conf)


def parse_text_meta(text: Optional[Mapping[str, Any]], *, seq: int = 0) -> TextSnapshot:
    """Parse ``perception.text`` slice from ``/meta``."""
    root = text if isinstance(text, Mapping) else {}
    spans: Tuple[TextSpan, ...] = ()
    raw_spans = root.get("spans")
    if not isinstance(raw_spans, list):
        raw_spans = root.get("fishing_spans")
    if isinstance(raw_spans, list):
        parsed = [_parse_text_span(s) for s in raw_spans if isinstance(s, dict)]
        spans = tuple(s for s in parsed if s is not None)

    try:
        span_count = int(root.get("span_count", len(spans)))
    except (TypeError, ValueError):
        span_count = len(spans)
    try:
        client_w = int(root.get("client_w", 0))
    except (TypeError, ValueError):
        client_w = 0
    try:
        client_h = int(root.get("client_h", 0))
    except (TypeError, ValueError):
        client_h = 0
    try:
        scan_ms = float(root.get("scan_ms", 0.0))
    except (TypeError, ValueError):
        scan_ms = 0.0
    try:
        vision_fps = float(root.get("vision_fps", 0.0))
    except (TypeError, ValueError):
        vision_fps = 0.0
    try:
        snap_seq = int(root.get("processed_seq", root.get("capture_seq", seq)))
    except (TypeError, ValueError):
        snap_seq = seq
    try:
        capture_seq = int(root.get("capture_seq", seq))
    except (TypeError, ValueError):
        capture_seq = seq

    return TextSnapshot(
        spans=spans,
        span_count=span_count,
        client_size=(client_w, client_h),
        scan_ms=scan_ms,
        vision_fps=vision_fps,
        seq=snap_seq,
        capture_seq=capture_seq,
    )


def parse_perception_tick(meta: Optional[Dict[str, Any]]) -> PerceptionTick:
    """Parse top-level ``/meta`` into a minimal ``PerceptionTick``."""
    root = meta if isinstance(meta, dict) else {}
    perception = root.get("perception")
    if not isinstance(perception, dict):
        perception = {}
    world_raw = perception.get("world")
    if not isinstance(world_raw, dict):
        world_raw = {}

    try:
        capture_seq = int(root.get("capture_seq", 0))
    except (TypeError, ValueError):
        capture_seq = 0
    try:
        frame_age_ms = float(root.get("frame_age_ms", 0.0))
    except (TypeError, ValueError):
        frame_age_ms = 0.0

    inventory_raw = perception.get("inventory")
    inventory = parse_inventory_meta(
        inventory_raw if isinstance(inventory_raw, dict) else None,
        seq=capture_seq,
    )
    client_rect = _rect4(root.get("client_rect"))

    try:
        ts = float(root.get("ts", 0.0))
    except (TypeError, ValueError):
        ts = 0.0

    world = parse_world_meta(world_raw, seq=capture_seq)
    action_raw = perception.get("action")
    action = parse_action_meta(
        action_raw if isinstance(action_raw, dict) else None,
        seq=capture_seq,
    )
    text_raw = perception.get("text")
    text = parse_text_meta(
        text_raw if isinstance(text_raw, dict) else None,
        seq=capture_seq,
    )
    return PerceptionTick(
        capture_seq=capture_seq,
        frame_age_ms=frame_age_ms,
        client_rect=client_rect,
        inventory=inventory,
        world=world,
        action=action,
        text=text,
        ts=ts,
    )


__all__ = [
    "INV_COLS",
    "INV_ROWS",
    "INV_SLOT_COUNT",
    "ActionSnapshot",
    "InventorySlot",
    "InventorySlotCountError",
    "InventorySnapshot",
    "PerceptionTick",
    "TextSnapshot",
    "TextSpan",
    "action_snapshot_to_dict",
    "empty_action_snapshot",
    "empty_text_snapshot",
    "parse_action_meta",
    "parse_text_meta",
    "text_snapshot_to_dict",
    "text_span_to_dict",
    "WorldHit",
    "WorldSnapshot",
    "WorldTrack",
    "empty_inventory_snapshot",
    "inventory_slot_to_dict",
    "inventory_snapshot_to_dict",
    "parse_inventory_meta",
    "parse_perception_tick",
    "parse_world_meta",
    "world_hit_to_dict",
    "world_snapshot_to_dict",
    "world_track_to_dict",
]
