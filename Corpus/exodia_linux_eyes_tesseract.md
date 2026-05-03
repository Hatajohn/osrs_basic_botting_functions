# BotEyes + Tesseract (Linux)

## Resolution order

1. Constructor arg: `BotEyes(..., tesseract_cmd="/path/to/tesseract")`
2. Environment: **`EXODIA_TESSERACT_CMD`**
3. **`shutil.which("tesseract")`**
4. Fallback command name: `"tesseract"` (pytesseract default)

`pytesseract.pytesseract.tesseract_cmd` is set in **`BotEyes.__init__`**.

## System packages

Install OCR engine separately, e.g. **`sudo apt install tesseract-ocr`** (and language packs as needed).

## Helpers

- **`run_ocr(roi_bgr, psm=None, whitelist=None, scale=None)`** — single place for **`image_to_string`** with optional **PSM**, **whitelist**, and **downscale** (e.g. `0.5`) before OCR to save time per tick.
- **`find_inventory(..., search_roi=None)`** — optional **`[x, y, w, h]`** in **client** coordinates to narrow **`matchTemplate`**.
- **`locate_image(..., search_roi=None)`** — same for template search on client/inventory buffer.
