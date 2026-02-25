# -*- coding: utf-8 -*-
"""
import_solutions_english.py
===========================
Importă exerciții din seria Oxford Solutions (Elementary → Upper-Intermediate)
în baza de date Avatar Tutor.

Parsează testele de progres și testele scurte (fișiere .doc) pentru:
  - Exerciții de gramatică (fill-in-blank, affirmative/negative)
  - Exerciții de vocabular (collocations, multiple choice)
  - Exerciții de citire (text scurt + True/False)

SKIP: Listening (necesită audio), Writing (necesită evaluare subiectivă).

Niveluri și grade în DB:
  Elementary        → grade 6  (A1-A2, 10 unități)
  Pre-Intermediate  → grade 7  (A2-B1)
  Intermediate      → grade 8  (B1-B2)  ← PDF only, skip
  Upper-Intermediate → grade 9 (B2-C1, 10 unități)

Utilizare:
  python import_solutions_english.py                      # toate nivelurile disponibile
  python import_solutions_english.py --level elementary   # doar Elementary
  python import_solutions_english.py --dry-run            # preview fără inserare în DB
  python import_solutions_english.py --db mydb.db         # alt fișier de bază de date

Cerințe:
  pip install pywin32   (Microsoft Word trebuie instalat pe acest calculator)
"""

import sys
import re
import json
import argparse
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# ── Căi de bază ───────────────────────────────────────────────────────────────
SOLUTIONS_BASE = Path(r"C:\Users\stefan.ionica\Documents\Temporare stick\books and cds")

ELEM_DIR   = SOLUTIONS_BASE / "Solutions 001 Elementary" / "Solutions Elementary"
PREINT_DIR = SOLUTIONS_BASE / "Solutions 002 Pre-Intermediate"
INT_DIR    = SOLUTIONS_BASE / "Solutions 003 Intermediate"
UPINT_DIR  = SOLUTIONS_BASE / "Solutions 004 Upper Intermediate"

# ── Teoria per unitate (Elementary) ──────────────────────────────────────────
# Text concis citit de avatar cu TTS (3-5 propoziții + exemple).
ELEM_THEORY = {
    1: (
        "Present Simple describes habits and routines. "
        "I/you/we/they + base verb: I love music, they play football. "
        "He/she/it + verb + s: She loves music, he plays football. "
        "Negative: I don't like, he doesn't watch. "
        "Family vocabulary: mother, father, sister, brother, cousin, aunt, uncle."
    ),
    2: (
        "Present Simple questions use DO or DOES. "
        "Do you play football? Yes, I do. No, I don't. "
        "Does she study? Yes, she does. No, she doesn't. "
        "Question words: What do you do? Where does he live? "
        "Hobbies: play tennis, go swimming, read books, listen to music."
    ),
    3: (
        "THERE IS describes one thing. THERE ARE describes more than one. "
        "There is a school near here. There are thirty students in my class. "
        "Negative: There isn't a park. There aren't any shops. "
        "Questions: Is there a gym? Are there any computers? "
        "School subjects: Maths, Science, History, Art, PE, English, IT."
    ),
    4: (
        "Present Continuous describes actions happening RIGHT NOW. "
        "Form: am/is/are + verb + ing. "
        "I am eating. She is wearing a blue dress. They are playing outside. "
        "Negative: He isn't sleeping. We aren't studying. "
        "Clothes vocabulary: jeans, jacket, shirt, dress, boots, trainers, coat."
    ),
    5: (
        "Comparative adjectives compare two things. "
        "Short adjectives add -er: tall → taller, big → bigger, hot → hotter. "
        "Long adjectives use MORE: interesting → more interesting. "
        "Irregular forms: good → better, bad → worse, far → farther. "
        "Superlatives: the tallest, the most interesting, the best, the worst."
    ),
    6: (
        "Past Simple regular verbs add -ED to describe finished actions. "
        "walk → walked, play → played, study → studied, stop → stopped. "
        "Negative: didn't + base verb: I didn't walk. She didn't study. "
        "Questions: Did you walk? Where did they go? "
        "Places in town: museum, cinema, market, park, hospital, station."
    ),
    7: (
        "Past Simple IRREGULAR verbs have special forms you must memorise. "
        "go → went, see → saw, eat → ate, take → took, have → had, come → came. "
        "buy → bought, make → made, write → wrote, give → gave, find → found. "
        "Negative and questions still use DIDN'T / DID + base form. "
        "I went to Paris. Did you see the film? Yes, I did."
    ),
    8: (
        "SOME is used in positive sentences. ANY in negatives and questions. "
        "I have some bread. There are some apples. "
        "There isn't any milk. Are there any eggs? "
        "HOW MUCH with uncountable nouns: How much sugar do you need? "
        "HOW MANY with countable nouns: How many students are there?"
    ),
    9: (
        "Present Perfect connects a past action with the present moment. "
        "Form: have/has + past participle: I have visited Rome. "
        "Key words: already, yet, ever, never, just, recently. "
        "Have you ever been to London? Yes, I've been there twice. "
        "I haven't finished yet. She has just arrived. They've already eaten."
    ),
    10: (
        "GOING TO expresses future plans and intentions. "
        "Form: am/is/are + going to + base verb. "
        "I'm going to study medicine. She's going to travel the world. "
        "Negative: He isn't going to come. We aren't going to watch TV. "
        "Jobs vocabulary: doctor, engineer, teacher, pilot, chef, architect, nurse."
    ),
}

