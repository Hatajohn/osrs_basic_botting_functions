"""
Canonical agent-facing game state snapshot built from ``BotEyes`` perception.

Simple — ``GameState`` dataclass, ``occupied_cell_count``, ``inventory_is_full``,
``game_state_to_dict`` serialization.

Compound — ``build_game_state``: action-strip + dialogue OCR and inventory via
``read_inventory_labels`` (``bot_inventory_items``). Item labels land on
``perception_envelope["inventory_slot_items"]`` only; ``GameState`` carries
occupancy counts, not per-slot names.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from bot_action_ui import ACTION_FISHING
from bot_eyes import INV_SLOTS
from bot_inventory_items import read_inventory_labels

if TYPE_CHECKING:
    import bot_eyes as Eyes

Rect = List[int]

__all__ = [
    "GameState",
    "build_game_state",
    "game_state_to_dict",
    "inventory_is_full",
    "occupied_cell_count",
]


@dataclass
class GameState:
    """Question: What sensory summary does the agent have this tick (screen-only)?"""

    tick: int
    action_busy: bool
    action_line_text: Optional[str]
    dialogue_text: Optional[str]
    inventory_occupied: Optional[List[List[bool]]]
    inventory_item_count: Optional[int]
    inventory_calibrated: bool
    client_rect: Rect
    capture_backend: str
    frame_paths: Dict[str, str] = field(default_factory=dict)
    action_text_code: int = 2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def occupied_cell_count(grid: Optional[List[List[bool]]]) -> Optional[int]:
    """Question: How many ``True`` cells are in an occupancy grid?"""
    if grid is None:
        return None
    return sum(1 for row in grid for cell in row if cell)


def _inventory_occupancy_from_eyes(eyes: "Eyes.BotEyes") -> Optional[List[List[bool]]]:
    pe = eyes.perception_envelope or {}
    occ = pe.get("inventory_slot_occupancy")
    if occ is None:
        occ = eyes.compute_inventory_slot_occupancy()
    return occ


def inventory_is_full(eyes: "Eyes.BotEyes", *, slot_count: int = INV_SLOTS) -> bool:
    """Question: Is the inventory full (occupied cells ≥ ``slot_count``, default 28)?"""
    n = occupied_cell_count(_inventory_occupancy_from_eyes(eyes))
    return n is not None and n >= slot_count


def build_game_state(
    eyes: "Eyes.BotEyes",
    tick: int,
    *,
    frame_paths: Optional[Dict[str, str]] = None,
) -> GameState:
    """Question: What is the canonical game-state snapshot from current ``BotEyes`` frames?

    Compound: ``get_action_text_with_ocr(refresh=False)``, ``ocr_dialogue_roi``, and
    ``read_inventory_labels`` for occupancy. Updates ``perception_envelope`` with
    ``inventory_slot_occupancy`` and ``inventory_slot_items`` (labels not on
    ``GameState``). Caller must have refreshed capture/geometry first.
    """
    code, ocr_action = eyes.get_action_text_with_ocr(refresh=False)
    ocr_dialogue = eyes.ocr_dialogue_roi()

    action_line = (ocr_action or {}).get("text") or None
    if action_line is not None:
        action_line = action_line.strip() or None

    dialogue = (ocr_dialogue or {}).get("text") or None
    if dialogue is not None:
        dialogue = dialogue.strip() or None

    slot_items, occupied = read_inventory_labels(eyes)
    pe = eyes.perception_envelope
    if pe is not None:
        pe["inventory_slot_occupancy"] = occupied
        pe["inventory_slot_items"] = slot_items

    calibrated = bool((pe or {}).get("inventory_rect_client_local"))
    item_count = occupied_cell_count(occupied)

    rect = list(eyes.client_rect) if eyes.client_rect is not None else []
    backend = str((pe or {}).get("capture_backend") or "")

    return GameState(
        tick=tick,
        action_busy=(code == ACTION_FISHING),
        action_line_text=action_line,
        dialogue_text=dialogue,
        inventory_occupied=occupied,
        inventory_item_count=item_count,
        inventory_calibrated=calibrated,
        client_rect=rect,
        capture_backend=backend,
        frame_paths=dict(frame_paths or {}),
        action_text_code=int(code),
    )


def game_state_to_dict(state: GameState) -> Dict[str, Any]:
    """Question: How do I serialize ``GameState`` for observation meta or logs?"""
    return state.to_dict()
