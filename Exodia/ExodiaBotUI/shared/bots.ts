/** Bot manifest schema (desktop/bots.manifest.json). */

export type BotArgDef = {
  name: string;
  flag: string;
  type: 'number' | 'string' | 'boolean';
  default?: number | string | boolean;
  label?: string;
};

export type BotManifestEntry = {
  id: string;
  title: string;
  kind: 'bot';
  /** e.g. ["-m", "SacredEelFishing.sacred_eel_fishing"] */
  moduleArgv?: string[];
  /** e.g. ["run_agent.py"] — resolved under exodia root */
  scriptArgv?: string[];
  defaultArgv: string[];
  runtimeScriptId: string;
  runtimeCommands: string[];
  args?: BotArgDef[];
  note?: string;
  deprecated?: boolean;
};

export type BotsManifest = {
  version: number;
  bots: BotManifestEntry[];
};

export type BotProcessState = 'idle' | 'starting' | 'running' | 'stopping' | 'paused';

export type BotRunInfo = {
  runId: string;
  botId: string;
  botTitle: string;
  pid: number | null;
  startedAt: number | null;
  exitCode: number | null;
  state: BotProcessState;
  runtimeScriptId: string;
  runtimeCommands: string[];
  usesStream: boolean;
};

export type RuntimeStatusPayload = {
  script?: string;
  updated_at?: string;
  paused?: boolean;
  state?: string;
  last_action?: string;
  stop_reason?: string;
  session_uptime_s?: number;
  context?: Record<string, unknown>;
  perception?: Record<string, unknown>;
};

export type StartBotRequest = {
  botId: string;
  argValues?: Record<string, number | string | boolean>;
};

export type StartBotResult = {
  ok: boolean;
  run?: BotRunInfo;
  error?: string;
};

export type StopBotResult = {
  ok: boolean;
  error?: string;
};

export type RuntimeCommandResult = {
  ok: boolean;
  error?: string;
};
