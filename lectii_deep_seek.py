from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple

from md_library import load_md_clean_text
from md_chunker import chunk_text  # dacă ai deja md_chunker.py

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)$", re.MULTILINE)

# “tasky” = mai degrabă exercițiu / fișă, nu poveste TTS
TASK_MARKERS = [
    "completează", "scrie", "notează", "rezolvă", "calculează",
    "încercuiește", "subliniază", "transcrie", "alcătuiește",
    "desenează", "măsoară", "compară", "alege varianta",
]

def guess_subject_from_filename(name: str) -> str:
    low = name.lower()
    if "matematica" in low or "mate" in low:
        return "Matematică"
    if "romana" in low or "comunicare" in low or "limba" in low:
        return "Limba Română"
    return "Unknown"

def guess_grade_from_filename(name: str) -> int | None:
    # dacă ai în nume “clasa a III-a” etc nu e în filename; fallback None
    return None

@dataclass
class Section:
    title: str
    level: int
    text: str

def split_into_sections(md_text: str) -> List[Section]:
    """Split generic pe headings. Preferă ##, altfel #, altfel tot doc."""
    md_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    matches = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(md_text)]
    if not matches:
        return [Section(title="Document", level=0, text=md_text)]

    # alege nivel “lecție”: dacă există ## => 2, altfel # => 1
    has_h2 = any(lvl == 2 for _, lvl, _ in matches)
    target_lvl = 2 if has_h2 else 1

    heads = [(pos, lvl, title) for (pos, lvl, title) in matches if lvl == target_lvl]
    if not heads:
        return [Section(title="Document", level=0, text=md_text)]

    sections: List[Section] = []
    for i, (pos, lvl, title) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(md_text)
        body = md_text[pos:end].strip()
        sections.append(Section(title=title, level=lvl, text=body))
    return sections

def is_task_heavy(text: str) -> bool:
    low = text.lower()
    hits = sum(1 for w in TASK_MARKERS if w in low)
    # prag simplu: dacă are multe “instrucțiuni” e mai degrabă fișă/exercițiu
    return hits >= 3

def build_quiz_rule_based(clean_text: str, n: int = 3) -> List[Dict]:
    """Întrebări simple din propoziții: maschează un cuvânt."""
    s = re.sub(r"\s+", " ", clean_text).strip()
    sents = re.split(r"(?<=[.!?])\s+", s)
    sents = [x.strip() for x in sents if 25 <= len(x.strip()) <= 140]
    if not sents:
        return [{"q": "Spune pe scurt ce ai înțeles din lecție.", "type": "open", "a": "răspuns liber"}]

    out: List[Dict] = []
    for sent in sents[: max(n, 1)]:
        words = sent.split()
        if len(words) < 8:
            out.append({"q": f"Spune pe scurt: {sent}", "type": "open", "a": "răspuns liber"})
            continue
        k = max(3, len(words) * 2 // 3)
        hidden = words[k]
        q = " ".join(words[:k] + ["__"] + words[k + 1 :])
        out.append({"q": f"Completează: {q}", "type": "open", "a": hidden})
        if len(out) >= n:
            break
    return out

def build_lesson_pack(md_file: Path, sec: Section, subject: str, grade: int | None) -> Dict:
    clean = load_md_clean_text(md_file, keep_headings=True)
    # pentru secțiuni, curățăm doar sec.text (dar reuse sanitize din md_library deja)
    # ca să nu dublăm, aplicăm load_md_clean_text pe tot fișierul și extragem simplu:
    # fallback: folosim sec.text “raw” și chunkuim direct
    sec_clean = re.sub(r"\s+", " ", load_md_clean_text(md_file, keep_headings=True)).strip()

    # dacă secțiunea e prea mică, păstrează tot fișierul (unele manuale au headings ciudate)
    if len(sec.text) > 200:
        sec_clean = re.sub(r"\s+", " ", sec_clean).strip()

    chunks = chunk_text(sec_clean, max_chars=900)
    if not chunks:
        chunks = [sec_clean[:900]] if sec_clean else []

    quiz = build_quiz_rule_based(sec_clean, n=3)

    return {
        "meta": {
            "source_md": str(md_file).replace("\\", "/"),
            "title": sec.title,
            "subject": subject,
            "grade": grade,
        },
        "theory_chunks": chunks,
        "pretest": quiz[:1],
        "micro_quiz": quiz[1:2],
        "practice": quiz[2:3],
        "posttest": quiz[:3],
        "notes": {
            "task_heavy": is_task_heavy(sec.text),
        },
    }

def main():
    manuals_dir = Path(r"C:\Users\stefan.ionica\Downloads\avatar_tutor_2026_ready\manuale_main")
    out_dir = Path("lesson_packs")
    out_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(manuals_dir.rglob("*.md"))
    if not md_files:
        print("N-am găsit .md în manuale/.")
        return

    packs: List[Tuple[str, Dict]] = []
    for md in md_files:
        subject = guess_subject_from_filename(md.name)
        grade = guess_grade_from_filename(md.name)

        raw = md.read_text(encoding="utf-8", errors="ignore")
        sections = split_into_sections(raw)

        # filtrează secțiuni “foarte scurte”
        sections = [s for s in sections if len(s.text.strip()) >= 200] or sections[:1]

        for idx, sec in enumerate(sections, 1):
            pack = build_lesson_pack(md, sec, subject=subject, grade=grade)
            safe_title = re.sub(r"[^a-zA-Z0-9ăâîșțĂÂÎȘȚ _-]+", "", sec.title).strip().replace(" ", "_")
            out_name = f"{md.stem}__{idx:03d}__{safe_title[:80]}.json"
            out_path = out_dir / out_name
            out_path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
            packs.append((out_name, pack))

    zip_path = Path("lesson_packs.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out_dir.glob("*.json")):
            z.write(p, arcname=f"lesson_packs/{p.name}")

    print(f"OK: generated {len(packs)} lesson packs -> {zip_path}")

if __name__ == "__main__":
    main()