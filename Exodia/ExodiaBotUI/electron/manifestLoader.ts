import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { BotArgDef, BotManifestEntry, BotsManifest } from '../shared/bots';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BOT_ENTRY_KEYS = new Set([
  'id',
  'title',
  'kind',
  'moduleArgv',
  'scriptArgv',
  'defaultArgv',
  'runtimeScriptId',
  'runtimeCommands',
  'args',
  'note',
  'deprecated',
  'requiresStream',
  'usesSharedStream',
]);

const ARG_KEYS = new Set(['name', 'flag', 'type', 'default', 'label']);

function assertObject(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function validateArgDef(raw: unknown, botId: string, index: number): BotArgDef {
  const obj = assertObject(raw, `bots[${botId}].args[${index}]`);
  for (const key of Object.keys(obj)) {
    if (!ARG_KEYS.has(key)) {
      throw new Error(`Unknown field "${key}" in bots[${botId}].args[${index}]`);
    }
  }
  const name = obj.name;
  const flag = obj.flag;
  const type = obj.type;
  if (typeof name !== 'string' || !name.trim()) {
    throw new Error(`bots[${botId}].args[${index}].name must be a non-empty string`);
  }
  if (typeof flag !== 'string' || !flag.startsWith('--')) {
    throw new Error(`bots[${botId}].args[${index}].flag must start with --`);
  }
  if (type !== 'number' && type !== 'string' && type !== 'boolean') {
    throw new Error(`bots[${botId}].args[${index}].type must be number|string|boolean`);
  }
  return {
    name,
    flag,
    type,
    default: obj.default as BotArgDef['default'],
    label: typeof obj.label === 'string' ? obj.label : undefined,
  };
}

function validateBotEntry(raw: unknown, index: number): BotManifestEntry {
  const obj = assertObject(raw, `bots[${index}]`);
  for (const key of Object.keys(obj)) {
    if (!BOT_ENTRY_KEYS.has(key)) {
      throw new Error(`Unknown field "${key}" in bots[${index}]`);
    }
  }

  const id = obj.id;
  const title = obj.title;
  const kind = obj.kind;
  if (typeof id !== 'string' || !id.trim()) {
    throw new Error(`bots[${index}].id must be a non-empty string`);
  }
  if (typeof title !== 'string' || !title.trim()) {
    throw new Error(`bots[${index}].title must be a non-empty string`);
  }
  if (kind !== 'bot') {
    throw new Error(`bots[${index}].kind must be "bot"`);
  }

  const moduleArgv = obj.moduleArgv;
  const scriptArgv = obj.scriptArgv;
  const hasModule = Array.isArray(moduleArgv) && moduleArgv.length > 0;
  const hasScript = Array.isArray(scriptArgv) && scriptArgv.length > 0;
  if (hasModule === hasScript) {
    throw new Error(`bots[${id}] must have exactly one of moduleArgv or scriptArgv`);
  }
  if (hasModule && !moduleArgv!.every((v) => typeof v === 'string')) {
    throw new Error(`bots[${id}].moduleArgv must be string[]`);
  }
  if (hasScript && !scriptArgv!.every((v) => typeof v === 'string')) {
    throw new Error(`bots[${id}].scriptArgv must be string[]`);
  }

  const defaultArgv = obj.defaultArgv;
  if (!Array.isArray(defaultArgv) || !defaultArgv.every((v) => typeof v === 'string')) {
    throw new Error(`bots[${id}].defaultArgv must be string[]`);
  }

  const runtimeScriptId = obj.runtimeScriptId;
  const runtimeCommands = obj.runtimeCommands;
  if (typeof runtimeScriptId !== 'string' || !runtimeScriptId.trim()) {
    throw new Error(`bots[${id}].runtimeScriptId must be a non-empty string`);
  }
  if (
    !Array.isArray(runtimeCommands) ||
    !runtimeCommands.every((v) => typeof v === 'string')
  ) {
    throw new Error(`bots[${id}].runtimeCommands must be string[]`);
  }

  const argsRaw = obj.args;
  const args =
    argsRaw === undefined
      ? undefined
      : Array.isArray(argsRaw)
        ? argsRaw.map((a, i) => validateArgDef(a, id, i))
        : (() => {
            throw new Error(`bots[${id}].args must be an array`);
          })();

  return {
    id,
    title,
    kind: 'bot',
    moduleArgv: hasModule ? (moduleArgv as string[]) : undefined,
    scriptArgv: hasScript ? (scriptArgv as string[]) : undefined,
    defaultArgv: defaultArgv as string[],
    runtimeScriptId,
    runtimeCommands: runtimeCommands as string[],
    args,
    note: typeof obj.note === 'string' ? obj.note : undefined,
    deprecated: obj.deprecated === true,
    requiresStream: obj.requiresStream === true ? true : undefined,
    usesSharedStream: obj.usesSharedStream === true ? true : undefined,
  };
}

function validateManifest(raw: unknown): BotsManifest {
  const root = assertObject(raw, 'manifest root');
  for (const key of Object.keys(root)) {
    if (key !== 'version' && key !== 'bots') {
      throw new Error(`Unknown top-level field "${key}" in bots.manifest.json`);
    }
  }
  if (root.version !== 1) {
    throw new Error('bots.manifest.json version must be 1');
  }
  const botsRaw = root.bots;
  if (!Array.isArray(botsRaw)) {
    throw new Error('bots.manifest.json "bots" must be an array');
  }
  const bots = botsRaw.map((entry, i) => validateBotEntry(entry, i));
  const ids = new Set<string>();
  for (const bot of bots) {
    if (ids.has(bot.id)) {
      throw new Error(`Duplicate bot id "${bot.id}" in bots.manifest.json`);
    }
    ids.add(bot.id);
  }
  return { version: 1, bots };
}

export function manifestPath(): string {
  return path.join(__dirname, '..', 'bots.manifest.json');
}

export function loadBotsManifest(): BotsManifest {
  const filePath = manifestPath();
  const text = fs.readFileSync(filePath, 'utf8');
  const parsed = JSON.parse(text) as unknown;
  return validateManifest(parsed);
}

export function findBot(manifest: BotsManifest, botId: string): BotManifestEntry | undefined {
  return manifest.bots.find((b) => b.id === botId);
}

export function buildArgvFromArgs(
  bot: BotManifestEntry,
  argValues?: Record<string, number | string | boolean>,
): string[] {
  const argv: string[] = [];
  for (const arg of bot.args ?? []) {
    const value = argValues?.[arg.name] ?? arg.default;
    if (value === undefined || value === null) continue;
    if (arg.type === 'boolean') {
      if (value === true) argv.push(arg.flag);
    } else {
      argv.push(arg.flag, String(value));
    }
  }
  return argv;
}

export function botRequiresStream(bot: BotManifestEntry): boolean {
  if (bot.requiresStream === true) return true;
  const all = [...bot.defaultArgv];
  for (let i = 0; i < all.length - 1; i += 1) {
    if (all[i] === '--stream-port' && all[i + 1] !== '0') return true;
  }
  return false;
}

/** Whether the active bot run should use the perception MJPEG overlay in the UI. */
export function botUsesStream(bot: BotManifestEntry): boolean {
  return botRequiresStream(bot);
}
