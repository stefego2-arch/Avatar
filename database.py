from __future__ import annotations

import sqlite3
import json
from datetime import datetime
from typing import Optional, Iterable


class Database:
    def __init__(self, db_path: str = "production.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()
        self._seed_demo_data()
        self._ensure_all_grades()           # mereu - adauga lectii pt clasele lipsa
        self._ensure_default_skills()       # mereu - adauga skill codes cu INSERT OR IGNORE
        self._ensure_lesson_numere_0_5()    # mereu - migrare lecție clasa I matematică 0–5
        self._ensure_grade1_from_manual()   # mereu - populare 24 lecții clasa I CD PRESS
        print(f"Database: {db_path}")


    # ───────────────────────────────────────────────────────────────────
    # Schema
    # ───────────────────────────────────────────────────────────────────

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                age         INTEGER,
                grade       INTEGER NOT NULL DEFAULT 1,
                level       INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    DEFAULT (datetime('now')),
                last_active TEXT
            );

            CREATE TABLE IF NOT EXISTS lessons (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT    NOT NULL,
                subject     TEXT    NOT NULL,
                grade       INTEGER NOT NULL,
                unit        INTEGER NOT NULL DEFAULT 1,
                order_in_unit INTEGER DEFAULT 1,
                theory      TEXT,
                summary     TEXT,
                objectives  TEXT,
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS exercises (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id   INTEGER NOT NULL REFERENCES lessons(id),
                type        TEXT    NOT NULL DEFAULT 'text',
                phase       TEXT    NOT NULL DEFAULT 'practice',
                enunt       TEXT    NOT NULL,
                raspuns     TEXT    NOT NULL,
                choices     TEXT,
                hint1       TEXT,
                hint2       TEXT,
                hint3       TEXT,
                explicatie  TEXT,
                dificultate INTEGER DEFAULT 1,
                skill_codes TEXT,   -- JSON list: ["MATH_ADD_10", ...]
                created_at  TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS micro_quiz (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                lesson_id   INTEGER NOT NULL REFERENCES lessons(id),
                chunk_index INTEGER NOT NULL,
                type        TEXT    NOT NULL DEFAULT 'truefalse',
                enunt       TEXT    NOT NULL,
                raspuns     TEXT    NOT NULL,
                choices     TEXT,
                explicatie  TEXT,
                skill_codes TEXT,
                UNIQUE(lesson_id, chunk_index)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                lesson_id   INTEGER NOT NULL REFERENCES lessons(id),
                phase       TEXT    DEFAULT 'practice',
                score       REAL,
                total_q     INTEGER DEFAULT 0,
                correct_q   INTEGER DEFAULT 0,
                duration_s  INTEGER DEFAULT 0,
                started_at  TEXT    DEFAULT (datetime('now')),
                ended_at    TEXT,
                attention_pct REAL DEFAULT 100.0
            );

            CREATE TABLE IF NOT EXISTS session_answers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  INTEGER NOT NULL REFERENCES sessions(id),
                exercise_id INTEGER NOT NULL REFERENCES exercises(id),
                user_answer TEXT,
                is_correct  INTEGER DEFAULT 0,
                hints_used  INTEGER DEFAULT 0,
                time_sec    REAL    DEFAULT 0,
                answered_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS progress (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL REFERENCES users(id),
                lesson_id       INTEGER NOT NULL REFERENCES lessons(id),
                best_score      REAL    DEFAULT 0,
                attempts        INTEGER DEFAULT 0,
                passed          INTEGER DEFAULT 0,
                current_level   INTEGER DEFAULT 1,
                consecutive_good INTEGER DEFAULT 0,
                last_attempt    TEXT,
                UNIQUE(user_id, lesson_id)
            );

            -- Skill graph minimal
            CREATE TABLE IF NOT EXISTS skills (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                code        TEXT UNIQUE NOT NULL,
                subject     TEXT NOT NULL,
                grade       INTEGER NOT NULL,
                name        TEXT NOT NULL,
                description TEXT,
                prereq_codes TEXT  -- JSON list
            );

            CREATE TABLE IF NOT EXISTS user_skill (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(id),
                skill_code  TEXT NOT NULL REFERENCES skills(code),
                mastery     REAL DEFAULT 0.0,
                attempts    INTEGER DEFAULT 0,
                correct     INTEGER DEFAULT 0,
                last_update TEXT,
                UNIQUE(user_id, skill_code)
            );

            -- Spaced repetition: exerciții greșite reapar în sesiuni viitoare
            CREATE TABLE IF NOT EXISTS user_exercise_stats (
                user_id     INTEGER NOT NULL,
                exercise_id INTEGER NOT NULL,
                wrong_count INTEGER DEFAULT 0,
                retry_after TEXT,   -- ISO date "YYYY-MM-DD", NULL = nu e programat
                PRIMARY KEY (user_id, exercise_id)
            );
        """)
        self._conn.commit()
        self._migrate_schema()

    def _migrate_schema(self):
        """Adauga coloane noi la tabelele existente (migrare non-destructiva)."""
        migrations = [
            # stars per lectie (1-3 stele)
            "ALTER TABLE progress ADD COLUMN stars INTEGER DEFAULT 0",
            # stele totale + streak zilnic pentru user
            "ALTER TABLE users ADD COLUMN total_stars INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN streak_days INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN streak_last_date TEXT",
            # track de progression: 'school' | 'admission' | 'olympiad'
            "ALTER TABLE users ADD COLUMN track TEXT DEFAULT 'school'",
            # skill mastery tracking extins (progression framework)
            "ALTER TABLE user_skill ADD COLUMN mastery_level INTEGER DEFAULT 0",
            "ALTER TABLE user_skill ADD COLUMN last_practiced TEXT",
            "ALTER TABLE user_skill ADD COLUMN avg_time REAL DEFAULT 0.0",
            "ALTER TABLE user_skill ADD COLUMN skill_streak INTEGER DEFAULT 0",
            # ITS v2: tier 4 "Boss Fight" + sursa examen real
            "ALTER TABLE exercises ADD COLUMN difficulty_tier INTEGER DEFAULT 1",
            "ALTER TABLE exercises ADD COLUMN source_exam TEXT",
        ]
        for sql in migrations:
            try:
                self._conn.execute(sql)
            except Exception:
                pass  # coloana exista deja
        # Backfill: copiază dificultate → difficulty_tier pentru exerciții existente
        try:
            self._conn.execute(
                "UPDATE exercises SET difficulty_tier = dificultate "
                "WHERE difficulty_tier IS NULL OR difficulty_tier = 1"
            )
        except Exception:
            pass
        self._conn.commit()

    # ───────────────────────────────────────────────────────────────────
    # Seed demo
    # ───────────────────────────────────────────────────────────────────

    def _normalize_subject(self, subject: str) -> str:
        s = (subject or "").strip().lower()
        # simplifică diacritice ca să potrivim și "Matematica"
        s2 = (
            s.replace("ă", "a")
            .replace("â", "a")
            .replace("î", "i")
            .replace("ș", "s")
            .replace("ş", "s")
            .replace("ț", "t")
            .replace("ţ", "t")
        )
        if s2 in ("matematica", "mate"):
            return "Matematică"
        if s2 in ("romana", "limba romana", "lb romana", "romană", "limba română"):
            return "Limba Română"
        if s2 in ("engleza", "limba engleza", "lb engleza", "english"):
            return "Limba Engleză"
        # fallback: încearcă să păstrezi cum a venit
        return subject

    def get_next_lesson(self, user_id: int, grade: int, subject: str):
        """
        Next lesson = prima lecție (grade, subject) care NU e trecută (progress.passed != 1).
        Dacă nu există progres, întoarce prima lecție din ordine.
        """
        subject_norm = self._normalize_subject(subject)

        cur = self._conn.cursor()

        # 1) prima lecție ne-trecută (lipsește din progress sau passed=0)
        cur.execute(
            """
            SELECT l.*
            FROM lessons l
            LEFT JOIN progress p
              ON p.lesson_id = l.id AND p.user_id = ?
            WHERE l.grade = ? AND l.subject = ?
              AND COALESCE(p.passed, 0) = 0
            ORDER BY l.unit ASC, l.order_in_unit ASC, l.id ASC
            LIMIT 1
            """,
            (user_id, grade, subject_norm),
        )
        row = cur.fetchone()
        if row:
            return dict(row)

        # 2) fallback: dacă toate sunt passed=1, întoarce ultima (sau prima) ca "review"
        cur.execute(
            """
            SELECT l.*
            FROM lessons l
            WHERE l.grade = ? AND l.subject = ?
            ORDER BY l.unit DESC, l.order_in_unit DESC, l.id DESC
            LIMIT 1
            """,
            (grade, subject_norm),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    @property
    def conn(self):
        return self._conn



    def _seed_demo_data(self):
        count = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count > 0:
            return
        print("📦 Populare DB cu date demo...")
        self._seed_users()
        self._seed_lessons_math()
        self._seed_lessons_romanian()
        self._seed_micro_quiz_demo()
        self._conn.commit()
        print("✅ Date demo create")

    def _seed_users(self):
        users = [
            ("Elev Demo", 7, 1),
            ("Maria", 8, 2),
            ("Ion", 7, 1),
            ("Giorgel", 7, 1),
        ]
        for name, age, grade in users:
            self._conn.execute(
                "INSERT INTO users (name, age, grade) VALUES (?,?,?)",
                (name, age, grade),
            )

    def _ensure_default_skills(self):
        """Inserează toate skill codes standard (INSERT OR IGNORE).
        Apelat mereu la startup — adaugă skills noi fără a le suprascrie pe cele existente.

        Structură skill code: {SUBJ}{GRAD}_{DOMENIU}
          MATH = Matematică, RO = Limba Română
          1-5 = clasa
        """
        skills = [
            # ── Clasa 1 — Matematică ─────────────────────────────────────
            ("MATH1_COUNT_10",   "Matematică", 1, "Numără 0-10",
             "Recunoaște și numără obiectele 0-10", []),
            ("MATH1_ADD_10",     "Matematică", 1, "Adunare până la 10",
             "Adunări fără trecere peste ordin", ["MATH1_COUNT_10"]),
            ("MATH1_SUB_10",     "Matematică", 1, "Scădere până la 10",
             "Scăderi simple", ["MATH1_COUNT_10"]),
            # ── Clasa 1 — Română ─────────────────────────────────────────
            ("RO1_LETTERS",      "Limba Română", 1, "Litere mari și mici",
             "Recunoaște și scrie literele alfabetului", []),
            ("RO1_SYLLABLES",    "Limba Română", 1, "Silabe",
             "Desparte cuvintele în silabe", ["RO1_LETTERS"]),
            # ── Clasa 2 — Matematică ─────────────────────────────────────
            ("MATH2_UNITS_TENS", "Matematică", 2, "Zeci și unități",
             "Descompune numerele în zeci și unități", ["MATH1_COUNT_10"]),
            ("MATH2_ADD_100",    "Matematică", 2, "Adunare până la 100",
             "Adunare cu și fără transport", ["MATH2_UNITS_TENS"]),
            ("MATH2_SUB_100",    "Matematică", 2, "Scădere până la 100",
             "Scădere cu și fără împrumut", ["MATH2_UNITS_TENS"]),
            ("MATH2_COMPARE",    "Matematică", 2, "Comparare numere",
             "Compară și ordonează numere 0-100", ["MATH2_UNITS_TENS"]),
            # ── Clasa 2 — Română ─────────────────────────────────────────
            ("RO2_SENTENCE",     "Limba Română", 2, "Propoziția",
             "Identifică subiect și predicat", ["RO1_SYLLABLES"]),
            ("RO2_NOUN",         "Limba Română", 2, "Substantivul",
             "Recunoaște substantivele", ["RO2_SENTENCE"]),
            # ── Clasa 3 — Matematică (10 skill codes) ───────────────────
            ("MATH3_MULT_TABLE", "Matematică", 3, "Tabla înmulțirii",
             "Memorează și aplică tabla înmulțirii 1-10", ["MATH2_ADD_100"]),
            ("MATH3_DIV_BASIC",  "Matematică", 3, "Împărțire exactă",
             "Împarte numere la 1-10, verifică cu înmulțire", ["MATH3_MULT_TABLE"]),
            ("MATH3_MULT_2DIGIT","Matematică", 3, "Înmulțire cu 2 cifre",
             "Înmulțire număr 2 cifre × 1 cifră", ["MATH3_MULT_TABLE"]),
            ("MATH3_ADD_1000",   "Matematică", 3, "Adunare până la 1000",
             "Adunare cu transport, numere 3 cifre", ["MATH2_ADD_100"]),
            ("MATH3_SUB_1000",   "Matematică", 3, "Scădere până la 1000",
             "Scădere cu împrumut, numere 3 cifre", ["MATH2_SUB_100"]),
            ("MATH3_FRACTION",   "Matematică", 3, "Fracții simple",
             "Înțelege și compară 1/2, 1/4, 3/4", []),
            ("MATH3_ORDER",      "Matematică", 3, "Ordonarea numerelor",
             "Ordonează crescător și descrescător", ["MATH3_ADD_1000"]),
            ("MATH3_PERIMETER",  "Matematică", 3, "Perimetrul figurilor",
             "Calculează perimetrul pătratului și dreptunghiului", ["MATH3_ADD_1000"]),
            ("MATH3_WORD_PROB",  "Matematică", 3, "Probleme text",
             "Rezolvă probleme cu o operație", ["MATH3_ADD_1000"]),
            ("MATH3_MEASURE",    "Matematică", 3, "Unități de măsură",
             "Conversii simple m↔cm, kg, L", []),
            # ── Clasa 3 — Română ─────────────────────────────────────────
            ("RO3_VERB",         "Limba Română", 3, "Verbul",
             "Identifică verbele și conjugă la prezent", ["RO2_SENTENCE"]),
            ("RO3_ADJECTIVE",    "Limba Română", 3, "Adjectivul",
             "Recunoaște adjectivele și acordul", ["RO2_NOUN"]),
            # ── Clasa 4 — Matematică ─────────────────────────────────────
            ("MATH4_LARGE_NUM",  "Matematică", 4, "Numere până la 1 000 000",
             "Scrie, citește și compară numere mari", ["MATH3_ADD_1000"]),
            ("MATH4_FRACTION_OP","Matematică", 4, "Operații cu fracții",
             "Adunare și scădere de fracții cu același numitor", ["MATH3_FRACTION"]),
            ("MATH4_DECIMALS",   "Matematică", 4, "Numere zecimale",
             "Citește și compară numere zecimale", ["MATH4_FRACTION_OP"]),
            # ── Clasa 4 — Română ─────────────────────────────────────────
            ("RO4_NARRATIVE",    "Limba Română", 4, "Textul narativ",
             "Identifică structura intro-cuprins-încheiere", ["RO3_VERB"]),
            ("RO4_PRONOUN",      "Limba Română", 4, "Pronumele personal",
             "Recunoaște și folosește pronumele la toate persoanele", ["RO3_VERB"]),
            # ── Clasa 5 — Matematică ─────────────────────────────────────
            ("MATH5_INTEGERS",   "Matematică", 5, "Numere întregi",
             "Operații cu numere pozitive și negative", ["MATH4_LARGE_NUM"]),
            ("MATH5_PERCENT",    "Matematică", 5, "Procente",
             "Calculează procente din numere întregi", ["MATH4_DECIMALS"]),
            ("MATH5_ALGEBRA",    "Matematică", 5, "Expresii algebrice simple",
             "Calculează valoarea expresiilor cu o necunoscută", ["MATH5_INTEGERS"]),
            # ── Clasa 5 — Română ─────────────────────────────────────────
            ("RO5_METAPHOR",     "Limba Română", 5, "Figuri de stil",
             "Identifică și explică metafora și comparația", ["RO4_NARRATIVE"]),
            ("RO5_ARGUMENT",     "Limba Română", 5, "Textul argumentativ",
             "Structurează teză, argumente, concluzie", ["RO4_NARRATIVE"]),
            # ── Limba Engleză — Elementary (grade 6) ─────────────────────
            ("EN1_BE_VERB",        "Limba Engleză", 6, "Verb TO BE",
             "I am / you are / he is — present & past", []),
            ("EN1_PRES_SIMPLE",    "Limba Engleză", 6, "Present Simple",
             "Habits & routines, he/she/it adds -s", ["EN1_BE_VERB"]),
            ("EN1_THERE_IS",       "Limba Engleză", 6, "There is / There are",
             "Describe existence of things and places", ["EN1_PRES_SIMPLE"]),
            ("EN1_PRES_CONT",      "Limba Engleză", 6, "Present Continuous",
             "Actions happening now: am/is/are + -ing", ["EN1_PRES_SIMPLE"]),
            ("EN1_COMPARATIVES",   "Limba Engleză", 6, "Comparatives/Superlatives",
             "taller, more beautiful, the best, the worst", ["EN1_PRES_SIMPLE"]),
            ("EN1_PAST_SIMPLE_REG","Limba Engleză", 6, "Past Simple (regular)",
             "walked, played, studied — add -ed rules", ["EN1_PRES_SIMPLE"]),
            ("EN1_PAST_SIMPLE_IRR","Limba Engleză", 6, "Past Simple (irregular)",
             "went, saw, ate, took — must memorise", ["EN1_PAST_SIMPLE_REG"]),
            ("EN1_QUANTIFIERS",    "Limba Engleză", 6, "Quantifiers",
             "some/any, how much/many, a lot of", ["EN1_THERE_IS"]),
            ("EN1_PRES_PERFECT",   "Limba Engleză", 6, "Present Perfect",
             "have/has + past participle, already/yet/ever/never", ["EN1_PAST_SIMPLE_IRR"]),
            ("EN1_GOING_TO",       "Limba Engleză", 6, "Going to (future)",
             "I'm going to + verb — plans and intentions", ["EN1_PRES_CONT"]),
            ("EN1_VOCAB",          "Limba Engleză", 6, "Vocabulary (Elementary)",
             "Family, hobbies, places, food, clothes, jobs", []),
            ("EN1_READING",        "Limba Engleză", 6, "Reading (Elementary)",
             "Short texts, True/False, comprehension questions", ["EN1_VOCAB"]),
            # ── Limba Engleză — Pre-Intermediate (grade 7) ───────────────
            ("EN2_PAST_CONT",      "Limba Engleză", 7, "Past Continuous",
             "was/were + -ing: I was sleeping when...", ["EN1_PAST_SIMPLE_IRR"]),
            ("EN2_MODALS",         "Limba Engleză", 7, "Modal Verbs",
             "can/could/must/should/might/have to", ["EN1_PRES_SIMPLE"]),
            ("EN2_FUTURE",         "Limba Engleză", 7, "Future: will / going to",
             "Predictions (will) vs intentions (going to)", ["EN1_GOING_TO"]),
            ("EN2_COND_1",         "Limba Engleză", 7, "1st Conditional",
             "If + present simple, will + base verb", ["EN2_FUTURE"]),
            ("EN2_PP_CONT",        "Limba Engleză", 7, "Present Perfect Continuous",
             "have/has been + -ing: I've been waiting for...", ["EN1_PRES_PERFECT"]),
            ("EN2_PASSIVE",        "Limba Engleză", 7, "Passive Voice",
             "be + past participle: The book was written by...", ["EN2_PAST_CONT"]),
            ("EN2_VOCAB",          "Limba Engleză", 7, "Vocabulary (Pre-Int)",
             "Feelings, environment, technology, health, media", []),
            # ── Limba Engleză — Intermediate (grade 8) ───────────────────
            ("EN3_COND_2_3",       "Limba Engleză", 8, "2nd & 3rd Conditional",
             "If I were.../If I had been... would/would have", ["EN2_COND_1"]),
            ("EN3_REPORTING",      "Limba Engleză", 8, "Reported Speech",
             "She said that she was tired / asked if...", ["EN2_MODALS"]),
            ("EN3_REL_CLAUSES",    "Limba Engleză", 8, "Relative Clauses",
             "who, which, where, that, whose — defining/non-defining", ["EN3_REPORTING"]),
            ("EN3_GERUNDS_INF",    "Limba Engleză", 8, "Gerunds & Infinitives",
             "enjoy + -ing / want + to + verb", ["EN3_REL_CLAUSES"]),
            ("EN3_VOCAB",          "Limba Engleză", 8, "Vocabulary (Intermediate)",
             "Crime, science, money, media, travel, art", []),
            # ── Limba Engleză — Upper-Intermediate (grade 9) ─────────────
            ("EN4_INVERSION",      "Limba Engleză", 9, "Inversion",
             "Not only did..., Rarely have I..., Hardly had...", ["EN3_COND_2_3"]),
            ("EN4_CLEFT",          "Limba Engleză", 9, "Cleft Sentences",
             "It is/was... that... / What I need is...", ["EN3_REPORTING"]),
            ("EN4_ADV_PASSIVE",    "Limba Engleză", 9, "Advanced Passive",
             "It is said that... / is thought to be...", ["EN3_COND_2_3"]),
            ("EN4_VOCAB",          "Limba Engleză", 9, "Vocabulary (Upper-Int)",
             "Abstract nouns, collocations, formal register", []),
        ]
        for code, subj, grade, name, desc, prereq in skills:
            self._conn.execute(
                """INSERT OR IGNORE INTO skills
                   (code, subject, grade, name, description, prereq_codes)
                   VALUES (?,?,?,?,?,?)""",
                (code, subj, grade, name, desc, json.dumps(prereq)),
            )
        self._conn.commit()

    def _seed_lessons_math(self):
        lessons_math = [
            ("Numere de la 0 la 10", 1, 1, 1,
             "Numerele de la 0 la 10 sunt: zero, unu, doi, trei, patru, cinci, șase, șapte, opt, nouă, zece. Fiecare număr are un simbol (cifră) și un cuvânt. Putem număra obiecte folosind aceste numere.",
             "Învățăm să numărăm de la 0 la 10",
             ["MATH_COUNT_0_10"]),

            ("Adunarea cu numere până la 10", 1, 1, 2,
             "Adunarea înseamnă să punem lucruri împreună. Semnul adunării este +. Dacă am 3 mere și mai iau 2, am 3 + 2 = 5. Rezultatul adunării se numește sumă.",
             "Adunăm numere mici și aflăm suma",
             ["MATH_ADD_10"]),

            ("Scăderea cu numere până la 10", 1, 1, 3,
             "Scăderea înseamnă să luăm ceva din ce avem. Semnul scăderii este -. Dacă am 7 bomboane și mănânc 3, îmi rămân 7 - 3 = 4. Rezultatul scăderii se numește diferență.",
             "Scădem numere și aflăm diferența",
             ["MATH_SUB_10"]),
        ]
        for title, grade, unit, order, theory, summary, skill_codes in lessons_math:
            cur = self._conn.execute(
                """INSERT INTO lessons (title, subject, grade, unit, order_in_unit, theory, summary)
                   VALUES (?,?,?,?,?,?,?)""",
                (title, "Matematică", grade, unit, order, theory, summary),
            )
            lesson_id = cur.lastrowid
            self._seed_exercises_for_lesson(lesson_id, title, "Matematică", grade, skill_codes)

    def _seed_lessons_romanian(self):
        lessons_ro = [
            ("Litera A și sunetul A", 1, 1, 1,
             "Litera A este prima literă din alfabet. Se pronunță 'a' ca în cuvintele: albină, apă, arici. Litera A poate fi mare (A) sau mică (a).",
             "Recunoaștem și scriem litera A",
             ["RO_LETTERS_AE"]),

            ("Silabele și despărțirea cuvintelor", 1, 2, 1,
             "O silabă este o parte dintr-un cuvânt care se pronunță dintr-o suflare. 'masă' are două silabe: ma-să. 'elefant' are trei: e-le-fant.",
             "Despărțim cuvintele în silabe",
             ["RO_SYLLABLES"]),
        ]
        for title, grade, unit, order, theory, summary, skill_codes in lessons_ro:
            cur = self._conn.execute(
                """INSERT INTO lessons (title, subject, grade, unit, order_in_unit, theory, summary)
                   VALUES (?,?,?,?,?,?,?)""",
                (title, "Limba Română", grade, unit, order, theory, summary),
            )
            lesson_id = cur.lastrowid
            self._seed_exercises_for_lesson(lesson_id, title, "Limba Română", grade, skill_codes)

    def _seed_exercises_for_lesson(self, lesson_id: int, title: str, subject: str, grade: int, skill_codes: list[str]):
        """Exerciții demo, cu tagging skill_codes."""
        if subject == "Matematică" and "Adunarea" in title:
            exs = [
                ("pretest", "2 + 3 = ?", "5", 1),
                ("practice", "4 + 1 = ?", "5", 1),
                ("practice", "7 + 2 = ?", "9", 1),
                ("posttest", "3 + 6 = ?", "9", 1),
            ]
        elif subject == "Matematică" and "Numere" in title:
            exs = [
                ("pretest", "Scrie numărul care vine după 6.", "7", 1),
                ("practice", "Câte mere sunt?  🍎🍎🍎", "3", 1),
                ("posttest", "Scrie numărul care vine înainte de 10.", "9", 1),
            ]
        elif subject == "Limba Română" and "Litera A" in title:
            exs = [
                ("pretest", "Scrie litera mare A.", "A", 1),
                ("practice", "În cuvântul 'apă', ce literă este prima?", "a", 1),
                ("posttest", "Scrie litera mică a.", "a", 1),
            ]
        else:
            exs = [
                ("pretest", f"Întrebare rapidă din lecția: {title}", "da", 1),
                ("practice", f"Exercițiu de practică: {title}", "da", 1),
                ("posttest", f"Test final: {title}", "da", 1),
            ]

        for phase, enunt, rasp, diff in exs:
            self.add_exercise(
                lesson_id=lesson_id,
                phase=phase,
                enunt=enunt,
                raspuns=rasp,
                dificultate=diff,
                hint1="Gândește-te pas cu pas.",
                hint2="Poți folosi degete sau desene.",
                hint3="Încearcă să verifici cu un exemplu.",
                explicatie="Verifică încă o dată și încearcă din nou.",
                skill_codes=skill_codes,
            )

    def _seed_micro_quiz_demo(self):
        # micro-quiz pentru lecția 1, chunk 0
        lesson = self._conn.execute("SELECT id FROM lessons ORDER BY id LIMIT 1").fetchone()
        if not lesson:
            return
        self._conn.execute(
            """INSERT OR IGNORE INTO micro_quiz (lesson_id, chunk_index, type, enunt, raspuns, explicatie, skill_codes)
               VALUES (?,?,?,?,?,?,?)""",
            (int(lesson["id"]), 0, "truefalse", "Numerele de la 0 la 10 includ și 0? (da/nu)", "da",
             "0 este un număr și îl folosim la numărare.", json.dumps(["MATH_COUNT_0_10"])),
        )

    # ───────────────────────────────────────────────────────────────────
    # Lecția 1 clasa I — Numerele 0, 1, 2, 3, 4, 5 (hardcodat curricular)
    # ───────────────────────────────────────────────────────────────────

    def _seed_lesson_numere_0_5(self):
        """Inserează lecția completă 'Numerele 0, 1, 2, 3, 4, 5' pentru clasa I.

        16 exerciții proprii (3 pretest + 8 practică + 5 posttest) + 4 micro-quizuri.
        Nu depinde de DeepSeek — conținut curricular hardcodat.
        """
        theory = (
            "Numerele ne ajută să spunem câte lucruri avem. "
            "Azi lucrăm cu: 0, 1, 2, 3, 4 și 5. "
            "Zero înseamnă că nu avem nimic. Unu înseamnă un singur lucru. "
            "Doi, trei, patru și cinci urmează în ordine."
            "\n\n"
            "Potrivim un număr cu o mulțime numărând obiectele. "
            "Dacă vedem ●●●, numărăm: unu, doi, trei — deci scriem 3. "
            "Dacă nu e niciun obiect, numărul este 0. "
            "Dacă sunt 5 obiecte, numărul este 5."
            "\n\n"
            "Putem forma un număr mai mare prin adăugare. "
            "Exemplu: am 2 buline și vreau 4. Adaug 2: 2 + 2 = 4. "
            "Regula: numărăm câte lipsesc până la numărul dorit și le adăugăm."
            "\n\n"
            "Putem forma un număr mai mic prin eliminare. "
            "Exemplu: am 5 buline și vreau 2. Elimin 3: 5 - 3 = 2. "
            "Regula: calculăm câte trebuie scoase ca să ajungem la numărul dorit."
        )

        cur = self._conn.execute(
            """INSERT INTO lessons (title, subject, grade, unit, order_in_unit, theory, summary)
               VALUES (?,?,?,?,?,?,?)""",
            ("Numerele 0, 1, 2, 3, 4, 5", "Matematică", 1, 1, 1,
             theory, "Recunoaștem și folosim numerele de la 0 la 5"),
        )
        lid = int(cur.lastrowid)

        SC = ["MATH1_COUNT_0_5"]

        # ── Pretest (3) ─────────────────────────────────────────────────
        self.add_exercise(lid, phase="pretest", type="choice",
            enunt="Câte obiecte reprezintă numărul 0?",
            raspuns="Niciun obiect",
            choices=["Niciun obiect", "1 obiect", "5 obiecte", "2 obiecte"],
            hint1="Gândește-te: zero înseamnă că nu avem nimic.",
            hint2="Numără obiectele când nu există niciunul.",
            hint3="Zero = nimic = niciun obiect.",
            explicatie="Zero înseamnă că nu avem niciun obiect.",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="pretest", type="text",
            enunt="Scrie numărul care vine după 3.",
            raspuns="4",
            hint1="Numără pe degete: 1, 2, 3 — ce urmează?",
            hint2="Șirul este: 0, 1, 2, 3, __, 5.",
            hint3="Vine 4. Încearcă să scrii cifra 4.",
            explicatie="După 3 vine 4. Șirul: 0, 1, 2, 3, 4, 5.",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="pretest", type="choice",
            enunt="Care este cel mai mare număr din: 0, 1, 2, 3, 4, 5?",
            raspuns="5",
            choices=["0", "3", "5", "4"],
            hint1="Numără de la 0 la 5. Ultimul număr este cel mai mare.",
            hint2="0 < 1 < 2 < 3 < 4 < 5",
            hint3="Cel mai mare este 5.",
            explicatie="Cel mai mare număr din seria 0–5 este 5.",
            dificultate=1, skill_codes=SC)

        # ── Practică (8) ────────────────────────────────────────────────
        self.add_exercise(lid, phase="practice", type="choice",
            enunt="Câte buline sunt? ●●",
            raspuns="2",
            choices=["1", "2", "3", "4"],
            hint1="Numără încet cu degetul fiecare bulină.",
            hint2="Ridică un deget pentru fiecare bulină.",
            hint3="Unu, doi — sunt 2 buline.",
            explicatie="Sunt 2 buline: ●●",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="choice",
            enunt="Câte buline sunt? ●●●●",
            raspuns="4",
            choices=["2", "3", "4", "5"],
            hint1="Numără încet cu degetul fiecare bulină.",
            hint2="Ridică un deget pentru fiecare bulină.",
            hint3="Unu, doi, trei, patru — sunt 4 buline.",
            explicatie="Sunt 4 buline: ●●●●",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="text",
            enunt="Completează șirul: 0, 1, __, 3, 4, 5",
            raspuns="2",
            hint1="Numără de la 0: zero, unu, ... ce urmează după unu?",
            hint2="Între 1 și 3 lipsește un număr.",
            hint3="Lipsește 2. Scrie cifra 2.",
            explicatie="Șirul este 0, 1, 2, 3, 4, 5. Lipsea 2.",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="text",
            enunt="Completează șirul: 0, 1, 2, 3, __, 5",
            raspuns="4",
            hint1="Numără de la 0 până la 5. Ce vine înainte de 5?",
            hint2="Între 3 și 5 lipsește un număr.",
            hint3="Lipsește 4. Scrie cifra 4.",
            explicatie="Șirul este 0, 1, 2, 3, 4, 5. Lipsea 4.",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="text",
            enunt="Am 3 buline și vreau să am 5. Câte mai adaug?",
            raspuns="2",
            hint1="Numără de la 3 în sus până ajungi la 5.",
            hint2="3 → 4 → 5: ai numărat de 2 ori.",
            hint3="3 + 2 = 5. Adaugi 2.",
            explicatie="3 + 2 = 5. Trebuie să adaugi 2 buline.",
            dificultate=2, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="text",
            enunt="Am 1 bilă și vreau să am 3. Câte mai adaug?",
            raspuns="2",
            hint1="Numără de la 1 în sus până ajungi la 3.",
            hint2="1 → 2 → 3: ai numărat de 2 ori.",
            hint3="1 + 2 = 3. Adaugi 2.",
            explicatie="1 + 2 = 3. Trebuie să adaugi 2 bile.",
            dificultate=2, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="text",
            enunt="Am 5 buline și vreau să rămân cu 4. Câte elimin?",
            raspuns="1",
            hint1="Câte buline trebuie să scoți din 5 ca să rămână 4?",
            hint2="5 − ? = 4",
            hint3="5 − 1 = 4. Elimini 1.",
            explicatie="5 − 1 = 4. Trebuie să elimini 1 bulină.",
            dificultate=2, skill_codes=SC)

        self.add_exercise(lid, phase="practice", type="text",
            enunt="Am 4 buline și vreau să rămân cu 1. Câte elimin?",
            raspuns="3",
            hint1="Câte buline trebuie să scoți din 4 ca să rămână 1?",
            hint2="4 − ? = 1",
            hint3="4 − 3 = 1. Elimini 3.",
            explicatie="4 − 3 = 1. Trebuie să elimini 3 buline.",
            dificultate=2, skill_codes=SC)

        # ── Posttest (5) ────────────────────────────────────────────────
        self.add_exercise(lid, phase="posttest", type="text",
            enunt="Ce înseamnă numărul 0?",
            raspuns="nimic",
            hint1="Gândește-te: dacă nu ai nicio bilă, câte ai?",
            hint2="Zero înseamnă că nu există niciun obiect.",
            hint3="Răspunsul este: nimic.",
            explicatie="Numărul 0 înseamnă că nu avem niciun obiect — nimic.",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="posttest", type="choice",
            enunt="Câte buline sunt? ●●●",
            raspuns="3",
            choices=["2", "3", "4", "5"],
            hint1="Numără încet cu degetul fiecare bulină.",
            hint2="Unu, doi, trei.",
            hint3="Sunt 3 buline.",
            explicatie="Sunt 3 buline: ●●●",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="posttest", type="text",
            enunt="Completează: 0, 1, 2, __, 4, 5",
            raspuns="3",
            hint1="Ce vine după 2 în șirul 0–5?",
            hint2="Între 2 și 4 lipsește un număr.",
            hint3="Lipsește 3.",
            explicatie="Șirul este 0, 1, 2, 3, 4, 5. Lipsea 3.",
            dificultate=1, skill_codes=SC)

        self.add_exercise(lid, phase="posttest", type="text",
            enunt="Am 2 și vreau 5. Câte mai adaug?",
            raspuns="3",
            hint1="Numără de la 2 până la 5.",
            hint2="2 → 3 → 4 → 5: ai numărat de 3 ori.",
            hint3="2 + 3 = 5.",
            explicatie="2 + 3 = 5. Trebuia să adaugi 3.",
            dificultate=2, skill_codes=SC)

        self.add_exercise(lid, phase="posttest", type="text",
            enunt="Am 5 și vreau 1. Câte elimin?",
            raspuns="4",
            hint1="Câte trebuie să scoți din 5 ca să rămâi cu 1?",
            hint2="5 − ? = 1",
            hint3="5 − 4 = 1.",
            explicatie="5 − 4 = 1. Trebuia să elimini 4.",
            dificultate=2, skill_codes=SC)

        # ── Micro-quiz (4, câte unul per chunk de teorie) ───────────────
        mq_data = [
            (0, "truefalse",
             "Zero înseamnă că nu avem niciun obiect? (da/nu)", "da",
             "Corect! Zero = nimic = niciun obiect."),
            (1, "short_answer",
             "Câte obiecte sunt dacă vedem ●●●●? Scrie cifra.", "4",
             "Numărăm: unu, doi, trei, patru — sunt 4 obiecte."),
            (2, "truefalse",
             "Am 1 și vreau 3. Adaug 2? (da/nu)", "da",
             "Corect! 1 + 2 = 3."),
            (3, "short_answer",
             "Am 4 și elimin 1. Cu câte rămân?", "3",
             "4 − 1 = 3."),
        ]
        for ci, tp, enunt, rasp, expl in mq_data:
            self._conn.execute(
                """INSERT OR IGNORE INTO micro_quiz
                   (lesson_id, chunk_index, type, enunt, raspuns, explicatie, skill_codes)
                   VALUES (?,?,?,?,?,?,?)""",
                (lid, ci, tp, enunt, rasp, expl, json.dumps(SC)),
            )

    def _ensure_lesson_numere_0_5(self):
        """Migrare sigură: adaugă lecția '0–5' dacă nu există deja.

        Apelată la fiecare startup — face ceva doar dacă lecția lipsește.
        Șterge lecția placeholder 'Numere de la 0 la 10' (grade=1, order=1)
        dacă aceasta există.
        """
        exists = self._conn.execute(
            "SELECT id FROM lessons WHERE title=? AND subject='Matematică' AND grade=1",
            ("Numerele 0, 1, 2, 3, 4, 5",)
        ).fetchone()
        if exists:
            return  # Deja există — nimic de făcut

        # Șterge lecția veche placeholder (unit=1, order=1) dacă există
        old = self._conn.execute(
            "SELECT id FROM lessons WHERE subject='Matematică' AND grade=1 "
            "AND unit=1 AND order_in_unit=1"
        ).fetchone()
        if old:
            oid = int(old["id"])
            self._conn.execute("DELETE FROM micro_quiz WHERE lesson_id=?", (oid,))
            self._conn.execute("DELETE FROM exercises WHERE lesson_id=?", (oid,))
            self._conn.execute("DELETE FROM sessions WHERE lesson_id=?", (oid,))
            self._conn.execute("DELETE FROM lessons WHERE id=?", (oid,))
            print(f"🔄 Migrare: lecție placeholder (id={oid}) înlocuită cu 'Numerele 0–5'")

        self._seed_lesson_numere_0_5()
        self._conn.commit()
        print("✅ Migrare completă: 'Numerele 0, 1, 2, 3, 4, 5' adăugată în DB")

    # ── Populare automată 24 lecții clasa I din curriculum CD PRESS ──────────

    def _theory_for_title(self, title: str) -> str:
        """Returnează teoria template (>= 150 chars, 2 chunk-uri separate prin \\n\\n)
        pentru o lecție de clasa I, pe baza cuvintelor-cheie din titlu."""
        t = title.lower()

        if "compar" in t:
            return (
                "Comparăm numerele pentru a afla care este mai mare sau mai mic. "
                "Folosim semnele: < (mai mic decât), > (mai mare decât), = (egal cu). "
                "Exemplu: 3 < 5 înseamnă că 3 este mai mic decât 5."
                "\n\n"
                "Ordonăm numerele în ordine crescătoare: de la cel mai mic la cel mai mare. "
                "Exemplu: 1, 2, 3, 4, 5. Sau descrescătoare: 5, 4, 3, 2, 1. "
                "Comparăm întâi zecile; dacă sunt egale, comparăm unitățile."
            )
        if "adun" in t:
            return (
                "Adunarea înseamnă a pune împreună două mulțimi de obiecte. "
                "Semnul + arată că adunăm. Exemplu: 3 + 2 = 5. "
                "Numărăm mai departe de la primul număr: 3... 4, 5."
                "\n\n"
                "Rezultatul adunării se numește sumă. "
                "Adunarea este comutativă: 3 + 2 = 2 + 3. "
                "Orice număr adunat cu 0 rămâne același: 4 + 0 = 4."
            )
        if "scăd" in t or "scad" in t:
            return (
                "Scăderea înseamnă a lua din sau a afla câte rămân. "
                "Semnul - arată că scădem. Exemplu: 5 - 2 = 3. "
                "Numărul din care scădem se numește descăzut."
                "\n\n"
                "Rezultatul scăderii se numește rest sau diferență. "
                "Scăderea este operația inversă adunării: dacă 3 + 2 = 5, atunci 5 - 2 = 3. "
                "Orice număr din care scădem 0 rămâne același: 4 - 0 = 4."
            )
        if "numere" in t or "numerele" in t:
            if "6" in t and ("10" in t or "7" in t or "8" in t or "9" in t):
                return (
                    "Numerele 6, 7, 8, 9 și 10 vin după 5. Numărăm: șase, șapte, opt, nouă, zece. "
                    "Scriem cifrele: 6, 7, 8, 9, 10. Numărul 10 este format din 1 zece și 0 unități."
                    "\n\n"
                    "Șirul complet: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10. "
                    "Predecesorul lui 10 este 9. Succesorul lui 9 este 10. "
                    "Cel mai mic este 0, cel mai mare în acest interval este 10."
                )
            if "20" in t or "11" in t or "12" in t or "15" in t or "16" in t or "19" in t:
                return (
                    "Numerele de la 0 la 20 includ zeci și unități. "
                    "Numerele 11-20 sunt formate din 1 zece și unități: "
                    "11 = 1 zece + 1, 15 = 1 zece + 5, 20 = 2 zeci + 0."
                    "\n\n"
                    "Comparăm: 15 > 12 deoarece ambele au 1 zece dar 5 > 2 la unități. "
                    "Cel mai mare număr din interval este 20, cel mai mic este 0. "
                    "Numărăm înainte și înapoi în intervalul 0–20."
                )
            if "31" in t:
                return (
                    "Numerele de la 0 la 31 includ zeci și unități. "
                    "Zecile din acest interval: 0, 10, 20, 30. "
                    "Exemplu: 25 = 2 zeci + 5 unități; 31 = 3 zeci + 1 unitate."
                    "\n\n"
                    "Comparăm întâi zecile, apoi unitățile: 25 > 21 deoarece 5 > 1 la unități. "
                    "Cel mai mare număr din interval este 31. "
                    "Numărăm înainte și înapoi în intervalul 0–31."
                )
            if "100" in t:
                return (
                    "Numerele de la 0 la 100 sunt formate din zeci și unități. "
                    "Zecile: 10, 20, 30, 40, 50, 60, 70, 80, 90, 100. "
                    "Exemplu: 47 = 4 zeci + 7 unități; 83 = 8 zeci + 3 unități."
                    "\n\n"
                    "100 se numește o sută. Comparăm întâi zecile: 47 < 83 deoarece 4 zeci < 8 zeci. "
                    "Dacă zecile sunt egale, comparăm unitățile: 43 < 47 deoarece 3 < 7. "
                    "Cel mai mare număr din interval este 100."
                )
            # Generic numere
            return (
                "Numerele ne ajută să spunem câte lucruri avem. "
                "Fiecare număr are un loc precis în șir. "
                "Predecesorul unui număr este cel de dinaintea lui; succesorul este cel de după."
                "\n\n"
                "Comparăm numere pentru a afla care e mai mare sau mai mic. "
                "Scriem cifrele de la 0 la 9 și le combinăm pentru numere mai mari. "
                "Numărăm obiecte din jurul nostru pentru a exersa."
            )
        if "șiruri" in t or "siruri" in t:
            return (
                "Un șir de numere urmează o regulă. "
                "Descoperim regula comparând numerele consecutive: cresc sau scad cu același număr. "
                "Exemplu: 0, 2, 4, 6, 8 — crește cu 2 la fiecare pas."
                "\n\n"
                "Exemple de șiruri: 0, 5, 10, 15, 20 (crește cu 5); 10, 8, 6, 4, 2 (scade cu 2). "
                "Găsim numărul următor aplicând regula descoperită. "
                "Dacă regula e +3: 3, 6, 9, 12, 15..."
            )
        if "măsur" in t and ("lung" in t or "centim" in t or "metr" in t):
            return (
                "Lungimea se măsoară cu rigla sau metrul de croitor. "
                "Unitatea principală este metrul (m). O unitate mai mică este centimetrul (cm). "
                "1 m = 100 cm. Creionul are ~15 cm, masa are ~60 cm înălțime."
                "\n\n"
                "Comparăm lungimi spunând: mai lung, mai scurt, la fel de lung. "
                "Exemplu: un metru de șnur e mai lung decât 50 cm. "
                "Măsurăm obiecte din clasă cu rigla pentru a exersa."
            )
        if "măsur" in t and ("capac" in t or "litru" in t or "litr" in t):
            return (
                "Capacitatea arată cât lichid încape într-un vas. "
                "Unitatea principală este litrul (l). O unitate mai mică este mililitrul (ml). "
                "1 l = 1000 ml. O sticlă de apă are de obicei 0,5 l sau 1 l."
                "\n\n"
                "Comparăm capacități: un vas mai mare are capacitate mai mare. "
                "Exemplu: o găleată are mai mulți litri decât o cană. "
                "Estimăm cât lichid încape înainte de a măsura."
            )
        if "bani" in t or "monede" in t or "bancnote" in t:
            return (
                "Banii sunt folosiți pentru a cumpăra lucruri. "
                "Moneda României este leul (lei). 1 leu = 100 de bani. "
                "Monede: 1 ban, 5 bani, 10 bani, 50 bani, 1 leu, 5 lei, 10 lei."
                "\n\n"
                "Bancnote: 1 leu, 5 lei, 10 lei, 50 lei, 100 lei. "
                "Adunăm valorile monedelor sau bancnotelor pentru a afla suma totală. "
                "Exemplu: 5 lei + 2 lei = 7 lei."
            )
        if "problem" in t:
            return (
                "Rezolvăm problemele urmând pași clari: "
                "1. Citim cu atenție ce se dă și ce ni se cere. "
                "2. Alegem operația: adunare sau scădere."
                "\n\n"
                "3. Calculăm și scriem răspunsul complet. "
                "Problemele cu două operații au doi pași de calcul. "
                "Exemplu: Am 5 mere, cumpăr 3 și dau 2. Câte îmi rămân? "
                "5 + 3 = 8, apoi 8 - 2 = 6 mere."
            )
        if "soare" in t or ("lumina" in t and "căldur" in t):
            return (
                "Soarele este o stea uriașă care dă lumină și căldură Pământului. "
                "Fără Soare, plantele nu pot crăște și ar fi întuneric permanent. "
                "Ziua, Soarele luminează cerul; noaptea, Pământul se rotește departe de el."
                "\n\n"
                "Vara căldura soarelui este mai puternică decât iarna. "
                "Lumina și căldura soarelui influențează creșterea plantelor și viața animalelor. "
                "Energia solară poate fi captată pentru a produce electricitate."
            )
        if "plant" in t:
            return (
                "Plantele sunt ființe vii care produc hrană cu ajutorul luminii solare. "
                "Principalele părți: rădăcina (absoarbe apa), tulpina (susține și transportă), "
                "frunzele (produc hrană), florile (produc semințe), fructele (conțin semințe)."
                "\n\n"
                "Plantele au nevoie de apă, lumină, căldură și sol cu substanțe nutritive. "
                "Fără aceste condiții, plantele se ofilesc și mor. "
                "Oxigenul pe care îl respirăm este produs de frunzele plantelor."
            )
        if "animal" in t:
            return (
                "Animalele sunt ființe vii care se mișcă, respiră și se hrănesc. "
                "Animalele domestice trăiesc lângă oameni: vaca, câinele, pisica, oaia, calul. "
                "Animalele sălbatice trăiesc libere în natură: lupul, ursul, vulpea."
                "\n\n"
                "Corpul animalelor are: cap, trunchi și membre. "
                "Scheletul din oase susține corpul și îl protejează organele interne. "
                "Animalele se adaptează la mediu: unele înoată, altele zboară sau aleargă."
            )
        if ("corp" in t and ("omen" in t or "nostru" in t)) or ("organ" in t and "major" in t):
            return (
                "Corpul omenesc are trei mari părți: capul, trunchiul și membrele. "
                "Capul conține creierul — centrul gândirii și al simțurilor. "
                "Trunchiul are torace (cu inima și plămânii) și abdomen (cu stomacul)."
                "\n\n"
                "Membrele superioare sunt brațele cu mâinile. "
                "Membrele inferioare sunt picioarele cu tălpile. "
                "Scheletul format din oase susține corpul și protejează organele."
            )
        if "apă" in t or "apa" in t or "transfor" in t or "fierbere" in t or "îngheț" in t:
            return (
                "Apa se găsește în natură în râuri, lacuri, mări și oceane. "
                "Apa are trei stări: lichidă (apa normală), solidă (gheața) și gazoasă (aburul). "
                "Apa îngheață la 0°C și fierbe la 100°C."
                "\n\n"
                "Evaporarea: apa se transformă în abur când se încălzește. "
                "Condensarea: aburul se transformă în picături de apă când se răcește. "
                "Topirea: gheața se transformă în apă când temperatura urcă peste 0°C."
            )
        if "energ" in t or ("surse" in t and ("energ" in t or "lumina" in t)):
            return (
                "Energia face ca lucrurile să se miște, să se încălzească sau să lumineze. "
                "Surse de energie: Soarele (lumină și căldură), vântul (mișcă morile), "
                "apa (produce electricitate în hidrocentrale)."
                "\n\n"
                "Energia electrică ajunge la noi prin prize și cabluri electrice. "
                "O utilizăm pentru becuri, televizor, frigider, calculator. "
                "Economimsim energia: stingem lumina când ieșim din cameră."
            )
        if "anotim" in t or ("luni" in t and "an" in t) or ("an" in t and "sezon" in t):
            return (
                "Un an are 4 anotimpuri: primăvara, vara, toamna și iarna. "
                "Primăvara: înfloresc plantele, vin păsările, vremea se încălzește. "
                "Vara: e cald, soarele luminează mult, copiii se joacă afară."
                "\n\n"
                "Toamna: frunzele cad, recoltăm fructe și legume, vremea se răcește. "
                "Iarna: ninge, e frig, unele animale hibernează. "
                "Un an are 12 luni: ianuarie, februarie, ..., decembrie."
            )
        if "ocrot" in t or ("mediu" in t and "înconj" in t):
            return (
                "Mediul înconjurător cuprinde tot ce ne înconjoară: aer, apă, sol, plante, animale. "
                "Trebuie să îl ocrotim pentru a trăi sănătos. "
                "Acțiuni de protecție: nu aruncăm gunoaie, reciclăm hârtia, plasticul și sticla."
                "\n\n"
                "Economisim apa: închidem robinetul când nu folosim. "
                "Economisim energia: stingem lumina. "
                "Plantăm copaci: ei produc oxigenul pe care îl respirăm."
            )
        if "lumea vie" in t or ("lume" in t and "vie" in t):
            return (
                "Lumea vie cuprinde toate ființele: plante, animale, ciuperci și oameni. "
                "Toate ființele vii se hrănesc, cresc, respiră și se înmulțesc. "
                "Plantele produc oxigenul pe care îl respirăm noi și animalele."
                "\n\n"
                "Animalele se hrănesc cu plante sau cu alte animale. "
                "Oamenii au grijă de plante și animale. "
                "Ocrotim lumea vie pentru a menține echilibrul din natură."
            )
        if "sunet" in t:
            return (
                "Sunetele sunt vibrații care se propagă prin aer, apă sau corpuri solide. "
                "Urechile noastre primesc vibrațiile și le transformăm în sunete auzite. "
                "Sunete puternice: tunetul, toba. Sunete slabe: foșnetul frunzelor, șoapta."
                "\n\n"
                "Sunetele foarte puternice pot dăuna auzului — purtăm căști de protecție. "
                "Muzica este sunete organizate în melodii și ritmuri. "
                "Vocea umană produce sunete prin vibrarea corzilor vocale."
            )
        if "figuri" in t or "geometr" in t or "forme" in t:
            return (
                "Figurile geometrice plane sunt: pătratul, dreptunghiul, triunghiul și cercul. "
                "Pătratul are 4 laturi egale și 4 unghiuri drepte. "
                "Dreptunghiul are 2 perechi de laturi egale și 4 unghiuri drepte."
                "\n\n"
                "Triunghiul are 3 laturi și 3 unghiuri. "
                "Cercul nu are laturi — toate punctele de pe margine sunt la aceeași distanță de centru. "
                "Recunoaștem aceste figuri în obiectele din viața de zi cu zi."
            )
        if "cădere" in t or "cader" in t:
            return (
                "Căderea liberă este mișcarea unui obiect atras de Pământ când nu e susținut. "
                "Toate obiectele cad în jos din cauza gravitației — forța cu care Pământul atrage. "
                "Exemplu: o bilă aruncată sus cade înapoi pe pământ."
                "\n\n"
                "Obiectele grele și ușoare cad cu aceeași viteză în absența aerului. "
                "Pana cade mai lent decât o bilă din cauza rezistenței aerului. "
                "Gravitația este forța care atrage toate obiectele spre centrul Pământului."
            )
        # Fallback generic
        return (
            f"Lecția '{title}' face parte din programa clasei I de matematică și explorarea mediului. "
            "Parcurgem conținuturile pas cu pas, cu exemple clare și exerciții practice. "
            "Fiecare concept nou se bazează pe ceea ce am învățat deja."
            "\n\n"
            "Exersăm prin exerciții variate: recunoaștere, completare și rezolvare de probleme. "
            "Dacă ceva e greu, ne reamintim regula de bază și mai încercăm o dată. "
            "Greșelile ne ajută să înțelegem mai bine."
        )

    def _populate_grade1_from_manual(self):
        """Inserează 24 lecții de clasa I (curriculum CD PRESS) dacă nu există deja.

        Lecția 1 'Numerele 0, 1, 2, 3, 4, 5' este omisă deoarece e deja hardcodată
        prin _ensure_lesson_numere_0_5(). Fiecare lecție nouă primește teorie template
        proprie (>= 100 chars) și 3 exerciții placeholder pe care DeepSeek le înlocuiește.
        """
        LESSONS = [
            # (unit, order_in_unit, title)
            # Unit 1 — Numere 0–5 (lecția 1 deja există)
            (1, 2, "Compararea numerelor de la 0 la 5"),
            (1, 3, "Adunarea numerelor de la 0 la 5"),
            (1, 4, "Scăderea numerelor de la 0 la 5"),
            (1, 5, "Soarele, sursă de lumină și căldură"),
            # Unit 2 — Numere 6–10
            (2, 1, "Numerele 6, 7, 8, 9 și 10"),
            (2, 2, "Compararea numerelor de la 0 la 10"),
            (2, 3, "Adunarea numerelor de la 0 la 10"),
            (2, 4, "Scăderea numerelor de la 0 la 10"),
            (2, 5, "Plantele. Părțile unei plante"),
            # Unit 3 — Numere 0–20
            (3, 1, "Numerele de la 0 la 20"),
            (3, 2, "Adunarea numerelor de la 0 la 20"),
            (3, 3, "Scăderea numerelor de la 0 la 20"),
            (3, 4, "Animale. Scheletul"),
            (3, 5, "Transformările apei"),
            # Unit 4 — Numere 0–31, Măsurare
            (4, 1, "Numerele de la 0 la 31"),
            (4, 2, "Adunarea numerelor de la 0 la 31"),
            (4, 3, "Scăderea numerelor de la 0 la 31"),
            (4, 4, "Măsurarea lungimii"),
            (4, 5, "An, anotimpuri, lunile anului"),
            # Unit 5 — Numere 0–100, Bani, Probleme
            (5, 1, "Numerele de la 0 la 100"),
            (5, 2, "Adunarea și scăderea până la 100"),
            (5, 3, "Banii. Monede și bancnote"),
            (5, 4, "Probleme cu două operații"),
            (5, 5, "Lumea vie"),
        ]
        added = 0
        for unit, order, title in LESSONS:
            exists = self._conn.execute(
                "SELECT id FROM lessons WHERE title=? AND subject='Matematică' AND grade=1",
                (title,)
            ).fetchone()
            if exists:
                continue
            theory = self._theory_for_title(title)
            cur = self._conn.execute(
                """INSERT INTO lessons
                   (title, subject, grade, unit, order_in_unit, theory, summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (title, "Matematică", 1, unit, order, theory,
                 f"Lecție clasa I: {title}"),
            )
            lid = int(cur.lastrowid)
            self._seed_exercises_for_lesson(lid, title, "Matematică", 1, ["MATH1_GENERAL"])
            added += 1
        if added:
            print(f"✅ Database: adăugate {added} lecții noi pentru clasa I")

    def _ensure_grade1_from_manual(self):
        """Migrare idempotentă: populează 24 lecții clasa I dacă nu există deja.

        Apelată la fiecare startup — face ceva doar dacă ultima lecție din listă lipsește.
        """
        exists = self._conn.execute(
            "SELECT id FROM lessons WHERE title='Lumea vie' "
            "AND subject='Matematică' AND grade=1"
        ).fetchone()
        if exists:
            return
        self._populate_grade1_from_manual()
        self._conn.commit()

    def seed_min_lessons_if_missing(self):
        """Alias pastrat pentru compatibilitate."""
        self._ensure_all_grades()

    def _ensure_all_grades(self):
        """Asigura ca exista cel putin 2 lectii per (clasa, materie) pentru toate clasele 1-5."""
        cur = self._conn.cursor()

        # Date lectii per clasa si materie
        MATH_LESSONS = {
            1: [
                ("Numere de la 0 la 10", 1, 1,
                 "Numerele de la 0 la 10 sunt: zero, unu, doi, trei, patru, cinci, sase, sapte, opt, noua, zece. Fiecare numar are un simbol (cifra) si un cuvant.",
                 [("pretest","Scrie numarul care vine dupa 6.","7"),("practice","Cate mere sunt? 🍎🍎🍎","3"),("posttest","Scrie numarul care vine inainte de 10.","9")]),
                ("Adunarea pana la 10", 1, 2,
                 "Adunarea inseamna sa punem lucruri impreuna. Semnul adunarii este +. Daca am 3 mere si mai iau 2, am 3+2=5.",
                 [("pretest","2 + 3 = ?","5"),("practice","4 + 1 = ?","5"),("practice","7 + 2 = ?","9"),("posttest","3 + 6 = ?","9")]),
            ],
            2: [
                ("Numere pana la 100", 1, 1,
                 "Numerele de la 0 la 100 se formeaza cu zeci si unitati. 45 = 4 zeci si 5 unitati. Cel mai mare numar de doua cifre este 99.",
                 [("pretest","Cate zeci are numarul 73?","7"),("practice","Scrie numarul: 5 zeci si 8 unitati.","58"),("posttest","Care este cel mai mare numar de doua cifre?","99")]),
                ("Adunarea si scaderea pana la 100", 1, 2,
                 "Adunam si scadem numere pana la 100. 35 + 42 = 77. Procedam cifra cu cifra: unitatile cu unitatile, zecile cu zecile.",
                 [("pretest","25 + 30 = ?","55"),("practice","63 - 21 = ?","42"),("practice","48 + 15 = ?","63"),("posttest","90 - 35 = ?","55")]),
            ],
            3: [
                ("Inmultirea numerelor 0-10", 1, 1,
                 "Inmultirea este o adunare repetata. 3 x 4 = 4+4+4 = 12. Semnul inmultirii este x sau ·. Rezultatul se numeste produs.",
                 [("pretest","3 x 4 = ?","12"),("practice","5 x 6 = ?","30"),("practice","7 x 8 = ?","56"),("posttest","9 x 9 = ?","81")]),
                ("Impartirea numerelor", 1, 2,
                 "Impartirea este operatia inversa inmultirii. 20 : 4 = 5, pentru ca 5 x 4 = 20. Semnul impartirii este : sau /.",
                 [("pretest","12 : 3 = ?","4"),("practice","30 : 6 = ?","5"),("practice","45 : 9 = ?","5"),("posttest","56 : 8 = ?","7")]),
            ],
            4: [
                ("Numere pana la 1.000.000", 1, 1,
                 "Numerele mari au clase: clasa unitatilor (sute, zeci, unitati) si clasa miilor. 234.567 = 234 mii si 567.",
                 [("pretest","Cate cifre are numarul 45.678?","5"),("practice","Scrie in cifre: doua sute trei mii.","203000"),("posttest","234.000 + 56.000 = ?","290000")]),
                ("Fractii", 1, 2,
                 "O fractie reprezinta parti dintr-un intreg. 1/2 inseamna o parte din doua parti egale. 3/4 inseamna trei parti din patru.",
                 [("pretest","1/2 + 1/2 = ?","1"),("practice","Care fractie este mai mare: 1/3 sau 1/4?","1/3"),("posttest","3/4 - 1/4 = ?","2/4")]),
            ],
            5: [
                ("Numere intregi pozitive si negative", 1, 1,
                 "Numerele intregi includ numere pozitive (+), zero si numere negative (-). Pe axa numerelor: ...-3, -2, -1, 0, 1, 2, 3...",
                 [("pretest","Care este opusul lui 5?","-5"),("practice","-3 + 7 = ?","4"),("posttest","-8 + 3 = ?","-5")]),
                ("Procente", 1, 2,
                 "Procentul exprima o parte din 100. 25% = 25/100 = 0.25. 50% din 80 = 40.",
                 [("pretest","50% din 100 = ?","50"),("practice","25% din 80 = ?","20"),("posttest","10% din 350 = ?","35")]),
            ],
        }

        RO_LESSONS = {
            1: [
                ("Litera A si sunetul A", 1, 1,
                 "Litera A este prima litera din alfabet. Se pronunta 'a' ca in cuvintele: albina, apa, arici. Litera A poate fi mare (A) sau mica (a).",
                 [("pretest","Scrie litera mare A.","A"),("practice","In cuvantul 'apa', ce litera este prima?","a"),("posttest","Scrie litera mica a.","a")]),
                ("Silabele si despartirea cuvintelor", 2, 1,
                 "O silaba este o parte dintr-un cuvant care se pronunta dintr-o suflare. 'masa' are doua silabe: ma-sa.",
                 [("pretest","Cate silabe are cuvantul 'masa'?","2"),("practice","Desparte in silabe: elefant.","e-le-fant"),("posttest","Cate silabe are 'fluture'?","3")]),
            ],
            2: [
                ("Propozitia si partile ei", 1, 1,
                 "O propozitie exprima un gand intreg. Ea are subiect (cine?) si predicat (ce face?). 'Copilul citeste.' - subiect: copilul, predicat: citeste.",
                 [("pretest","Ce exprima o propozitie?","un gand"),("practice","Care este subiectul? 'Maria canta.'","Maria"),("posttest","Care este predicatul? 'Vantul bate.'","bate")]),
                ("Substantivul", 1, 2,
                 "Substantivul este cuvantul care denumeste fiinte, lucruri sau fenomene. Exemple: copil, carte, ploaie, mama.",
                 [("pretest","Ce denumeste substantivul?","fiinte lucruri"),("practice","Este 'carte' un substantiv? (da/nu)","da"),("posttest","Gaseste substantivul: 'Pisica doarme.'","pisica")]),
            ],
            3: [
                ("Verbul", 1, 1,
                 "Verbul este cuvantul care exprima actiunea sau starea. Exemple: a merge, a citi, a fi. Verbele se conjuga dupa persoana si numar.",
                 [("pretest","Ce exprima verbul?","actiunea"),("practice","Este 'alearga' un verb? (da/nu)","da"),("posttest","Gaseste verbul: 'Copiii se joaca.'","se joaca")]),
                ("Adjectivul", 1, 2,
                 "Adjectivul este cuvantul care exprima insusiri ale substantivului. Exemple: frumos, mare, rapid, bun.",
                 [("pretest","Ce exprima adjectivul?","insusiri"),("practice","Care este adjectivul: 'floare frumoasa'?","frumoasa"),("posttest","Gaseste adjectivul: 'cartea grea'.","grea")]),
            ],
            4: [
                ("Textul narativ", 1, 1,
                 "Textul narativ povesteste intamplari reale sau imaginare. Are introducere, cuprins si incheiere. Autorul foloseste personaje si actiuni.",
                 [("pretest","Ce tip de text povesteste intamplari?","narativ"),("practice","Ce are un text narativ? (introducere/cuprins/incheiere)","introducere cuprins incheiere"),("posttest","Cate parti are un text narativ?","3")]),
                ("Pronumele personal", 1, 2,
                 "Pronumele personal inlocuieste un substantiv. Persoanele: eu, tu, el/ea (singular); noi, voi, ei/ele (plural).",
                 [("pretest","Ce inlocuieste pronumele?","substantivul"),("practice","Care este pronumele la pers. 1 singular?","eu"),("posttest","Inlocuieste cu pronume: 'Maria citeste.'","ea citeste")]),
            ],
            5: [
                ("Figura de stil: metafora", 1, 1,
                 "Metafora inlocuieste un cuvant cu altul pe baza asemanarii. 'Luna e o moneda de argint' - luna este comparata cu o moneda.",
                 [("pretest","Ce este metafora?","figura de stil"),("practice","In 'ochii de azur' ce figura de stil este?","metafora"),("posttest","Creeaza o metafora pentru soare.","orice raspuns")]),
                ("Textul argumentativ", 1, 2,
                 "Textul argumentativ sustine o opinie cu argumente. Are: teza (opinia), argumentele (dovezi), concluzia.",
                 [("pretest","Ce contine un text argumentativ?","opinie argumente"),("practice","Cate parti principale are?","3"),("posttest","Ce este teza?","opinia")]),
            ],
        }

        def add_lessons(lessons_dict, subject):
            for grade, lessons in lessons_dict.items():
                n = cur.execute(
                    "SELECT COUNT(*) FROM lessons WHERE grade=? AND subject=?",
                    (grade, subject)
                ).fetchone()[0]
                if n >= len(lessons):
                    continue   # deja exista suficiente lectii
                for lesson_data in lessons:
                    title, unit, order = lesson_data[0], lesson_data[1], lesson_data[2]
                    theory = lesson_data[3]
                    exercises = lesson_data[4]
                    # verifica sa nu existe deja
                    ex = cur.execute(
                        "SELECT id FROM lessons WHERE grade=? AND subject=? AND title=?",
                        (grade, subject, title)
                    ).fetchone()
                    if ex:
                        continue
                    cur.execute(
                        """INSERT INTO lessons (title, subject, grade, unit, order_in_unit, theory, summary)
                           VALUES (?,?,?,?,?,?,?)""",
                        (title, subject, grade, unit, order, theory, f"Lectie: {title}")
                    )
                    lid = cur.lastrowid
                    for phase, enunt, raspuns in exercises:
                        cur.execute(
                            """INSERT INTO exercises (lesson_id, type, phase, enunt, raspuns,
                               hint1, hint2, hint3, explicatie, dificultate, skill_codes)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (lid, "text", phase, enunt, raspuns,
                             "Citeste din nou enuntul cu atentie.",
                             "Incearca sa rezolvi pas cu pas.",
                             "Verifica raspunsul tau.",
                             "Raspunsul corect este: " + raspuns,
                             grade, json.dumps([]))
                        )

        add_lessons(MATH_LESSONS, "Matematică")
        add_lessons(RO_LESSONS, "Limba Română")
        self._conn.commit()

    # ───────────────────────────────────────────────────────────────────
    # Users
    # ───────────────────────────────────────────────────────────────────
    def get_all_users(self):
        return self.get_users()

    def update_user_active(self, user_id: int):
        cur = self._conn.cursor()
        cur.execute(
            "UPDATE users SET last_active = datetime('now') WHERE id = ?",
            (int(user_id),)
        )
        self._conn.commit()

    def create_user(self, name: str, age: int | None, grade: int):
        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO users (name, age, grade, level, created_at, last_active)
            VALUES (?, ?, ?, 1, datetime('now'), datetime('now'))
            """,
            (name.strip(), int(age) if age is not None else None, int(grade)),
        )
        self._conn.commit()
        user_id = cur.lastrowid
        return self.get_user(user_id)

    # aliasuri pentru compatibilitate cu UI
    def add_user(self, name: str, age: int | None, grade: int):
        return self.create_user(name, age, grade)

    def get_user(self, user_id: int):
        cur = self._conn.cursor()
        row = cur.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
        return dict(row) if row else None

    def get_users(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM users ORDER BY last_active DESC, id ASC").fetchall()
        return [dict(r) for r in rows]

    def touch_user(self, user_id: int):
        self._conn.execute("UPDATE users SET last_active=datetime('now') WHERE id=?", (user_id,))
        self._conn.commit()

    # ───────────────────────────────────────────────────────────────────
    # Lessons
    # ───────────────────────────────────────────────────────────────────

    def get_lessons(self, grade: int = None, subject: str = None) -> list[dict]:
        q = "SELECT * FROM lessons WHERE 1=1"
        params = []
        if grade is not None:
            q += " AND grade=?"
            params.append(int(grade))
        if subject:
            q += " AND subject=?"
            params.append(subject)
        q += " ORDER BY grade ASC, unit ASC, order_in_unit ASC, id ASC"
        rows = self._conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def get_lesson(self, lesson_id: int) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM lessons WHERE id=?", (lesson_id,)).fetchone()
        return dict(row) if row else None

    # ───────────────────────────────────────────────────────────────────
    # Exercises & micro quiz
    # ───────────────────────────────────────────────────────────────────

    def add_exercise(self, lesson_id: int, enunt: str, raspuns: str,
                     phase: str = "practice", type: str = "text",
                     choices: list[str] = None,
                     hint1: str = None, hint2: str = None, hint3: str = None,
                     explicatie: str = None, dificultate: int = 1,
                     skill_codes: list[str] = None) -> int:
        cur = self._conn.execute(
            """INSERT INTO exercises (lesson_id, type, phase, enunt, raspuns, choices, hint1, hint2, hint3, explicatie, dificultate, skill_codes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(lesson_id), type, phase, enunt, raspuns,
                json.dumps(choices) if choices else None,
                hint1, hint2, hint3, explicatie, int(dificultate),
                json.dumps(skill_codes) if skill_codes else None,
            ),
        )
        return int(cur.lastrowid)

    # Coduri-răspuns din import defectuos (single-char, truncate, coduri textbook)
    _BAD_RASPUNS = frozenset({
        "w", "m", "t", "f", "a", "b", "c", "d",   # single-letter codes
        "A", "B", "C", "D", "T", "F",              # uppercase single-letter
        "Rep", "hist", "I b", "He f",              # known truncated imports
    })

    def get_exercises(self, lesson_id: int, phase: str = "practice", count: int = 10) -> list[dict]:
        # Fetch mai multe rânduri ca să avem rezervă după filtrare
        rows = self._conn.execute(
            "SELECT * FROM exercises WHERE lesson_id=? AND phase=? ORDER BY dificultate ASC, id ASC LIMIT ?",
            (int(lesson_id), phase, int(count) * 3),
        ).fetchall()
        out = []
        for r in rows:
            if len(out) >= count:
                break
            d = dict(r)
            # ── Filtrare răspunsuri corupte ─────────────────────────────────
            raspuns = (d.get("raspuns") or "").strip()
            if not raspuns:
                continue                             # gol → sărim
            if raspuns in self._BAD_RASPUNS:
                continue                             # cod de import defectuos
            # Răspunsuri de 1-2 caractere care nu sunt cuvinte reale
            if len(raspuns) <= 2 and not raspuns.isalpha():
                continue
            # Răspuns evident trunchiat (conține spațiu dar e mai scurt de 4 chars)
            if len(raspuns) < 4 and " " in raspuns:
                continue
            # ── Curăță explicatie: elimină label-urile de secțiune din textbook ──
            expl = d.get("explicatie") or ""
            if expl:
                # Elimină sufixe de tip "(... Short a)" / "(... I/yo)" etc.
                import re as _re
                expl = _re.sub(
                    r"\.\s*(?:Short\s+\w\)?|I/y\w+\)?|Long\s+\w\)?|Ex\s+\d+\w?\)?)\s*$",
                    ".", expl
                ).strip()
                d["explicatie"] = expl
            # ── Parsing choices / skill_codes ────────────────────────────────
            if d.get("choices"):
                try:
                    d["choices"] = json.loads(d["choices"])
                except Exception:
                    pass
            if d.get("skill_codes"):
                try:
                    d["skill_codes"] = json.loads(d["skill_codes"])
                except Exception:
                    d["skill_codes"] = None
            out.append(d)
        return out

    # ── Error bank / Spaced repetition ───────────────────────────────────────

    def mark_exercise_wrong(self, user_id: int, exercise_id: int) -> None:
        """
        Marchează un exercițiu ca greșit și calculează data de retry.
        SM-2 simplificat:
          - prima greșeală  → retry mâine (+1 zi)
          - a doua greșeală → retry peste 3 zile
          - a treia+        → retry peste 7 zile
        """
        from datetime import date, timedelta

        row = self._conn.execute(
            "SELECT wrong_count FROM user_exercise_stats WHERE user_id=? AND exercise_id=?",
            (int(user_id), int(exercise_id)),
        ).fetchone()

        wrong_count = (row["wrong_count"] + 1) if row else 1

        interval = 1 if wrong_count <= 1 else (3 if wrong_count == 2 else 7)
        retry_after = (date.today() + timedelta(days=interval)).isoformat()

        self._conn.execute(
            """INSERT INTO user_exercise_stats (user_id, exercise_id, wrong_count, retry_after)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, exercise_id)
               DO UPDATE SET wrong_count=excluded.wrong_count, retry_after=excluded.retry_after""",
            (int(user_id), int(exercise_id), wrong_count, retry_after),
        )
        self._conn.commit()

    def get_due_exercises(self, user_id: int, lesson_id: int) -> list[dict]:
        """
        Returnează exercițiile programate pentru astăzi (spaced repetition).
        Același format dict ca get_exercises().
        """
        from datetime import date
        today = date.today().isoformat()

        rows = self._conn.execute(
            """SELECT e.* FROM exercises e
               JOIN user_exercise_stats s ON s.exercise_id = e.id
               WHERE s.user_id = ? AND e.lesson_id = ?
                 AND s.retry_after IS NOT NULL AND s.retry_after <= ?
               ORDER BY s.wrong_count DESC, e.dificultate ASC""",
            (int(user_id), int(lesson_id), today),
        ).fetchall()

        out = []
        for r in rows:
            d = dict(r)
            if d.get("choices"):
                try:
                    d["choices"] = json.loads(d["choices"])
                except Exception:
                    pass
            if d.get("skill_codes"):
                try:
                    d["skill_codes"] = json.loads(d["skill_codes"])
                except Exception:
                    d["skill_codes"] = None
            out.append(d)
        return out

    def get_micro_quiz_for_lesson(self, lesson_id: int, chunk_index: int) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM micro_quiz WHERE lesson_id=? AND chunk_index=?",
            (int(lesson_id), int(chunk_index)),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("choices"):
            try:
                d["choices"] = json.loads(d["choices"])
            except Exception:
                pass
        if d.get("skill_codes"):
            try:
                d["skill_codes"] = json.loads(d["skill_codes"])
            except Exception:
                d["skill_codes"] = None
        return d

    # ───────────────────────────────────────────────────────────────────
    # Sessions
    # ───────────────────────────────────────────────────────────────────

    def start_session(self, user_id: int, lesson_id: int, phase: str = "practice") -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (user_id, lesson_id, phase, started_at) VALUES (?,?,?,datetime('now'))",
            (int(user_id), int(lesson_id), phase),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record_answer(self, session_id: int, exercise_id: int, user_answer: str,
                      is_correct: bool, hints_used: int = 0, time_sec: float = 0.0):
        self._conn.execute(
            """INSERT INTO session_answers (session_id, exercise_id, user_answer, is_correct, hints_used, time_sec)
               VALUES (?,?,?,?,?,?)""",
            (int(session_id), int(exercise_id), user_answer, 1 if is_correct else 0, int(hints_used), float(time_sec)),
        )
        self._conn.commit()

    def end_session(self, session_id: int, score: float, total_q: int, correct_q: int, duration_s: int, attention_pct: float = 100.0):
        self._conn.execute(
            """UPDATE sessions SET score=?, total_q=?, correct_q=?, duration_s=?, ended_at=datetime('now'), attention_pct=?
               WHERE id=?""",
            (float(score), int(total_q), int(correct_q), int(duration_s), float(attention_pct), int(session_id)),
        )
        self._conn.commit()

    # ───────────────────────────────────────────────────────────────────
    # Progress
    # ───────────────────────────────────────────────────────────────────

    def update_progress(self, user_id: int, lesson_id: int, score: float, passed: bool):
        row = self._conn.execute(
            "SELECT * FROM progress WHERE user_id=? AND lesson_id=?",
            (int(user_id), int(lesson_id)),
        ).fetchone()

        now = datetime.now().isoformat(timespec="seconds")
        if not row:
            self._conn.execute(
                """INSERT INTO progress (user_id, lesson_id, best_score, attempts, passed, current_level, consecutive_good, last_attempt)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (int(user_id), int(lesson_id), float(score), 1, 1 if passed else 0, 1, 1 if passed else 0, now),
            )
        else:
            best = max(float(row["best_score"] or 0), float(score))
            attempts = int(row["attempts"] or 0) + 1
            consecutive_good = int(row["consecutive_good"] or 0)
            if passed:
                consecutive_good += 1
            else:
                consecutive_good = 0
            self._conn.execute(
                """UPDATE progress
                   SET best_score=?, attempts=?, passed=?, consecutive_good=?, last_attempt=?
                   WHERE user_id=? AND lesson_id=?""",
                (best, attempts, 1 if passed else int(row["passed"] or 0), consecutive_good, now, int(user_id), int(lesson_id)),
            )
        self._conn.commit()

    def get_progress(self, user_id: int) -> list[dict]:
        rows = self._conn.execute(
            """SELECT p.*, l.title, l.subject, l.grade
               FROM progress p JOIN lessons l ON l.id=p.lesson_id
               WHERE p.user_id=?
               ORDER BY l.grade ASC, l.subject ASC, l.unit ASC, l.order_in_unit ASC""",
            (int(user_id),),
        ).fetchall()
        return [dict(r) for r in rows]

    # ───────────────────────────────────────────────────────────────────
    # Skill tracking
    # ───────────────────────────────────────────────────────────────────

    def ensure_skills_exist(self, skill_codes: Iterable[str]):
        for code in skill_codes:
            row = self._conn.execute("SELECT 1 FROM skills WHERE code=?", (code,)).fetchone()
            if row:
                continue
            # create generic
            self._conn.execute(
                "INSERT OR IGNORE INTO skills (code, subject, grade, name, description, prereq_codes) VALUES (?,?,?,?,?,?)",
                (code, "Generic", 1, code, "", json.dumps([])),
            )
        self._conn.commit()

    def update_user_skills(self, user_id: int, skill_codes: Iterable[str],
                           is_correct: bool, weight: float = 1.0,
                           time_sec: float = 0.0, hints_used: int = 0):
        """Actualizează mastery pentru fiecare skill din lista.

        Parametri noi (skill progression framework):
          time_sec   — durata răspunsului în secunde (0 = necunoscut)
          hints_used — câte hint-uri a folosit elevul la acest exercițiu
        """
        skill_codes = list(skill_codes or [])
        if not skill_codes:
            return
        self.ensure_skills_exist(skill_codes)
        now = datetime.now().isoformat(timespec="seconds")
        today = datetime.now().strftime("%Y-%m-%d")

        for code in skill_codes:
            raw = self._conn.execute(
                "SELECT * FROM user_skill WHERE user_id=? AND skill_code=?",
                (int(user_id), code),
            ).fetchone()
            row = dict(raw) if raw else None

            if not row:
                attempts = 1
                correct = 1 if is_correct else 0
                mastery = 0.6 if is_correct else 0.2
                skill_streak = 1 if is_correct else 0
                self._conn.execute(
                    """INSERT INTO user_skill
                       (user_id, skill_code, mastery, attempts, correct, last_update,
                        avg_time, skill_streak, mastery_level, last_practiced)
                       VALUES (?,?,?,?,?,?,?,?,0,?)""",
                    (int(user_id), code, float(mastery), attempts, correct, now,
                     float(time_sec) if time_sec > 0 else 0.0,
                     skill_streak, today),
                )
            else:
                attempts = int(row.get("attempts") or 0) + 1
                correct  = int(row.get("correct") or 0) + (1 if is_correct else 0)
                old_m    = float(row.get("mastery") or 0.0)

                # Mastery float: creștem rapid la început, mai lent ulterior
                delta  = (0.15 if is_correct else -0.10) * float(weight)
                mastery = max(0.0, min(1.0, old_m + delta))

                # avg_time: medie mobilă exponențială (EMA α=0.2)
                old_avg_t = float(row.get("avg_time") or 0.0)
                avg_time = (old_avg_t * 0.8 + time_sec * 0.2) if time_sec > 0 else old_avg_t

                # skill_streak
                skill_streak = int(row.get("skill_streak") or 0)
                skill_streak = skill_streak + 1 if is_correct else 0

                # mastery_level (0-3): avansat discret, cu spaced mastery
                # Nivel avansează DOAR dacă azi != last_practiced (2 zile diferite)
                old_level     = int(row.get("mastery_level") or 0)
                last_practiced = row.get("last_practiced") or ""
                new_level = old_level

                if last_practiced != today:
                    accuracy = correct / max(1, attempts)
                    if accuracy >= 0.90 and attempts >= 12:
                        new_level = max(old_level, 3)   # L3 Avansat
                    elif accuracy >= 0.85 and attempts >= 8:
                        new_level = max(old_level, 2)   # L2 Consolidare
                    elif accuracy >= 0.80 and attempts >= 5:
                        new_level = max(old_level, 1)   # L1 Manual

                    # Downgrade dacă elevul se luptă semnificativ
                    if accuracy < 0.50 and attempts >= 10 and new_level > 0:
                        new_level = max(0, new_level - 1)

                self._conn.execute(
                    """UPDATE user_skill
                       SET mastery=?, attempts=?, correct=?, last_update=?,
                           avg_time=?, skill_streak=?, mastery_level=?, last_practiced=?
                       WHERE user_id=? AND skill_code=?""",
                    (mastery, attempts, correct, now,
                     avg_time, skill_streak, new_level, today,
                     int(user_id), code),
                )
        self._conn.commit()

    def get_user_skills(self, user_id: int, subject: str = None) -> list[dict]:
        if subject:
            rows = self._conn.execute(
                """SELECT us.*, s.subject, s.grade, s.name
                   FROM user_skill us JOIN skills s ON s.code=us.skill_code
                   WHERE us.user_id=? AND s.subject=?
                   ORDER BY s.grade ASC, s.code ASC""",
                (int(user_id), subject),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT us.*, s.subject, s.grade, s.name
                   FROM user_skill us JOIN skills s ON s.code=us.skill_code
                   WHERE us.user_id=?
                   ORDER BY s.subject ASC, s.grade ASC, s.code ASC""",
                (int(user_id),),
            ).fetchall()
        return [dict(r) for r in rows]


    def can_access_tier4(self, user_id: int, skill_codes: list) -> bool:
        """Tier 4 (Boss Fight / Admitere) deblocat doar când mastery_level >= 2
        pe TOATE skill-urile cerute. Fără skill_codes → blocat implicit."""
        if not skill_codes:
            return False
        placeholders = ",".join("?" * len(skill_codes))
        rows = self._conn.execute(
            f"SELECT mastery_level FROM user_skill "
            f"WHERE user_id=? AND skill_code IN ({placeholders})",
            [int(user_id)] + list(skill_codes),
        ).fetchall()
        if len(rows) < len(skill_codes):
            return False   # Utilizatorul nu a practicat toate skill-urile
        return all((r["mastery_level"] or 0) >= 2 for r in rows)

    def select_adaptive_exercises(self, user_id: int, lesson_id: int,
                                   n: int = 8) -> list[dict]:
        """Returnează n exerciții ordonate adaptiv după skill mastery.

        Strategie:
          1. Exercițiile scadente (spaced repetition) au prioritate maximă.
          2. Exercițiile cu skill_codes unde mastery e mai scăzut sunt preferate.
          3. Dificultatea exercițiului este aliniată la nivelul curent al skill-ului:
             mastery_level 0 → dific 1, nivel 1 → dific 1-2, nivel 2 → dific 2-3, nivel 3 → dific 3.
          4. Tier 4 (Boss Fight) exclus dacă utilizatorul nu are mastery_level >= 2.
        """
        from datetime import date
        today = date.today().isoformat()

        all_exs = self.get_exercises(lesson_id, "practice", 50)
        if not all_exs:
            return []

        # Tier 4 gating: exclude exerciții Boss Fight dacă mastery insufficient
        all_skill_codes = list({c for e in all_exs for c in (e.get("skill_codes") or [])})
        tier4_ok = self.can_access_tier4(user_id, all_skill_codes)
        if not tier4_ok:
            all_exs = [
                e for e in all_exs
                if int(e.get("difficulty_tier") or e.get("dificultate") or 1) < 4
            ]

        # Construim dicționar skill_code → {level, mastery}
        skill_info: dict[str, dict] = {}
        for row in self._conn.execute(
            "SELECT skill_code, mastery_level, mastery FROM user_skill WHERE user_id=?",
            (int(user_id),)
        ).fetchall():
            skill_info[row["skill_code"]] = {
                "level":   int(row["mastery_level"] or 0),
                "mastery": float(row["mastery"] or 0.0),
            }

        # Exerciții scadente din spaced repetition
        due_ids: set[int] = set()
        for row in self._conn.execute(
            """SELECT exercise_id FROM user_exercise_stats
               WHERE user_id=? AND retry_after IS NOT NULL AND retry_after <= ?""",
            (int(user_id), today)
        ).fetchall():
            due_ids.add(int(row["exercise_id"]))

        def _priority(ex: dict) -> float:
            codes = ex.get("skill_codes") or []
            ex_diff = int(ex.get("dificultate") or 1)

            if not codes:
                return 0.5  # neutral

            masteries = [skill_info.get(c, {}).get("mastery", 0.5) for c in codes]
            avg_mastery = sum(masteries) / len(masteries)
            avg_level   = sum(skill_info.get(c, {}).get("level", 0) for c in codes) / len(codes)

            # Preferăm skill-urile slabe (prioritate inversă față de mastery)
            weakness_score = 1.0 - avg_mastery

            # Penalizare dacă dificultatea nu se potrivește nivelului
            target_diff = min(3, int(avg_level) + 1)
            diff_penalty = abs(ex_diff - target_diff) * 0.25
            match_score = max(0.0, 1.0 - diff_penalty)

            return weakness_score * match_score

        scored = sorted(all_exs, key=_priority, reverse=True)

        # Exercițiile scadente vin primele
        due   = [e for e in scored if e.get("id") in due_ids]
        rest  = [e for e in scored if e.get("id") not in due_ids]
        combined = due + rest
        return combined[:n]

    def get_skill_mastery_summary(self, user_id: int) -> dict:
        """Returnează un rezumat al progresiei skill-urilor pe grade și niveluri.

        Format:
          {
            "by_grade": { grade: {"L0": n, "L1": n, "L2": n, "L3": n} },
            "weak_skills": [ {code, name, mastery_level, mastery, subject, grade} ],
            "strong_skills": [ ... ],
          }
        """
        rows = self._conn.execute(
            """SELECT us.skill_code, us.mastery, us.mastery_level,
                      s.name, s.subject, s.grade
               FROM user_skill us JOIN skills s ON s.code=us.skill_code
               WHERE us.user_id=?
               ORDER BY s.grade ASC, us.mastery ASC""",
            (int(user_id),)
        ).fetchall()

        by_grade: dict[int, dict] = {}
        weak: list[dict] = []
        strong: list[dict] = []

        for row in rows:
            g = int(row["grade"] or 1)
            lvl = int(row["mastery_level"] or 0)
            if g not in by_grade:
                by_grade[g] = {"L0": 0, "L1": 0, "L2": 0, "L3": 0}
            by_grade[g][f"L{lvl}"] += 1

            d = {
                "code":          row["skill_code"],
                "name":          row["name"],
                "mastery_level": lvl,
                "mastery":       float(row["mastery"] or 0.0),
                "subject":       row["subject"],
                "grade":         g,
            }
            if lvl == 0 or float(row["mastery"] or 0) < 0.60:
                weak.append(d)
            elif lvl >= 2:
                strong.append(d)

        return {
            "by_grade":     by_grade,
            "weak_skills":  weak[:10],
            "strong_skills": strong[:10],
        }

    # ───────────────────────────────────────────────────────────────────
    # Stele si streak
    # ───────────────────────────────────────────────────────────────────

    @staticmethod
    def score_to_stars(score: float) -> int:
        """Converteste scorul (0..1) in 1-3 stele."""
        if score >= 0.9:
            return 3
        if score >= 0.7:
            return 2
        if score >= 0.5:
            return 1
        return 0

    def award_stars(self, user_id: int, lesson_id: int, score: float) -> int:
        """
        Calculeaza stelee pentru aceasta sesiune si actualizeaza progresul.
        Returneaza numarul de stele acordate (0-3).
        """
        stars = self.score_to_stars(score)
        if stars == 0:
            return 0
        # Stele in progress (pastram max)
        row = self._conn.execute(
            "SELECT stars FROM progress WHERE user_id=? AND lesson_id=?",
            (int(user_id), int(lesson_id))
        ).fetchone()
        if row is None:
            return stars  # update_progress inca nu a rulat
        old_stars = int(row["stars"] or 0)
        new_stars = max(old_stars, stars)
        self._conn.execute(
            "UPDATE progress SET stars=? WHERE user_id=? AND lesson_id=?",
            (new_stars, int(user_id), int(lesson_id))
        )
        # Totalul de stele al userului (recalculeaza din progress)
        total = self._conn.execute(
            "SELECT SUM(stars) FROM progress WHERE user_id=?",
            (int(user_id),)
        ).fetchone()[0] or 0
        self._conn.execute(
            "UPDATE users SET total_stars=? WHERE id=?",
            (int(total), int(user_id))
        )
        self._conn.commit()
        return stars

    def update_streak(self, user_id: int) -> int:
        """
        Actualizeaza streak-ul zilnic al utilizatorului.
        Returneaza streak-ul curent (numarul de zile consecutive).
        """
        today = datetime.now().strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT streak_days, streak_last_date FROM users WHERE id=?",
            (int(user_id),)
        ).fetchone()
        if row is None:
            return 0
        streak = int(row["streak_days"] or 0)
        last_date = row["streak_last_date"] or ""
        if last_date == today:
            return streak  # deja actualizat azi
        # Verifica daca este ziua de dupa
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if last_date == yesterday:
            streak += 1
        else:
            streak = 1  # reset streak
        self._conn.execute(
            "UPDATE users SET streak_days=?, streak_last_date=? WHERE id=?",
            (streak, today, int(user_id))
        )
        self._conn.commit()
        return streak

    def get_user_stars(self, user_id: int) -> dict:
        """Returneaza totalul de stele si streak-ul pentru un user."""
        row = self._conn.execute(
            "SELECT total_stars, streak_days, streak_last_date FROM users WHERE id=?",
            (int(user_id),)
        ).fetchone()
        if row is None:
            return {"total_stars": 0, "streak_days": 0}
        return {
            "total_stars": int(row["total_stars"] or 0),
            "streak_days": int(row["streak_days"] or 0),
            "streak_last_date": row["streak_last_date"] or "",
        }

    def close(self):
        try:
            self._conn.commit()
            self._conn.close()
        except Exception:
            pass

