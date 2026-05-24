# Exodia: simple vs compound functions

Living reference for how automation is layered in this repo. Update this file when you add primitives or composites.

## Definitions

| Term | Meaning |
|------|---------|
| **Simple** | One layer, one concern: window geometry, capture, vision-only, or input-only. Callers combine these. |
| **Compound** | Orchestrates **two or more** layers (client + eyes + arms), or runs a **multi-step** loop (pan → locate → click, poll until condition, FSM tick). README calls `bot_actions` composites “glue.” |

**Not in scope here:** `BrainCommand` types, harness `step()`, runtime/CLI, tests, and private `_`-prefixed helpers unless they are the main public API.

**Future compound work:** shift+click drop (modifier + inventory locate + click); wire `identify_inventory_slot_items` into harness `GameState`.

---

## Simple functions

### Client (`bot_client.py`)

| Function / method | Role |
|-------------------|------|
| `ClientWindow.update()` | Refresh HWND / window handle |
| `ClientWindow.get_window_rect()` | Screen `[left, top, width, height]` |
| `FixedClientWindow` | Same API with a fixed rect (WSL / manual calibration) |

### Eyes — perception (`bot_eyes.py`)

| Function / method | Role |
|-------------------|------|
| `BotEyes.setRect()` | Bind client rect; optional `capture_frame()` |
| `BotEyes.capture_frame()` | Buffer copy or sync grab + ROIs / masks |
| `BotEyes.update()` | Alias for `capture_frame()` |
| `BotEyes.locate_image()` | Template match → screen points |
| `BotEyes.locate_image_detailed()` | Match + scores/metadata for agents |
| `BotEyes.locate_color()` | Color mask → points (optional DBSCAN) |
| `BotEyes.locate_cluster()` | Clustered color → single best point |
| `BotEyes.get_action_text()` | Action-strip tri-state code `0/1/2` |
| `BotEyes.get_action_text_with_ocr()` | Code + OCR payload |
| `BotEyes.ocr_action_text_roi()` / `ocr_dialogue_roi()` | OCR on UI strips |
| `BotEyes.find_inventory()` / `check_inventory()` | Inventory panel geometry (legacy ui_icons path) |
| `BotEyes.compute_inventory_slot_occupancy()` | 4×7 occupancy grid |
| `inventory_grid_cell_xywh()` / `inventory_slot_screen_xy()` | Slot ROI / screen center from panel rect |
| `analyze_inventory_panel_occupancy()` | Occupancy from cropped panel BGR |
| `resolve_action_strip_roi_client()` | Action-line ROI from layout / env |

### Inventory detect (`bot_inventory_detect.py`)

| Function | Role |
|----------|------|
| `match_inventory_by_outline()` | Full-frame dark-frame template → panel `[x,y,w,h]` + score |
| `validate_inventory_rect()` | Grid-structure score for a candidate rect |
| `inventory_occupancy_from_client()` | Client BGR + rect → 7×4 bool grid + count + empty BGR prototype |
| `auto_detect_inventory_rect()` | Search + refine (fallback when outline disabled) |
| `draw_inventory_outline_overlay()` / `draw_inventory_occupancy_overlay()` | Debug overlays (grid tint, occupied vs empty) |
| `inventory_outline_template_path()` | Default `captures/osrs_inventory_base.png` |

Matching crops the **full slot tile** (`EXODIA_INV_ITEM_MATCH_INSET`, default `0`) so icons can slide within the cell; occupancy uses the tighter inset crop separately. Gated matching and seen-item fingerprints live in `bot_match_index.py` (see below).

### Match index (`bot_match_index.py`)