ELEM_TITLES = {
    1: "My Network",     2: "Free Time",        3: "School Life",
    4: "Time to Party!", 5: "Wild!",             6: "Out and About",
    7: "World Famous",   8: "On the Menu",       9: "Journeys",
    10: "Just the Job",
}

ELEM_SKILLS = {
    1:  ["EN1_PRES_SIMPLE",    "EN1_VOCAB"],
    2:  ["EN1_PRES_SIMPLE",    "EN1_VOCAB"],
    3:  ["EN1_THERE_IS",       "EN1_VOCAB"],
    4:  ["EN1_PRES_CONT",      "EN1_VOCAB"],
    5:  ["EN1_COMPARATIVES",   "EN1_VOCAB"],
    6:  ["EN1_PAST_SIMPLE_REG","EN1_VOCAB"],
    7:  ["EN1_PAST_SIMPLE_IRR","EN1_VOCAB"],
    8:  ["EN1_QUANTIFIERS",    "EN1_VOCAB"],
    9:  ["EN1_PRES_PERFECT",   "EN1_VOCAB"],
    10: ["EN1_GOING_TO",       "EN1_VOCAB"],
}

# ── Upper-Intermediate unit info ──────────────────────────────────────────────
UPINT_TITLES = {
    1: "Identity",        2: "Mind",           3: "Justice",
    4: "Communication",   5: "Environment",    6: "Innovation",
    7: "Culture",         8: "Risk",           9: "Media",
    10: "The Future",
}

UPINT_SKILLS = {
    1:  ["EN4_INVERSION", "EN4_VOCAB"],
    2:  ["EN4_CLEFT",     "EN4_VOCAB"],
    3:  ["EN4_ADV_PASSIVE","EN4_VOCAB"],
    4:  ["EN4_CLEFT",     "EN4_VOCAB"],
    5:  ["EN4_INVERSION", "EN4_VOCAB"],
    6:  ["EN4_ADV_PASSIVE","EN4_VOCAB"],
    7:  ["EN4_CLEFT",     "EN4_VOCAB"],
    8:  ["EN4_INVERSION", "EN4_VOCAB"],
    9:  ["EN4_ADV_PASSIVE","EN4_VOCAB"],
    10: ["EN4_CLEFT",     "EN4_VOCAB"],
}

