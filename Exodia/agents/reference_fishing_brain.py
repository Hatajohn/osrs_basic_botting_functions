"""
Reference rule-based BotBrain: infernal eel fishing + Imcando hammer cracking.

Ports logic from ``infernal_fishing.py`` to declarative ``BrainCommand``s.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Sequence

from bot_harness import (
    BotBrain,
    BrainCommand,
    CmdClickImage,
    CmdLog,
    CmdUseItemOn,
    Observation,
)

__all__ = ["ReferenceFishingBrain"]

EEL_TEMPLATE = "infernal_eel_fish.png"
HAMMER_TEMPLATE = "imcando_hammer.png"
FULL_EEL_COUNT = 22


class ReferenceFishingBrain(BotBrain):
    """Fish infernal eels; crack full stacks with Imcando hammer."""

    def __init__(self) -> None:
        self.cracking = False

    def _eel_count(self, observation: Observation, harness: Any) -> int:
        matches = harness.eyes.locate_image(
            filename=EEL_TEMPLATE, inv=True, name="eel count"
        )
        return len(matches) if matches else 0

    def decide(self, observation: Observation, harness: Any) -> Sequence[BrainCommand]:
        gs = observation.meta.get("game_state") or {}
        action_busy = gs.get("action_busy", observation.action_text_code == 0)
        eel_count = self._eel_count(observation, harness)

        if eel_count == 0 and self.cracking:
            self.cracking = False

        cmds: List[BrainCommand] = []

        if (eel_count >= FULL_EEL_COUNT or self.cracking) and eel_count > 0:
            self.cracking = True
            cmds.append(CmdUseItemOn(HAMMER_TEMPLATE, EEL_TEMPLATE))
            cmds.append(CmdLog("Cracking eels (%d remaining)" % eel_count))
        elif not action_busy and not self.cracking and eel_count < FULL_EEL_COUNT:
            cmds.append(CmdClickImage(EEL_TEMPLATE, inv=False, refresh=True))
            cmds.append(CmdLog("Click fishing spot"))
        elif action_busy:
            cmds.append(CmdLog("Currently fishing"))
        elif not _template_exists(EEL_TEMPLATE):
            cmds.append(CmdLog("Warning: missing template %s" % EEL_TEMPLATE))

        return cmds


def _template_exists(template: str) -> bool:
    p = Path(template)
    if p.is_file():
        return True
    return (Path("images") / template).is_file()