| Function / type | Role |
|-----------------|------|
| `extract_signals()` | Hue/edge/dHash/aspect + stack-text aux from slot BGR |
| `gate_signals()` | Cheap reject with `RejectionReason` (`color`, `edge`, `size`, `dhash`) |
| `TemplateCatalog` / `load_named_catalog()` | Named `items/*.png` only (not 8-char temp ids) |
| `TemplateCatalog.match_query()` | Gated match → `MatchVerdict` with per-candidate diagnostics |
| `SeenItemRegistry` / `load_seen_registry()` | Temp-id PNGs in `items/seen/`, JSON in `items/fingerprints/` |
| `SeenItemRegistry.resolve()` | Match seen → `unknown:<id>` or register new 8-char id |
| `is_temp_item_id()` / `allocate_temp_id()` | Temp stem rules and collision-safe allocation |
| `audit_seen_duplicates()` | Pairwise duplicate audit across temp + named templates |
| `merge_duplicate_clusters()` | Apply cleanup merge (use with `python -m bot_match_index cleanup --merge`) |

**Match / seen env:** `EXODIA_MATCH_COLOR_MAX_L1`, `EXODIA_MATCH_EDGE_MAX_DIFF`, `EXODIA_MATCH_SIZE_MAX_RATIO`, `EXODIA_MATCH_DHASH_MAX_BITS`, `EXODIA_MATCH_STACK_MASK`, `EXODIA_STACK_WHITE_TEXT`, `EXODIA_SEEN_ITEMS` (default `0` — set `1` for temp ids), `EXODIA_SEEN_MATCH_THRESHOLD`, `EXODIA_SEEN_DHASH_MAX_BITS`, `EXODIA_SEEN_COLOR_MAX_L1`, `EXODIA_SEEN_FRAME_DEDUPE`, `EXODIA_SEEN_MERGE_ON_LOAD`, `EXODIA_MATCH_DEBUG`, `EXODIA_CLEANUP_*`.

### Inventory items (`bot_inventory_items.py`)

| Function | Role |
|----------|------|
| `items_directory()` | Named template root (default `items/`, override `EXODIA_ITEMS_DIR`) |
| `seen_images_directory()` | Temp-id PNG crops (default `items/seen/`, `EXODIA_SEEN_ITEMS_DIR`) |
| `seen_fingerprints_directory()` | Temp-id JSON sidecars (default `items/fingerprints/`, `EXODIA_SEEN_FINGERPRINTS_DIR`) |
| `load_item_catalog()` | Named templates → `TemplateCatalog` |
| `load_item_templates()` | Named `items/*.png` → `{name: gray}` (skips temp ids) |
| `resolve_cell_item()` | Named catalog → seen registry → label + `MatchVerdict` |
| `match_cell_to_item()` | Best gated match for one slot crop |
| `identify_inventory_slot_items()` | Occupied slots → name, `unknown:<id>`, `"?"`, or `None` + scores + optional diagnostics |
| `draw_inventory_item_identify_overlay()` | Occupancy tint + item labels on occupied slots |

Matching crops the **full slot tile** (`EXODIA_INV_ITEM_MATCH_INSET`, default `0`) so icons can slide within the cell; occupancy uses the tighter inset crop separately.

### Arms — input (`bot_arms.py`)

| Function / method | Role |
|-------------------|------|
| `BotArms.click_at()` | Move + click one point |
| `BotArms.click_here()` | Pick nearest point to center, then click |
| `BotArms.move_mouse()` | Move only; **`wsl_ps`**: smooth linear path in one PS call (`wsl_windows_move_to`); local: Bezier via PyAutoGUI |
| `BotArms.drag_at()` | Move to start, left-button drag to end; **`wsl_ps`**: `wsl_windows_left_drag_from_current` after move |
| `BotArms.pan_left()` / `pan_right()` / `pan_up()` / `pan_down()` | Camera rotation |
| `BotArms.control_camera()` | Middle-mouse drag pan |
| `BotArms.walk_direction()` | Ground click to walk N/E/S/W |
| `BotArms.drop_all()` | Shift-style multi-click drop (inventory points) |
| `BotArms.hit_escape()` | ESC key |

