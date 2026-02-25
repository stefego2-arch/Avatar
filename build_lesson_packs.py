"""build_lesson_packs.py — generează lesson_packs/*.json din manualele .md.

Versiunea cu fix-uri aplicate:
  FIX 1 — grade + subject din manual_index.json (nu mai e null)
  FIX 2 — filtrare secțiuni junk: cuprins, prezentare, evaluare predictivă etc.
  FIX 3 — artefacte DA/NU + linii majuscule scurte filtrate suplimentar

Rulare:
    python build_lesson_packs.py           # exerciții rule-based (implicit)
    python build_lesson_packs.py --llm     # exerciții generate de DeepSeek

Output:
    lesson_packs/*.json
    lesson_packs.zip
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from md_library import load_md_clean_text
from md_chunker import chunk_text

# ── Constante ─────────────────────────────────────────────────────────────────

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)$", re.MULTILINE)

# "tasky" = mai degrabă exercițiu / fișă, nu poveste TTS
TASK_MARKERS = [
    "completează", "scrie", "notează", "rezolvă", "calculează",
    "încercuiește", "subliniază", "transcrie", "alcătuiește",
    "desenează", "măsoară", "compară", "alege varianta",
]

# FIX 2: titluri de secțiuni care NU sunt lecții reale — le sărim
SKIP_TITLE_KEYWORDS = frozenset({
    "cuprins",
    "prezentarea",
    "prezentare",
    "competenț",          # competențe, competențele
    "introduc",           # introducere, introductivă
    "ghid",
    "bibliografi",
    "evaluare predict",   # evaluare predictivă
    "evaluare ini",       # evaluare inițială
    "cip ",               # pagina CIP editorial
    "document",           # titlu fallback generic produs de split
    "organizar",          # organizarea manualului
    "cum utiliz",         # cum utilizăm manualul
    "stimate elev",
})

# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_junk_title(title: str) -> bool:
    """Returnează True dacă titlul secțiunii nu reprezintă o lecție reală."""
    low = title.lower().strip()
    return any(kw in low for kw in SKIP_TITLE_KEYWORDS)


def guess_subject_from_filename(name: str) -> str:
    """Fallback subiect dacă manual_index.json nu are intrare pentru fișier."""
    low = name.lower()
    if "matematica" in low or "mate" in low:
        return "Matematică"
    if "romana" in low or "comunicare" in low or "limba" in low:
        return "Limba Română"
    return "Unknown"


@dataclass
class Section:
    title: str
    level: int
    text: str


def split_into_sections(md_text: str) -> List[Section]:
    """Split generic pe headings. Preferă ##, altfel #, altfel tot doc."""
    md_text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    matches = [
        (m.start(), len(m.group(1)), m.group(2).strip())
        for m in HEADING_RE.finditer(md_text)
    ]
    if not matches:
        return [Section(title="Document", level=0, text=md_text)]

    # alege nivel "lecție": dacă există ## => 2, altfel # => 1
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


def _normalize_llm_exercise(ex: dict) -> dict:
    """Convertește formatul DeepSeek {enunt/raspuns/hint*} → formatul intern {q/a/type}."""
    return {
        "q":     ex.get("enunt", ""),
        "type":  "open",
        "a":     ex.get("raspuns", ""),
        "hint1": ex.get("hint1", ""),
        "hint2": ex.get("hint2", ""),
        "hint3": ex.get("hint3", ""),
    }


