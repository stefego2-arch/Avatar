# md_library.py
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import re
from pathlib import Path

from md_chunker import chunk_text

import re

_MD_RE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_MD_RE_INLINE_CODE = re.compile(r"`([^`]*)`")

# ── Answer-block / test-solution detection ────────────────────────────────────
# Pattern: "Exercițiul 5: a) ..." — colon/dot after number + answer letter
_ANSWER_CHUNK_RE = re.compile(
    r"Exerci[tț]iul\s+\d+\s*[:.]\s*[a-e]\)",
    re.IGNORECASE | re.UNICODE,
)
# "Exercițiul 6: harnic ≠ leneș; obosit ≠ energic" — antonyms / list answers
_ANSWER_INLINE_RE = re.compile(
    r"Exerci[tț]iul\s+\d+\s*:\s*\w{3,}",   # "Exercițiul N: cuvant" right after colon
    re.IGNORECASE | re.UNICODE,
)
_TEST_EVAL_RE = re.compile(r"Test\s+de\s+evaluare", re.IGNORECASE)
# Density check: 2+ exercise-answer headers in same chunk = answer-key block
_EXNR_RE = re.compile(r"Exerci[tț]iul\s+\d+\s*:", re.IGNORECASE | re.UNICODE)


def _chunk_is_answer_block(chunk: str) -> bool:
    """Return True if chunk is primarily an answer-key or test-solution block.

    Filters out blocks like:
      "Exercițiul 5: a) text b) text c) text"
      "Exercițiul 6: harnic ≠ leneș; obosit ≠ energic"
      "UNITATEA 8 | Test de evaluare. Exercițiul 1: a) literar"
    These come from the answer-key sections of the scanned textbook.
    """
    if _TEST_EVAL_RE.search(chunk):
        return True
    if _ANSWER_CHUNK_RE.search(chunk):
        return True
    # 2+ exercise-colon headers = answer block (e.g. "Exercițiul 6: ... Exercițiul 7: ...")
    if len(_EXNR_RE.findall(chunk)) >= 2:
        return True
    # Single "Exercițiul N: word" (inline short answers, not a question text)
    if _ANSWER_INLINE_RE.search(chunk):
        # Make sure it's not just a question with a number prefix
        # Distinguish: "Exercițiul 5: Citește textul." (question) vs "Exercițiul 5: cuvânt" (answer)
        m = _ANSWER_INLINE_RE.search(chunk)
        if m:
            # If chunk is short AND has semicolons or ≠ signs, it's answers
            after_colon = chunk[m.end():].strip()
            if len(chunk) < 400 and ("; " in after_colon or "≠" in after_colon or "!=" in after_colon):
                return True
    return False


# ── Clasificare chunk THEORY / TASK / NOISE ──────────────────────────────────
# Verbe imperative românești care indică o instrucțiune de lucru (TASK)
_TASK_RE = re.compile(
    r"(?im)^\s*("
    r"Notea[zț][aă]|Rezolv[aă]|Rezolva[tț]i|Scrie\b|Scrie[tț]i|"
    r"Calculea[zț][aă]|Calcula[tț]i|Complet[aă]\b|Completa[tț]i|"
    r"Exersea[zț][aă]|Desoper[aă]|Colorea[zț][aă]|Colora[tț]i|"
    r"Desena[zț][aă]|Desena[tț]i|Construie[sș]te|M[aă]soar[aă]|"
    r"G[aă]se[sș]te|G[aă]si[tț]i|Alege\b|Alege[tț]i|"
    r"Num[aă]r[aă]|Num[aă]ra[tț]i|Une[sș]te|Une[sș]te[tț]i|"
    r"Sortea[zț][aă]|Ordonea[zț][aă]|Compar[aă]|Compara[tț]i|"
    r"Taie\b|Tai[aă]\b|Formea[zț][aă]|Forma[tț]i|Identific[aă]|"
    r"Subliniaz[aă]|Sublinia[tț]i|Observ[aă]\s+[sș]i\s+[iî]n[tț]eleg|"
    r"Exersez\b|Aflu\b|Citesc\b|Citi[tț]i\b|Lipesc\b|Colec[tț]ionea[zț][aă]|"
    r"Clasific[aă]|Asociaz[aă]|Desf[aă][sș]oar[aă]|Transfor[mń][aă]|"
    # Markeri pedagogici Romanian CD Press (apar ca headings standalone după sanitizare)
    r"Observ[aă]?!?\s*$|Re[tț]in[eă]?!?\s*$|Exersez!?\s*$|"
    r"[iÎ]mi\s+imaginez!?\s*$|Investighez!?\s*$|Proiect\b|"
    r"[iÎ]ncerc!?\s*$|Realizez!?\s*$|Aplic[aă]?!?\s*$|"
    r"Lucrez!?\s*$|Creez!?\s*$|Prezint!?\s*$"
    r")"
)

