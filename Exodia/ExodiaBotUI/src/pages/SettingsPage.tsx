import { useCallback, useEffect, useState } from 'react';
import type { SettingsResult } from '../../shared/ipc';
import './SettingsPage.css';

type SettingsPageProps = {
  open: boolean;
  onClose: () => void;
  onCalibrate: () => Promise<void>;
  calibrating: boolean;
};

type FormState = {
  exodiaRoot: string;
  pythonPath: string;
  logsDir: string;
  chainsDir: string;
  streamPort: string;
};

type FieldErrors = Partial<Record<keyof FormState, string>>;

function toForm(settings: SettingsResult['settings']): FormState {
  return {
    exodiaRoot: settings.exodiaRoot,
    pythonPath: settings.pythonPath,
    logsDir: settings.logsDir,
    chainsDir: settings.chainsDir,
    streamPort: String(settings.streamPort),
  };
}

export function SettingsPage({ open, onClose, onCalibrate, calibrating }: SettingsPageProps) {
  const [form, setForm] = useState<FormState | null>(null);
  const [resolved, setResolved] = useState<SettingsResult['resolved'] | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [smokeStatus, setSmokeStatus] = useState<string | null>(null);
  const [smokeRunning, setSmokeRunning] = useState(false);
  const [calibrateStatus, setCalibrateStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await window.exodia.getSettings();
    setForm(toForm(result.settings));
    setResolved(result.resolved);
    setErrors({});
    setSaveMessage(null);
    setCalibrateStatus(null);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  if (!open) return null;

  const update = (key: keyof FormState, value: string) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
    setSaveMessage(null);
  };

  const validatePython = async (pythonPath: string): Promise<string | undefined> => {
    const result = await window.exodia.setSettings({ pythonPath });
    setResolved(result.resolved);
    const test = await window.exodia.spawnSmokeTest();
    if (!test.ok) {
      return (
        test.error ??
        test.stderr ??
        `Python failed (exit ${test.exitCode}). Check that the path is correct and executable. Resolved: ${result.resolved.pythonPath}`
      );
    }
    return undefined;
  };

  const handleSave = async () => {
    if (!form) return;
    setSaveMessage(null);
    setSmokeStatus(null);

    const port = Number(form.streamPort);
    if (!Number.isFinite(port) || port < 1 || port > 65535) {
      setErrors({ streamPort: 'Enter a valid port (1–65535).' });
      return;
    }

    await window.exodia.setSettings({
      exodiaRoot: form.exodiaRoot,
      pythonPath: form.pythonPath,
      logsDir: form.logsDir,
      chainsDir: form.chainsDir,
      streamPort: port,
    });

    const refreshed = await window.exodia.getSettings();
    setResolved(refreshed.resolved);

    const pythonError = await validatePython(form.pythonPath);
    if (pythonError) {
      setErrors({ pythonPath: pythonError });
      return;
    }

    setSaveMessage('Settings saved.');
  };

  const handleSmokeTest = async () => {
    if (!form) return;
    setSmokeRunning(true);
    setSmokeStatus(null);
    setErrors((prev) => ({ ...prev, pythonPath: undefined }));

    await window.exodia.setSettings({
      exodiaRoot: form.exodiaRoot,
      pythonPath: form.pythonPath,
      logsDir: form.logsDir,
      chainsDir: form.chainsDir,
      streamPort: Number(form.streamPort) || 8765,
    });

    const refreshed = await window.exodia.getSettings();
    setResolved(refreshed.resolved);

    const test = await window.exodia.spawnSmokeTest();
    setSmokeRunning(false);

    if (test.ok) {
      setSmokeStatus('Smoke test passed — saw "ok" from Python.');
    } else {
      const msg =
        test.error ??
        test.stderr ??
        `Smoke test failed (exit ${test.exitCode}). Resolved Python: ${refreshed.resolved.pythonPath}`;
      setErrors({ pythonPath: msg });
      setSmokeStatus(null);
    }
  };

  const handleCalibrate = async () => {
    setCalibrateStatus(null);
    await onCalibrate();
    setCalibrateStatus('Calibration finished — see Log panel for details.');
  };

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <dialog
        className="settings-modal"
        open
        aria-labelledby="settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="settings-modal__header">
          <h2 id="settings-title">Preferences</h2>
          <button type="button" className="btn btn--icon" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        {loading || !form ? (
          <p className="settings-modal__loading">Loading…</p>
        ) : (
          <div className="settings-modal__body">
            <label className="field">
              <span className="field__label">Exodia root</span>
              <input
                className="field__input"
                value={form.exodiaRoot}
                onChange={(e) => update('exodiaRoot', e.target.value)}
                placeholder={resolved?.exodiaRoot}
              />
              <span className="field__hint">Resolved: {resolved?.exodiaRoot}</span>
            </label>

            <label className="field">
              <span className="field__label">Python path</span>
              <input
                className={`field__input${errors.pythonPath ? ' field__input--error' : ''}`}
                value={form.pythonPath}
                onChange={(e) => update('pythonPath', e.target.value)}
                placeholder="Leave blank for venv default"
              />
              <span className="field__hint">Resolved: {resolved?.pythonPath}</span>
              {errors.pythonPath && (
                <span className="field__error">{errors.pythonPath}</span>
              )}
            </label>

            <label className="field">
              <span className="field__label">Logs directory</span>
              <input
                className="field__input"
                value={form.logsDir}
                onChange={(e) => update('logsDir', e.target.value)}
                placeholder="Default: {exodiaRoot}/logs"
              />
              <span className="field__hint">Resolved: {resolved?.logsDir}</span>
            </label>

            <label className="field">
              <span className="field__label">Chains directory</span>
              <input
                className="field__input"
                value={form.chainsDir}
                onChange={(e) => update('chainsDir', e.target.value)}
                placeholder="Default: {exodiaRoot}/ExodiaBotUI/chains"
              />
              <span className="field__hint">Resolved: {resolved?.chainsDir}</span>
            </label>

            <label className="field">
              <span className="field__label">Stream port</span>
              <input
                className={`field__input field__input--narrow${errors.streamPort ? ' field__input--error' : ''}`}
                value={form.streamPort}
                onChange={(e) => update('streamPort', e.target.value)}
                inputMode="numeric"
              />
              {errors.streamPort && (
                <span className="field__error">{errors.streamPort}</span>
              )}
            </label>

            {saveMessage && <p className="settings-modal__success">{saveMessage}</p>}
            {smokeStatus && <p className="settings-modal__success">{smokeStatus}</p>}
            {calibrateStatus && <p className="settings-modal__success">{calibrateStatus}</p>}

            <div className="settings-modal__tools">
              <p className="settings-modal__tools-title">Setup</p>
              <p className="field__hint">
                Opens the ROI picker on the primary monitor. Drag a box around the RuneLite
                client window to write client_rect.json.
              </p>
              <button
                type="button"
                className="btn"
                onClick={handleCalibrate}
                disabled={loading || calibrating || smokeRunning}
              >
                {calibrating ? 'Calibrating…' : 'Calibrate client rect'}
              </button>
            </div>
          </div>
        )}

        <footer className="settings-modal__footer">
          <button
            type="button"
            className="btn"
            onClick={handleSmokeTest}
            disabled={loading || smokeRunning || calibrating}
          >
            {smokeRunning ? 'Testing…' : 'Run smoke test'}
          </button>
          <div className="settings-modal__footer-right">
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="button" className="btn btn--primary" onClick={handleSave} disabled={loading}>
              Save
            </button>
          </div>
        </footer>
      </dialog>
    </div>
  );
}