# ── English skill codes ───────────────────────────────────────────────────────
ENGLISH_SKILLS = [
    # Elementary — grade 6
    ("EN1_BE_VERB",        "Limba Engleză", 6, "Verb TO BE",               "I am / you are / he is — present & past",           []),
    ("EN1_PRES_SIMPLE",    "Limba Engleză", 6, "Present Simple",           "Habits & routines, he/she/it adds -s",               ["EN1_BE_VERB"]),
    ("EN1_THERE_IS",       "Limba Engleză", 6, "There is / There are",     "Describe existence of things/places",                 ["EN1_PRES_SIMPLE"]),
    ("EN1_PRES_CONT",      "Limba Engleză", 6, "Present Continuous",       "Actions happening now: am/is/are + -ing",             ["EN1_PRES_SIMPLE"]),
    ("EN1_COMPARATIVES",   "Limba Engleză", 6, "Comparatives/Superlatives","taller, more beautiful, the best",                   ["EN1_PRES_SIMPLE"]),
    ("EN1_PAST_SIMPLE_REG","Limba Engleză", 6, "Past Simple (regular)",    "walked, played, studied + -ed rules",                ["EN1_PRES_SIMPLE"]),
    ("EN1_PAST_SIMPLE_IRR","Limba Engleză", 6, "Past Simple (irregular)",  "went, saw, ate, took — must memorise",               ["EN1_PAST_SIMPLE_REG"]),
    ("EN1_QUANTIFIERS",    "Limba Engleză", 6, "Quantifiers",              "some/any, how much/many, a lot of",                  ["EN1_THERE_IS"]),
    ("EN1_PRES_PERFECT",   "Limba Engleză", 6, "Present Perfect",          "have/has + past participle, already/yet/ever",       ["EN1_PAST_SIMPLE_IRR"]),
    ("EN1_GOING_TO",       "Limba Engleză", 6, "Going to (future)",        "I'm going to + verb — plans and intentions",         ["EN1_PRES_CONT"]),
    ("EN1_VOCAB",          "Limba Engleză", 6, "Vocabulary (Elementary)",  "Family, hobbies, places, food, clothes, jobs",       []),
    ("EN1_READING",        "Limba Engleză", 6, "Reading (Elementary)",     "Short texts, True/False, comprehension questions",   ["EN1_VOCAB"]),
    # Pre-Intermediate — grade 7
    ("EN2_PAST_CONT",      "Limba Engleză", 7, "Past Continuous",          "was/were + -ing: I was sleeping when...",            ["EN1_PAST_SIMPLE_IRR"]),
    ("EN2_MODALS",         "Limba Engleză", 7, "Modal Verbs",              "can/could/must/should/might/have to",                ["EN1_PRES_SIMPLE"]),
    ("EN2_FUTURE",         "Limba Engleză", 7, "Future: will / going to",  "Predictions (will) vs plans (going to)",             ["EN1_GOING_TO"]),
    ("EN2_COND_1",         "Limba Engleză", 7, "1st Conditional",          "If + present simple → will + base",                 ["EN2_FUTURE"]),
    ("EN2_PP_CONT",        "Limba Engleză", 7, "Present Perfect Cont.",    "have/has been + -ing: I've been waiting",           ["EN1_PRES_PERFECT"]),
    ("EN2_PASSIVE",        "Limba Engleză", 7, "Passive Voice",            "be + past participle: The book was written by...",  ["EN2_PAST_CONT"]),
    ("EN2_VOCAB",          "Limba Engleză", 7, "Vocabulary (Pre-Int)",     "Feelings, environment, technology, health",          []),
    # Intermediate — grade 8
    ("EN3_COND_2_3",       "Limba Engleză", 8, "2nd & 3rd Conditional",   "If I were.../If I had been... would have",          ["EN2_COND_1"]),
    ("EN3_REPORTING",      "Limba Engleză", 8, "Reported Speech",          "She said (that) she was tired / asked if...",       ["EN2_MODALS"]),
    ("EN3_REL_CLAUSES",    "Limba Engleză", 8, "Relative Clauses",         "who, which, where, that, whose — defining/non-def",["EN3_REPORTING"]),
    ("EN3_GERUNDS_INF",    "Limba Engleză", 8, "Gerunds & Infinitives",   "enjoy + -ing / want + to + verb / stop to/doing",  ["EN3_REL_CLAUSES"]),
    ("EN3_VOCAB",          "Limba Engleză", 8, "Vocabulary (Intermediate)","Crime, science, money, media, travel",              []),
    # Upper-Intermediate — grade 9
    ("EN4_INVERSION",      "Limba Engleză", 9, "Inversion",               "Not only did..., Rarely have I..., Hardly had...", ["EN3_COND_2_3"]),
    ("EN4_CLEFT",          "Limba Engleză", 9, "Cleft Sentences",         "It is/was... that... / What I need is...",          ["EN3_REPORTING"]),
    ("EN4_ADV_PASSIVE",    "Limba Engleză", 9, "Advanced Passive",        "Complex passives: it is said that, is thought to", ["EN3_COND_2_3"]),
    ("EN4_VOCAB",          "Limba Engleză", 9, "Vocabulary (Upper-Int)",  "Abstract nouns, collocations, formal register",     []),
]

