"""
Optional rich session recorder with per-tick PNG sidecars for offline replay.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot_frames import write_tick_frames

__all__ = ["SessionRecorder"]


class SessionRecorder:
    """Writes observation/commands/verify JSON + frame PNGs per tick."""

    def __init__(self, run_id: str, root: Path = Path("sessions")) -> None:
        self.run_id = run_id
        self.root = Path(root)
        self.run_dir = self.root / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._tick = 0

    def record_tick(
        self,
        eyes,
        observation_dict: Dict[str, Any],
        commands: List[Dict[str, Any]],
        verify: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        self._tick += 1
        tick_dir = self.run_dir / ("tick_%04d" % self._tick)
        tick_dir.mkdir(parents=True, exist_ok=True)

        frame_paths = write_tick_frames(eyes, tick_dir, "frame", ocr=True)

        (tick_dir / "observation.json").write_text(
            json.dumps(observation_dict, indent=2, default=str), encoding="utf-8"
        )
        (tick_dir / "commands.json").write_text(
            json.dumps(commands, indent=2, default=str), encoding="utf-8"
        )
        if verify is not None:
            (tick_dir / "verify.json").write_text(
                json.dumps(verify, indent=2, default=str), encoding="utf-8"
            )
        return frame_paths
