"""
Inventory progress score for sacred eel fishing.

Counts sacred eel icons in the inventory over time:

- **Increase** — fishing progress (more eels caught) → score up
- **Decrease** — scaling progress (eels turned into scales) → score up
- **No change** — stagnation (bad); streak counter rises, no score gain
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


STAGNATION_WARN_STREAK = int(os.environ.get("EXODIA_STAGNATION_WARN", "5"))


@dataclass
class InventoryProgressScore:
    """Tracks eel-in-inventory changes as a session health metric."""

    score: int = 0
    stagnation_streak: int = 0
    max_stagnation_streak: int = 0
    last_eel_count: Optional[int] = None
    last_inv_slots: Optional[int] = None
    last_delta: int = 0
    eels_gained: int = 0
    eels_processed: int = 0
    stagnant_observations: int = 0
    progress_events: int = 0
    _last_event: str = field(default="", repr=False)

    def observe(self, eel_count: int, inv_slots: Optional[int] = None) -> str:
        """
        Record eel icon count and occupied inv slots. Progress if either changes.

        Returns ``baseline``, ``fishing``, ``scaling``, ``inv_change``, or ``stagnant``.
        """
        if self.last_eel_count is None:
            self.last_eel_count = eel_count
            self.last_inv_slots = inv_slots
            self._last_event = "baseline"
            return self._last_event

        eel_delta = eel_count - self.last_eel_count
        inv_delta = 0
        if inv_slots is not None and self.last_inv_slots is not None:
            inv_delta = inv_slots - self.last_inv_slots

        self.last_eel_count = eel_count
        self.last_inv_slots = inv_slots

        if eel_delta == 0 and inv_delta == 0:
            self.stagnation_streak += 1
            self.stagnant_observations += 1
            if self.stagnation_streak > self.max_stagnation_streak:
                self.max_stagnation_streak = self.stagnation_streak
            self._last_event = "stagnant"
            return self._last_event

        self.stagnation_streak = 0
        self.progress_events += 1

        if eel_delta != 0:
            self.last_delta = eel_delta
            gain = abs(eel_delta)
            self.score += gain
            if eel_delta > 0:
                self.eels_gained += eel_delta
                self._last_event = "fishing"
            else:
                self.eels_processed += -eel_delta
                self._last_event = "scaling"
            return self._last_event

        self.last_delta = inv_delta
        self.score += abs(inv_delta)
        self._last_event = "inv_change"
        return self._last_event

    def is_stagnant(self) -> bool:
        """True once stagnation streak reaches the warning threshold (default 5)."""
        return self.stagnation_streak >= STAGNATION_WARN_STREAK

    def last_event_label(self) -> str:
        return self._last_event or "—"

    def summary_line(self) -> str:
        return (
            "score=%d | progress_events=%d | gained=%d | processed=%d | "
            "stagnation=%d (max %d) | stagnant_ticks=%d"
            % (
                self.score,
                self.progress_events,
                self.eels_gained,
                self.eels_processed,
                self.stagnation_streak,
                self.max_stagnation_streak,
                self.stagnant_observations,
            )
        )