# ── DOC text extraction via Word COM ─────────────────────────────────────────
_word_app = None   # singleton Word COM instance

def _get_word():
    global _word_app
    if _word_app is None:
        try:
            import win32com.client
            _word_app = win32com.client.Dispatch("Word.Application")
            _word_app.Visible = False
            _word_app.DisplayAlerts = False
        except ImportError:
            print("ERROR: pywin32 nu este instalat. Rulați: pip install pywin32")
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: Nu pot porni Word COM: {e}")
            sys.exit(1)
    return _word_app


def extract_doc_text(path: str) -> str:
    """Extrage textul dintr-un fișier .doc/.docx via Word COM."""
    abs_path = str(Path(path).resolve())
    word = _get_word()
    try:
        doc = word.Documents.Open(abs_path)
        text = doc.Content.Text
        doc.Close(False)
        return text
    except Exception as e:
        print(f"    WARN: Nu pot deschide {Path(path).name}: {e}")
        return ""


def close_word():
    global _word_app
    if _word_app is not None:
        try:
            _word_app.Quit()
        except Exception:
            pass
        _word_app = None


# ── Parser exerciții ──────────────────────────────────────────────────────────
# Secțiuni care se SKIP complet
_SKIP = frozenset({"listening", "writing", "tapescript"})
# Secțiuni de procesat
_PROCESS = frozenset({"grammar", "vocabulary", "reading", "comprehension", "general"})

# Regex pentru item numerotat: "3 My sister ___ tennis. (love)"
_ITEM_RE = re.compile(r'^(\d{1,2})\s{1,4}(.{5,150})$')


def _split_sections(raw_text: str) -> list[tuple[str, list[str]]]:
    """Împarte textul în (section_name, [lines]) după header-uri de secțiune."""
    # Word COM folosește \r ca separator de paragraf, uneori \n sau \x07
    lines = re.split(r'[\r\n\x07\x0c]+', raw_text)

    sections: list[tuple[str, list[str]]] = [("general", [])]
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Header detection: linie scurtă, doar litere și spații
        if 3 <= len(stripped) <= 30 and re.match(r'^[A-Za-z &/]+$', stripped):
            norm = stripped.lower().strip()
            if norm in _SKIP or norm in _PROCESS:
                sections.append((norm, []))
                continue
        sections[-1][1].append(stripped)
    return sections


# Cuvinte care indică linie de instrucțiune (nu exercițiu)
_INSTR_WORDS = frozenset({
    "complete", "choose", "match", "write", "read", "look", "decide",
    "circle", "underline", "listen", "answer", "correct", "find",
    "mark", "tick", "fill", "order", "put", "use", "rewrite",
    "total", "marks", "exercise", "ex",
})


def _is_instruction(text: str) -> bool:
    words = text.lower().split()
    return bool(words) and words[0] in _INSTR_WORDS and len(words) < 18