# Cuvinte-cheie care indică definiții/concepte (THEORY)
_THEORY_RE = re.compile(
    r"(?i)("
    r"Re[tț]ine[tț]i?!?|Important[aă]?!?|Defini[tț]i[ae]\b|"
    r"Regul[aă]\b|Proprietate\b|Observa[tț]ie\b|[SȘ]tiai c[aă]\b|"
    r"Informa[tț]ie\b|Este important\b|Trebuie s[aă] [sș]tii\b|"
    r"Regula de baz[aă]\b|Aten[tț]ie!|Not[aă]!\b"
    r")"
)


def classify_chunk(text: str) -> str:
    """Clasifică un chunk de text ca 'task', 'theory' sau 'noise'.

    'task'   — instrucțiuni de lucru (verbe imperative la început de rând)
    'theory' — definiții/concepte (cuvinte-cheie definitionale)
    'noise'  — chunk prea scurt sau gol
    """
    stripped = text.strip()
    if not stripped or len(stripped) < 15:
        return "noise"
    if _TASK_RE.match(stripped):
        return "task"
    if _THEORY_RE.search(stripped):
        return "theory"
    return "theory"   # default: teoria dacă nu detectăm instrucțiune


_MD_RE_IMG = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MD_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)$", re.MULTILINE)
_MD_RE_HR = re.compile(r"^\s{0,3}[-*_]{3,}\s*$", re.MULTILINE)
_MD_RE_BLOCKQUOTE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MD_RE_LIST_BULLET = re.compile(r"^\s{0,6}[-*+]\s+", re.MULTILINE)
_MD_RE_LIST_NUM = re.compile(r"^\s{0,6}\d+[.)]\s+", re.MULTILINE)
_MD_RE_TABLE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)  # linii cu |
_MD_RE_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$", re.MULTILINE)
_MD_RE_EMPH = re.compile(r"(\*\*|__|\*|_)")
_MD_RE_HTML = re.compile(r"<[^>]+>")

# ── markdown-it-py AST parser (optional, graceful fallback) ──────────────────
try:
    from markdown_it import MarkdownIt as _MDIt
    _md_parser = _MDIt()

    def _md_to_plain_ast(text: str) -> str:
        """Convertește markdown → text plain folosind AST (markdown-it-py).
        Returnează None dacă markdown-it-py nu e instalat (fallback la regex).
        """
        lines: list[str] = []
        for tok in _md_parser.parse(text):
            if tok.type == "inline" and tok.children:
                lines.append("".join(
                    c.content for c in tok.children
                    if c.type in ("text", "softbreak", "hardbreak", "code_inline")
                ))
        return "\n".join(lines)

except ImportError:
    _md_to_plain_ast = None   # type: ignore[assignment]


