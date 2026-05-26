"""
Agent runtime for Exodia: ``BotBrain`` policies, declarative ``BrainCommand`` types,
and ``ExodiaHarness`` tick loop.

**Agent = brain.** Pilots (LLM tools, planners, scripts) implement ``BotBrain`` or
``CallbackBrain``. ``ExodiaHarness`` is the body: refresh sensors, build
``Observation``, call ``brain.decide``, execute ``BrainCommand`` objects via
``bot_actions``, verify outcomes, and log.

**BrainCommand index** (see dataclass docstrings): ``CmdWait``, ``CmdWaitTicks``,
``CmdLog``, ``CmdClickImage``, ``CmdClickColor``, ``CmdUseItemOn``.

Typical loop: ``create_harness(...)`` or manual wiring, then
``harness.refresh_geometry()`` + ``harness.step()`` — or queue ``HarnessStepper.tick``
from ``BotLegs``.
"""
from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import bot_actions as Actions
import constants
from bot_action_log import ActionLogger, TickLogRecord, command_to_dict
from bot_gamestate import GameState, build_game_state, game_state_to_dict
from bot_verify import ActionVerifyResult, verify_action

if TYPE_CHECKING:
    import bot_arms as Arms
    import bot_client as Client
    import bot_eyes as Eyes
    from bot_capture import CapturePipeline
    from bot_session import SessionRecorder
    from bot_stream import FramePublisher

Rect = List[int]

__all__ = [
    "Observation",
    "StepResult",
    "CmdWait",
    "CmdWaitTicks",
    "CmdLog",
    "CmdClickImage",
    "CmdClickColor",
    "CmdUseItemOn",
    "BrainCommand",
    "BotBrain",
    "IdleBrain",
    "CallbackBrain",
    "ExodiaHarness",
    "HarnessStepper",
    "create_harness",
]


@dataclass
class Observation:
    """One timestep of sensory summary for policy code or an external agent."""

    tick: int
    client_rect: Rect
    action_text_code: Any
    action_line_text: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    observation: Observation
    commands: Tuple[BrainCommand, ...] = ()
    skipped_agent: bool = False
    verify: Optional[ActionVerifyResult] = None
    game_state_before: Optional[GameState] = None
    game_state_after: Optional[GameState] = None


@dataclass(frozen=True)
class CmdWait:
    """Wall-clock sleep for ``seconds``."""

    seconds: float


@dataclass(frozen=True)
class CmdWaitTicks:
    """Sleep ``num`` OSRS ticks (× ``constants.OSRS_TICK_S``) plus ``adj`` seconds."""

    num: int
    adj: float = 0.0


@dataclass(frozen=True)
class CmdLog:
    """Print ``message`` and include it in the tick action log."""

    message: str


@dataclass(frozen=True)
class CmdClickImage:
    """Click ``template``; ``inv=True`` searches inventory. → ``click_on_image``."""

    template: str
    inv: bool = False
    refresh: bool = True


@dataclass(frozen=True)
class CmdClickColor:
    """Click nearest ``color`` in client view (± ``range``). → ``click_on_color``."""

    color: Tuple[int, int, int]
    range: int = 20
    refresh: bool = True


@dataclass(frozen=True)
class CmdUseItemOn:
    """Use inventory template ``target_1`` on ``target_2`` (closest dest). → ``use_x_on_y``."""

    target_1: str
    target_2: str


BrainCommand = Union[
    CmdWait,
    CmdWaitTicks,
    CmdLog,
    CmdClickImage,
    CmdClickColor,
    CmdUseItemOn,
]


class BotBrain(ABC):
    @abstractmethod
    def decide(self, observation: Observation, harness: Any) -> Sequence[BrainCommand]:
        """
        Return commands the harness will execute in order.

        ``harness`` is ``ExodiaHarness`` (typed as ``Any`` to keep type hints simple).
        You may also call ``harness.click_image(...)`` or use ``harness.eyes`` /
        ``harness.arms`` inside ``decide`` for imperative control.
        """