def _extract_items(sections: list[tuple[str, list[str]]],
                   skip_skip_secs: bool) -> list[tuple[str, int, str]]:
    """Returnează (section, num, text) pentru fiecare item numerotat găsit."""
    items = []
    for sec_name, lines in sections:
        if skip_skip_secs and sec_name in _SKIP:
            continue
        for line in lines:
            m = _ITEM_RE.match(line)
            if not m:
                continue
            num = int(m.group(1))
            text = m.group(2).strip()
            if num > 40 or _is_instruction(text):
                continue
            items.append((sec_name, num, text))
    return items


def _build_key_dict(key_sections: list[tuple[str, list[str]]]) -> dict:
    """Construiește dict (section, num) → answer_text din textul cheii."""
    key_dict: dict[tuple, str] = {}
    for sec, num, text in _extract_items(key_sections, skip_skip_secs=False):
        k = (sec, num)
        if k in key_dict:
            continue
        # Ia primul fragment (înainte de / sau ,)
        answer = re.split(r'\s*/\s*|\s*(or|OR)\s*', text)[0].strip()
        # Elimină adnotări de punctaj
        answer = re.sub(r'\(\d+\s*marks?\)', '', answer).strip()
        answer = answer.strip(' .,;')
        if answer and len(answer) <= 80:
            key_dict[k] = answer
    return key_dict


def _find_answer(key_dict: dict, section: str, num: int) -> str | None:
    """Caută răspunsul în cheie — mai întâi exact, apoi fallback pe num."""
    if (section, num) in key_dict:
        return key_dict[(section, num)]
    # Fallback: dacă există un singur răspuns pentru acest num
    matches = {k: v for k, v in key_dict.items() if k[1] == num}
    if len(matches) == 1:
        return next(iter(matches.values()))
    return None


def _clean_enunt(text: str) -> str:
    text = re.sub(r'_{2,}', '___', text)           # normalizează blank-uri
    text = re.sub(r'\(\d+\s*marks?\)', '', text)    # elimină "(7 marks)"
    text = re.sub(r'\s+', ' ', text).strip(' .,')   # whitespace redundant
    return text


def parse_test_pair(test_path: str, key_path: str) -> list[dict]:
    """Parsează o pereche (test.doc, key.doc) → listă de exerciții.

    Returnează dicts cu cheile: enunt, raspuns, section, dificultate.
    """
    test_text = extract_doc_text(test_path)
    key_text  = extract_doc_text(key_path)

    if not test_text or not key_text:
        return []

    test_secs = _split_sections(test_text)
    key_secs  = _split_sections(key_text)

    test_items = _extract_items(test_secs, skip_skip_secs=True)
    key_dict   = _build_key_dict(key_secs)

    exercises: list[dict] = []
    seen_enunts: set[str] = set()

    for sec, num, enunt_raw in test_items:
        answer = _find_answer(key_dict, sec, num)
        if not answer:
            continue

        enunt = _clean_enunt(enunt_raw)
        if len(enunt) < 8:
            continue

        # Deduplicare
        key = enunt.lower()
        if key in seen_enunts:
            continue
        seen_enunts.add(key)

        # Dificultate: grammar = 2, vocabulary = 1, reading = 2
        diff = 1 if sec == "vocabulary" else 2

        exercises.append({
            "enunt":       enunt,
            "raspuns":     answer,
            "section":     sec,
            "dificultate": diff,
        })

    return exercises


# ── Hint-uri per tip de secțiune ─────────────────────────────────────────────
def _hints(section: str, grammar_topic: str) -> tuple[str, str, str]:
    if section == "vocabulary":
        return (
            "Look at the context. What type of word fits here?",
            "Think about collocations — words that naturally go together.",
            "Check your vocabulary list for this unit.",
        )
    if section in ("reading", "comprehension"):
        return (
            "Read the text carefully before answering True or False.",
            "Find the key sentence in the text that answers this.",
            "True = the text says this. False = the text contradicts this.",
        )
    # grammar
    short_topic = grammar_topic[:60] if grammar_topic else "this grammar rule"
    return (
        f"Think about: {short_topic}.",
        "Check the subject — does the verb agree with it?",
        "Look for time expressions (yesterday, now, tomorrow) for the tense.",
    )


