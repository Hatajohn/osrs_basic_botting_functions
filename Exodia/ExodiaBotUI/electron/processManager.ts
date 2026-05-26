import { randomUUID } from 'node:crypto';
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import type {
  BotManifestEntry,
  BotProcessState,
  BotRunInfo,
  RuntimeStatusPayload,
  StartBotResult,
  StopBotResult,
} from '../shared/bots';
import {
  botUsesStream,
  buildArgvFromArgs,
  findBot,
  loadBotsManifest,
} from './manifestLoader';
import { pythonExists } from './paths';
import { sendRuntimeCommand, waitForRuntimeStop } from './runtimeClient';
import { loadSettings, resolveSettings } from './settings';
import { StatusWatcher } from './statusWatcher';

export type LogSink = (line: string, stream: 'stdout' | 'stderr' | 'system') => void;

export type ProcessManagerEvents = {
  onRunUpdate: (run: BotRunInfo | null) => void;
  onStatusUpdate: (status: RuntimeStatusPayload | null) => void;
};

function pipeLines(
  chunk: string,
  stream: 'stdout' | 'stderr',
  sink: LogSink,
  prefix?: string,
): void {
  chunk.split(/\r?\n/).filter(Boolean).forEach((line) => {
    sink(prefix ? `${prefix}${line}` : line, stream);
  });
}

export class ProcessManager {
  private child: ChildProcess | null = null;
  private run: BotRunInfo | null = null;
  private sink: LogSink;
  private events: ProcessManagerEvents;
  private statusWatcher: StatusWatcher;
  private killTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(sink: LogSink, events: ProcessManagerEvents) {
    this.sink = sink;
    this.events = events;
    this.statusWatcher = new StatusWatcher((status) => {
      if (this.run && status?.paused !== undefined) {
        const nextState: BotProcessState = status.paused ? 'paused' : 'running';
        if (this.run.state === 'running' || this.run.state === 'paused') {
          this.run = { ...this.run, state: nextState };
          this.events.onRunUpdate(this.run);
        }
      }
      this.events.onStatusUpdate(status);
    });
  }

  getActiveRun(): BotRunInfo | null {
    return this.run;
  }

  listBots(): BotManifestEntry[] {
    return loadBotsManifest().bots;
  }

  async startBot(
    botId?: string,
    argValues?: Record<string, number | string | boolean>,
    specPaths?: string[],
  ): Promise<StartBotResult> {
    const resolvedBotId = botId?.trim() || 'agent_reference_fishing';

    if (this.run && this.run.state !== 'idle') {
      const error = `Cannot start "${resolvedBotId}": ${this.run.botTitle} is already ${this.run.state}`;
      this.sink(error, 'stderr');
      return { ok: false, error };
    }

    let manifest;
    try {
      manifest = loadBotsManifest();
    } catch (err) {
      const error = err instanceof Error ? err.message : String(err);
      this.sink(error, 'stderr');
      return { ok: false, error };
    }

    const bot = findBot(manifest, resolvedBotId);
    if (!bot) {
      const error = `Unknown bot id: ${resolvedBotId}`;
      this.sink(error, 'stderr');
      return { ok: false, error };
    }

    const { resolvedExodiaRoot, resolvedPythonPath, resolvedLogsDir } = resolveSettings(
      loadSettings(),
    );

    if (!pythonExists(resolvedPythonPath)) {
      const error = `Python not found at: ${resolvedPythonPath}`;
      this.sink(error, 'stderr');
      return { ok: false, error };
    }

    const userArgv = buildArgvFromArgs(bot, argValues);
    const specArgv = (specPaths ?? []).flatMap((specPath) => ['--spec', specPath]);
    const spawnArgs = this.buildSpawnArgs(bot, resolvedExodiaRoot, [...userArgv, ...specArgv]);
    const runId = randomUUID();
    const usesStream = botUsesStream(bot);

    const run: BotRunInfo = {
      runId,
      botId: bot.id,
      botTitle: bot.title,
      pid: null,
      startedAt: Date.now(),
      exitCode: null,
      state: 'starting',
      runtimeScriptId: bot.runtimeScriptId,
      runtimeCommands: [...bot.runtimeCommands],
      usesStream,
    };
    this.run = run;
    this.events.onRunUpdate(run);

    this.sink(`Starting ${bot.title}…`, 'system');
    this.sink(`${resolvedPythonPath} ${spawnArgs.join(' ')}`, 'system');

    return new Promise((resolve) => {
      const child = spawn(resolvedPythonPath, spawnArgs, {
        cwd: resolvedExodiaRoot,
        stdio: ['ignore', 'pipe', 'pipe'],
        detached: process.platform !== 'win32',
        env: {
          ...process.env,
          EXODIA_ROOT: resolvedExodiaRoot,
          EXODIA_LOG_DIR: resolvedLogsDir,
          PYTHONUNBUFFERED: '1',
        },
      });

      this.child = child;
      this.run = { ...run, pid: child.pid ?? null, state: 'running' };
      this.events.onRunUpdate(this.run);
      this.statusWatcher.setRuntimeScriptId(bot.runtimeScriptId);
      this.statusWatcher.start();

      child.stdout?.on('data', (chunk: Buffer) => {
        pipeLines(chunk.toString(), 'stdout', this.sink);
      });

      child.stderr?.on('data', (chunk: Buffer) => {
        pipeLines(chunk.toString(), 'stderr', this.sink);
      });

      child.on('error', (err) => {
        this.sink(err.message, 'stderr');
        this.finishRun(null, err.message);
        resolve({ ok: false, error: err.message });
      });

      child.on('close', (code) => {
        const exitCode = code ?? null;
        this.sink(
          `${bot.title} exited${exitCode !== null ? ` with code ${exitCode}` : ''}`,
          exitCode === 0 ? 'system' : 'stderr',
        );
        this.finishRun(exitCode);
        resolve({ ok: exitCode === 0, run: this.run ?? undefined });
      });

      resolve({ ok: true, run: this.run });
    });
  }

