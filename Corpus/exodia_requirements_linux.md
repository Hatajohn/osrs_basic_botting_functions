# Exodia requirements (Linux)

- **`Exodia/requirements-linux.txt`** — mirrors `requirements.txt` but **drops**:
  - **`pywin32`**
  - **`PyGetWindow`** (unused in Exodia code; Windows helper)
- **System:** `tesseract-ocr`, **`xdotool`** (for `BotBrain` / `core` window targeting).

Install: `pip install -r Exodia/requirements-linux.txt` inside your venv.

Windows-based dev can keep using **`Exodia/requirements.txt`**.
