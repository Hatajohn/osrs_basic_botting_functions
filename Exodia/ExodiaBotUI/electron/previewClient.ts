import http from 'node:http';
import { loadSettings, resolveSettings } from './settings';

export type PreviewFrame = {
  imageDataUrl: string;
  fetchedAt: number;
};

async function fetchJpegSnapshot(path: string, port?: number): Promise<PreviewFrame | null> {
  const settings = loadSettings();
  const streamPort = port ?? settings.streamPort ?? 8765;
  const url = `http://127.0.0.1:${streamPort}${path}`;

  return new Promise((resolve) => {
    const req = http.get(url, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        resolve(null);
        return;
      }
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));
      res.on('end', () => {
        const body = Buffer.concat(chunks);
        if (body.length === 0) {
          resolve(null);
          return;
        }
        const b64 = body.toString('base64');
        resolve({
          imageDataUrl: `data:image/jpeg;base64,${b64}`,
          fetchedAt: Date.now(),
        });
      });
    });
    req.on('error', () => resolve(null));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(null);
    });
  });
}

export async function fetchGamePreview(port?: number): Promise<PreviewFrame | null> {
  return fetchJpegSnapshot('/snapshot/game_preview', port);
}

export async function fetchPristineClient(port?: number): Promise<PreviewFrame | null> {
  return fetchJpegSnapshot('/snapshot/pristine_client', port);
}

export async function fetchInventoryOverlay(port?: number): Promise<PreviewFrame | null> {
  return fetchJpegSnapshot('/snapshot/inventory_overlay', port);
}

export function resolveStreamPort(override?: number): number {
  const settings = loadSettings();
  return override ?? settings.streamPort ?? 8765;
}

export function previewUrl(port?: number): string {
  const p = resolveStreamPort(port);
  return `http://127.0.0.1:${p}/snapshot/game_preview`;
}

/** @internal for tests */
export function logsDirFromSettings(): string {
  return resolveSettings(loadSettings()).resolvedLogsDir;
}
