# Legacy example scripts

Historical one-off bots kept for reference. **Not canonical entrypoints** — use `run_agent.py`, package FSMs (`SacredEelFishing/`, `InfernalEelFishing/`), or integration tests for production work.

Run from the Exodia repo root:

```bash
python legacyCode/agility.py
python legacyCode/WhyFletch.py
python legacyCode/infernal_fishing.py   # redirects to InfernalEelFishing
```

Each script prepends the repo root to `sys.path` so `bot_*` imports resolve.
