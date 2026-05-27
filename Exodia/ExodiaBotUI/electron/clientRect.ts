import path from 'node:path';

export function defaultClientRectPath(exodiaRoot: string): string {
  return path.join(exodiaRoot, 'client_rect.json');
}
