# validate_manual_index.py
import json
from pathlib import Path
from collections import defaultdict

INDEX = Path("manual_index.json")
MANUALE_DIR = Path("manuale")

CANON = {
    "editura didactică și pedagogică s.a.": "edp",
    "editura didactica si pedagogica s.a.": "edp",
    "cd press": "cd_press",
    "cd_press": "cd_press",
    "intuitext": "intuitext",
    "booklet": "booklet",
    "paralela45": "paralela45",
    "artklett": "artklett",
    "artlibri": "artlibri",
    "art_libri": "artlibri",
    "litera": "litera",
    "corint": "corint",
    "edu": "edu",
    "aramis": "aramis",
}

def norm_pub(s: str) -> str:
    s2 = (s or "").strip().lower()
    return CANON.get(s2, s2.replace(" ", "_"))

data = json.loads(INDEX.read_text(encoding="utf-8"))

# 1) file exists check
missing = []
for k, v in data.items():
    f = MANUALE_DIR / v["file"]
    if not f.exists():
        missing.append(v["file"])

# 2) default count per (subject, grade)
defaults = defaultdict(list)
for v in data.values():
    defaults[(v["subject"], v["grade"])].append(v.get("is_default", False))

bad_defaults = {k: sum(vals) for k, vals in defaults.items() if sum(vals) != 1}

# 3) publisher normalization suggestions
pub_map = defaultdict(set)
for v in data.values():
    pub_map[norm_pub(v.get("publisher",""))].add(v.get("publisher",""))

print("Missing files:", missing)
print("Bad default groups (need exactly 1 default):", bad_defaults)
print("Publisher variants (should be 1 canonical each):")
for canon, variants in sorted(pub_map.items()):
    if len(variants) > 1:
        print(" ", canon, "=>", sorted(variants))
