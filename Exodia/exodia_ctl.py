#!/usr/bin/env python3
"""Send live commands to a running Exodia script (see ``bot_runtime.py``)."""
from bot_runtime import exodia_ctl_main

if __name__ == "__main__":
    raise SystemExit(exodia_ctl_main())
