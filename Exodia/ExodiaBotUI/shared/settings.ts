export type ExodiaSettings = {
  exodiaRoot: string;
  pythonPath: string;
  logsDir: string;
  chainsDir: string;
  scriptsFolder: string;
  streamPort: number;
  /** Auto-start perception stream when client_rect.json exists (default on). */
  autoStartStream: boolean;
  streamMaxWidth: number;
  streamCaptureFps: number;
  streamVisionFps: number;
  streamPublishFps: number;
};
