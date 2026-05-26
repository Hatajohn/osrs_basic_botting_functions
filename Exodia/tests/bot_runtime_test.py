"""Tests for runtime control file I/O."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from bot_perception_status import perception_status_from_eyes
from bot_runtime import (
    RuntimeBridge,
    RuntimeCommand,
    exodia_ctl_main,
    parse_control_command,
    write_json_atomic,
)


class TestBotRuntime(unittest.TestCase):
    def test_parse_control_command(self):
        cmd = parse_control_command({"command": "pause", "issued_at": "t"})
        self.assertEqual(cmd.name, "pause")

    def test_bridge_dispatches_and_clears(self):
        with tempfile.TemporaryDirectory() as td:
            control = Path(td) / "control.json"
            status = Path(td) / "status.json"
            bridge = RuntimeBridge(
                script_name="test",
                control_path=control,
                status_path=status,
                poll_interval_s=0.0,
            )
            seen = []

            def on_pause(_cmd: RuntimeCommand) -> str:
                seen.append("pause")
                bridge.paused = True
                return "paused"

            bridge.register("pause", on_pause)
            write_json_atomic(control, {"command": "pause"})
            lines = bridge.poll()
            self.assertEqual(lines, ["paused"])
            self.assertFalse(control.exists())
            bridge.publish_status({"state": "IDLE"})
            data = json.loads(status.read_text())
            self.assertTrue(data["paused"])
            self.assertEqual(data["state"], "IDLE")

    def test_merge_context_and_last_action_in_status(self):
        with tempfile.TemporaryDirectory() as td:
            status = Path(td) / "status.json"
            bridge = RuntimeBridge(
                script_name="test",
                control_path=Path(td) / "control.json",
                status_path=status,
                poll_interval_s=0.0,
            )
            bridge.merge_context(fsm_state="SEEK", eel_count=3)
            bridge.set_last_action("pan_left 612ms")
            bridge.stop_reason = "user stop"
            bridge.publish_status(
                perception_status_from_eyes(_mock_eyes(action_code=1, capture_mean=42.0))
            )
            data = json.loads(status.read_text())
            self.assertEqual(data["last_action"], "pan_left 612ms")
            self.assertEqual(data["stop_reason"], "user stop")
            self.assertEqual(data["context"]["fsm_state"], "SEEK")
            self.assertEqual(data["context"]["eel_count"], 3)
            self.assertEqual(data["perception"]["action_code"], 1)
            self.assertEqual(data["perception"]["capture_mean"], 42.0)
            self.assertTrue(data["perception"]["inventory_calibrated"])
            self.assertIn("session_started_at", data)
            self.assertGreaterEqual(data["session_uptime_s"], 0.0)

    def test_register_health_probe(self):
        bridge = RuntimeBridge(script_name="test", enabled=False)
        probe = MagicMock(return_value={"ok": True})
        bridge.register_health_probe(probe)
        self.assertEqual(bridge._health_probes, [probe])

    def test_health_command_runs_probes(self):
        with tempfile.TemporaryDirectory() as td:
            control = Path(td) / "control.json"
            status = Path(td) / "status.json"
            bridge = RuntimeBridge(
                script_name="test",
                control_path=control,
                status_path=status,
                poll_interval_s=0.0,
            )
            probe = MagicMock(return_value={"eel_count": 2})
            bridge.register_health_probe(probe)

            def on_health(_cmd: RuntimeCommand) -> str:
                bridge.run_health()
                return "health OK"

            bridge.register("health", on_health)
            write_json_atomic(control, {"command": "health"})
            lines = bridge.poll()
            self.assertEqual(lines, ["health OK"])
            probe.assert_called_once()
            bridge.publish_status({"state": "IDLE"})
            data = json.loads(status.read_text())
            self.assertEqual(data["context"]["health"], {"eel_count": 2})

    def test_exodia_ctl_health_queues_and_prints_status(self):
        with tempfile.TemporaryDirectory() as td:
            control = Path(td) / "control.json"
            status = Path(td) / "status.json"
            write_json_atomic(
                status,
                {
                    "script": "sacred_eel_fishing",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "perception": {"action_code": 1},
                    "context": {"fsm_state": "FISHING"},
                },
            )
            import io
            import os
            from contextlib import redirect_stdout

            buf = io.StringIO()
            env = os.environ.copy()
            env["EXODIA_RUNTIME_STATUS"] = str(status)
            with patch.dict(os.environ, env, clear=False):
                with redirect_stdout(buf):
                    rc = exodia_ctl_main(
                        ["health", "--control-file", str(control)]
                    )
            self.assertEqual(rc, 0)
            self.assertTrue(control.is_file())
            queued = json.loads(control.read_text())
            self.assertEqual(queued["command"], "health")
            out = buf.getvalue()
            self.assertIn("Queued command", out)
            self.assertIn("fsm_state", out)
            self.assertIn("action_code", out)

    def test_poll_logs_runtime_command_when_events_available(self):
        log_mock = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            control = Path(td) / "control.json"
            bridge = RuntimeBridge(
                script_name="test",
                control_path=control,
                status_path=Path(td) / "status.json",
                poll_interval_s=0.0,
            )
            bridge.register("pause", lambda _c: "paused")
            write_json_atomic(control, {"command": "pause"})
            with patch("bot_runtime._get_log_event", return_value=log_mock):
                bridge.poll()
            log_mock.assert_called_once_with(
                "runtime.command", command="pause", ack="paused"
            )

    def test_perception_status_from_eyes(self):
        eyes = _mock_eyes(action_code=0, capture_mean=10.0, calibrated=False)
        out = perception_status_from_eyes(eyes)
        self.assertEqual(out["perception"]["action_code"], 0)
        self.assertEqual(out["perception"]["capture_mean"], 10.0)
        self.assertFalse(out["perception"]["inventory_calibrated"])

    def test_snapshot_saves_client(self):
        with tempfile.TemporaryDirectory() as td:
            bot_e = MagicMock()
            import numpy as np

            bot_e.curr_client = np.zeros((10, 10, 3), dtype=np.uint8)
            bot_e.curr_inventory = None
            bot_e._action_strip_bgr.return_value = None
            from bot_runtime import save_perception_snapshot

            out = save_perception_snapshot(bot_e, tag="test", log_dir=Path(td))
            self.assertTrue((out / "client.png").is_file())


def _mock_eyes(*, action_code: int, capture_mean: float = 5.0, calibrated: bool = True):
    import numpy as np

    eyes = MagicMock()
    eyes.perception_envelope = {
        "inventory_rect_client_local": [0, 0, 10, 10] if calibrated else None,
    }
    eyes.curr_client = np.full((4, 4, 3), capture_mean, dtype=np.uint8)
    eyes.get_action_text.return_value = action_code
    return eyes


if __name__ == "__main__":
    unittest.main()