### Environment (`bot_env.py`)

| Function | Role |
|----------|------|
| `screen_image()` / `screen_image_fast()` | BGR capture (mss / pil / `wsl_ps`); reads capture buffer when pipeline active |
| `send_camera_arrow()` | Arrow-key camera on Windows from WSL |
| `wsl_windows_move_to()` | Smooth linear cursor path (smoothstep, one PS call) |
| `wsl_windows_left_drag_from_current()` | Left drag from current cursor to target |
| `wsl_windows_click_current()` | Click at current cursor (after move) |
| `wsl_windows_click()` / `wsl_windows_set_cursor()` | Legacy teleport click / cursor set |
| `wsl_move_duration_ms()` | Distance-scaled move duration for WSL paths |
| `pick_point_in_circle()` | Random point in click radius |
| `human_pause()` | Jittered sleep |
| `debug_view()` | OpenCV debug window |

### Capture pipeline (`bot_capture.py`)

| Function / class | Role |
|------------------|------|
| `FrameBuffer` | Depth-1 latest BGR + `seq` / timestamp |
| `CaptureProducer` | Timer thread — screen grab only |
| `VisionProcessor` | Separate thread — `bot_track` → `PerceptionCache` |
| `CapturePipeline` | Owns buffer, cache, producer, vision |
| `start_capture_pipeline()` / `stop_capture_pipeline()` | Lifecycle |
| `capture_stream_latest()` | Non-blocking buffer copy for `screen_image` / `capture_frame` |
| `WslPsCaptureSession` | Persistent PowerShell GDI session (WSL) |

### Motion tracking (`bot_track.py`)

| Function | Role |
|----------|------|
| `motion_mask()` / `detect_blobs()` | Frame-diff motion → contours |
| `update_tracks()` / `track_blobs_from_frame()` | Centroid ID assignment (v1 blobs) |
| `overlay_tracks()` | Debug / MJPEG `playspace_blobs` overlay |
| `TrackState` | Mutable tracker state (VisionProcessor-owned) |

### Stream (`bot_stream.py`)

| Function / class | Role |
|------------------|------|
| `FramePublisher` | Latest JPEG per stream key |
| `CaptureStreamPublisher` | Timer — buffer + cache → MJPEG (no vision work) |
| `MJPEGStreamServer` | HTTP `/stream/*`, `/snapshot/*`, `/meta` |

### Small utilities (module-level)

| Module | Function | Role |
|--------|----------|------|
| `bot_actions.py` | `bgr_bounds_from_color()` | BGR lower/upper for color ops |
| `bot_gamestate.py` | `occupied_cell_count()` | Count `True` cells in grid |
| `bot_inventory_count.py` | `count_inventory_*()` | Stack / object / quantity counts |
| `bot_action_ui.py` | `is_action_*()`, `action_code_label()` | Predicates on action code |
| `bot_search.py` | `playspace_search_roi()`, `ground_click_target()`, `walk_direction_for_attempt()` | ROI / walk target math (no I/O loop) |
| `bot_spot_verify.py` | `cyan_marker_ratio()`, `eel_icon_score_at()`, `verify_spot_at_client_xy()` | Single-spot checks |
| `BasicUtils.py` | `wait_ticks()` | Sleep `n` OSRS ticks + jitter |
| `bot_wait.py` | `poll_until()` | Generic timed condition poll |

---

## Compound functions

