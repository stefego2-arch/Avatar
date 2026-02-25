from __future__ import annotations
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from pathlib import Path
from typing import Dict, Any, Tuple

INDEX_PATH = Path("manual_index.json")

# ── Prioritate edituri (1 = cea mai bună) ─────────────────────────────────────
# Ierarhie: EDP → CD Press → Intuitext → altele (99)
PUBLISHER_PRIORITY: Dict[str, int] = {
    # EDP / Editura Didactică și Pedagogică (prioritate 1)
    "edp": 1,
    "edu": 1,
    "editura didactica si pedagogica": 1,
    "editura_didactica_si_pedagogica": 1,
    "didactica si pedagogica": 1,
    "edpl": 1,
    # CD Press (prioritate 2)
    "cd press": 2,
    "cd_press": 2,
    "cdpress": 2,
    "cd-press": 2,
    # Intuitext (prioritate 3)
    "intuitext": 3,
    # Corint (prioritate 10)
    "corint": 10,
    # Paralela 45 (prioritate 15)
    "paralela45": 15,
    "paralela 45": 15,
    # Art / ArtLibri / ArtKlett (prioritate 20)
    "art": 20,
    "artlibri": 20,
    "artklett": 20,
    "art_libri": 20,
    # Litera (prioritate 25)
    "litera": 25,
    # Booklet (prioritate 30)
    "booklet": 30,
    # Aramis (prioritate 35)
    "aramis": 35,
}


def norm_pub(s: str) -> str:
    """Normalizează numele editurii: lowercase, fără underscore/cratime extra."""
    return (s or "").strip().lower().replace("-", " ").replace("_", " ")


def get_priority(item: Dict[str, Any]) -> int:
    pub_raw = item.get("publisher", "")
    pub = norm_pub(pub_raw)
    # Caută mai întâi exact, apoi subcheie
    if pub in PUBLISHER_PRIORITY:
        return PUBLISHER_PRIORITY[pub]
    for key, pri in PUBLISHER_PRIORITY.items():
        if key in pub or pub in key:
            return pri
    return 99


def main():
    if not INDEX_PATH.exists():
        print("Nu există manual_index.json. Rulează manual_indexer.py întâi.")
        return

    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    # ── Pas 1: actualizează priority pentru toate intrările ───────────────────
    for k, v in data.items():
        if "publisher" not in v:
            v["publisher"] = ""
        old_pri = v.get("priority", 99)
        new_pri = get_priority(v)
        v["priority"] = new_pri
        v["is_default"] = False
        if old_pri != new_pri:
            print(f"  priority {old_pri}→{new_pri}  {v['publisher']:30s}  {k}")

    # ── Pas 2: alege default per (subject, grade) ─────────────────────────────
    groups: Dict[Tuple[str, int], list[tuple[str, Dict[str, Any]]]] = {}
    for k, v in data.items():
        subj = v.get("subject")
        grade = v.get("grade")
        if not subj or grade is None:
            continue
        groups.setdefault((subj, int(grade)), []).append((k, v))

    print("\n📚 Manuale default selectate:")
    for (subj, grade), items in sorted(groups.items()):
        # sortează: priority ASC, apoi filename ASC (deterministă)
        items.sort(key=lambda kv: (get_priority(kv[1]), kv[0]))
        best_key, best = items[0]
        best["is_default"] = True
        pub = best.get("publisher", "?")
        pri = get_priority(best)
        print(f"  Clasa {grade} {subj:20s} → {pub:30s} (priority={pri})  {best_key}")

    # ── Pas 3: salvează ──────────────────────────────────────────────────────
    INDEX_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n✅ manual_index.json actualizat cu priorities + defaults corecte.")


if __name__ == "__main__":
    main()
