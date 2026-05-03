# Mouse input safety and OSRS ticks

## Game tick (~0.6 s)

State can change every server tick. Prefer **frequent, cheap** sensing (ROIs via **`bot_env.screen_regions`**) and reserve full-client work for when the task needs it. **`Env.PERF_TICK_S`** documents the nominal interval.

## Flow vs “human” motion

- Humanize **path shape, move duration, and short pre/post-click delays** — not **long idle gaps** between steps that must land in the same tick window.
- **`BotArms` `move_profile`**:
  - **`tight`** (default): small Bezier control jitter (scaled to **`rad`**), **no** elastic/bounce tweens — best for **inventory, objects, dense UI**.
  - **`normal`**: slightly more jitter, still no overshoot tweens.
  - **`open`**: use for **camera drags / open ground** where lateral excursions are safer (e.g. **`control_camera`**).
- **`click_at(..., move_profile="tight")`** forwards to **`move_mouse`**.

## Misclick envelope

Overshooty easing (elastic, bounce) was removed from **`tight` / `normal`** because adjacent tiles and UI widgets sit close together. Keep **endpoint noise** tied to **`rad`** (target hitbox); do not use large lateral arcs near clusters unless **`open`** and the scene is verified clear.

## Related

- [`exodia_linux_brain_env.md`](exodia_linux_brain_env.md) — capture backends and ROIs.
- [`automation_quality.md`](automation_quality.md) — **`human_pause`** for sub-tick jitter, not multi-tick stalls.
