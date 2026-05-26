import fs from 'node:fs';
import type { RuntimeStatusPayload } from '../shared/bots';
import { loadSettings, resolveSettings } from './settings';

export type StatusUpdateCallback = (status: RuntimeStatusPayload | null) => void;

export class StatusWatcher {
  private interval: ReturnType<typeof setInterval> | null = null;
  private lastJson = '';
  private runtimeScriptId: string | null = null;
  private onUpdate: StatusUpdateCallback;

  constructor(onUpdate: StatusUpdateCallback) {
    this.onUpdate = onUpdate;
  }

  setRuntimeScriptId(scriptId: string | null): void {
    this.runtimeScriptId = scriptId;
    if (!scriptId) {
      this.onUpdate(null);
    }
  }

  start(pollMs = 500): void {
    this.stop();
    this.interval = setInterval(() => this.poll(), pollMs);
    this.poll();
  }

  stop(): void {
    if (this.interval !== null) {
      clearInterval(this.interval);
      this.interval = null;
    }
    this.lastJson = '';
  }

  private statusPath(): string {
    const { resolvedLogsDir } = resolveSettings(loadSettings());
    return `${resolvedLogsDir}/runtime_status.json`;
  }

  private poll(): void {
    if (!this.runtimeScriptId) {
      this.onUpdate(null);
      return;
    }

    const filePath = this.statusPath();
    try {
      if (!fs.existsSync(filePath)) {
        if (this.lastJson !== '') {
          this.lastJson = '';
          this.onUpdate(null);
        }
        return;
      }
      const text = fs.readFileSync(filePath, 'utf8');
      if (text === this.lastJson) return;
      this.lastJson = text;
      const data = JSON.parse(text) as RuntimeStatusPayload;
      if (data.script !== this.runtimeScriptId) {
        this.onUpdate(null);
        return;
      }
      this.onUpdate(data);
    } catch {
      // partial write — ignore until next poll
    }
  }
}
