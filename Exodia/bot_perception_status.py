"""
Lightweight ``BotEyes`` snapshot for ``runtime_status.json`` (no FSM imports).
"""
from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    import bot_eyes as Eyes

__all__ = ["perception_status_from_eyes"]


def perception_status_from_eyes(eyes: "Eyes.BotEyes") -> Dict[str, Any]:
    """Build nested ``perception`` fields for :meth:`RuntimeBridge.publish_status`."""
    pe = eyes.perception_envelope or {}
    capture_mean = None
    frame = eyes.curr_client
    if frame is not None and getattr(frame, "size", 0) > 0:
        capture_mean = float(frame.mean())
    calibrated = bool(pe.get("inventory_rect_client_local"))
    action_code = int(eyes.get_action_text_robust(refresh=False))
    return {
        "perception": {
            "capture_mean": capture_mean,
            "inventory_calibrated": calibrated,
            "action_code": action_code,
        }
    }