def sanitize_markdown_for_tts(text: str, *, keep_headings: bool = True) -> str:
    t = text

    # 1) scoate blocuri de cod
    t = _MD_RE_FENCE.sub(" ", t)

    # 2) imagini: păstrează doar alt text-ul dacă există
    t = _MD_RE_IMG.sub(r"\1", t)

    # 3) linkuri: păstrează doar textul linkului
    t = _MD_RE_LINK.sub(r"\1", t)

    # 4) inline code: păstrează conținutul, scoate backticks
    t = _MD_RE_INLINE_CODE.sub(r"\1", t)

    # 5) headings: fie le păstrăm ca propoziții, fie le eliminăm
    if keep_headings:
        # transformă "# Titlu" -> "Titlu."
        t = _MD_RE_HEADING.sub(lambda m: f"{m.group(2).strip()}.", t)
    else:
        t = _MD_RE_HEADING.sub(" ", t)

    # 6) separatori orizontali
    t = _MD_RE_HR.sub(" ", t)

    # 7) blockquote marker ">"
    t = _MD_RE_BLOCKQUOTE.sub("", t)

    # 8) liste: scoate markerii (-, *, +) și păstrează textul
    t = _MD_RE_LIST_BULLET.sub("", t)

    # 9) liste numerotate: scoate "1)" / "1." dar păstrează textul
    # (dacă vrei să păstrezi numerele, spune-mi și schimbăm)
    t = _MD_RE_LIST_NUM.sub("", t)

    # 10) tabele: elimină linii cu | și separatori
    t = _MD_RE_TABLE_SEP.sub(" ", t)
    t = _MD_RE_TABLE.sub(" ", t)

    # 11) bold/italic markers
    t = _MD_RE_EMPH.sub("", t)

    # 12) HTML tags
    t = _MD_RE_HTML.sub(" ", t)

    # 13) curățare finală: spații, semne ciudate
    t = t.replace("\ufeff", " ")  # BOM
    t = re.sub(r"[•●▪◦]", " ", t)
    t = re.sub(r"[ \t]+", " ", t)  # doar spații/tabs
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    # 14) dacă rămâne prea "lipit", ajută un pic cu pauze
    # transformă " ; " / " : " în punctuație citibilă
    t = t.replace(" ;", ";").replace(" :", ":")

    # 15) numere de pagină standalone (linii cu doar 1-3 cifre) — artefacte OCR
    t = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", t)
    # "Exercițiul N:" rămas după filtrare → scos din TTS
    t = re.sub(r"Exerci[tț]iul\s+\d+\s*[:.]\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    # 16) separator de mii românesc (punct): 234.567 → 234 567
    # Pattern: 1-3 cifre, punct, exact 3 cifre — distinge de zecimale (e.g. 3.14)
    # Aplicăm de 2x pentru numere de forma 1.234.567
    t = re.sub(r"(\d{1,3})\.(\d{3})(?!\d)", r"\1 \2", t)
    t = re.sub(r"(\d{1,3})\.(\d{3})(?!\d)", r"\1 \2", t)

    return t


@dataclass
class ManualEntry:
    key: str
    file: str
    subject: str
    grade: int
    title: str
    publisher: str
    priority: int
    is_default: bool


_FRONT_START_PATTERNS = [
    r"\bUNITATEA\b", r"\bUnitatea\b",
    r"\bCAPITOLUL\b", r"\bCapitolul\b",
    r"\bLECȚIA\b", r"\bLecția\b",
    r"\bRecapitulare\b", r"\bEvaluare\b",
    r"\bExerciții\b", r"\bProbleme\b",
]

# Raw-markdown front-matter detection (runs before sanitize)
_RAW_HEADING_RE = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)
_RAW_CONTENT_KW_RE = re.compile(
    r'\b(?:UNITATEA|Unitatea|CAPITOLUL|Capitolul|LECȚIA|Lecția|Lecţia|'
    r'Activitate|Tema|Modulul|Recapitulare|Evaluare|Exerciţii|Exerciții)\b',
    re.UNICODE,
)
# TOC entries have "......." or trailing page numbers
_RAW_TOC_RE = re.compile(r'\.{3,}|(?:─{3,}|─{2,})\s*\d+\s*$')

