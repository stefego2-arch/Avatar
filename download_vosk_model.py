"""
download_vosk_model.py
======================
Descarca modelul vosk roman (mic, ~45 MB) pentru recunoastere vocala offline.

Rulare:
    python download_vosk_model.py
"""
import sys
import io
import urllib.request
import zipfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

MODEL_URL  = "https://alphacephei.com/vosk/models/vosk-model-small-ro-0.8.zip"
MODEL_NAME = "vosk-model-small-ro-0.8"
DEST_DIR   = Path(__file__).parent


def download_with_progress(url: str, dest: Path):
    print(f"Descarcare: {url}")
    print(f"Destinatie: {dest}")

    def reporthook(count, block_size, total_size):
        if total_size > 0:
            pct = min(100, count * block_size * 100 // total_size)
            mb  = count * block_size / 1_000_000
            sys.stdout.write(f"\r  {pct:3d}%  {mb:.1f} MB")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, reporthook=reporthook)
    print()


def main():
    out_dir = DEST_DIR / MODEL_NAME
    if out_dir.exists() and (out_dir / "am").exists():
        print(f"Modelul exista deja: {out_dir}")
        return

    zip_path = DEST_DIR / (MODEL_NAME + ".zip")
    if not zip_path.exists():
        try:
            download_with_progress(MODEL_URL, zip_path)
        except Exception as e:
            print(f"Eroare la descarcare: {e}")
            print("Descarca manual de la:")
            print(f"  {MODEL_URL}")
            print(f"si dezarhiveaza in: {DEST_DIR}")
            sys.exit(1)

    print("Dezarhivare...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(DEST_DIR)
    zip_path.unlink()

    if (out_dir / "am").exists():
        print(f"Model instalat cu succes: {out_dir}")
        print("Acum poti folosi microfonul in aplicatie!")
    else:
        print("Dezarhivat, dar structura modelului pare diferita.")
        print(f"Verifica: {DEST_DIR}")


if __name__ == "__main__":
    main()
