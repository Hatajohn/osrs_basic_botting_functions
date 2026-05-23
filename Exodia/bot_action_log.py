"""
Always-on JSONL action log for agent harness review.

Writes ``actions.jsonl`` (machine-readable) and ``actions.log`` (human tail) per run.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "ActionLogger",
    "TickLogRecord",
    "make_run_id",
    "command_to_dict",
]


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def command_to_dict(cmd: Any) -> Dict[str, Any]:
    if hasattr(cmd, "__dataclass_fields__"):
        d = asdict(cmd)
        d["type"] = type(cmd).__name__
        return d
    return {"type": type(cmd).__name__, "value": repr(cmd)}


@dataclass
class TickLogRecord:
    tick: int
    skipped_agent: bool
    game_state: Dict[str, Any]
    commands: List[Dict[str, Any]] = field(default_factory=list)
    verify: Optional[Dict[str, Any]] = None
    logs: List[str] = field(default_factory=list)


class ActionLogger:
    """Append-only per-run action log (JSONL + plain text companion)."""

    def __init__(self, run_id: str, root: Path = Path("logs")) -> None:
        self.run_id = run_id
        self.root = Path(root)
        self.run_dir = self.root / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.run_dir / "actions.jsonl"
        self.text_path = self.run_dir / "actions.log"
        self._jsonl = open(self.jsonl_path, "a", encoding="utf-8")
        self._text = open(self.text_path, "a", encoding="utf-8")
        self.tick_count = 0
        self.started_at = datetime.now(timezone.utc).isoformat()

    def log_tick(self, record: TickLogRecord) -> None:
        self.tick_count += 1
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tick": record.tick,
            "skipped_agent": record.skipped_agent,
            "game_state": record.game_state,
            "commands": record.commands,
            "verify": record.verify,
            "logs": record.logs,
        }
        self._jsonl.write(json.dumps(payload, default=str) + "\n")
        self._jsonl.flush()
        self._text.write(self._format_text_line(record) + "\n")
        self._text.flush()

    def _format_text_line(self, record: TickLogRecord) -> str:
        gs = record.game_state
        action = gs.get("action_line_text") or gs.get("action_text_code")
        parts = ["tick=%s" % record.tick]
        if record.skipped_agent:
            parts.append("SKIPPED")
        for cmd in record.commands:
            ctype = cmd.get("type", "?")
            if ctype == "CmdClickImage":
                parts.append("CLICK %s" % cmd.get("template", ""))
            elif ctype == "CmdClickColor":
                parts.append("CLICK_COLOR")
            elif ctype == "CmdUseItemOn":
                parts.append("USE %s ON %s" % (cmd.get("target_1", ""), cmd.get("target_2", "")))
            elif ctype == "CmdWaitTicks":
                parts.append("WAIT_TICKS %s" % cmd.get("num", ""))
            elif ctype == "CmdWait":
                parts.append("WAIT %ss" % cmd.get("seconds", ""))
            elif ctype == "CmdLog":
                parts.append("LOG %r" % cmd.get("message", ""))
            else:
                parts.append(ctype)
        parts.append("action=%s" % action)
        if record.verify:
            parts.append("verify=%s" % ("changed" if record.verify.get("changed") else "unchanged"))
        return " | ".join(parts)

    def close(self, run_meta: Optional[Dict[str, Any]] = None) -> None:
        meta = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "tick_count": self.tick_count,
        }
        if run_meta:
            meta.update(run_meta)
        (self.run_dir / "run_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
        self._jsonl.close()
        self._text.close()

    def __enter__(self) -> "ActionLogger":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