### Glue — `bot_actions.py` (client + eyes + arms)

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `bot_init()` | Create client, eyes, arms; set rect | `run_agent.py`, legacy scripts, sacred eel, diagnose |
| `sync_window()` | `client.update()` + rect geometry only (no grab) | Harness refresh (geometry leg) |
| `bot_update()` | `sync_window()` + `eyes.capture_frame()` | Harness, FSM, infernal/agility loops |
| `scan_for()` | Locate (image/color); pan camera on miss; click | Commented in `infernal_fishing.py` |
| `click_on_image()` | Optional refresh → `locate_image` → `click_at` | Harness, `infernal_fishing.py`, reference brain (via harness) |
| `click_on_color()` | Refresh → cluster → `click_at` | `infernal_fishing.py`, `agility.py`, harness `CmdClickColor` |
| `click_color_near_color()` | Anchor color → `click_on_color` near it | — (available) |
| `use_item_on()` | Two inv templates → use-on click sequence | `infernal_fishing.py`, harness, reference brain |
| `color_is_close()` | Refresh → cluster → distance check | `agility.py` (via `check_color`) |
| `check_color()` | `color_is_close` + log | `agility.py` |
| `mouse_fidgit()` | Refresh → move mouse offset from center | `agility.py`, `bot_actions` `__main__` |

### Inventory integration tests

| Suite | File | Layers |
|-------|------|--------|
| **Eyes** | `tests/bot_inventory_test.py` | find inventory, count, identify — capture/vision only |
| **Arms** | `tests/bot_inventory_arms_test.py --online` | drag item(s); verify move via occupancy (uses eyes for read-back only) |

Shared helpers: `tests/inventory_test_common.py`.

| Step (eyes) | Summary |
|-------------|---------|
| find inventory | Outline match + grid validation |
| count items | 4×7 bool grid |
| identify items | Template match vs `items/`; `?` if unknown |

| Step (arms) | Summary |
|-------------|---------|
| drag item | Random occupied → empty; center mouse before captures; verify occupancy |
| drag rounds | Extra drags when `EXODIA_INV_DRAG_ROUNDS` > 1 |

Outputs (local, gitignored): `captures/inventory_test_overlay.png` (eyes); `captures/offline_inventory_detect.png` (eyes offline); `captures/inventory_arms_overlay.png` (arms).

### Search loop — `bot_search.py`

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `search_with_camera_pan()` | `locate()` → pan → retry; optional ground relocate | `sacred_eel_fsm.py` |
| `click_random_hit()` | Random choice + `click_fn` | `sacred_eel_fsm.py` (with `click_at`) |

### Wait + UI — `bot_action_ui.py` + `bot_wait.py`

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `wait_for_action_code()` | Repeated `read_code` + predicate via `poll_until` | `sacred_eel_fsm.py` |

### Game state — `bot_gamestate.py`

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `build_game_state()` | Eyes: action text, inventory grid, capture meta → `GameState` | `bot_harness.py`, perception status |
| `game_state_to_dict()` | Serialize for observation / logs | Harness |

### Spot pipeline — `bot_spot_verify.py`

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `locate_sacred_eel_spots()` | Template peaks → filter/verify → candidates | Sacred eel fishing, diagnose |
| `filter_sacred_eel_spots()` | Trust + cyan + eel icon gates | Inside locate pipeline |
| `sacred_eel_spot_click_points()` | Candidates → click points | Sacred eel fishing |

### Harness — `bot_harness.py`

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `ExodiaHarness.refresh_geometry()` | `bot_update` | Every tick |
| `ExodiaHarness.observe()` | Frames, `build_game_state`, OCR meta | Agent path |
| `ExodiaHarness.apply_commands()` | Map `BrainCommand` → `bot_actions` | Agent path |
| `ExodiaHarness.step()` | Refresh → observe → brain → apply → verify → log | `run_agent.py`, `HarnessStepper` |
| `create_harness()` | `bot_init` + wiring | `run_agent.py` |

### Sacred eel — `SacredEelFishing/`

| Function | Steps (summary) | Used by |
|----------|-----------------|---------|
| `use_knife_on_eel()` | Locate knife + eels → two `click_at` | FSM (`configure_fsm`) |
| `_locate_sacred_eels()` | `locate_sacred_eel_spots` + reject hook | Main loop, FSM |
| `SacredEelFSM` states / `_seek_spot_click()` | Action waits + `search_with_camera_pan` + click | `sacred_eel_fishing.py` |