  async stopBot(): Promise<StopBotResult> {
    if (!this.run || this.run.state === 'idle') {
      return { ok: false, error: 'No active bot to stop' };
    }
    if (this.run.state === 'stopping') {
      return { ok: false, error: 'Stop already in progress' };
    }

    const active = this.run;
    this.run = { ...active, state: 'stopping' };
    this.events.onRunUpdate(this.run);
    this.sink(`Stopping ${active.botTitle}…`, 'system');

    const { resolvedLogsDir } = resolveSettings(loadSettings());
    const statusPath = path.join(resolvedLogsDir, 'runtime_status.json');

    if (active.runtimeCommands.map((c) => c.toLowerCase()).includes('stop')) {
      const ctl = await sendRuntimeCommand('stop', active.runtimeCommands);
      if (ctl.stdout) pipeLines(ctl.stdout, 'stdout', this.sink);
      if (ctl.stderr) pipeLines(ctl.stderr, 'stderr', this.sink);
      await waitForRuntimeStop(statusPath, active.runtimeScriptId, 8000);
    }

    await this.terminateChild();
    return { ok: true };
  }

  async sendRuntimeCommand(command: string): Promise<{ ok: boolean; error?: string }> {
    if (!this.run || this.run.state === 'idle' || this.run.state === 'stopping') {
      return { ok: false, error: 'No active bot' };
    }
    const result = await sendRuntimeCommand(command, this.run.runtimeCommands);
    if (result.stdout) pipeLines(result.stdout, 'stdout', this.sink);
    if (result.stderr) pipeLines(result.stderr, 'stderr', this.sink);
    return { ok: result.ok, error: result.error };
  }

  dispose(): void {
    this.statusWatcher.stop();
    void this.terminateChild();
  }

  private buildSpawnArgs(
    bot: BotManifestEntry,
    exodiaRoot: string,
    userArgv: string[],
  ): string[] {
    const args: string[] = [];
    if (bot.moduleArgv) {
      args.push(...bot.moduleArgv);
    } else if (bot.scriptArgv) {
      args.push(path.join(exodiaRoot, bot.scriptArgv[0]));
      if (bot.scriptArgv.length > 1) {
        args.push(...bot.scriptArgv.slice(1));
      }
    }
    args.push(...bot.defaultArgv, ...userArgv);
    return args;
  }

  private async terminateChild(): Promise<void> {
    const child = this.child;
    if (!child || child.killed) {
      this.finishRun(this.run?.exitCode ?? null);
      return;
    }

    const pid = child.pid;
    if (pid !== undefined && process.platform !== 'win32') {
      try {
        process.kill(-pid, 'SIGTERM');
      } catch {
        try {
          child.kill('SIGTERM');
        } catch {
          // already dead
        }
      }
    } else {
      try {
        child.kill('SIGTERM');
      } catch {
        // already dead
      }
    }

    await new Promise<void>((resolve) => {
      if (this.killTimer) clearTimeout(this.killTimer);
      this.killTimer = setTimeout(() => {
        if (child.exitCode === null && !child.killed) {
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
        if (this.killTimer) clearTimeout(this.killTimer);
        resolve();
      });
    });
  }

  private finishRun(exitCode: number | null, error?: string): void {
    this.statusWatcher.stop();
    this.statusWatcher.setRuntimeScriptId(null);
    this.child = null;

    if (this.run) {
      this.run = {
        ...this.run,
        state: 'idle',
        exitCode,
        pid: null,
        startedAt: null,
      };
      this.events.onRunUpdate(null);
      this.events.onStatusUpdate(null);
    }

    if (error) {
      this.sink(error, 'stderr');
    }

    this.run = null;
  }
}