_BOILERPLATE_LINE_PATTERNS = [
    r"^Acest manual\b",
    r"^Manualul școlar\b",
    r"\bproprietatea Ministerului\b",
    r"\bMinisterul Educației\b",
    r"\bOrdinul ministrului\b",
    r"\bprograma școlară\b",
    r"\bNumăr de pagini\b",
    r"^Disciplina:\b",
    r"^Clasa:\b",
    r"\bCopyright\b",
    r"\bToate drepturile rezervate\b",
    r"\bEditura\b",
    r"\bISBN\b",
    r"\bTipar\b",
    r"\bRedactor\b",
    r"\bGrafica\b",
    r"\bIlustra(ț|t)ii\b",
    r"\bwww\.",
    r"\bemail\b",
    r"^\*?\*?[Uu]nitatea\s*\d+\*?\*?\s*$",   # "**unitatea1**" / "Unitatea 3" standalone
]

_RE_BOILER = re.compile("|".join(_BOILERPLATE_LINE_PATTERNS), re.IGNORECASE)


def _skip_raw_front_matter(raw: str, max_scan: int = 80_000) -> str:
    """Skip publisher pages, CIP, Cuprins, Competente.

    Strategy 1 (fast): first `#` heading with a content keyword that isn't a TOC entry.
    Strategy 2 (fallback): find the *last* TOC line (ends with page number like 12-13),
      then scan forward for the first real content line.
    """
    scan = raw[:max_scan]

    # ── Strategy 1: books with # headings ────────────────────────────────────
    for m in _RAW_HEADING_RE.finditer(scan):
        heading_text = m.group(2).strip()
        if not _RAW_CONTENT_KW_RE.search(heading_text):
            continue
        if _RAW_TOC_RE.search(heading_text):
            continue
        pos = m.start()
        if pos > 200:
            return raw[pos:]

    # ── Strategy 2: books without # headings (plain-text MD) ─────────────────
    # TOC entry = line whose cleaned text ends with page numbers like "12-13" or "124"
    _toc_page_re = re.compile(
        r'[\s\.]{2,}\d{1,3}(?:-\d{1,3})?\s*$'   # "...... 12-13" or "... 124"
    )
    lines = scan.split('\n')
    last_toc_end = 0
    char_offset = 0
    for line in lines:
        # Strip markdown bold/italic for matching
        clean = re.sub(r'[\*_]', '', line).strip()
        if len(clean) > 10 and _toc_page_re.search(clean):
            last_toc_end = char_offset + len(line) + 1
        char_offset += len(line) + 1

    if last_toc_end > 500:
        # After the TOC, skip competente/methodology lines and find first real sentence.
        after = raw[last_toc_end:]
        content_off = _first_content_line(after)
        return raw[last_toc_end + content_off:]

    return raw


_REAL_CONTENT_RE = re.compile(
    r'^(?:'
    r'-\s+[A-ZĂÎÂȘȚŞŢ]'         # dialogue: "- Salut!"
    r'|\*\*\d+\.'                # bold numbered exercise: "**1. Citește"
    r'|[A-ZĂÎÂȘȚŞŢ][a-zăîâșțşţ]{3,}.{20,}'  # proper sentence >= 25 chars
    r')',
    re.UNICODE,
)
_SKIP_LINE_RE = re.compile(
    r'^(?:'
    r'\*\*\d{1,3}\*\*'           # bold lone page number: **7**
    r'|\d+\.\d[^a-z]*$'         # competente code lines: "1.1; 1.2;"
    r'|[A-Z ÎĂ]{4,}\:?$'        # all-caps labels: "VEI DISCUTA"
    r')',
    re.UNICODE,
)

