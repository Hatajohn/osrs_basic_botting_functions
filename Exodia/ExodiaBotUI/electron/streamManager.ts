import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { spawn, type ChildProcess } from 'node:child_process';
import { loadSettings, resolveSettings } from './settings';
import { pythonExists } from './paths';
import { defaultClientRectPath } from './clientRect';
import { killListenersOnPort, killPerceptionStreamProcesses } from './streamPortKill';

export type PerceptionMeta = {
  occupied?: number;
  unknown?: number;
  tmp_count?: number;
  inventory_calibrated?: boolean;
  vision_fps?: number;
  dirty_slots?: number[][];
};

export type StreamMeta = {
  capture_seq?: number;
  processed_seq?: number;
  capture_fps?: number;
  vision_fps?: number;
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

function controlFilePath(exodiaRoot: string): string {
  return path.join(exodiaRoot, 'captures', 'perception_stream_control.json');
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

  constructor(sink: LogSink) {
    this.sink = sink;
  }

  isSpawned(): boolean {
    return this.spawnedByUs && this.child !== null && this.child.exitCode === null;
  }

  getLastError(): string | undefined {
    return this.lastError;
  }

  async getStatus(): Promise<StreamStatus> {
    const settings = loadSettings();
    const port = settings.streamPort ?? 8765;
    const base = `http://127.0.0.1:${port}`;
    const probed = await probeStreamPort(port);
    const childUp = this.isSpawned();
    const running = probed || childUp;
    const meta = probed ? await fetchStreamMeta(port) : null;

    return {
      running,
      attached: running && probed && !childUp,
      port,
      url: base,
      inventoryOverlayUrl: `${base}/stream/inventory_overlay`,
      gamePreviewUrl: `${base}/stream/game_preview`,
      metaUrl: `${base}/meta`,
      error: running ? undefined : this.lastError,
      meta: meta ?? undefined,
    };
  }

  async start(options?: { force?: boolean }): Promise<StreamStatus> {
    const { resolvedExodiaRoot, resolvedPythonPath } = resolveSettings(loadSettings());
    const settings = loadSettings();
    const port = settings.streamPort ?? 8765;
    const force = options?.force === true;

    if (!force && (await probeStreamPort(port))) {
      this.sink(`Perception stream already active on port ${port}`, 'system');
      return this.getStatus();
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
      String(settings.streamCaptureFps ?? 15),
      '--vision-fps',
      String(settings.streamVisionFps ?? 15),
      '--publish-fps',
      String(settings.streamPublishFps ?? 15),
    ];

    this.sink(`Starting perception stream (port ${port})…`, 'system');
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
      await new Promise((r) => setTimeout(r, 400));
    }
    return !(await probeStreamPort(port));
  }

  /** Hard-reset: kill zombies on the port, then spawn a fresh stream process. */
  async restart(): Promise<StreamStatus> {
    const settings = loadSettings();
    const port = settings.streamPort ?? 8765;
    this.sink('Hard-resetting perception stream…', 'system');
    this.lastError = undefined;

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
    const filePath = controlFilePath(resolvedExodiaRoot);
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify({ invalidate: true }, null, 2), 'utf8');
    this.sink('Requested perception cache invalidate', 'system');
  }

  dispose(): void {
    void this.stop();
  }
}
