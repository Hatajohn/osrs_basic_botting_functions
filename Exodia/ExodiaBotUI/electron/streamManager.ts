import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawn, type ChildProcess } from 'node:child_process';
import { loadSettings, resolveSettings } from './settings';
import { pythonExists } from './paths';
import { defaultClientRectPath } from './clientRect';
import {
  killListenersOnPort,
  killOrphanCapturePowerShell,
  killPerceptionStreamProcesses,
} from './streamPortKill';
import {
  controlFilePath as watchlistControlFilePath,
  enabledInventoryTemplates,
  enabledWorldTemplates,
  loadTemplateWatchlist,
  syncWatchlistToControlFile,
} from './templateWatchlist';

export type InventoryPerceptionMeta = {
  occupied?: number;
  unknown?: number;
  tmp_count?: number;
  inventory_calibrated?: boolean;
  vision_fps?: number;
  dirty_slots?: number[][];
  occupancy?: boolean[][];
  slot_items?: (string | null)[][];
  inventory_rect?: number[] | null;
  outline_score?: number;
  reidentify_pending?: number;
  capture_seq?: number;
  processed_seq?: number;
};

export type WorldTemplateStat = {
  template: string;
  hits: number;
  best_score?: number | null;
};

export type WorldTrackMeta = {
  track_id: number;
  template: string;
  client_xy: number[];
  screen_xy: number[];
  velocity_xy: number[];
  score: number;
  age_frames: number;
  missed_frames: number;
  stable: boolean;
};

export type WorldPerceptionMeta = {
  hits?: Array<{ template: string; client_xy: number[]; screen_xy?: number[]; score: number }>;
  tracks?: WorldTrackMeta[];
  hit_count?: number;
  track_count?: number;
  templates_scanned?: string[];
  template_stats?: WorldTemplateStat[];
  vision_fps?: number;
  pan_in_progress?: boolean;
  motion_magnitude?: number;
};

export type TextSpanMeta = {
  text: string;
  color: string;
  bbox: number[];
  conf?: number;
};

export type TextPerceptionMeta = {
  processed_seq?: number;
  capture_seq?: number;
  span_count?: number;
  client_w?: number;
  client_h?: number;
  scan_ms?: number;
  vision_fps?: number;
  spans?: TextSpanMeta[];
  fishing_spans?: TextSpanMeta[];
};

export type ActionPerceptionMeta = {
  action_code?: number;
  action_strip_rect?: number[] | null;
  action_line_text?: string | null;
  action_line_color?: string | null;
  detection_source?: string;
  processed_seq?: number;
  capture_seq?: number;
  vision_fps?: number;
};

export type PerceptionMeta = {
  inventory?: InventoryPerceptionMeta;
  world?: WorldPerceptionMeta;
  text?: TextPerceptionMeta;
  action?: ActionPerceptionMeta;
};

export type StreamMeta = {
  capture_seq?: number;
  processed_seq?: number;
  capture_fps?: number;
  vision_fps?: number;
  frame_age_ms?: number;
  frame_width?: number;
  frame_height?: number;
  preview_width?: number;
  preview_height?: number;
  overlay_max_width?: number;
  perception?: PerceptionMeta;
};

export type StreamStatus = {
  running: boolean;
  attached: boolean;
  port: number;
  url: string;
  inventoryOverlayUrl: string;
  gamePreviewUrl: string;
  metaUrl: string;
  error?: string;
  meta?: StreamMeta;
};

export type LogSink = (line: string, stream: 'stdout' | 'stderr' | 'system') => void;

/** Matches ``EXODIA_CAPTURE_STALE_MS`` default in bot_capture.py. */
const MAX_FRAME_AGE_MS = 600;
/** Gap between meta polls when verifying capture_seq is advancing. */
const HEALTH_POLL_GAP_MS = 500;
const HEALTH_VERIFY_TIMEOUT_MS = 8000;

export type StreamHealthResult = {
  healthy: boolean;
  error?: string;
};

/** ``capture_seq`` must advance across two polls and ``frame_age_ms`` must be below threshold. */
export async function verifyStreamHealthy(port: number): Promise<StreamHealthResult> {
  const meta1 = await fetchStreamMeta(port);
  if (!meta1 || meta1.capture_seq == null) {
    return { healthy: false, error: 'Stream meta missing capture_seq' };
  }
  await new Promise((r) => setTimeout(r, HEALTH_POLL_GAP_MS));
  const meta2 = await fetchStreamMeta(port);
  if (!meta2 || meta2.capture_seq == null) {
    return { healthy: false, error: 'Stream meta unavailable on health re-poll' };
  }
  if (meta2.capture_seq <= meta1.capture_seq) {
    return {
      healthy: false,
      error: `capture_seq frozen (${meta1.capture_seq} → ${meta2.capture_seq})`,
    };
  }
  const frameAge = meta2.frame_age_ms;
  if (frameAge != null && frameAge > MAX_FRAME_AGE_MS) {
    return {
      healthy: false,
      error: `frame too stale (${frameAge}ms > ${MAX_FRAME_AGE_MS}ms)`,
    };
  }
  return { healthy: true };
}

