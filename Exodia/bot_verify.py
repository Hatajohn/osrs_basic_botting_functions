"""
Post-action verification by diffing ``GameState`` snapshots (screen-only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from bot_gamestate import GameState, occupied_cell_count

__all__ = ["ActionVerifyResult", "verify_action"]


@dataclass
class ActionVerifyResult:
    changed: bool
    signals: Dict[str, Any] = field(default_factory=dict)


def verify_action(
    before: GameState,
    after: GameState,
    *,
    item_count_before: Optional[int] = None,
    item_count_after: Optional[int] = None,
) -> ActionVerifyResult:
    """Compare before/after game state and return change signals."""
    signals: Dict[str, Any] = {}

    if before.action_line_text != after.action_line_text:
        signals["action_line_changed"] = True
        signals["action_line_before"] = before.action_line_text
        signals["action_line_after"] = after.action_line_text

    if before.action_busy != after.action_busy:
        signals["action_busy_flipped"] = True
        signals["action_busy_before"] = before.action_busy
        signals["action_busy_after"] = after.action_busy

    before_count = item_count_before if item_count_before is not None else before.inventory_item_count
    after_count = item_count_after if item_count_after is not None else after.inventory_item_count
    if before_count is not None and after_count is not None and before_count != after_count:
        signals["inventory_count_delta"] = after_count - before_count

    before_occ = occupied_cell_count(before.inventory_occupied)
    after_occ = occupied_cell_count(after.inventory_occupied)
    if before_occ is not None and after_occ is not None and before_occ != after_occ:
        signals["inventory_occupied_delta"] = after_occ - before_occ

    changed = bool(signals)
    return ActionVerifyResult(changed=changed, signals=signals)