class IdleBrain(BotBrain):
    """No-op policy until you attach a real agent."""

    def decide(self, observation: Observation, harness: Any) -> Sequence[BrainCommand]:
        return ()


class CallbackBrain(BotBrain):
    """
    Delegate to ``fn(observation, harness) -> Optional[Sequence[BrainCommand]]``.
    Return None or () to do nothing this tick.
    """

    def __init__(self, fn: Callable[..., Optional[Sequence[BrainCommand]]]):
        self._fn = fn

    def decide(self, observation: Observation, harness: Any) -> Sequence[BrainCommand]:
        out = self._fn(observation, harness)
        if not out:
            return ()
        return tuple(out)


class ExodiaHarness:
    def __init__(
        self,
        client: "Client.ClientWindow",
        eyes: "Eyes.BotEyes",
        arms: "Arms.BotArms",
        brain: Optional[BotBrain] = None,
        enable_significance_gate: bool = True,
        action_logger: Optional[ActionLogger] = None,
        frame_publisher: Optional["FramePublisher"] = None,
        session_recorder: Optional["SessionRecorder"] = None,
        session_dir: Optional[Path] = None,
        capture_pipeline: Optional["CapturePipeline"] = None,
    ):
        self.client = client
        self.eyes = eyes
        self.arms = arms
        self.brain = brain if brain is not None else IdleBrain()
        self._tick = 0
        self.enable_significance_gate = enable_significance_gate
        self.significance_max_skips = int(os.environ.get("EXODIA_SIGNIFICANCE_MAX_SKIPS", "0") or "0")
        self._last_observation_signature: Optional[str] = None
        self._stall_skip_count = 0
        self._force_next_agent_invocation = False
        self.action_logger = action_logger
        self.frame_publisher = frame_publisher
        self.session_recorder = session_recorder
        self.session_dir = session_dir
        self._session_run_id: Optional[str] = None
        self.capture_pipeline = capture_pipeline

    def refresh_geometry(self) -> None:
        """Refresh window rect, pipeline geometry, and eyes frame from buffer."""
        Actions.sync_window(self.client, self.eyes)
        if self.capture_pipeline is not None and self.client.win_rect is not None:
            inv = self.eyes.inventory_rect
            chat = self.eyes.chat_rect
            self.capture_pipeline.set_geometry(
                list(self.client.win_rect),
                inventory_rect=list(inv) if inv else None,
                chat_rect=list(chat) if chat else None,
            )
        self.eyes.capture_frame()

    def force_agent_next_step(self) -> None:
        """Next ``step()`` will run ``brain.decide`` even if the observation signature is unchanged."""
        self._force_next_agent_invocation = True

    def _observation_signature(self, observation: Observation) -> str:
        gs = observation.meta.get("game_state") or {}
        payload = {
            "action": observation.action_text_code,
            "action_line": observation.action_line_text,
            "pe": observation.meta.get("perception_envelope"),
            "inv_count": gs.get("inventory_item_count"),
        }
        return json.dumps(payload, sort_keys=True, default=str)

    def observe(self, *, frame_paths: Optional[Dict[str, str]] = None) -> Observation:
        """Question: What does the bot perceive right now (one tick snapshot)?

        Builds ``Observation`` with game state, OCR meta, and optional capture tracks.
        Increments the harness tick counter. Call ``refresh_geometry()`` first unless
        invoked from ``step()``.
        """
        self._tick += 1
        if self.frame_publisher is not None:
            self.frame_publisher.publish_from_eyes(self.eyes)

        gs = build_game_state(self.eyes, self._tick, frame_paths=frame_paths or {})
        rect = list(self.eyes.client_rect) if self.eyes.client_rect is not None else []
        meta: Dict[str, Any] = {}
        if self.eyes.perception_envelope is not None:
            meta["perception_envelope"] = dict(self.eyes.perception_envelope)
        meta["ocr_action_strip"] = self.eyes.ocr_action_text_roi()
        meta["ocr_dialogue"] = self.eyes.ocr_dialogue_roi()
        meta["game_state"] = game_state_to_dict(gs)
        if frame_paths:
            meta["frame_paths"] = dict(frame_paths)

        if self.capture_pipeline is not None:
            ps = self.capture_pipeline.cache.snapshot()
            meta["tracks"] = list(ps.tracks)
            meta["motion_magnitude"] = ps.motion_magnitude
            meta["capture_seq"] = self.capture_pipeline.buffer.seq
            meta["processed_seq"] = ps.processed_seq
            meta["seq_lag"] = self.capture_pipeline.buffer.seq - ps.processed_seq
            meta["capture_fps"] = self.capture_pipeline.capture_fps
            meta["vision_fps"] = self.capture_pipeline.vision_fps

        return Observation(
            tick=self._tick,
            client_rect=rect,
            action_text_code=gs.action_text_code,
            action_line_text=gs.action_line_text,
            meta=meta,
        )

    def apply_commands(self, commands: Sequence[BrainCommand]) -> List[str]:
        """Question: How do I run declarative brain commands without a full agent tick?

        Maps each ``BrainCommand`` to ``bot_actions`` (or sleep/log). Returns
        ``CmdLog`` messages for the action log.
        """
        log_messages: List[str] = []
        for cmd in commands:
            if isinstance(cmd, CmdWait):
                if cmd.seconds > 0:
                    time.sleep(cmd.seconds)
            elif isinstance(cmd, CmdWaitTicks):
                if cmd.num > 0:
                    delay = cmd.num * constants.OSRS_TICK_S + cmd.adj
                    time.sleep(max(0.0, delay))
            elif isinstance(cmd, CmdLog):
                print(cmd.message)
                log_messages.append(cmd.message)
            elif isinstance(cmd, CmdClickImage):
                Actions.click_on_image(
                    self.client, self.arms, self.eyes, cmd.template,
                    refresh=cmd.refresh,
                    inv=cmd.inv,
                )
            elif isinstance(cmd, CmdClickColor):
                Actions.click_on_color(
                    self.client, self.arms, self.eyes,
                    color=cmd.color, range=cmd.range, refresh=cmd.refresh,
                )
            elif isinstance(cmd, CmdUseItemOn):
                result = Actions.use_x_on_y(
                    self.eyes, self.arms, cmd.target_1, cmd.target_2,
                    client=self.client,
                )
                if not result.ok:
                    print(
                        "use_x_on_y failed: %s (%s)"
                        % (result.reason, result.missing_item or "unknown")
                    )
        return log_messages

    def step(self, refresh: bool = True, force_agent: bool = False) -> StepResult:
        """Question: How do I run one full agent tick (observe → decide → act → verify)?

        Refreshes geometry, builds observation, optionally skips brain when the
        observation signature is unchanged, runs ``brain.decide``, applies commands,
        verifies, and logs. Returns ``StepResult`` with before/after game state.
        """
        if refresh:
            self.refresh_geometry()

        observation = self.observe()
        gs_before = build_game_state(self.eyes, observation.tick)
        sig = self._observation_signature(observation)

        skip = False
        if self.enable_significance_gate and not force_agent and not self._force_next_agent_invocation:
            if self._last_observation_signature is not None and sig == self._last_observation_signature:
                skip = True

        if skip and self.significance_max_skips > 0:
            self._stall_skip_count += 1
            if self._stall_skip_count >= self.significance_max_skips:
                skip = False
                self._stall_skip_count = 0
        elif not skip:
            self._stall_skip_count = 0

        cmds: Tuple[BrainCommand, ...] = ()
        log_messages: List[str] = []
        verify_result: Optional[ActionVerifyResult] = None
        gs_after: Optional[GameState] = None

        if skip:
            observation.meta["skipped_agent"] = True
            self._last_observation_signature = sig
            result = StepResult(
                observation=observation,
                commands=cmds,
                skipped_agent=True,
                game_state_before=gs_before,
            )
            self._log_step(result, log_messages)
            return result

        observation.meta.pop("skipped_agent", None)
        cmds = tuple(self.brain.decide(observation, self))
        log_messages = self.apply_commands(cmds)

        self.refresh_geometry()
        gs_after = build_game_state(self.eyes, observation.tick)
        verify_result = verify_action(gs_before, gs_after)

        self._last_observation_signature = sig
        self._force_next_agent_invocation = False

        result = StepResult(
            observation=observation,
            commands=cmds,
            skipped_agent=False,
            verify=verify_result,
            game_state_before=gs_before,
            game_state_after=gs_after,
        )
        self._log_step(result, log_messages)
        if self.session_recorder is not None:
            cmd_dicts = [command_to_dict(c) for c in cmds]
            verify_dict = asdict(verify_result) if verify_result else None
            obs_dict = {
                "tick": observation.tick,
                "client_rect": observation.client_rect,
                "action_text_code": observation.action_text_code,
                "action_line_text": observation.action_line_text,
                "meta": observation.meta,
            }
            self.session_recorder.record_tick(
                self.eyes, obs_dict, cmd_dicts, verify_dict
            )
        return result

    def _log_step(self, result: StepResult, log_messages: List[str]) -> None:
        if self.action_logger is None:
            return
        gs = result.game_state_before or build_game_state(self.eyes, result.observation.tick)
        gs_summary = {
            "action_busy": gs.action_busy,
            "action_line_text": gs.action_line_text,
            "action_text_code": gs.action_text_code,
            "inventory_item_count": gs.inventory_item_count,
            "inventory_calibrated": gs.inventory_calibrated,
        }
        verify_dict = asdict(result.verify) if result.verify else None
        record = TickLogRecord(
            tick=result.observation.tick,
            skipped_agent=result.skipped_agent,
            game_state=gs_summary,
            commands=[command_to_dict(c) for c in result.commands],
            verify=verify_dict,
            logs=log_messages,
        )
        self.action_logger.log_tick(record)

    def click_image(self, target: str, refresh: bool = True) -> None:
        Actions.click_on_image(self.client, self.arms, self.eyes, target, refresh=refresh)

    def click_color(self, *args, **kwargs) -> None:
        Actions.click_on_color(self.client, self.arms, self.eyes, *args, **kwargs)

    def use_item_on(self, target_1: str, target_2: str) -> None:
        """Question: How do I imperatively use inventory item X on Y inside decide()?

        Delegates to ``Actions.use_x_on_y`` (source template, dest template).
        """
        Actions.use_x_on_y(
            self.eyes, self.arms, target_1, target_2, client=self.client,
        )