### Legacy script composites

| Location | Function | Notes |
|----------|----------|-------|
| `infernal_fishing.py` | `keep_fishing()` | Action code + inv count → `use_item_on` / `click_on_color` / waits |
| `infernal_fishing.py` | `__main__` loop | Inline version of fishing + cracking (no `BotLegs`) |
| `agility.py` | `__main__` loop | `click_on_color` + `mouse_fidgit` per course segment |

---

## Agent path mapping

`BrainCommand` → compound implementation in `ExodiaHarness.apply_commands()`:

| Command | Compound callee |
|---------|-----------------|
| `CmdClickImage` | `Actions.click_on_image()` |
| `CmdClickColor` | `Actions.click_on_color()` |
| `CmdUseItemOn` | `Actions.use_item_on()` |
| `CmdWait` / `CmdWaitTicks` | `time.sleep` (+ `constants.OSRS_TICK_S`) |
| `CmdLog` | Print only |

`ReferenceFishingBrain` mixes **compound** commands with a **simple** call (`harness.eyes.locate_image` for eel count).

---

## Quick usage by entrypoint

| Entrypoint | Simple (typical) | Compound (typical) |
|------------|------------------|---------------------|
| `run_agent.py` | via harness eyes/arms | `step()`, `click_on_image`, `use_item_on` |
| `infernal_fishing.py` | `get_action_text`, `locate_image` | `bot_init`, `bot_update`, `click_on_image`, `use_item_on`, `click_on_color` |
| `SacredEelFishing/sacred_eel_fishing.py` | `get_action_text`, `locate_image` (knife) | `bot_init`, FSM, `locate_sacred_eel_spots`, `search_with_camera_pan`, `wait_for_action_code` |
| `agility.py` | — | `click_on_color`, `mouse_fidgit`, `color_is_close` |
| `tests/bot_inventory_test.py` (offline) | `match_inventory_by_outline`, occupancy, `identify_inventory_slot_items` | — |
| `tests/bot_inventory_test.py --online` | same (live capture) | — |
| `tests/bot_inventory_arms_test.py --online` | occupancy read-back | `BotArms.drag_at`, center-mouse capture discipline |

---

## Repository safety (PNG)

Live client PNGs may contain account-identifying UI. **Allowlisted in git:** `captures/osrs_inventory_base.png`, `items/*.png` (item icon templates). Pre-commit hook at repo root: `githooks/pre-commit` (enable with `git config core.hooksPath githooks` from `Botting/`).

---

## Gaps / TODO

- [ ] **Compound modifier actions** — shift+click drop, key chords.
- [ ] **`scan_for`** — implemented but unused; deprecate in favor of `search_with_camera_pan`.
- [ ] **`drop_all`** — simple arms API exists; no script-level compound wrapper yet.
- [ ] **Item identity in harness** — `bot_inventory_items` + offline test; not yet on `GameState` / `BotEyes.resolve_inventory_slot_items`.
- [ ] **`bot_track` blobs** — motion blob pipeline (`bot_track.py` + `VisionProcessor`).
- [ ] **Sacred eel → `BotLegs`** — FSM as legs task; retire bespoke main `while` loop.

**Architecture plan (decisions + phases):** [`PlansTODO/function-architecture-plan.md`](PlansTODO/function-architecture-plan.md)

**Product decisions:** Canonical work in Exodia harness/FSM only; legacy root scripts not first-class; blob tracking v1; chat kept as separate crop; scheduler owned by `bot_legs` via **`SacredEelStepper`** (not harness brain).

**Recent:** `bot_inventory_items` template match (`items/flax.png`); full-tile match inset; offline identify test + `offline_inventory_detect.png`; `wsl_ps` smooth drag; outline inventory detect.

---

*Last reviewed: inventory item identification + offline detect overlay.*