export async function waitForStreamHealthy(
  port: number,
  timeoutMs = HEALTH_VERIFY_TIMEOUT_MS,
): Promise<StreamHealthResult> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const result = await verifyStreamHealthy(port);
    if (result.healthy) {
      return result;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  return verifyStreamHealthy(port);
}

function controlFilePath(exodiaRoot: string): string {
  return watchlistControlFilePath(exodiaRoot);
}

function writeControlPayload(exodiaRoot: string, payload: Record<string, unknown>): void {
  const filePath = controlFilePath(exodiaRoot);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2), 'utf8');
}

function readControlPayload(exodiaRoot: string): Record<string, unknown> {
  const filePath = controlFilePath(exodiaRoot);
  if (!fs.existsSync(filePath)) {
    return { invalidate: false, world_templates: [] };
  }
  try {
    const data = JSON.parse(fs.readFileSync(filePath, 'utf8')) as Record<string, unknown>;
    return typeof data === 'object' && data !== null ? data : { invalidate: false };
  } catch {
    return { invalidate: false, world_templates: [] };
  }
}

export async function probeStreamPort(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/meta`, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.setTimeout(2500, () => {
      req.destroy();
      resolve(false);
    });
  });
}

export async function fetchStreamMeta(port: number): Promise<StreamMeta | null> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/meta`, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        resolve(null);
        return;
      }
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));
      res.on('end', () => {
        try {
          resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')) as StreamMeta);
        } catch {
          resolve(null);
        }
      });
    });
    req.on('error', () => resolve(null));
    req.setTimeout(1500, () => {
      req.destroy();
      resolve(null);
    });
  });
}

export class StreamProcessManager {
  private child: ChildProcess | null = null;
  private sink: LogSink;
  private lastError: string | undefined;
  private spawnedByUs = false;
  private lastCaptureSeq: number | undefined;
  private lastCaptureSeqChangeAt = 0;

  constructor(sink: LogSink) {
    this.sink = sink;
  }

  isSpawned(): boolean {
    return this.spawnedByUs && this.child !== null && this.child.exitCode === null;
  }

  getLastError(): string | undefined {
    return this.lastError;
  }