def _first_content_line(text: str, max_search: int = 8_000) -> int:
    """Return the char offset of the first real-content line in `text`."""
    char_offset = 0
    for line in text[:max_search].split('\n'):
        stripped = line.strip()
        if stripped and not _SKIP_LINE_RE.match(stripped):
            if _REAL_CONTENT_RE.match(stripped):
                return char_offset
        char_offset += len(line) + 1
    return 0


_TEXT_TOC_RE = re.compile(r'\.{3,}|\s{3,}\d{1,3}\s*$')

def drop_front_matter(text: str, *, max_chars_scan: int = 20000) -> str:
    """Secondary fallback (post-sanitize): finds first content keyword that is
    NOT a TOC entry and returns text from that point.
    """
    scan = text[:max_chars_scan]
    lines = scan.split('\n')
    char_offset = 0
    for line in lines:
        stripped = line.strip()
        if stripped:
            for pat in _FRONT_START_PATTERNS:
                if re.search(pat, stripped):
                    # Skip TOC entries (trailing dots or page numbers)
                    if not _TEXT_TOC_RE.search(stripped):
                        pos = text.find(line, max(0, char_offset - 5))
                        if pos > 100:
                            return text[pos:].lstrip()
                    break
        char_offset += len(line) + 1
    return text

def filter_boilerplate_lines(text: str) -> str:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _RE_BOILER.search(s):
            continue
        out.append(s)
    return "\n".join(out)


# ── Filtrare clustere mini-TOC "Lecția N | Titlu" (Română CD Press) ───────────
_RO_LESSON_CLUSTER_RE = re.compile(
    r"^Lecți[ae]\s+\d+\s*\|", re.IGNORECASE
)

def _filter_ro_lesson_clusters(text: str) -> str:
    """Elimină grupuri de 2+ linii consecutive 'Lecția N | Titlu' (mini-TOC).

    O singură linie de acest tip este păstrată (poate fi titlul lecției active).
    Grupuri de 2 sau mai multe sunt tratate ca mini-TOC și eliminate.
    """
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        if _RO_LESSON_CLUSTER_RE.match(lines[i].strip()):
            run_start = i
            while i < len(lines) and _RO_LESSON_CLUSTER_RE.match(lines[i].strip()):
                i += 1
            run_len = i - run_start
            if run_len < 2:
                out.append(lines[run_start])   # singulară → păstrăm
            # run_len >= 2 → cluster TOC → sărim complet
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _trim_intro_pages(text: str) -> str:
    # încearcă să sară peste paginile de gardă / CIP
    markers = [
        "Cuprins",
        "UNITATEA",
        "Unitatea",
        "Capitolul",
        "Lecția",
        "Lecţia",
        "Activitate",
        "Exerciții",
        "Exerciţii",
    ]
    for m in markers:
        idx = text.find(m)
        if idx != -1 and idx > 4000:
            return text[idx:]
    return text



from pathlib import Path
import re

