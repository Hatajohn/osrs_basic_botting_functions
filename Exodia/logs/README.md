# Exodia script logs

Runtime output from skill scripts lives here (git ignores `*.log` contents).

## Generic monitoring

Long-running scripts can expose three shared artifacts under `Exodia/logs/`:

| File | Purpose |
|------|---------|
| `<script_id>_events.jsonl` | Append-only JSONL session events (`bot_session_events`) — one object per line: `ts`, `script`, `event`, … |
| `runtime_status.json` | Live bot snapshot (FSM context, perception, pause/stop) — rewritten each tick |
| `runtime_control.json` | Pending command for the running bot (consumed on read) |

Install events once per process: `install_session_events("<script_id>")` → default path `logs/<script_id>_events.jsonl`. Override with `EXODIA_EVENTS_LOG`. Disable JSONL entirely: `EXODIA_EVENTS=0` (or `false` / `no` / `off`).

Disable control/status files: `EXODIA_RUNTIME=0` or script flag `--no-runtime-control`. Override paths: `EXODIA_RUNTIME_CONTROL`, `EXODIA_RUNTIME_STATUS`, `EXODIA_RUNTIME_POLL_S` (default `0.5` s).

### Control a running bot (second terminal)

```bash
cd /home/hata/Botting
python Exodia/exodia_ctl.py pause
python Exodia/exodia_ctl.py resume
python Exodia/exodia_ctl.py stop
python Exodia/exodia_ctl.py snapshot
python Exodia/exodia_ctl.py pan_left
python Exodia/exodia_ctl.py pan_right
python Exodia/exodia_ctl.py refresh
python Exodia/exodia_ctl.py step
python Exodia/exodia_ctl.py set_state --args '{"state":"SEEK_SPOT"}'
python Exodia/exodia_ctl.py stagnation_snapshot
python Exodia/exodia_ctl.py status
```

Or write JSON directly:

```bash
echo '{"command":"pause"}' > /home/hata/Botting/Exodia/logs/runtime_control.json
```

`status` (default when no subcommand) prints control/status paths and the latest `runtime_status.json`. Sacred eel registers: `pause`, `resume`, `stop`, `snapshot`, `refresh`, `step`, `pan_left`, `pan_right`, `set_state`, `stagnation_snapshot`.

### Read live status (agents / humans)

```bash
cat /home/hata/Botting/Exodia/logs/runtime_status.json
```

Canonical modules: `bot_session_events.py` (events), `bot_runtime.py` + `exodia_ctl.py` (control/status).

## Sacred eel fishing

| File | Purpose |
|------|---------|
| `sacred_eel_latest.log` | Current / last session — **tail this for live stdout/stderr** |
| `sacred_eel_fishing_events.jsonl` | Session events for script id `sacred_eel_fishing` (see generic table above) |
| `sacred_eel_events.jsonl` | **Alias name** — same file when using default path; override only via `EXODIA_EVENTS_LOG` |
| `runtime_status.json` | Live FSM + eel/inv/stagnation + `perception` block — see generic monitoring |
| `runtime_control.json` | Write a command while the bot runs — see `exodia_ctl` above |
| `diag/` | Manual / stagnation / snapshot PNG crops |

### Tail the session log

```bash
tail -f /home/hata/Botting/Exodia/logs/sacred_eel_latest.log
```

Override session log: `--log-file PATH` or `EXODIA_SACRED_EEL_LOG`. Paths: `SacredEelFishing/sacred_eel_log.py` (`LOGS_DIR`, `SESSION_LOG_FILE`, `EVENTS_LOG_FILE`).

## Progress score

Each FSM step records inventory progress in the session log and JSONL (`progress.observe` with `score`, `stagnation_streak`, `event`). There is **no stagnation auto-stop**; `EXODIA_STAGNATION_WARN` (default 5) only affects the `STUCK` hint on throttled cycle lines.
