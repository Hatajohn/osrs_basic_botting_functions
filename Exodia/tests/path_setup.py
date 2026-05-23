"""Insert Exodia project root on ``sys.path`` (import before project modules)."""
from __future__ import annotations

import sys
from pathlib import Path

EXODIA_ROOT = Path(__file__).resolve().parent.parent


def ensure() -> Path:
    root = str(EXODIA_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return EXODIA_ROOT


ensure()