# ── Inserare în DB ────────────────────────────────────────────────────────────
def ensure_english_skills(db):
    """Inserează (INSERT OR IGNORE) toate skill codes pentru engleză."""
    for code, subj, grade, name, desc, prereq in ENGLISH_SKILLS:
        db.conn.execute(
            """INSERT OR IGNORE INTO skills
               (code, subject, grade, name, description, prereq_codes)
               VALUES (?,?,?,?,?,?)""",
            (code, subj, grade, name, desc, json.dumps(prereq)),
        )
    db.conn.commit()
    print(f"  Skills: {len(ENGLISH_SKILLS)} English skill codes OK")


def _get_or_create_lesson(db, title: str, subject: str, grade: int,
                           unit: int, theory: str, summary: str) -> int:
    """Returnează ID-ul lecției existente sau o creează."""
    row = db.conn.execute(
        "SELECT id FROM lessons WHERE subject=? AND grade=? AND title=?",
        (subject, grade, title),
    ).fetchone()
    if row:
        return int(row["id"])

    cur = db.conn.execute(
        """INSERT INTO lessons (title, subject, grade, unit, order_in_unit, theory, summary)
           VALUES (?,?,?,?,?,?,?)""",
        (title, subject, grade, unit, 1, theory, summary),
    )
    db.conn.commit()
    return int(cur.lastrowid)


def _insert_exercises(db, lesson_id: int, exercises: list[dict],
                       phase: str, skill_codes: list[str],
                       grammar_topic: str, dry_run: bool) -> int:
    """Inserează exerciții în DB. Returnează numărul inserat."""
    count = 0
    for ex in exercises:
        h1, h2, h3 = _hints(ex["section"], grammar_topic)
        expl = f"Correct answer: {ex['raspuns']}. ({grammar_topic[:50]})"
        if not dry_run:
            db.add_exercise(
                lesson_id=lesson_id,
                phase=phase,
                enunt=ex["enunt"],
                raspuns=ex["raspuns"],
                hint1=h1,
                hint2=h2,
                hint3=h3,
                explicatie=expl,
                dificultate=ex.get("dificultate", 2),
                skill_codes=skill_codes,
            )
        count += 1
    return count