class HarnessStepper:
    """Question: How do I drive harness ticks from ``BotLegs``?

    Queue-friendly wrapper for ``BotLegs.add_task(stepper, 'tick')``. Each ``tick()``
    runs ``harness.step(refresh=True)`` and stores the result in ``last_result``.
    """

    def __init__(self, harness: ExodiaHarness):
        self._harness = harness
        self.last_result: Optional[StepResult] = None

    def tick(self) -> None:
        """Question: How do I advance the harness one step from a legs cycle?"""
        self.last_result = self._harness.step(refresh=True)


def create_harness(
    DEBUG: bool = False,
    brain: Optional[BotBrain] = None,
    enable_significance_gate: bool = True,
    action_logger: Optional[ActionLogger] = None,
    frame_publisher: Optional["FramePublisher"] = None,
    session_recorder: Optional["SessionRecorder"] = None,
    capture_pipeline: Optional["CapturePipeline"] = None,
    win_rect: Optional[Rect] = None,
) -> ExodiaHarness:
    """Question: How do I wire up ``ExodiaHarness`` in one call?

    Runs ``Actions.bot_init`` and attaches optional brain, logger, frame publisher,
    session recorder, and capture pipeline.
    """
    client, eyes, arms = Actions.bot_init(DEBUG=DEBUG, win_rect=win_rect)
    return ExodiaHarness(
        client, eyes, arms,
        brain=brain,
        enable_significance_gate=enable_significance_gate,
        action_logger=action_logger,
        frame_publisher=frame_publisher,
        session_recorder=session_recorder,
        capture_pipeline=capture_pipeline,
    )
