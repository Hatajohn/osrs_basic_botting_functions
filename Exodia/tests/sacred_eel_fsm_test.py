"""Unit tests for sacred eel state transitions (no game client)."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import unittest
from unittest.mock import MagicMock, patch

from bot_inventory_actions import UseItemOnResult

from bot_action_ui import (
    ACTION_FISHING,
    ACTION_IDLE,
    ACTION_NO_UI,
    is_action_fishing,
    is_action_idle,
    should_seek_fishing_spot,
)
from SacredEelFishing.sacred_eel_fsm import (
    SacredEelContext,
    SacredEelMachine,
    SacredEelState,
    ScalePhase,
    configure_fsm,
    should_enter_scaling,
)


class TestSacredEelFSM(unittest.TestCase):
    def setUp(self):
        self._events: list = []
        self._use_x_on_y_patcher = patch(
            "SacredEelFishing.sacred_eel_fsm.Actions.use_x_on_y",
            return_value=UseItemOnResult(True),
        )
        self._use_x_on_y_patcher.start()
        configure_fsm(
            sleep_fn=lambda _s: None,
            stop_check=lambda: False,
            count_eels=lambda _e: _e._eel_count,
            inv_slots=lambda _e: _e._inv_slots,
            inv_full=lambda _e: _e._inv_full,
            locate_spots=lambda _e: _e._spots,
            spot_templates=["spot.png"],
            full_eel_count=22,
            inv_slot_count=28,
            max_spot_pan_attempts=0,
            max_spot_walk_attempts=0,
            scale_tick_delay_s=0.0,
            max_scale_actions=5,
            log_event=self._collect_event,
        )

    def tearDown(self):
        self._use_x_on_y_patcher.stop()

    def _collect_event(self, event: str, **fields) -> None:
        self._events.append((event, fields))

    def _ctx(self, **kwargs):
        bot_e = MagicMock()
        code = kwargs.get("action_code", 2)
        bot_e.get_action_text.return_value = code
        bot_e.get_action_text_robust.return_value = code
        bot_e._eel_count = kwargs.get("eel_count", 0)
        bot_e._inv_slots = kwargs.get("inv_slots", 10)
        bot_e._inv_full = kwargs.get("inv_full", False)
        bot_e._spots = kwargs.get("spots", [])
        client = MagicMock()
        bot_a = MagicMock()
        ctx = SacredEelContext(client=client, bot_e=bot_e, bot_a=bot_a)
        ctx.state = kwargs.get("state", SacredEelState.SEEK_SPOT)
        ctx.action_code = bot_e.get_action_text.return_value
        ctx.eel_count = bot_e._eel_count
        ctx.inv_slots = bot_e._inv_slots
        return ctx

    def test_should_enter_scaling_full_inv(self):
        ctx = self._ctx(inv_full=True, eel_count=5)
        self.assertTrue(should_enter_scaling(ctx))

    def test_fishing_to_scaling(self):
        ctx = self._ctx(state=SacredEelState.FISHING, action_code=0, eel_count=22)
        SacredEelMachine(ctx).step()
        self.assertEqual(ctx.state, SacredEelState.SCALING)
        self.assertEqual(ctx.scale_phase, ScalePhase.CLICK)
        transition_fields = [f for e, f in self._events if e == "fsm.transition"]
        self.assertTrue(transition_fields)
        self.assertEqual(transition_fields[-1]["to_state"], "SCALING")

    def test_fishing_does_not_seek_spot_on_green(self):
        spots_called = []

        def track_spots(_e):
            spots_called.append(1)
            return []

        configure_fsm(
            sleep_fn=lambda _s: None,
            stop_check=lambda: False,
            count_eels=lambda _e: _e._eel_count,
            inv_slots=lambda _e: _e._inv_slots,
            inv_full=lambda _e: False,
            locate_spots=track_spots,
            spot_templates=["spot.png"],
            full_eel_count=22,
            inv_slot_count=28,
            max_spot_pan_attempts=0,
            max_spot_walk_attempts=0,
            scale_tick_delay_s=0.0,
            max_scale_actions=5,
        )
        ctx = self._ctx(state=SacredEelState.FISHING, action_code=ACTION_FISHING, eel_count=5)
        SacredEelMachine(ctx).step()
        self.assertEqual(ctx.state, SacredEelState.FISHING)
        self.assertEqual(spots_called, [])

    def test_fishing_to_seek_on_red(self):
        ctx = self._ctx(state=SacredEelState.FISHING, action_code=ACTION_IDLE, eel_count=5)
        SacredEelMachine(ctx).step()
        self.assertEqual(ctx.state, SacredEelState.SEEK_SPOT)

    def test_seek_spot_skips_locate_when_green(self):
        spots_called = []

        def track_spots(_e):
            spots_called.append(1)
            return [[100, 100]]

        configure_fsm(
            sleep_fn=lambda _s: None,
            stop_check=lambda: False,
            count_eels=lambda _e: 0,
            inv_slots=lambda _e: 10,
            inv_full=lambda _e: False,
            locate_spots=track_spots,
            spot_templates=["spot.png"],
            full_eel_count=22,
            inv_slot_count=28,
            max_spot_pan_attempts=0,
            max_spot_walk_attempts=0,
            scale_tick_delay_s=0.0,
            max_scale_actions=5,
        )
        ctx = self._ctx(state=SacredEelState.SEEK_SPOT, action_code=ACTION_FISHING)
        SacredEelMachine(ctx).step()
        self.assertEqual(ctx.state, SacredEelState.FISHING)
        self.assertEqual(spots_called, [])

    def test_fishing_stays_when_no_ui(self):
        ctx = self._ctx(state=SacredEelState.FISHING, action_code=ACTION_NO_UI, eel_count=0)
        SacredEelMachine(ctx).step()
        self.assertEqual(ctx.state, SacredEelState.FISHING)

    def test_wait_for_fishing_after_click(self):
        clicked = [False]
        pre_click_polls = [0]
        post_click_polls = [0]

        def get_action(refresh=False):
            if not clicked[0]:
                pre_click_polls[0] += 1
                return ACTION_IDLE if pre_click_polls[0] >= 1 else ACTION_NO_UI
            post_click_polls[0] += 1
            return ACTION_FISHING if post_click_polls[0] >= 2 else ACTION_NO_UI

        bot_e = MagicMock()
        bot_e.get_action_text_robust.side_effect = get_action
        bot_e._eel_count = 0
        bot_e._inv_slots = 0
        bot_e._inv_full = False
        bot_e._spots = [[100, 100]]
        bot_a = MagicMock()

        def on_click(*_a, **_k):
            clicked[0] = True

        bot_a.click_at.side_effect = on_click
        ctx = SacredEelContext(
            client=MagicMock(), bot_e=bot_e, bot_a=bot_a, action_code=ACTION_NO_UI
        )
        ctx.state = SacredEelState.SEEK_SPOT
        SacredEelMachine(ctx).step()
        self.assertEqual(ctx.state, SacredEelState.FISHING)
        bot_a.click_at.assert_called_once()

    def test_seek_spot_waits_for_red_not_no_ui(self):
        spots_called = []
        polls = [0]

        def track_spots(_e):
            spots_called.append(1)
            return []

        def get_action(refresh=False):
            polls[0] += 1
            return ACTION_IDLE if polls[0] >= 2 else ACTION_NO_UI

        configure_fsm(
            sleep_fn=lambda _s: None,
            stop_check=lambda: False,
            count_eels=lambda _e: 0,
            inv_slots=lambda _e: 10,
            inv_full=lambda _e: False,
            locate_spots=track_spots,
            spot_templates=["spot.png"],
            full_eel_count=22,
            inv_slot_count=28,
            max_spot_pan_attempts=0,
            max_spot_walk_attempts=0,
            scale_tick_delay_s=0.0,
            max_scale_actions=5,
        )
        ctx = self._ctx(state=SacredEelState.SEEK_SPOT, action_code=ACTION_NO_UI)
        ctx.bot_e.get_action_text_robust.side_effect = get_action
        SacredEelMachine(ctx).step()
        self.assertEqual(len(spots_called), 1)

    def test_action_helpers(self):
        self.assertTrue(is_action_fishing(ACTION_FISHING))
        self.assertTrue(is_action_idle(ACTION_IDLE))
        self.assertTrue(should_seek_fishing_spot(ACTION_IDLE))
        self.assertFalse(should_seek_fishing_spot(ACTION_NO_UI))
        self.assertFalse(is_action_fishing(ACTION_NO_UI))

    def test_scaling_completes_to_seek_spot(self):
        ctx = self._ctx(state=SacredEelState.SCALING, eel_count=3, action_code=2)
        ctx.scale_phase = ScalePhase.CLICK
        m = SacredEelMachine(ctx)
        m.step()  # CLICK → WAIT_TICK
        self.assertEqual(ctx.scale_phase, ScalePhase.WAIT_TICK)
        ctx.bot_e._eel_count = 0
        m.step()  # WAIT_TICK → SEEK_SPOT
        self.assertEqual(ctx.state, SacredEelState.SEEK_SPOT)


if __name__ == "__main__":
    unittest.main()