def build_lesson_pack(
    md_file: Path,
    sec: Section,
    subject: str,
    grade: Optional[int],
    *,
    llm_client=None,
) -> Dict:
    """Construiește un lesson pack JSON pentru o secțiune a unui manual."""
    # Curăță textul secțiunii pentru TTS (folosim load_md_clean_text pe fișierul complet,
    # dar chunkuim doar textul secțiunii curente pentru a nu amesteca lecțiile)
    sec_raw_clean = re.sub(r"\s+", " ", sec.text).strip()
    # Aplică sanitizarea de markdown pe secțiune (rapid, inline)
    from md_library import sanitize_markdown_for_tts
    sec_clean = re.sub(r"\s+", " ", sanitize_markdown_for_tts(sec_raw_clean)).strip()

    # Dacă secțiunea e prea mică sau sanitizată → fallback la fișierul complet
    if len(sec_clean) < 100:
        sec_clean = re.sub(r"\s+", " ", load_md_clean_text(md_file)).strip()

    chunks = chunk_text(sec_clean, max_chars=900)
    if not chunks:
        chunks = [sec_clean[:900]] if sec_clean else []

    # ── Generare exerciții: LLM sau rule-based ────────────────────────────────
    if llm_client is not None and grade is not None:
        exercises = [
            _normalize_llm_exercise(e)
            for e in llm_client.generate_exercises(
                sec.title, grade=grade, subject=subject,
                theory=sec_clean[:600], count=5, phase="practice",
            )
        ]
        if not exercises:
            # Fallback la rule-based dacă LLM-ul nu răspunde
            exercises = build_quiz_rule_based(sec_clean, n=5)
    else:
        exercises = build_quiz_rule_based(sec_clean, n=5)

    return {
        "meta": {
            "source_md": str(md_file).replace("\\", "/"),
            "title": sec.title,
            "subject": subject,
            "grade": grade,  # FIX 1: acum vine din manual_index.json, nu mai e null
        },
        "theory_chunks": chunks,
        "pretest":   exercises[:1],
        "micro_quiz": exercises[1:2],
        "practice":   exercises[2:3],
        "posttest":   exercises[:3],
        "notes": {
            "task_heavy": is_task_heavy(sec.text),
            "llm_exercises": llm_client is not None and grade is not None,
        },
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generează lesson_packs/*.json din manualele .md"
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="Generează exerciții cu DeepSeek în loc de rule-based (necesită Ollama activ)"
    )
    args = parser.parse_args()

    # ── Inițializare opțională DeepSeek ──────────────────────────────────────
    llm_client = None
    if args.llm:
        from deepseek_client import DeepSeekClient
        llm_client = DeepSeekClient()
        if not llm_client.available:
            print("⚠️  DeepSeek indisponibil — fallback la rule-based pentru toate lecțiile.")
            llm_client = None
        else:
            print("🤖 Mod LLM activat — exerciții generate de DeepSeek")

    # Detectează directorul de manuale (manuale_main/ are prioritate, fallback manuale/)
    root = Path(__file__).parent
    for candidate in ("manuale_main", "manuale"):
        manuals_dir = root / candidate
        if manuals_dir.exists():
            break
    else:
        print("EROARE: nu am găsit directorul manuale/ sau manuale_main/.")
        return

    out_dir = root / "lesson_packs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── FIX 1: încarcă manual_index.json pentru grade + subject corecte ──────
    index_lookup: dict[str, dict] = {}
    index_path = root / "manual_index.json"
    if index_path.exists():
        raw_index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in raw_index.values():
            if isinstance(entry, dict) and "file" in entry:
                stem = Path(entry["file"]).stem
                index_lookup[stem] = entry
        print(f"📚 manual_index.json încărcat: {len(index_lookup)} intrări")
    else:
        print("⚠️  manual_index.json nu a fost găsit — grade va fi null!")

    md_files = sorted(manuals_dir.rglob("*.md"))
    if not md_files:
        print(f"N-am găsit .md în {manuals_dir}.")
        return

    print(f"📂 Procesez {len(md_files)} fișiere din {manuals_dir.name}/")

    packs: List[Tuple[str, Dict]] = []
    skipped_junk = 0
    grade_resolved = 0

    for md in md_files:
        # ── FIX 1: grade + subject din index ─────────────────────────────────
        meta_info = index_lookup.get(md.stem, {})
        subject = meta_info.get("subject") or guess_subject_from_filename(md.name)
        grade: Optional[int] = meta_info.get("grade")  # int sau None
        if grade is not None:
            grade_resolved += 1

        raw = md.read_text(encoding="utf-8", errors="ignore")
        sections = split_into_sections(raw)

        # filtrează secțiuni prea scurte (< 200 chars)
        sections = [s for s in sections if len(s.text.strip()) >= 200]

        # ── FIX 2: filtrează titluri junk (cuprins, prezentare etc.) ─────────
        valid = [s for s in sections if not _is_junk_title(s.title)]
        if valid:
            skipped_junk += len(sections) - len(valid)
            sections = valid

        # fallback: dacă tot e gol, ia cel puțin prima secțiune
        if not sections:
            sections = split_into_sections(raw)[:1]

        for idx, sec in enumerate(sections, 1):
            pack = build_lesson_pack(md, sec, subject=subject, grade=grade,
                                     llm_client=llm_client)
            safe_title = re.sub(
                r"[^a-zA-Z0-9ăâîșțĂÂÎȘȚ _\-]+", "", sec.title
            ).strip().replace(" ", "_")
            out_name = f"{md.stem}__{idx:03d}__{safe_title[:80]}.json"
            out_path = out_dir / out_name
            out_path.write_text(
                json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            packs.append((out_name, pack))

    # ── Raport ───────────────────────────────────────────────────────────────
    grade_null  = sum(1 for _, p in packs if p["meta"]["grade"] is None)
    llm_used    = sum(1 for _, p in packs if p["notes"].get("llm_exercises"))
    print(f"\n✅ Generat: {len(packs)} lesson packs")
    print(f"   Grade rezolvate din index: {grade_resolved}/{len(md_files)} fișiere")
    print(f"   Grade null în output:      {grade_null}/{len(packs)} pack-uri")
    print(f"   Secțiuni junk eliminate:   {skipped_junk}")
    if args.llm:
        print(f"   Exerciții LLM:             {llm_used}/{len(packs)} pack-uri")

    # ── ZIP ───────────────────────────────────────────────────────────────────
    zip_path = root / "lesson_packs.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out_dir.glob("*.json")):
            z.write(p, arcname=f"lesson_packs/{p.name}")

    print(f"   Arhivă: {zip_path} ({zip_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
