"""
convert_missing_manuals.py
==========================
Convertește PDF-uri lipsă din Avatar/Clasa_X/ → manuale/*.md
Detectează publisher din metadata PDF și actualizează manual_index.json.

Rulare:
    python convert_missing_manuals.py

Progres: afișează fiecare fișier și durată estimată.
"""
from __future__ import annotations

import sys
import io
import json
import re
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    import pymupdf4llm
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("❌ Instalează: pip install pymupdf pymupdf4llm")
    sys.exit(1)

# ── Căi ────────────────────────────────────────────────────────────────────────
AVATAR_BASE = Path(r"C:\Users\stefan.ionica\PycharmProjects\Avatar")
TARGET_DIR  = Path(__file__).parent / "manuale"
INDEX_PATH  = Path(__file__).parent / "manual_index.json"

# ── Publisher detection ────────────────────────────────────────────────────────
# Mapare subcheie → publisher canonical (lowercase)
PUBLISHER_KEYWORDS = [
    ("didactica si pedagogica",     "edp"),
    ("didactică și pedagogică",      "edp"),
    ("didactica și pedagogica",      "edp"),
    ("EDP",                          "edp"),
    ("EDU SRL",                      "edp"),
    ("EDU ",                         "edp"),
    ("cd press",                     "cd_press"),
    ("CD PRESS",                     "cd_press"),
    ("cdpress",                      "cd_press"),
    ("intuitext",                    "intuitext"),
    ("Intuitext",                    "intuitext"),
    ("artlibri",                     "artlibri"),
    ("art libri",                    "artlibri"),
    ("artklett",                     "artklett"),
    ("art klett",                    "artklett"),
    ("paralela 45",                  "paralela45"),
    ("paralela45",                   "paralela45"),
    ("corint",                       "corint"),
    ("litera",                       "litera"),
    ("booklet",                      "booklet"),
    ("aramis",                       "aramis"),
    ("sigma",                        "sigma"),
    ("didactica nova",               "didactica_nova"),
    ("clasa viitorului",             "clasa_viitorului"),
]

# ID → publisher, bazat pe datele deja indexate (manual_index.json)
KNOWN_ID_PUBLISHER: dict[str, str] = {
    # Cl.II Romana (din manual_index.json existent)
    "1488": "booklet",   "1489": "artklett",  "1490": "artlibri",
    "1491": "paralela45","1492": "edp",        "1493": "intuitext",
    "1494": "aramis",    "1495": "litera",     "1496": "cd_press",
    # Cl.III Romana
    "1126": "paralela45","1127": "intuitext",  "1128": "artlibri",
    "1129": "aramis",    "1130": "litera",     "1131": "cd_press",
    "1132": "artklett",  "1133": "corint",     "1134": "booklet",
    # Cl.IV Romana
    "1098": "paralela45","1099": "artlibri",   "1100": "intuitext",
    "1101": "litera",    "1102": "artklett",   "1103": "cd_press",
    # Cl.V Romana
    "1246": "booklet",   "1247": "artklett",   "1248": "corint",
    "1249": "litera",    "1250": "intuitext",  "1251": "cd_press",
    # Cl.III Matematica
    "1105": "edp",       "1106": "intuitext",  "1107": "artklett",
}


def detect_publisher_from_pdf(pdf_path: Path) -> str:
    """Încearcă să detecteze editorul din metadata PDF sau primele pagini."""
    try:
        doc = fitz.open(str(pdf_path))
        # 1) Metadata
        meta = doc.metadata
        all_text = " ".join([
            meta.get("title", ""),
            meta.get("author", ""),
            meta.get("creator", ""),
            meta.get("producer", ""),
            meta.get("subject", ""),
        ]).lower()

        for kw, pub in PUBLISHER_KEYWORDS:
            if kw.lower() in all_text:
                doc.close()
                return pub

        # 2) Prima pagina (text)
        if len(doc) > 0:
            page_text = doc[0].get_text().lower()[:2000]
            for kw, pub in PUBLISHER_KEYWORDS:
                if kw.lower() in page_text:
                    doc.close()
                    return pub

        doc.close()
    except Exception:
        pass

    return "necunoscut"


def detect_publisher_from_id(filename: str) -> str:
    """Detectează publisher din ID-ul numeric din filename (fallback)."""
    m = re.search(r"_(\d+)\.pdf$", filename)
    if m:
        return KNOWN_ID_PUBLISHER.get(m.group(1), "")
    return ""


def guess_subject(filename: str) -> str:
    n = filename.lower()
    if "matematica_si_explorarea" in n:
        return "Matematică"  # Clasa I-II
    if "matematica" in n:
        return "Matematică"
    if "comunicare_in_limba_romana" in n:
        return "Limba Română"
    if "limba_si_literatura_romana" in n:
        return "Limba Română"
    return "Necunoscut"


