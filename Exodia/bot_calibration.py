"""
Startup health checks before entering the agent harness loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import bot_client as Client
    import bot_eyes as Eyes

__all__ = ["CalibrationReport", "run_calibration"]


@dataclass
class CalibrationReport:
    ok: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    capture_backend: str = ""
    client_rect: Optional[List[int]] = None
    inventory_calibrated: bool = False
    capture_mean_pixel: float = 0.0


def run_calibration(
    client: "Client.ClientWindow",
    eyes: "Eyes.BotEyes",
    *,
    ui_icons_path: Path = Path("images/ui_icons.png"),
) -> CalibrationReport:
    """Run startup checks; returns report with ``ok=False`` on hard failures."""
    report = CalibrationReport(ok=True)

    try:
        client.update()
    except Exception as exc:
        report.ok = False
        report.errors.append("ClientWindow update failed: %s" % exc)
        return report

    eyes.setRect(client.win_rect)
    report.client_rect = list(client.win_rect) if client.win_rect else None

    frame = eyes.curr_client_unmasked if eyes.curr_client_unmasked is not None else eyes.curr_client
    if frame is None:
        report.ok = False
        report.errors.append("Capture returned no frame — check EXODIA_CAPTURE_BACKEND")
        return report

    report.capture_mean_pixel = float(frame.mean())
    if report.capture_mean_pixel < 1.0:
        report.ok = False
        report.errors.append(
            "Capture appears blank (mean pixel %.2f) — try EXODIA_CAPTURE_BACKEND=wsl_ps on WSLg"
            % report.capture_mean_pixel
        )

    pe = eyes.perception_envelope or {}
    report.capture_backend = str(pe.get("capture_backend") or "")
    report.inventory_calibrated = bool(pe.get("inventory_rect_client_local"))

    if not ui_icons_path.is_file():
        report.warnings.append(
            "Missing %s — inventory template match disabled" % ui_icons_path
        )
    elif not report.inventory_calibrated:
        report.warnings.append(
            "Inventory template present but no match — check ui_icons.png or client layout"
        )

    return report
