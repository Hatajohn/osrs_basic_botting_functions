"""
Pure query helpers over ``ClientTextSnapshot`` / ``ColoredTextSpan``.

Bots filter the shared text snapshot by color, substring, regex, or screen region
instead of running per-script ROI OCR. Fishing ``action_code`` derivation lives in
``infer_action_code_from_snapshot`` (colored OCR first; template fusion in
``bot_action_vision`` later).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, List, Optional, Pattern, Sequence, Tuple, Union

from bot_action_ui import ACTION_FISHING, ACTION_IDLE, ACTION_NO_UI
from bot_client_text import Bbox, ClientTextSnapshot, ColoredTextSpan, text_min_conf

if TYPE_CHECKING:
    from bot_perception_types import PerceptionTick

Rect = Sequence[int]

__all__ = [
    "ActionInference",
    "find_spans",
    "first_match",
    "fishing_action_label",
    "fishing_relevant_spans",
    "has_green_fishing_in_rect",
    "_infer_green_fishing_in_rect",
    "has_span",
    "infer_action_code_from_snapshot",
    "join_text",
    "perception_tick_to_client_text",
    "resolve_fishing_action_from_tick",
    "spans_in_rect",
    "stream_fishing_use_text",
]


@dataclass(frozen=True)
class ActionInference:
    action_code: int
    action_line_text: Optional[str]
    action_line_color: Optional[str]
    detection_source: str


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def default_fuzzy_threshold() -> float:
    return _env_float("EXODIA_TEXT_FISHING_FUZZY_THRESHOLD", 0.72)


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def stream_fishing_use_text() -> bool:
    """When true, stream fishing bots derive action state from OCR text first."""
    return _env_bool("EXODIA_BASIC_FISHING_USE_TEXT", True)


def fishing_action_label(action_code: int) -> str:
    return {
        ACTION_FISHING: "Fishing",
        ACTION_IDLE: "Not fishing",
        ACTION_NO_UI: "no fishing UI",
    }.get(action_code, "action %d" % action_code)


def perception_tick_to_client_text(tick: "PerceptionTick") -> ClientTextSnapshot:
    """Adapt stream ``TextSnapshot`` for query helpers."""
    text = tick.text
    spans = tuple(
        ColoredTextSpan(
            text=s.text,
            color=s.color,
            bbox=s.bbox,
            conf=s.conf,
            source="stream",
        )
        for s in text.spans
    )
    return ClientTextSnapshot(
        spans=spans,
        processed_seq=text.seq,
        capture_seq=text.capture_seq,
        client_size=text.client_size,
        elapsed_ms=text.scan_ms,
    )


def _frame_size_for_tick(tick: "PerceptionTick") -> Tuple[int, int]:
    tw, th = tick.text.client_size
    if tw > 0 and th > 0:
        return int(tw), int(th)
    rect = tick.client_rect
    if rect is not None and len(rect) == 4:
        return int(rect[2]), int(rect[3])
    return 0, 0


def _pad_rect(rect: Sequence[int], frame_w: int, frame_h: int, *, pad_x: int = 24, pad_y: int = 12) -> List[int]:
    x, y, w, h = (int(rect[i]) for i in range(4))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(frame_w, x + w + pad_x)
    y2 = min(frame_h, y + h + pad_y)
    return [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]


def _strip_rect_for_tick(tick: "PerceptionTick") -> Optional[List[int]]:
    action = tick.action
    fw, fh = _frame_size_for_tick(tick)
    if action.action_strip_rect is not None and len(action.action_strip_rect) == 4:
        base = [int(v) for v in action.action_strip_rect]
        if fw > 0 and fh > 0:
            return _pad_rect(base, fw, fh)
        return base
    inv = tick.inventory.rect
    rect = tick.client_rect
    if inv is not None and len(inv) == 4 and fw > 0 and fh > 0:
        from bot_eyes import resolve_action_strip_roi_client

        ax, ay, aw, ah = resolve_action_strip_roi_client(
            inventory_rect=list(inv),
            frame_w=fw,
            frame_h=fh,
        )
        return _pad_rect([ax, ay, aw, ah], fw, fh)
    if fw > 0 and fh > 0:
        return [
            max(0, int(fw * 0.45)),
            max(0, int(fh * 0.50)),
            max(200, int(fw * 0.55)),
            max(200, int(fh * 0.48)),
        ]
    return None


def _bottom_right_search_rect(frame_w: int, frame_h: int) -> List[int]:
    return [
        max(0, int(frame_w * 0.40)),
        max(0, int(frame_h * 0.45)),
        max(200, int(frame_w * 0.60)),
        max(200, int(frame_h * 0.52)),
    ]


def _inference_from_action_snapshot(action: "object") -> Optional[ActionInference]:
    """Use stream ``perception.action`` OCR line when span list is empty or stale."""
    code = int(getattr(action, "action_code", ACTION_NO_UI))
    line = getattr(action, "action_line_text", None) or ""
    color = getattr(action, "action_line_color", None)
    source = getattr(action, "detection_source", None) or "stream_action"
    norm = _normalize_text(line)
    fuzzy = default_fuzzy_threshold()

    if source in ("colored_ocr", "template", "contour") and code in (ACTION_FISHING, ACTION_IDLE):
        return ActionInference(
            action_code=code,
            action_line_text=line.strip() or None,
            action_line_color=color,
            detection_source=source,
        )
    if norm:
        if re.search(r"\bnot\b", norm) and _fuzzy_contains(line, "fish", threshold=fuzzy):
            return ActionInference(
                action_code=ACTION_IDLE,
                action_line_text=line.strip(),
                action_line_color=color or "red",
                detection_source=source or "stream_action_line",
            )
        if _fuzzy_contains(line, "fishing", threshold=fuzzy) and not re.search(r"\bnot\b", norm):
            return ActionInference(
                action_code=ACTION_FISHING,
                action_line_text=line.strip(),
                action_line_color=color or "green",
                detection_source=source or "stream_action_line",
            )
    return None


def _infer_green_fishing_in_rect(
    snapshot: ClientTextSnapshot,
    rect: Optional[Rect],
    *,
    label: str = "strip",
) -> Optional[ActionInference]:
    """
    Positive signal only: green ``Fishing`` in ``rect`` (or full frame when ``rect`` is None).

    Red NOT fishing is ignored — no green and no text both mean not fishing.
    """
    fuzzy_threshold = default_fuzzy_threshold()
    min_conf = text_min_conf()
    if rect is not None and len(rect) != 4:
        return None
    if rect is None:
        subset = tuple(s for s in snapshot.spans if s.conf >= min_conf)
    else:
        subset = tuple(s for s in spans_in_rect(snapshot, rect) if s.conf >= min_conf)
    if not subset:
        return None

    green_spans = [s for s in subset if s.color.lower() == "green"]
    green_text = join_text(green_spans)
    if green_text and _joined_strip_matches_fishing(green_text, fuzzy_threshold=fuzzy_threshold):
        return ActionInference(
            action_code=ACTION_FISHING,
            action_line_text=green_text[:80],
            action_line_color="green",
            detection_source="colored_ocr_%s" % label,
        )
    green_hits = tuple(
        s for s in subset if _is_green_fishing_span(s, fuzzy_threshold=fuzzy_threshold)
    )
    best_green = _best_span(green_hits)
    if best_green is not None:
        return ActionInference(
            action_code=ACTION_FISHING,
            action_line_text=best_green.text,
            action_line_color=best_green.color,
            detection_source="colored_ocr_%s" % label,
        )

    any_text = join_text(subset)
    norm = _normalize_text(any_text)
    if norm and _fuzzy_contains(any_text, "fishing", threshold=fuzzy_threshold) and not re.search(
        r"\bnot\b", norm
    ):
        return ActionInference(
            action_code=ACTION_FISHING,
            action_line_text=any_text[:80],
            action_line_color="unknown",
            detection_source="keyword_%s" % label,
        )
    return None


def _infer_fishing_from_spans(
    snapshot: ClientTextSnapshot,
    *,
    strip_rect: Optional[Rect] = None,
    search_rect: Optional[Rect] = None,
) -> Optional[ActionInference]:
    """Find green ``Fishing`` in strip, search band, then full frame."""
    for label, rect in (
        ("action_strip", strip_rect),
        ("search_band", search_rect),
        ("full_frame", None),
    ):
        if rect is not None and len(rect) != 4:
            continue
        hit = _infer_green_fishing_in_rect(snapshot, rect, label=label)
        if hit is not None:
            return hit
    return None


def resolve_fishing_action_from_tick(
    tick: "PerceptionTick",
    *,
    use_text: Optional[bool] = None,
) -> ActionInference:
    """
    Read ``tick.text`` (full OCR cache) and look for green ``Fishing`` only.

    Green in the action strip → fishing. No green in strip when other text exists
    → not fishing (``ACTION_IDLE``). Red spans in the cache are ignored. Falls
    back to stream ``perception.action`` when text is disabled or unavailable.
    """
    if use_text is None:
        use_text = stream_fishing_use_text()
    action = tick.action
    fallback = ActionInference(
        action_code=int(action.action_code),
        action_line_text=action.action_line_text,
        action_line_color=action.action_line_color,
        detection_source=action.detection_source or "stream_action",
    )
    action_inf = _inference_from_action_snapshot(action)
    spans = tick.text.spans
    has_span_data = len(spans) > 0

    if not use_text:
        return action_inf or fallback

    if not has_span_data:
        return action_inf or fallback

    strip_rect = _strip_rect_for_tick(tick)
    fw, fh = _frame_size_for_tick(tick)
    search_rect = _bottom_right_search_rect(fw, fh) if fw > 0 and fh > 0 else None

    client = perception_tick_to_client_text(tick)

    if strip_rect is not None:
        text_inf = _infer_green_fishing_in_rect(
            client, strip_rect, label="action_strip"
        )
        if text_inf is not None:
            return text_inf
        min_conf = text_min_conf()
        if any(s.conf >= min_conf for s in spans_in_rect(client, strip_rect)):
            return ActionInference(
                action_code=ACTION_IDLE,
                action_line_text=None,
                action_line_color=None,
                detection_source="no_green_fishing",
            )
        return action_inf or fallback

    if search_rect is not None:
        text_inf = _infer_green_fishing_in_rect(
            client, search_rect, label="search_band"
        )
        if text_inf is not None:
            return text_inf

    text_inf = _infer_green_fishing_in_rect(client, None, label="full_frame")
    if text_inf is not None:
        return text_inf

    return action_inf or fallback


def _fuzzy_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _fuzzy_contains(text: str, phrase: str, *, threshold: float) -> bool:
    norm = _normalize_text(text)
    phrase_n = _normalize_text(phrase)
    if not phrase_n:
        return False
    if phrase_n in norm:
        return True
    words = norm.split()
    if not words:
        return False
    phrase_words = phrase_n.split()
    if len(phrase_words) == 1:
        for word in words:
            if _fuzzy_ratio(word, phrase_n) >= threshold:
                return True
        if len(norm) <= len(phrase_n) + 6:
            return _fuzzy_ratio(norm, phrase_n) >= threshold
        return False
    n = len(phrase_words)
    for i in range(len(words) - n + 1):
        window = " ".join(words[i : i + n])
        if _fuzzy_ratio(window, phrase_n) >= threshold:
            return True
    return _fuzzy_ratio(norm, phrase_n) >= threshold


def _bbox_intersects(a: Bbox, rect: Rect) -> bool:
    ax, ay, aw, ah = (int(a[i]) for i in range(4))
    rx, ry, rw, rh = (int(rect[i]) for i in range(4))
    ax2, ay2 = ax + aw, ay + ah
    rx2, ry2 = rx + rw, ry + rh
    ix1 = max(ax, rx)
    iy1 = max(ay, ry)
    ix2 = min(ax2, rx2)
    iy2 = min(ay2, ry2)
    return ix2 > ix1 and iy2 > iy1


def spans_in_rect(snapshot: ClientTextSnapshot, rect: Rect) -> Tuple[ColoredTextSpan, ...]:
    if rect is None or len(rect) != 4:
        return ()
    return tuple(span for span in snapshot.spans if _bbox_intersects(span.bbox, rect))


def find_spans(
    snapshot: ClientTextSnapshot,
    *,
    color: Optional[str] = None,
    contains: Optional[str] = None,
    regex: Optional[Union[str, Pattern[str]]] = None,
    min_conf: Optional[float] = None,
    rect: Optional[Rect] = None,
) -> Tuple[ColoredTextSpan, ...]:
    spans = snapshot.spans
    if rect is not None:
        allowed = set(spans_in_rect(snapshot, rect))
        spans = tuple(s for s in spans if s in allowed)
    conf_floor = text_min_conf() if min_conf is None else float(min_conf)
    color_key = color.strip().lower() if color else None
    contains_norm = _normalize_text(contains) if contains else None
    pattern: Optional[Pattern[str]] = None
    if regex is not None:
        pattern = regex if isinstance(regex, re.Pattern) else re.compile(str(regex), re.IGNORECASE)
    out: List[ColoredTextSpan] = []
    for span in spans:
        if span.conf < conf_floor:
            continue
        if color_key is not None and span.color.lower() != color_key:
            continue
        if contains_norm is not None and contains_norm not in _normalize_text(span.text):
            continue
        if pattern is not None and pattern.search(span.text) is None:
            continue
        out.append(span)
    return tuple(out)


def first_match(
    snapshot: ClientTextSnapshot,
    *,
    color: Optional[str] = None,
    contains: Optional[str] = None,
    regex: Optional[Union[str, Pattern[str]]] = None,
    min_conf: Optional[float] = None,
    rect: Optional[Rect] = None,
) -> Optional[ColoredTextSpan]:
    matches = find_spans(
        snapshot,
        color=color,
        contains=contains,
        regex=regex,
        min_conf=min_conf,
        rect=rect,
    )
    return matches[0] if matches else None


def has_span(
    snapshot: ClientTextSnapshot,
    *,
    color: Optional[str] = None,
    contains: Optional[str] = None,
    regex: Optional[Union[str, Pattern[str]]] = None,
    min_conf: Optional[float] = None,
    rect: Optional[Rect] = None,
) -> bool:
    return first_match(
        snapshot,
        color=color,
        contains=contains,
        regex=regex,
        min_conf=min_conf,
        rect=rect,
    ) is not None


def join_text(spans: Sequence[ColoredTextSpan], sep: str = " ") -> str:
    parts = [s.text.strip() for s in spans if s.text and s.text.strip()]
    return sep.join(parts)


def _is_green_fishing_span(span: ColoredTextSpan, *, fuzzy_threshold: float) -> bool:
    if span.color.lower() != "green":
        return False
    norm = _normalize_text(span.text)
    if re.search(r"\bnot\b", norm):
        return False
    return _fuzzy_contains(span.text, "fishing", threshold=fuzzy_threshold)


def has_green_fishing_in_rect(
    snapshot: ClientTextSnapshot,
    rect: Rect,
    *,
    fuzzy_threshold: Optional[float] = None,
) -> bool:
    """True when the strip/search ROI contains green ``Fishing`` OCR."""
    if rect is None or len(rect) != 4:
        return False
    fuzzy = default_fuzzy_threshold() if fuzzy_threshold is None else fuzzy_threshold
    min_conf = text_min_conf()
    for span in spans_in_rect(snapshot, rect):
        if span.conf < min_conf:
            continue
        if _is_green_fishing_span(span, fuzzy_threshold=fuzzy):
            return True
    return False


def _is_red_not_fishing_span(span: ColoredTextSpan, *, fuzzy_threshold: float) -> bool:
    if span.color.lower() != "red":
        return False
    norm = _normalize_text(span.text)
    if not re.search(r"\bnot\b", norm):
        return False
    return _fuzzy_contains(span.text, "fish", threshold=fuzzy_threshold)


def _best_span(candidates: Sequence[ColoredTextSpan]) -> Optional[ColoredTextSpan]:
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s.conf, s.bbox[1], s.bbox[0]))


def _joined_strip_matches_idle(red_text: str, *, fuzzy_threshold: float) -> bool:
    norm = _normalize_text(red_text)
    if not norm or not re.search(r"\bnot\b", norm):
        return False
    return _fuzzy_contains(red_text, "fish", threshold=fuzzy_threshold)


def _joined_strip_matches_fishing(green_text: str, *, fuzzy_threshold: float) -> bool:
    norm = _normalize_text(green_text)
    if not norm or re.search(r"\bnot\b", norm):
        return False
    return _fuzzy_contains(green_text, "fishing", threshold=fuzzy_threshold)


def fishing_relevant_spans(
    spans: Sequence[ColoredTextSpan],
    *,
    fuzzy_threshold: Optional[float] = None,
) -> Tuple[ColoredTextSpan, ...]:
    """Green ``Fishing`` spans only (meta / highlights)."""
    fuzzy = default_fuzzy_threshold() if fuzzy_threshold is None else fuzzy_threshold
    min_conf = text_min_conf()
    return tuple(
        span
        for span in spans
        if span.conf >= min_conf
        and _is_green_fishing_span(span, fuzzy_threshold=fuzzy)
    )


def infer_action_code_from_snapshot(
    snapshot: ClientTextSnapshot,
    *,
    strip_rect: Rect,
    template_threshold: Optional[float] = None,
) -> ActionInference:
    """
    Green ``Fishing`` in the action strip → fishing; otherwise not fishing or no UI.

    Red text is not consulted. ``template_threshold`` is reserved for ``bot_action_vision``.
    """
    _ = template_threshold
    hit = _infer_green_fishing_in_rect(snapshot, strip_rect, label="action_strip")
    if hit is not None:
        return hit
    min_conf = text_min_conf()
    if any(s.conf >= min_conf for s in spans_in_rect(snapshot, strip_rect)):
        return ActionInference(
            action_code=ACTION_IDLE,
            action_line_text=None,
            action_line_color=None,
            detection_source="no_green_fishing",
        )
    return ActionInference(
        action_code=ACTION_NO_UI,
        action_line_text=None,
        action_line_color=None,
        detection_source="none",
    )