  async waitForCaptureSeqAdvance(port: number, prevSeq: number, timeoutMs = 2000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const meta = await fetchStreamMeta(port);
      if (meta?.capture_seq != null && meta.capture_seq > prevSeq) {
        return true;
      }
      await new Promise((r) => setTimeout(r, 200));
    }
    return false;
  }

  private noteCaptureSeq(seq: number | undefined): string | undefined {
    if (seq == null) {
      return undefined;
    }
    const now = Date.now();
    if (this.lastCaptureSeq !== seq) {
      this.lastCaptureSeq = seq;
      this.lastCaptureSeqChangeAt = now;
      return undefined;
    }
    if (now - this.lastCaptureSeqChangeAt > 4000) {
      return `capture_seq frozen at ${seq}`;
    }
    return undefined;
  }

  async getStatus(): Promise<StreamStatus> {
    const settings = loadSettings();
    const port = settings.streamPort ?? 8765;
    const base = `http://127.0.0.1:${port}`;
    const probed = await probeStreamPort(port);
    const childUp = this.isSpawned();
    const meta = probed ? await fetchStreamMeta(port) : null;
    const frozenError = this.noteCaptureSeq(meta?.capture_seq);
    let error = probed || childUp ? frozenError ?? this.lastError : this.lastError;
    const frameAge = meta?.frame_age_ms;
    if (
      probed &&
      frameAge != null &&
      frameAge > MAX_FRAME_AGE_MS &&
      frozenError == null
    ) {
      error = `frame too stale (${frameAge}ms)`;
    }

    return {
      running: probed || childUp,
      attached: probed && !childUp,
      port,
      url: base,
      inventoryOverlayUrl: `${base}/stream/inventory_overlay`,
      gamePreviewUrl: `${base}/stream/game_preview`,
      metaUrl: `${base}/meta`,
      error,
      meta: meta ?? undefined,
    };
  }

  async start(options?: { force?: boolean }): Promise<StreamStatus> {
    const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
    const settings = loadSettings();
    const port = settings.streamPort ?? 8765;
    const force = options?.force === true;

    if (!force && (await probeStreamPort(port))) {
      const health = await verifyStreamHealthy(port);
      if (health.healthy) {
        this.sink(`Perception stream already active on port ${port}`, 'system');
        syncWatchlistToControlFile(resolvedExodiaRoot);
        return this.getStatus();
      }
      this.sink(
        `Stream on port ${port} not healthy (${health.error ?? 'unknown'}) — killing and respawning…`,
        'system',
      );
      await this.hardKillAll(port);
      await this.waitForPortFree(port, 8000);
    }

    if (!pythonExists(resolvedPythonPath)) {
      this.lastError = `Python not found: ${resolvedPythonPath}`;
      return this.getStatus();
    }

    const rectPath = defaultClientRectPath(resolvedExodiaRoot);
    if (!fs.existsSync(rectPath)) {
      this.lastError = 'Missing client_rect.json — calibrate first';
      return this.getStatus();
    }

    if (this.child && this.child.exitCode === null) {
      return this.getStatus();
    }

    const script = path.join(resolvedExodiaRoot, 'exodia_perception_stream.py');
    const args = [
      script,
      '--port',
      String(port),
      '--max-width',
      String(settings.streamMaxWidth ?? 640),
      '--capture-fps',
      String(settings.streamCaptureFps ?? 10),
      '--vision-fps',
      String(settings.streamVisionFps ?? 10),
      '--publish-fps',
      String(settings.streamPublishFps ?? 10),
    ];

    this.sink(`Starting perception stream (port ${port})…`, 'system');
    syncWatchlistToControlFile(resolvedExodiaRoot);
    this.sink(`${resolvedPythonPath} ${args.join(' ')}`, 'system');

    return new Promise((resolve) => {
      const child = spawn(resolvedPythonPath, args, {
        cwd: resolvedExodiaRoot,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: process.platform !== 'win32',
        env: {
          ...process.env,
          EXODIA_ROOT: resolvedExodiaRoot,
          PYTHONUNBUFFERED: '1',
          EXODIA_CAPTURE_STREAM: '1',
          EXODIA_DEBUG_FRAME_MAX_WIDTH: String(settings.streamMaxWidth ?? 640),
          EXO_SHAPE_THR: process.env.EXO_SHAPE_THR ?? '0.52',
        },
      });

      this.child = child;
      this.spawnedByUs = true;
      this.lastError = undefined;

      let handshake = false;

      const onLine = (line: string, stream: 'stdout' | 'stderr') => {
        if (stream === 'stdout') {
          try {
            const parsed = JSON.parse(line) as { ok?: boolean; error?: string; url?: string };
            if (parsed.ok && parsed.url) {
              handshake = true;
              this.sink(`Perception stream ready: ${parsed.url}`, 'system');
            } else if (parsed.ok === false && parsed.error) {
              this.lastError = parsed.error;
            }
          } catch {
            // not JSON — pass through
          }
        }
        this.sink(line, stream);
      };

      child.stdout?.on('data', (chunk: Buffer) => {
        chunk
          .toString()
          .split(/\r?\n/)
          .filter(Boolean)
          .forEach((line) => onLine(line, 'stdout'));
      });

      child.stderr?.on('data', (chunk: Buffer) => {
        chunk
          .toString()
          .split(/\r?\n/)
          .filter(Boolean)
          .forEach((line) => onLine(line, 'stderr'));
      });

      child.on('error', (err) => {
        this.lastError = err.message;
        this.child = null;
        this.spawnedByUs = false;
        resolve(this.getStatus());
      });

      child.on('close', (code) => {
        if (!handshake && code !== 0) {
          this.lastError = `Perception stream exited with code ${code ?? 'unknown'}`;
        }
        this.child = null;
        this.spawnedByUs = false;
      });

      const waitUntil = Date.now() + 8000;
      const poll = async () => {
        if (await probeStreamPort(port)) {
          const health = await waitForStreamHealthy(port);
          if (!health.healthy) {
            this.lastError = health.error ?? 'Perception stream not healthy after start';
            this.sink(this.lastError, 'stderr');
            await this.hardKillAll(port);
            await this.waitForPortFree(port, 5000);
          } else {
            const metaOk = await fetchStreamMeta(port);
            this.lastCaptureSeq = metaOk?.capture_seq;
            this.lastCaptureSeqChangeAt = Date.now();
          }
          resolve(this.getStatus());
          return;
        }
        if (Date.now() >= waitUntil) {
          if (!this.lastError) {
            this.lastError = 'Perception stream did not become ready in time';
          }
          resolve(this.getStatus());
          return;
        }
        setTimeout(() => void poll(), 250);
      };
      void poll();
    });
  }

  /** Force-kill stream child, port listeners, and zombie perception processes. */
  private async hardKillAll(port: number): Promise<void> {
    const child = this.child;
    const pid = child?.pid;
    if (child && child.exitCode === null) {
      if (pid !== undefined && process.platform !== 'win32') {
        try {
          process.kill(-pid, 'SIGKILL');
        } catch {
          try {
            child.kill('SIGKILL');
          } catch {
            // already dead
          }
        }
      } else {
        try {
          child.kill('SIGKILL');
        } catch {
          // already dead
        }
      }
    }
    this.child = null;
    this.spawnedByUs = false;
    killPerceptionStreamProcesses(port);
    killListenersOnPort(port);
    await new Promise((r) => setTimeout(r, 350));
  }

  private async waitForPortFree(port: number, maxMs: number): Promise<boolean> {
    const deadline = Date.now() + maxMs;
    while (Date.now() < deadline) {
      if (!(await probeStreamPort(port))) {
        return true;
      }
      killListenersOnPort(port);
      killPerceptionStreamProcesses(port);
      killOrphanCapturePowerShell();
      await new Promise((r) => setTimeout(r, 450));
    }
    return !(await probeStreamPort(port));
  }

  /** Stop stream and release port + WSL capture so calibration can grab the monitor. */
  async stopForCalibration(): Promise<void> {
    const port = loadSettings().streamPort ?? 8765;
    this.sink('Stopping perception stream for calibration…', 'system');
    await this.stop();
    await this.hardKillAll(port);
    await this.waitForPortFree(port, 10000);
    this.lastCaptureSeq = undefined;
    this.lastCaptureSeqChangeAt = 0;
    this.lastError = undefined;
  }

  /** Hard-reset: kill zombies on the port, then spawn a fresh stream process. */
  async restart(): Promise<StreamStatus> {
    const settings = loadSettings();
    const port = settings.streamPort ?? 8765;
    this.sink('Hard-resetting perception stream…', 'system');
    this.lastError = undefined;
    this.lastCaptureSeq = undefined;
    this.lastCaptureSeqChangeAt = 0;

    await this.stop();
    await this.hardKillAll(port);

    let portFree = await this.waitForPortFree(port, 8000);
    if (!portFree) {
      this.sink('Port still in use — forcing kill again…', 'system');
      await this.hardKillAll(port);
      portFree = await this.waitForPortFree(port, 5000);
    }

    if (!portFree) {
      this.lastError = `Port ${port} still in use after hard reset — change stream port in Settings`;
      this.sink(this.lastError, 'stderr');
      return this.getStatus();
    }

    return this.start({ force: true });
  }

  async stop(): Promise<void> {
    const child = this.child;
    if (!child || child.exitCode !== null) {
      this.child = null;
      this.spawnedByUs = false;
      return;
    }

    this.sink('Stopping perception stream…', 'system');
    const pid = child.pid;
    if (pid !== undefined && process.platform !== 'win32') {
      try {
        process.kill(-pid, 'SIGTERM');
      } catch {
        child.kill('SIGTERM');
      }
    } else {
      child.kill('SIGTERM');
    }

    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        if (child.exitCode === null) {
          if (pid !== undefined && process.platform !== 'win32') {
            try {
              process.kill(-pid, 'SIGKILL');
            } catch {
              child.kill('SIGKILL');
            }
          } else {
            child.kill('SIGKILL');
          }
        }
        resolve();
      }, 3000);
      child.once('close', () => {
        clearTimeout(timer);
        resolve();
      });
    });

    this.child = null;
    this.spawnedByUs = false;
  }

  invalidateCache(): void {
    const { resolvedExodiaRoot } = resolveSettings(loadSettings());
    const existing = readControlPayload(resolvedExodiaRoot);
    const watchlist = loadTemplateWatchlist();
    writeControlPayload(resolvedExodiaRoot, {
      ...existing,
      invalidate: true,
      world_templates: enabledWorldTemplates(watchlist),
      inventory_templates: enabledInventoryTemplates(watchlist),
    });
    this.sink('Requested perception cache invalidate', 'system');
  }

  syncWatchlistControl(): void {
    const { resolvedExodiaRoot } = resolveSettings(loadSettings());
    syncWatchlistToControlFile(resolvedExodiaRoot);
    this.sink('Synced template watchlist to stream control file', 'system');
  }

  dispose(): void {
    void this.stop();
  }
}
