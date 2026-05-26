#!/usr/bin/env python3
"""
CLI for single-step and (later) multi-step action chains.

Phase 3:
  python exodia_chain.py single --block click_template_world --args '{"template":"flax.png"}'
  python exodia_chain.py single --block click_template_inv --args '{"template":"logout_button2.png"}'
  python exodia_chain.py single --block use_item_id_on_item_id --args '{"sourceId":"hammer","destId":"eel"}'
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

_EXODIA = Path(__file__).resolve().parent
if str(_EXODIA) not in sys.path:
    sys.path.insert(0, str(_EXODIA))

from bot_chain import dispatch  # noqa: E402


def _emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, separators=(",", ":")))


def cmd_single(block: str, args_json: str, dry_run: bool) -> int:
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError as exc:
        _emit({"ok": False, "error": "invalid_args_json", "detail": str(exc)})
        return 1
    if not isinstance(args, dict):
        _emit({"ok": False, "error": "args_must_be_object"})
        return 1

    t0 = time.perf_counter()
    result = dispatch(block, args, dry_run=dry_run)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    out: Dict[str, Any] = {
        "ok": bool(result.get("ok")),
        "block": block,
        "duration_ms": duration_ms,
        "result": result,
    }
    if not result.get("ok"):
        out["error"] = result.get("error") or "dispatch_failed"
    _emit(out)
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exodia action chain runner")
    sub = parser.add_subparsers(dest="command", required=True)

    single = sub.add_parser("single", help="Run one action block")
    single.add_argument("--block", required=True, help="Block id from actions.manifest.json")
    single.add_argument("--args", default="{}", help="JSON object of block arguments")
    single.add_argument("--dry-run", action="store_true", help="Locate/identify only; skip clicks")

    ns = parser.parse_args(argv)
    if ns.command == "single":
        return cmd_single(ns.block, ns.args, ns.dry_run)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
