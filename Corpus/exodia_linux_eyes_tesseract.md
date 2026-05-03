# BotEyes + Tesseract (Linux)

## Resolution order

1. Constructor arg: `BotEyes(..., tesseract_cmd="/path/to/tesseract")`
2. Environment: **`EXODIA_TESSERACT_CMD`**
3. **`shutil.which("tesseract")`**
4. Fallback command name: `"tesseract"` (pytesseract default)

`pytesseract.pytesseract.tesseract_cmd` is set in **`BotEyes.__init__`**.

## System packages

Install OCR engine separately, e.g. **`sudo apt install tesseract-ocr`** (and language packs as needed).

## Windows

The old hardcoded `..\..\Tesseract-OCR\tesseract.exe` is **removed**; use `EXODIA_TESSERACT_CMD` or PATH on all platforms.
