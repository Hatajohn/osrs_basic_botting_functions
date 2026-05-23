"""
Canonical agent-facing game state snapshot built from ``BotEyes`` perception.

Maps screen capture + OCR into a JSON-serializable ``GameState`` for ``Observation.meta``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from bot_action_ui import ACTION_FISHING

if TYPE_CHECKING:
    import bot_eyes as Eyes

Rect = List[int]

__all__ = ["GameState", "build_game_state", "game_state_to_dict", "occupied_cell_count"]


@dataclass
class GameState:
    """One timestep sensory summary for agent policy code."""

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
    if grid is None:
        return None
    return sum(1 for row in grid for cell in row if cell)


def build_game_state(
    eyes: "Eyes.BotEyes",
    tick: int,
    *,
    frame_paths: Optional[Dict[str, str]] = None,
) -> GameState:
    """
    Build ``GameState`` from current ``BotEyes`` frames (caller must have refreshed).

    Uses ``get_action_text_with_ocr(refresh=False)`` to avoid an extra capture.
    """
    code, ocr_action = eyes.get_action_text_with_ocr(refresh=False)
    ocr_dialogue = eyes.ocr_dialogue_roi()

    action_line = (ocr_action or {}).get("text") or None
    if action_line is not None:
        action_line = action_line.strip() or None

    dialogue = (ocr_dialogue or {}).get("text") or None
    if dialogue is not None:
        dialogue = dialogue.strip() or None

    pe = eyes.perception_envelope or {}
    occupied = pe.get("inventory_slot_occupancy")
    calibrated = bool(pe.get("inventory_rect_client_local"))
    item_count = occupied_cell_count(occupied)

    rect = list(eyes.client_rect) if eyes.client_rect is not None else []
    backend = str(pe.get("capture_backend") or "")

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
    return state.to_dict()
