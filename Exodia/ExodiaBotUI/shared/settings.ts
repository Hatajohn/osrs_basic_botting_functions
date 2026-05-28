export type ExodiaSettings = {
  exodiaRoot: string;
  pythonPath: string;
  logsDir: string;
  chainsDir: string;
  scriptsFolder: string;
  streamPort: number;
  /** @deprecated Stream always starts; kept for config compatibility. */
  autoStartStream: boolean;
  streamMaxWidth: number;
  streamCaptureFps: number;
  streamVisionFps: number;
  streamPublishFps: number;
};
