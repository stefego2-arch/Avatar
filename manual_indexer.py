from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

MANUALE_DIR = Path("manuale")
INDEX_PATH = Path("manual_index.json")

def guess_subject(name: str) -> str:
    n = name.lower()
    if "matematica" in n:
        return "Matematică"
    if "romana" in n or "comunicare_in_limba_romana" in n or "limba_si_literatura_romana" in n:
        return "Limba Română"
    return "Necunoscut"

def extract_title_from_md(path: Path) -> str:
    # ia primul heading "# ..." sau primul text non-gol
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return path.stem
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return re.sub(r"^#+\s*", "", line).strip() or path.stem
    for line in txt.splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return path.stem

@dataclass
class ManualItem:
    file: str
    subject: str
    grade: Optional[int] = None
    title: Optional[str] = None

def load_index() -> dict[str, ManualItem]:
    if not INDEX_PATH.exists():
        return {}
    raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    out: dict[str, ManualItem] = {}
    for k, v in raw.items():
        out[k] = ManualItem(**v)
    return out

def save_index(items: dict[str, ManualItem]):
    data = {k: asdict(v) for k, v in items.items()}
    INDEX_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    MANUALE_DIR.mkdir(exist_ok=True)
    md_files = sorted(MANUALE_DIR.glob("*.md"))
    if not md_files:
        print("Nu am găsit .md în:", MANUALE_DIR.resolve())
        return

    existing = load_index()

    updated = 0
    for f in md_files:
        key = f.name
        if key in existing:
            # păstrăm gradele setate manual, actualizăm doar dacă lipsesc
            item = existing[key]
            if not item.subject or item.subject == "Necunoscut":
                item.subject = guess_subject(f.name)
            if not item.title:
                item.title = extract_title_from_md(f)
            existing[key] = item
            continue

        item = ManualItem(
            file=f.name,
            subject=guess_subject(f.name),
            grade=None,
            title=extract_title_from_md(f),
        )
        existing[key] = item
        updated += 1

    save_index(existing)

    print("✅ manual_index.json generat/actualizat:", INDEX_PATH.resolve())
    print("Total manuale:", len(existing), "| noi adăugate:", updated)
    print("\nUrmătorul pas:")
    print("1) Deschide manual_index.json și completează grade: 1..5")
    print("2) Rulează din nou aplicația")

if __name__ == "__main__":
    main()