def load_md_clean_text(path: str | Path, *, keep_headings: bool = True) -> str:
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")

    # 0) Skip front matter in RAW markdown (most reliable — before any sanitizing)
    raw = _skip_raw_front_matter(raw)

    # 1) Sanitize Markdown → plain text for TTS
    text = sanitize_markdown_for_tts(raw, keep_headings=keep_headings)

    # 2) Secondary text-level front matter removal (fallback when raw scan missed)
    text = drop_front_matter(text)

    # 3) Remove remaining boilerplate lines (CIP, copyright, etc.)
    text = filter_boilerplate_lines(text)

    # 3b) Elimină clustere mini-TOC "Lecția N | Titlu" (specifice Română CD Press)
    text = _filter_ro_lesson_clusters(text)

    # 4) Clean scan artifacts
    _da_nu_re = re.compile(r"^(DA\s+NU\s*){2,}$", re.IGNORECASE)
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        # DA/NU simplu (câte un DA sau NU pe linie)
        if re.fullmatch(r"(DA|NU)(\s+(DA|NU))*", s, flags=re.IGNORECASE):
            continue
        # DA NU DA NU repetitiv (2+ perechi) — coloane de checkbox
        if _da_nu_re.match(s):
            continue
        # "Lista mea de verificare" / "Lista de verificare" — heading casetă
        if re.search(r"lista\s+(mea\s+de|de)\s+verificare", s, re.IGNORECASE):
            continue
        # Linii separator (doar cratime, liniuțe, bullets)
        if re.fullmatch(r"[\-\–\—•·\*\+]+", s):
            continue
        # Linii scurte (< 30 chars) compuse majoritar din majuscule → artefact titlu scan
        if len(s) < 30:
            alpha = [c for c in s if c.isalpha()]
            if alpha and sum(1 for c in alpha if c.isupper()) / len(alpha) > 0.75:
                continue
        s = re.sub(r"[\U00010000-\U0010FFFF]", " ", s)
        lines.append(s)

    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def load_md_chunks(path: str | Path, *, max_chars: int = 900, keep_headings: bool = True) -> list[str]:
    text = load_md_clean_text(path, keep_headings=keep_headings)
    all_chunks = chunk_text(text, max_chars=max_chars)
    # Filter out answer-key and test-solution blocks — they should never appear
    # as theory for the child (they contain solved exercises from the textbook).
    theory_chunks = [c for c in all_chunks if not _chunk_is_answer_block(c)]
    skipped = len(all_chunks) - len(theory_chunks)
    if skipped:
        print(f"   [{path}] filtrate {skipped} blocuri cu raspunsuri din {len(all_chunks)} chunk-uri")
    return theory_chunks



def _norm_pub(pub: str) -> str:
    p = (pub or "").strip().lower().replace(" ", "_")
    # normalize variants you saw
    if p in ("cd_press", "cdpress", "cd-press"):
        return "cd_press"
    if p in ("art_libri",):
        return "artlibri"
    if p in ("booklet",):
        return "booklet"
    return p

class ManualLibrary:
    def __init__(self, base_dir: Path | str = ".", manuals_dir: str = "manuale", index_file: str = "manual_index.json"):
        self.base_dir = Path(base_dir)
        self.manuals_dir = self.base_dir / manuals_dir
        self.index_path = self.base_dir / index_file
        self._entries: List[ManualEntry] = []
        self._load()

    def _load(self):
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        entries: List[ManualEntry] = []
        for key, v in data.items():
            entries.append(ManualEntry(
                key=key,
                file=v["file"],
                subject=v["subject"],
                grade=int(v["grade"]),
                title=v.get("title", v["file"]),
                publisher=_norm_pub(v.get("publisher", "")),
                priority=int(v.get("priority", 0)),
                is_default=bool(v.get("is_default", False)),
            ))
        self._entries = entries

    def list_manuals(self, subject: Optional[str] = None, grade: Optional[int] = None) -> List[ManualEntry]:
        items = self._entries
        if subject:
            items = [e for e in items if e.subject == subject]
        if grade is not None:
            items = [e for e in items if e.grade == int(grade)]
        # sort: default first, then priority, then publisher preference, then title
        pub_rank = {"edp": 300, "editura_didactica_si_pedagogica": 300, "cd_press": 200, "intuitext": 150}
        def score(e: ManualEntry):
            return (
                1 if e.is_default else 0,
                e.priority,
                pub_rank.get(e.publisher, 50),
                e.title,
            )
        return sorted(items, key=score, reverse=True)

    def get_default(self, subject: str, grade: int) -> Optional[ManualEntry]:
        for e in self._entries:
            if e.subject == subject and e.grade == int(grade) and e.is_default:
                return e
        return None

    def load_markdown(self, entry: ManualEntry) -> str:
        p = self.manuals_dir / entry.file
        return p.read_text(encoding="utf-8", errors="replace")