# ── Import Elementary ─────────────────────────────────────────────────────────
def import_elementary(db, dry_run: bool = False) -> tuple[int, int]:
    """Importă Solutions Elementary. Returnează (n_lessons, n_exercises)."""
    grade   = 6
    subject = "Limba Engleză"
    prog    = ELEM_DIR / "progress_tests"
    short   = ELEM_DIR / "shorttests"

    if not ELEM_DIR.exists():
        print(f"  ERROR: folder Elementary nu există: {ELEM_DIR}")
        return 0, 0

    total_lessons = total_exercises = 0

    for unit in range(1, 11):
        title  = ELEM_UNITS[unit]
        theory = ELEM_THEORY[unit]
        skills = ELEM_SKILLS[unit]

        print(f"  Unit {unit:2d}: {title}")

        lesson_id = _get_or_create_lesson(
            db, title, subject, grade, unit, theory,
            f"Unit {unit} — {title} | Solutions Elementary"
        )

        # Progress test → practică (2/3) + posttest (1/3)
        pt  = prog / f"sol_elem_progresstest_{unit}.doc"
        ptk = prog / f"sol_elem_progresstest_{unit}_key.doc"
        if pt.exists() and ptk.exists():
            exs = parse_test_pair(str(pt), str(ptk))
            mid = max(1, len(exs) * 2 // 3)
            n = _insert_exercises(db, lesson_id, exs[:mid],  "practice", skills, theory[:80], dry_run)
            m = _insert_exercises(db, lesson_id, exs[mid:],  "posttest", skills, theory[:80], dry_run)
            print(f"          progress: {n} practice + {m} posttest")
            total_exercises += n + m
        else:
            print(f"          WARN: progress test lipsă ({pt.name})")

        # Short test → pretest
        st  = short / f"sol_elem_shorttest_{unit:02d}.doc"
        stk = short / f"sol_elem_shorttest_{unit:02d}_key.doc"
        if st.exists() and stk.exists():
            exs = parse_test_pair(str(st), str(stk))
            n = _insert_exercises(db, lesson_id, exs, "pretest", skills, theory[:80], dry_run)
            print(f"          short:    {n} pretest")
            total_exercises += n
        else:
            print(f"          WARN: short test lipsă ({st.name})")

        total_lessons += 1

    return total_lessons, total_exercises


# ── Import Pre-Intermediate ───────────────────────────────────────────────────
def import_pre_intermediate(db, dry_run: bool = False) -> tuple[int, int]:
    """Importă Solutions Pre-Intermediate (test combinat). Returnează (n_lessons, n_exercises)."""
    grade   = 7
    subject = "Limba Engleză"
    folder  = PREINT_DIR / "test"

    if not folder.exists():
        print(f"  WARN: folder Pre-Int lipsă: {folder}")
        return 0, 0

    test_file = folder / "Solutions Pre-Intermediate Progress Test A.doc"
    key_file  = folder / "Sol tests pre-int progress answer key A.doc"

    if not test_file.exists() or not key_file.exists():
        print("  WARN: fișierele DOC Pre-Int lipsesc")
        return 0, 0

    theory = (
        "Pre-Intermediate grammar covers: past continuous (was/were + -ing), "
        "modal verbs (can/could/must/should), future (will / going to), "
        "first conditional (if + present → will), "
        "present perfect continuous (have/has been + -ing), "
        "passive voice (be + past participle)."
    )
    skills  = ["EN2_PAST_CONT", "EN2_MODALS", "EN2_FUTURE", "EN2_COND_1", "EN2_VOCAB"]

    lesson_id = _get_or_create_lesson(
        db, "Pre-Intermediate Review", subject, grade, 1, theory,
        "A2-B1 Grammar & Vocabulary Review | Solutions Pre-Intermediate"
    )

    exs = parse_test_pair(str(test_file), str(key_file))
    mid = max(1, len(exs) * 2 // 3)
    n = _insert_exercises(db, lesson_id, exs[:mid], "practice", skills, theory[:80], dry_run)
    m = _insert_exercises(db, lesson_id, exs[mid:], "posttest", skills, theory[:80], dry_run)
    print(f"  Pre-Int: {n} practice + {m} posttest")

    return 1, n + m


# ── Import Upper-Intermediate ─────────────────────────────────────────────────
def import_upper_intermediate(db, dry_run: bool = False) -> tuple[int, int]:
    """Importă Solutions Upper-Intermediate (short tests per unitate). Returnează (n_lessons, n_exercises)."""
    grade   = 9
    subject = "Limba Engleză"
    folder  = UPINT_DIR / "tests"

    if not folder.exists():
        print(f"  WARN: folder Upper-Int lipsă: {folder}")
        return 0, 0

    key_file = folder / "Sol Upper Int short  tests answer key.doc"
    if not key_file.exists():
        # try without double space
        key_file = folder / "Sol Upper Int short tests answer key.doc"

    key_text = extract_doc_text(str(key_file)) if key_file.exists() else ""
    if not key_text:
        print("  WARN: Upper-Int answer key lipsă sau nu poate fi citit")
        # Proceed without a global key — individual unit files may still work
        key_secs = []
    else:
        key_secs = _split_sections(key_text)

    global_key_dict = _build_key_dict(key_secs)

    total_lessons = total_exercises = 0

    for unit in range(1, 11):
        title  = UPINT_TITLES.get(unit, f"Unit {unit}")
        skills = UPINT_SKILLS.get(unit, ["EN4_VOCAB"])
        theory = f"Upper-Intermediate Unit {unit}: {title}. Advanced grammar and vocabulary."

        print(f"  Unit {unit:2d}: {title}")

        lesson_id = _get_or_create_lesson(
            db, title, subject, grade, unit, theory,
            f"Unit {unit} — {title} | Solutions Upper-Intermediate"
        )

        # Short test DOC per unitate
        st = folder / f"Sol Upper Int tests short tests unit {unit}.doc"
        if st.exists():
            test_text = extract_doc_text(str(st))
            if test_text:
                test_secs  = _split_sections(test_text)
                test_items = _extract_items(test_secs, skip_skip_secs=True)

                # Combină cheia globală cu cea din fișierul de test (dacă există și în el răspunsuri)
                local_key  = _build_key_dict(test_secs)
                combined_key = {**global_key_dict, **local_key}

                exs: list[dict] = []
                seen: set[str] = set()
                for sec, num, raw in test_items:
                    answer = _find_answer(combined_key, sec, num)
                    if not answer:
                        continue
                    enunt = _clean_enunt(raw)
                    if len(enunt) < 8 or enunt.lower() in seen:
                        continue
                    seen.add(enunt.lower())
                    exs.append({"enunt": enunt, "raspuns": answer,
                                "section": sec, "dificultate": 3})

                mid = max(1, len(exs) * 2 // 3)
                n = _insert_exercises(db, lesson_id, exs[:mid], "practice", skills, theory[:80], dry_run)
                m = _insert_exercises(db, lesson_id, exs[mid:], "posttest", skills, theory[:80], dry_run)
                print(f"          {n} practice + {m} posttest")
                total_exercises += n + m
        else:
            print(f"          WARN: {st.name} lipsă")

        total_lessons += 1

    return total_lessons, total_exercises


# ── Constante (alias pentru ELEM_TITLES cu cheie int) ────────────────────────
ELEM_UNITS = ELEM_TITLES


# ── Entry point CLI ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Importă Oxford Solutions în Avatar Tutor DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db",    default="production.db",
                        help="Calea DB (implicit: production.db)")
    parser.add_argument("--level", default="all",
                        choices=["all", "elementary", "pre-intermediate", "upper-intermediate"],
                        help="Nivelul de importat (implicit: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afișează ce s-ar importa fără a scrie în DB")
    args = parser.parse_args()

    print("=" * 60)
    print("Oxford Solutions → Avatar Tutor Import")
    print(f"  DB:      {args.db}")
    print(f"  Level:   {args.level}")
    print(f"  Dry-run: {args.dry_run}")
    print("=" * 60)

    from database import Database
    db = Database(args.db)

    ensure_english_skills(db)

    total_l = total_e = 0

    if args.level in ("all", "elementary"):
        print("\n── Elementary (grade 6, A1-A2) ──────────────────────────")
        l, e = import_elementary(db, args.dry_run)
        total_l += l; total_e += e
        print(f"  → {l} lecții, {e} exerciții")

    if args.level in ("all", "pre-intermediate"):
        print("\n── Pre-Intermediate (grade 7, A2-B1) ───────────────────")
        l, e = import_pre_intermediate(db, args.dry_run)
        total_l += l; total_e += e
        print(f"  → {l} lecții, {e} exerciții")

    if args.level in ("all", "upper-intermediate"):
        print("\n── Upper-Intermediate (grade 9, B2-C1) ─────────────────")
        l, e = import_upper_intermediate(db, args.dry_run)
        total_l += l; total_e += e
        print(f"  → {l} lecții, {e} exerciții")

    close_word()
    db.close()

    print("\n" + "=" * 60)
    print(f"TOTAL: {total_l} lecții, {total_e} exerciții importate")
    if args.dry_run:
        print("(DRY-RUN — nimic nu a fost scris în DB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