def is_romanian_language(filename: str) -> bool:
    """Filtrează manualele în limbi minoritare."""
    excl = [
        "germana", "maghiara", "materna", "rromani", "rusa",
        "sarba", "slovaca", "turca", "ucraineana", "italiana", "spaniola",
        "engleza", "franceza",
    ]
    fn = filename.lower()
    return not any(e in fn for e in excl)


def load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def save_index(data: dict):
    INDEX_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def convert_pdf_to_md(pdf_path: Path, out_path: Path) -> bool:
    """Converteste PDF → MD cu pymupdf4llm. Returneaza True dacă a reușit."""
    try:
        md_text = pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)
        if not md_text or len(md_text.strip()) < 200:
            print(f"      ⚠️  Conținut prea mic ({len(md_text)} chars) — posibil PDF scanat/imagine")
            return False
        out_path.write_text(md_text, encoding="utf-8")
        return True
    except Exception as e:
        print(f"      ❌ Eroare conversie: {e}")
        return False


# ── Lista PDF-uri lipsă ────────────────────────────────────────────────────────
SOURCES: list[tuple[int, str, Path]] = []

def add_source(grade: int, subj_hint: str, src_dir: Path, pattern_fn):
    """Adaugă fișiere dintr-un folder dacă MD-ul lipsește."""
    if not src_dir.exists():
        return
    for f in sorted(src_dir.iterdir()):
        if not f.suffix == ".pdf":
            continue
        if not pattern_fn(f.name):
            continue
        if not is_romanian_language(f.name):
            continue
        md_name = f.stem + ".md"
        if (TARGET_DIR / md_name).exists():
            continue  # deja convertit
        SOURCES.append((grade, subj_hint, f))


# Clasa I
add_source(1, "Limba Română", AVATAR_BASE / "Clasa_I",
           lambda n: "Comunicare_in_limba_romana_" in n)
add_source(1, "Matematică",   AVATAR_BASE / "Clasa_I",
           lambda n: "Matematica_si_explorarea" in n)

# Clasa II — doar Matematică (Română deja convertită)
add_source(2, "Matematică",   AVATAR_BASE / "Clasa_a_II-a",
           lambda n: "Matematica_si_explorarea" in n)

# Clasa III — Matematică rămasă
add_source(3, "Matematică",   AVATAR_BASE / "Clasa_a_III-a",
           lambda n: n.startswith("Matematica_") and "materna" not in n.lower())

# Clasa IV — Matematică
add_source(4, "Matematică",   AVATAR_BASE / "Clasa_a_IV-a",
           lambda n: n.startswith("Matematica_") and "materna" not in n.lower())

# Clasa V — Matematică
add_source(5, "Matematică",   AVATAR_BASE / "Clasa_a_V-a",
           lambda n: n.startswith("Matematica_") and "materna" not in n.lower())


def main():
    TARGET_DIR.mkdir(exist_ok=True)
    index = load_index()

    if not SOURCES:
        print("✅ Nu există PDF-uri lipsă. Totul e deja convertit.")
        return

    print(f"📚 De convertit: {len(SOURCES)} PDF-uri\n")

    converted = 0
    skipped   = 0
    failed    = 0
    t0_total  = time.time()

    for i, (grade, subj_hint, pdf_path) in enumerate(SOURCES, 1):
        md_name  = pdf_path.stem + ".md"
        out_path = TARGET_DIR / md_name
        subj     = guess_subject(pdf_path.name) or subj_hint

        # Detectează publisher
        pub = detect_publisher_from_id(pdf_path.name)
        if not pub:
            pub = detect_publisher_from_pdf(pdf_path)

        print(f"[{i:2}/{len(SOURCES)}] Cl.{grade} {subj} — {pdf_path.name}")
        print(f"        publisher: {pub}")

        t0 = time.time()
        ok = convert_pdf_to_md(pdf_path, out_path)
        dt = time.time() - t0

        if ok:
            converted += 1
            sz_kb = out_path.stat().st_size // 1024
            print(f"        ✅ {sz_kb} KB MD  ({dt:.1f}s)")

            # Actualizează index
            index[md_name] = {
                "file":       md_name,
                "subject":    subj,
                "grade":      grade,
                "title":      f"{subj} clasa {grade}",
                "publisher":  pub,
                "priority":   99,
                "is_default": False,
            }
            save_index(index)
        else:
            failed += 1
            if out_path.exists() and out_path.stat().st_size < 500:
                out_path.unlink()  # șterge fișierul gol

        # Estimare timp rămas
        elapsed = time.time() - t0_total
        avg     = elapsed / i
        remain  = avg * (len(SOURCES) - i)
        print(f"        Timp mediu: {avg:.1f}s | Ramas: ~{remain/60:.1f} min")
        print()

    total_time = time.time() - t0_total
    print("=" * 60)
    print(f"✅ Convertite: {converted} | ❌ Esuate: {failed} | ⏭ Sarite: {skipped}")
    print(f"⏱ Timp total: {total_time/60:.1f} minute")
    print()
    print("Pasul urmator: python manual_set_defaults.py")


if __name__ == "__main__":
    main()
