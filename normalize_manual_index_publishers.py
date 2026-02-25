# normalize_manual_index_publishers.py
import json
from pathlib import Path

INDEX = Path("manual_index.json")

CANON = {
    "art_libri": "artlibri",
    "artlibri": "artlibri",
    "booklet": "booklet",
    "Booklet": "booklet",
    "cd press": "cd_press",
    "cd_press": "cd_press",
}

data = json.loads(INDEX.read_text(encoding="utf-8"))

changed = 0
for k, v in data.items():
    pub = v.get("publisher", "")
    new_pub = CANON.get(pub, pub)
    if new_pub != pub:
        v["publisher"] = new_pub
        changed += 1

INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("Updated publishers:", changed)
