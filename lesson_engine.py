#!/usr/bin/env python3
"""
🎓 LESSON ENGINE — Orchestrator complet de lecție (2026-ready)

Flux:
  pre-test → introducere → teorie pe chunk-uri (+ micro-quiz) → practică ghidată → post-test → rezumat

Upgrade-uri "2026":
- "barge-in" logic: UI poate chema ask_free_question() oricând (oprește TTS, răspuns scurt)
- Misconception Engine: feedback specific pentru greșeli tipice (matematică + română)
- Skill tracking minimal: fiecare exercițiu poate avea skill_codes; DB actualizează mastery
- Adaptare: dificultatea și numărul de exerciții se ajustează după pre-test + ezitări

Import:
    from lesson_engine import LessonEngine, LessonState, QuestionResult
"""

from __future__ import annotations

import re
import time
import threading
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

from database import Database
from deepseek_client import DeepSeekClient
from tts_engine import TTSEngine, get_message
from md_library import classify_chunk, sanitize_markdown_for_tts


# ─────────────────────────────────────────────────────────────────────────────
# State machine
# ─────────────────────────────────────────────────────────────────────────────

class LessonState(Enum):
    IDLE         = auto()
    WARMUP       = auto()   # SRS: recapitulare exerciții din sesiuni anterioare
    PRE_TEST     = auto()
    LESSON_INTRO = auto()
    LESSON_CHUNK = auto()
    MICRO_QUIZ   = auto()
    PRACTICE     = auto()
    POST_TEST    = auto()
    SUMMARY      = auto()
    DONE         = auto()
    PAUSED       = auto()


@dataclass
class QuestionResult:
    exercise_id: int
    user_answer: str
    is_correct: bool
    hints_used: int
    time_sec: float
    feedback: str
    meta: dict = field(default_factory=dict)  # edits, hesitation, attention_state etc.


@dataclass
class LessonSession:
    user_id: int
    lesson: dict
    state: LessonState = LessonState.IDLE

    warmup_exercises:   list = field(default_factory=list)   # SRS due items
    srs_exercise_ids:   set  = field(default_factory=set)    # IDs ale exercițiilor SRS (pentru update)
    pretest_exercises:  list = field(default_factory=list)
    practice_exercises: list = field(default_factory=list)
    posttest_exercises: list = field(default_factory=list)

    pretest_results:  list = field(default_factory=list)
    practice_results: list = field(default_factory=list)
    posttest_results: list = field(default_factory=list)

    current_exercise_idx: int = 0
    current_hints_used: int = 0

    theory_chunks: list = field(default_factory=list)
    current_chunk_idx: int = 0

    started_at: float = field(default_factory=time.time)
    session_id: Optional[int] = None

    correct_streak:    int = 0
    consecutive_wrong: int = 0   # resetat la răspuns corect; declanșează re-explicare la 3

    # "2026" adaptation signals
    avg_answer_time: float = 0.0
    avg_edits: float = 0.0
    answers_count: int = 0

    # DDA (Dynamic Difficulty Adjustment) — tier intra-sesiune
    current_tier:    int = 2   # 1=Basic, 2=Medium, 3=Advanced, 4=BossFight
    tier_up_streak:  int = 0   # răspunsuri corecte consecutive → upgrade la 3
    tier_down_count: int = 0   # greșeli consecutive → downgrade la 2

    def duration_seconds(self) -> int:
        return int(time.time() - self.started_at)

    def get_score(self, results: list) -> float:
        if not results:
            return 0.0
        return sum(1 for r in results if r.is_correct) / len(results) * 100.0

    def get_pretest_score(self) -> float:
        return self.get_score(self.pretest_results) if self.pretest_results else 100.0

    def get_practice_score(self) -> float:
        return self.get_score(self.practice_results)

    def get_posttest_score(self) -> float:
        if self.posttest_results:
            return self.get_score(self.posttest_results)
        # Fallback: dacă posttest a fost sărit (nu există exerciții), folosim practica
        # Evită afișarea 0% când elevul a răspuns corect la exercițiile de practică.
        if self.practice_results:
            return self.get_score(self.practice_results)
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Misconception Engine (heuristici rapide, fără LLM)
# ─────────────────────────────────────────────────────────────────────────────

class MisconceptionEngine:
    """Feedback specific pentru greșeli tipice.

    Ținta: să pari "profesor" (diagnostic), nu doar "corector".
    """

    def feedback(self, subject: str, enunt: str, correct: str, user: str) -> Optional[str]:
        subject = (subject or "").lower()
        user_s = (user or "").strip()
        correct_s = (correct or "").strip()
        enunt_s = (enunt or "").strip().lower()

        if not user_s:
            return "Nu am primit un răspuns. Încearcă să scrii sau să spui un număr/cuvânt."

        # Matematică
        if "mat" in subject:
            # greșeală de +1/-1
            try:
                u = int(user_s)
                c = int(correct_s)
                if abs(u - c) == 1:
                    return "E foarte aproape! Verifică încă o dată ultima numărare (poate ai sărit un pas)."
            except Exception:
                pass

            # transport/împrumut
            if any(op in enunt_s for op in ["+", "adun", "-", "scăd"]):
                if any(w in enunt_s for w in ["zec", "unit", "două cifre", "transport", "împrumut"]):
                    return "Încearcă pe coloane: întâi unitățile, apoi zecile. Dacă treci de 9, transporți 1 la zeci."

            # inversare cifre (ex: 37 -> 73)
            if user_s.isdigit() and correct_s.isdigit() and len(user_s) == len(correct_s) == 2:
                if user_s == correct_s[::-1]:
                    return "Ai inversat cifrele. Uită-te la zeci și unități: prima cifră e zecile, a doua e unitățile."

        # Limba română
        if "rom" in subject:
            # diacritice simple
            if user_s.replace("â", "a").replace("ă", "a").replace("î", "i") == correct_s.replace("â", "a").replace("ă", "a").replace("î", "i") and user_s != correct_s:
                return "E foarte bine, doar diacriticele diferă. Încearcă să scrii cu ă/â/î unde trebuie."
            # literă mare la început
            if correct_s and user_s and correct_s[0].isupper() and user_s[0].islower():
                return "Propoziția începe cu literă mare. Încearcă să pui prima literă mare."
            # silabe (dacă răspunsul e număr)
            if "silab" in enunt_s:
                return "Spune cuvântul rar și numără de câte ori simți că se deschide gura. Asta te ajută la silabe."

        return None


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class LessonEngine:
    PRETEST_COUNT  = 3
    PRACTICE_COUNT = 8
    POSTTEST_COUNT = 5

    PRETEST_PASS_SCORE  = 70.0
    POSTTEST_PASS_SCORE = 75.0

    def __init__(self, db: Database, deepseek: DeepSeekClient, tts: TTSEngine):
        self.db = db
        self.deepseek = deepseek
        self.tts = tts

        self.session: Optional[LessonSession] = None
        self._prev_state: Optional[LessonState] = None
        self._mis = MisconceptionEngine()

        # Callbacks UI
        self.on_state_change:   Optional[Callable[[LessonState], None]] = None
        self.on_show_text:       Optional[Callable[[str], None]] = None
        self.on_show_exercise:   Optional[Callable[[dict, int, int], None]] = None
        self.on_show_hint:       Optional[Callable[[str, int], None]] = None
        self.on_show_scratchpad: Optional[Callable[[str], None]] = None
        self.on_exercise_result: Optional[Callable[[QuestionResult], None]] = None
        self.on_phase_complete:  Optional[Callable[[str, float], None]] = None
        self.on_done:            Optional[Callable[[LessonSession], None]] = None
        self.on_avatar_message:  Optional[Callable[[str, str], None]] = None  # text, emotion
        self.on_emotion_change:   Optional[Callable[[str, float], None]] = None  # (emotion, intensity)
        self.on_streak_milestone: Optional[Callable[[int], None]] = None         # streak 3/5/10

        # Control flux buton "Continuă →" din UI
        self._waiting_for_continue: bool = False

    # ───────────────────────────────────────────────────────────────────
    # Public control
    # ───────────────────────────────────────────────────────────────────

    def start(self, user_id: int, lesson_id: int):
        lesson = self.db.get_lesson(lesson_id)
        if not lesson:
            print(f"❌ LessonEngine: Lecția {lesson_id} nu există")
            return

        self.session = LessonSession(user_id=user_id, lesson=lesson)

        # exerciții din DB (no LLM)
        self.session.pretest_exercises   = self.db.get_exercises(lesson_id, "pretest",  self.PRETEST_COUNT)
        self.session.practice_exercises  = self.db.get_exercises(lesson_id, "practice", self.PRACTICE_COUNT)
        self.session.posttest_exercises  = self.db.get_exercises(lesson_id, "posttest", self.POSTTEST_COUNT)

        # teorie pe paragrafe
        theory = lesson.get("theory", "")
        self.session.theory_chunks = self._split_theory(theory)

        self.session.session_id = self.db.start_session(user_id, lesson_id, "full")

        # SRS Jocul de Încălzire — exerciții scadente din sesiuni anterioare
        srs_due = self.db.get_srs_due(user_id, limit=3)
        if srs_due:
            self.session.warmup_exercises = srs_due
            self.session.srs_exercise_ids = {ex["id"] for ex in srs_due}
            self._transition_to(LessonState.WARMUP)
            self._start_warmup()
        elif self.session.pretest_exercises:
            self._transition_to(LessonState.PRE_TEST)
            self._start_pretest()
        else:
            self._start_intro()

    def pause(self):
        if self.session and self.session.state not in (LessonState.PAUSED, LessonState.DONE):
            self._prev_state = self.session.state
            self._transition_to(LessonState.PAUSED)
            self._speak("Lecția e în pauză. Apasă Continuă când ești gata! ⏸️", "idle")

    def resume(self):
        if self.session and self.session.state == LessonState.PAUSED:
            self._transition_to(self._prev_state or LessonState.PRACTICE)
            self._speak("Bine ai revenit! Continuăm! 😊", "happy")
            # revine la contextul potrivit
            if self.session.state in (LessonState.LESSON_CHUNK, LessonState.MICRO_QUIZ):
                self._show_current_chunk()
            else:
                self._show_current_exercise()

    def request_hint(self) -> Optional[str]:
        if not self.session:
            return None
        if self.session.state not in (LessonState.PRE_TEST, LessonState.PRACTICE, LessonState.POST_TEST):
            return None

        exercises = self._get_current_exercises()
        idx = self.session.current_exercise_idx
        if not exercises or idx >= len(exercises):
            return None

        ex = exercises[idx]
        hint_nr = self.session.current_hints_used + 1
        self.session.current_hints_used = hint_nr

        key = f"hint_{min(hint_nr,3)}"
        hint_text = ex.get(f"hint{hint_nr}") or get_message(key)
        self._speak(hint_text, "thinking")
        if self.on_show_hint:
            self.on_show_hint(hint_text, hint_nr)
        return hint_text

    def submit_answer(self, answer: str, meta: Optional[dict] = None):
        """Primește răspunsul elevului.

        meta poate include: time_sec, edits, hesitation_score, attention_state
        """
        if not self.session:
            return
        if self.session.state not in (LessonState.PRE_TEST, LessonState.PRACTICE, LessonState.POST_TEST, LessonState.MICRO_QUIZ):
            return

        meta = meta or {}

        if self.session.state in (LessonState.PRE_TEST, LessonState.PRACTICE, LessonState.POST_TEST):
            self._answer_exercise(answer, meta)
        elif self.session.state == LessonState.MICRO_QUIZ:
            self._answer_micro_quiz(answer, meta)

    def ask_free_question(self, question: str):
        """Întrebare liberă ("barge-in").

        UI tipic:
          - oprește TTS
          - apelează engine.ask_free_question()
          - engine răspunde scurt și apoi revine la lecție
        """
        if not self.session or not question.strip():
            return

        lesson = self.session.lesson
        subject = lesson.get("subject", "")
        grade = lesson.get("grade", 1)

        # Context: chunk curent + rezumat
        chunk = ""
        if self.session.theory_chunks and 0 <= self.session.current_chunk_idx < len(self.session.theory_chunks):
            chunk = self.session.theory_chunks[self.session.current_chunk_idx]

        prompt = (
            f"Ești un profesor prietenos pentru clasa {grade} ({subject}).\n"
            f"Răspunde foarte scurt (max 4-6 propoziții), clar, cu un exemplu.\n\n"
            f"Context lecție: {lesson.get('title','')}\n"
            f"Rezumat: {lesson.get('summary','')}\n"
            f"Fragment teorie: {chunk[:800]}\n\n"
            f"Întrebare elev: {question.strip()}\n"
        )

        # Apel non-blocking — nu blocăm UI-ul pentru max 25s
        def _bg():
            if self.deepseek.available:
                ans = self.deepseek.ask(prompt, timeout=25)
                if not ans:
                    ans = "Întrebare bună! Reformulează în 1 propoziție și încercăm din nou."
            else:
                ans = "Momentan modelul nu este disponibil. Poți scrie mai simplu și reîncercăm."
            cite = (f"(din lecția «{lesson.get('title','')}», "
                    f"partea {self.session.current_chunk_idx + 1})")
            self._speak(f"{ans}\n\n{cite}", "talking")

        threading.Thread(target=_bg, daemon=True).start()

    # ───────────────────────────────────────────────────────────────────
    # Phase starts
    # ───────────────────────────────────────────────────────────────────

    def _start_warmup(self):
        """SRS Jocul de Încălzire — recapitulăm exerciții din lecțiile anterioare."""
        self.session.current_exercise_idx = 0
        self.session.current_hints_used   = 0
        n = len(self.session.warmup_exercises)
        self._speak(
            f"Jocul de Încălzire! Hai să recapitulăm {n} exerciții din lecțiile anterioare "
            "înainte să începem ceva nou.",
            "talking",
        )
        if self.on_state_change:
            self.on_state_change(LessonState.WARMUP)
        self._show_current_exercise()

    def _start_pretest(self):
        self.session.current_exercise_idx = 0
        self.session.current_hints_used = 0
        self._speak("Începem cu un mini-test rapid. 3 întrebări!", "talking")
        self._show_current_exercise()

    def _start_intro(self):
        lesson = self.session.lesson
        self._transition_to(LessonState.LESSON_INTRO)
        intro = f"Astăzi învățăm: {lesson.get('title', '')}."
        # Setăm mesajul avatarului fără TTS separat — primul chunk va fi vorbit imediat,
        # evitând efectul de "două voci" (intro + chunk în coadă rapid).
        if self.on_avatar_message:
            self.on_avatar_message(intro, "happy")
        # Pornește direct chunk 1 (un singur TTS)
        self.session.current_chunk_idx = 0
        self._transition_to(LessonState.LESSON_CHUNK)
        self._show_current_chunk()

    def _start_practice(self):
        self._transition_to(LessonState.PRACTICE)
        self.session.current_exercise_idx = 0
        self.session.current_hints_used = 0
        self._speak("Acum exersăm împreună. Începe cu primul exercițiu!", "encouraging")
        self._show_current_exercise()

    def _start_posttest(self):
        self._transition_to(LessonState.POST_TEST)
        self.session.current_exercise_idx = 0
        self.session.current_hints_used = 0

        # ── FIX: lecții importate din manual nu au exerciții posttest separate ──
        # generate_from_manuals.py pune tot în faza "practice". Dacă posttest e gol,
        # selectăm ultimele N exerciții practice (cele mai grele) ca "test final".
        if not self.session.posttest_exercises and self.session.practice_exercises:
            n = self.POSTTEST_COUNT
            # Sortăm descrescător după dificultate — test final = exerciții mai grele
            candidates = sorted(
                self.session.practice_exercises,
                key=lambda e: int(e.get("difficulty_tier") or e.get("dificultate") or 1),
                reverse=True,
            )
            self.session.posttest_exercises = candidates[:n]
            print(
                f"ℹ️  Posttest gol — folosim {len(self.session.posttest_exercises)} "
                f"exerciții practice (cele mai grele) ca test final"
            )

        self._emit_emotion("thinking", 0.6)
        self._speak("Gata! Facem un test scurt de final.", "talking")
        self._show_current_exercise()

    # ───────────────────────────────────────────────────────────────────
    # UI helpers
    # ───────────────────────────────────────────────────────────────────

    def _emit_emotion(self, emotion: str, intensity: float = 0.5):
        """Emite emoția curentă a avatarului (thread-safe via callback)."""
        try:
            if self.on_emotion_change:
                self.on_emotion_change(emotion, intensity)
        except Exception:
            pass

    def _transition_to(self, state: LessonState):
        if not self.session:
            return
        self.session.state = state
        if self.on_state_change:
            self.on_state_change(state)

    def _speak(self, text: str, emotion: str = "idle"):
        clean = sanitize_markdown_for_tts(text, keep_headings=False)
        if self.on_avatar_message:
            self.on_avatar_message(clean, emotion)
        self._emit_emotion(emotion, 0.5)
        self.tts.speak(clean)
        if self.on_show_text:
            self.on_show_text(clean)

    def _show_current_exercise(self):
        exercises = self._get_current_exercises()
        idx = self.session.current_exercise_idx
        if not exercises or idx >= len(exercises):
            self._complete_phase()
            return
        ex = exercises[idx]
        total = len(exercises)
        if self.on_show_exercise:
            self.on_show_exercise(ex, idx + 1, total)

    def _show_current_chunk(self):
        lesson = self.session.lesson
        if not self.session.theory_chunks:
            # dacă nu există teorie, sari direct în practică
            self._start_practice()
            return

        idx = self.session.current_chunk_idx
        if idx >= len(self.session.theory_chunks):
            self._start_practice()
            return

        chunk = self.session.theory_chunks[idx].strip()
        chunk_type = classify_chunk(chunk)

        if chunk_type == "task":
            # Chunk instrucțional — citim doar prima linie (sarcina) și deschidem scratchpad
            first_line = chunk.split("\n")[0][:160].strip()
            self._speak(
                f"Uite ce ai de făcut: {first_line} "
                "Scrie pașii în spațiul de lucru, apoi pune răspunsul final.",
                "talking"
            )
            if self.on_show_scratchpad:
                self.on_show_scratchpad(chunk)
        else:
            # THEORY / NOISE → comportament existent: citim tot chunk-ul
            self._speak(chunk, "talking")

        # Show micro-quiz only if DB has one for this chunk.
        # If not, the UI's "✅ Am înțeles! Continuă →" button handles advancement.
        mq = self.db.get_micro_quiz_for_lesson(lesson_id=lesson["id"], chunk_index=idx)
        if mq:
            self._micro_quiz_ex = mq
            self._transition_to(LessonState.MICRO_QUIZ)
            if self.on_show_exercise:
                self.on_show_exercise(mq, idx + 1, len(self.session.theory_chunks))
        else:
            self._micro_quiz_ex = None
            # Stay in LESSON_CHUNK; user clicks "Am înțeles!" → engine.next_chunk()

    def _get_current_exercises(self) -> list:
        if not self.session:
            return []
        st = self.session.state
        if st == LessonState.WARMUP:
            return self.session.warmup_exercises
        if st == LessonState.PRE_TEST:
            return self.session.pretest_exercises
        if st == LessonState.PRACTICE:
            return self.session.practice_exercises
        if st == LessonState.POST_TEST:
            return self.session.posttest_exercises
        return []

    # ───────────────────────────────────────────────────────────────────
    # Answer handling
    # ───────────────────────────────────────────────────────────────────

    def _answer_micro_quiz(self, answer: str, meta: dict):
        ex = getattr(self, "_micro_quiz_ex", None)
        if not ex:
            self._transition_to(LessonState.LESSON_CHUNK)
            self.session.current_chunk_idx += 1
            self._show_current_chunk()
            return

        expected = (ex.get("raspuns") or "").strip().lower()
        got = (answer or "").strip().lower()
        ok = got == expected or (expected in got)

        if ok:
            self._speak(get_message("encourage"), "happy")
            self._transition_to(LessonState.LESSON_CHUNK)
            self.session.current_chunk_idx += 1
            self._show_current_chunk()
        else:
            # reteach: un exemplu scurt
            self._speak("Ok, hai să mai luăm o dată cu un exemplu simplu.", "thinking")
            self._transition_to(LessonState.LESSON_CHUNK)
            # nu avansăm chunk-ul
            self._show_current_chunk()

    @staticmethod
    def _normalize_answer(text: str) -> str:
        """Normalizează un răspuns pentru comparare echitabilă.
        203.000 == 203000 == 203 000 (separator de mii românesc).
        Nu afectează zecimale reale (3.14 rămâne 3.14).
        """
        t = text.strip().lower()
        # Separator de mii cu punct (notație românească): aplicăm de 2x pentru 1.234.567
        t = re.sub(r"(\d{1,3})\.(\d{3})(?!\d)", r"\1\2", t)
        t = re.sub(r"(\d{1,3})\.(\d{3})(?!\d)", r"\1\2", t)
        # Separator de mii cu spațiu: "203 000" → "203000"
        t = re.sub(r"(\d{1,3}) (\d{3})(?!\d)", r"\1\2", t)
        t = re.sub(r"(\d{1,3}) (\d{3})(?!\d)", r"\1\2", t)
        return t

    def _answer_exercise(self, answer: str, meta: dict):
        exercises = self._get_current_exercises()
        idx = self.session.current_exercise_idx
        ex = exercises[idx]

        correct = (ex.get("raspuns") or "").strip()
        user = (answer or "").strip()

        # Comparam versiunile normalizate: 203.000 == 203000, 290 000 == 290000 etc.
        correct_n = self._normalize_answer(correct)
        user_n    = self._normalize_answer(user)
        is_correct = (user_n == correct_n)

        # Suport răspunsuri alternative ("32 sau 60"): oricare variantă e acceptată
        if not is_correct and re.search(r"\bsau\b", correct, flags=re.IGNORECASE):
            alts = [self._normalize_answer(a)
                    for a in re.split(r"\s+sau\s+", correct, flags=re.IGNORECASE)]
            is_correct = user_n in alts

        time_sec = float(meta.get("time_sec") or 0.0)
        edits = float(meta.get("edits") or 0.0)

        # "2026": update session averages (hesitation proxy)
        self.session.answers_count += 1
        n = self.session.answers_count
        self.session.avg_answer_time = ((self.session.avg_answer_time * (n - 1)) + time_sec) / n
        self.session.avg_edits = ((self.session.avg_edits * (n - 1)) + edits) / n

        # feedback
        if is_correct:
            self.session.correct_streak += 1
            self.session.consecutive_wrong = 0
            self.session.tier_up_streak += 1
            self.session.tier_down_count = 0
            feedback = get_message("encourage")
            streak = self.session.correct_streak
            if streak >= 10:
                self._emit_emotion("excited", 1.0)
                if self.on_streak_milestone: self.on_streak_milestone(streak)
            elif streak >= 5:
                self._emit_emotion("excited", 0.85)
                if self.on_streak_milestone: self.on_streak_milestone(streak)
            elif streak >= 3:
                self._emit_emotion("happy", 0.9)
                if self.on_streak_milestone: self.on_streak_milestone(streak)
            else:
                self._emit_emotion("happy", 0.6)
        else:
            self.session.correct_streak = 0
            self.session.consecutive_wrong += 1
            self.session.tier_up_streak = 0
            self.session.tier_down_count += 1
            fb = self._mis.feedback(self.session.lesson.get("subject", ""), ex.get("enunt", ""), correct, user)
            feedback = fb or ex.get("explicatie") or get_message("try_again")
            if self.session.consecutive_wrong >= 2:
                self._emit_emotion("encouraging", 0.8)
            else:
                self._emit_emotion("sad", 0.5)

        # DDA: tier upgrade la 3 răspunsuri corecte consecutive
        if self.session.tier_up_streak >= 3 and self.session.current_tier < 3:
            self.session.current_tier = min(3, self.session.current_tier + 1)
            self.session.tier_up_streak = 0
            tier_msg = f"Fantastic! Trecem la nivelul {self.session.current_tier} — exerciții mai dificile!"
            if self.on_avatar_message:
                self.on_avatar_message(tier_msg, "happy")
            self._emit_emotion("excited", 1.0)

        # DDA: tier downgrade la 2 greșeli consecutive
        elif self.session.tier_down_count >= 2 and self.session.current_tier > 1:
            self.session.current_tier = max(1, self.session.current_tier - 1)
            self.session.tier_down_count = 0
            tier_msg = f"Hai să consolidăm nivelul {self.session.current_tier} — ne pregătim mai bine!"
            if self.on_avatar_message:
                self.on_avatar_message(tier_msg, "neutral")
            self._emit_emotion("thinking", 0.6)

        qr = QuestionResult(
            exercise_id=int(ex.get("id", 0)),
            user_answer=user,
            is_correct=is_correct,
            hints_used=int(self.session.current_hints_used),
            time_sec=time_sec,
            feedback=feedback,
            meta=meta,
        )

        # ── Stochează rezultatul în lista fazei curente ──────────────────────
        # Fără acest append, get_practice_score() / get_posttest_score() returnează
        # mereu 0.0 (lista goală), iar get_pretest_score() returnează 100.0 (fallback).
        _st = self.session.state
        if _st == LessonState.PRE_TEST:
            self.session.pretest_results.append(qr)
        elif _st == LessonState.PRACTICE:
            self.session.practice_results.append(qr)
        elif _st == LessonState.POST_TEST:
            self.session.posttest_results.append(qr)

        # DB
        if self.session.session_id and qr.exercise_id > 0:
            self.db.record_answer(
                session_id=self.session.session_id,
                exercise_id=qr.exercise_id,
                user_answer=qr.user_answer,
                is_correct=qr.is_correct,
                hints_used=qr.hints_used,
                time_sec=qr.time_sec,
            )

        # Skill mastery — rulează indiferent de exercise_id (funcționează și pt JSON packs)
        if self.session.session_id:
            skill_codes = ex.get("skill_codes")
            if not skill_codes:
                # Fallback: derivăm un skill code din subiect + clasă (ex: "MATH_4", "RO_3")
                subj = (self.session.lesson.get("subject") or "").upper()
                grade = self.session.lesson.get("grade") or 0
                prefix = "MATH" if "MAT" in subj else ("RO" if "ROM" in subj or "COMUNICARE" in subj else "GEN")
                skill_codes = [f"{prefix}_{grade}"]

            # Tier-aware weight: tier 1 → delta mic, tier 3-4 → delta mare
            tier_weights = {1: 0.33, 2: 0.67, 3: 1.0, 4: 1.33}
            weight = tier_weights.get(self.session.current_tier, 1.0)

            self.db.update_user_skills(
                self.session.user_id, skill_codes, qr.is_correct,
                time_sec=qr.time_sec, hints_used=qr.hints_used,
                weight=weight,
            )

        # SRS — actualizare sau programare la prima întâlnire (orice exercițiu cu id > 0)
        if qr.exercise_id > 0 and self.session.session_id:
            quality = self._calc_srs_quality(
                qr.is_correct, qr.hints_used, qr.time_sec,
                avg_time=self.session.avg_answer_time or 30.0,
            )
            self.db.record_srs_answer(self.session.user_id, qr.exercise_id, quality)

        # Error bank: exercițiul greșit se reprogramează pentru sesiunile viitoare
        if not is_correct and qr.exercise_id > 0:
            self.db.mark_exercise_wrong(self.session.user_id, qr.exercise_id)

        # callback
        if self.on_exercise_result:
            self.on_exercise_result(qr)

        # vorbește feedback
        self._speak(feedback, "happy" if is_correct else "sad")

        # La 3 greșeli consecutive → pauză și re-explicare din alt chunk
        if self.session.consecutive_wrong >= 3:
            self.session.consecutive_wrong = 0
            self.session.current_hints_used = 0
            self.session.current_exercise_idx += 1
            self._trigger_alt_explanation()
            return

        # next — UI va apela advance_after_result() prin butonul "Continuă →"
        self.session.current_hints_used = 0
        self.session.current_exercise_idx += 1
        self._waiting_for_continue = True

    def advance_after_result(self):
        """Apelat de UI (butonul 'Continuă →') după ce copilul citește feedback-ul.

        Separă momentul afișării feedback-ului de tranziția la exercițiul următor:
        copilul citește explicația și apasă conștient în loc de auto-advance instant.
        """
        if not self.session or not self._waiting_for_continue:
            return
        self._waiting_for_continue = False
        self._show_current_exercise()

    # ───────────────────────────────────────────────────────────────────
    # Phase completion
    # ───────────────────────────────────────────────────────────────────

    def _complete_phase(self):
        st = self.session.state

        if st == LessonState.WARMUP:
            self._speak("Bine! Încălzire gata. Acum trecem la lecția de azi!", "happy")
            if self.session.pretest_exercises:
                self._transition_to(LessonState.PRE_TEST)
                self._start_pretest()
            else:
                self._start_intro()
            return

        if st == LessonState.PRE_TEST:
            score = self.session.get_pretest_score()
            if self.on_phase_complete:
                self.on_phase_complete("pretest", score)

            # adaptare: dacă e foarte bun, scurtăm lecția
            if score >= self.PRETEST_PASS_SCORE:
                self._speak("Super! Se pare că știi deja baza. Facem o recapitulare scurtă și trecem la exerciții mai grele.", "excited")
                # sare peste o parte din chunk-uri
                self.session.current_chunk_idx = max(0, len(self.session.theory_chunks) - 2)
                self._transition_to(LessonState.LESSON_CHUNK)
                self._show_current_chunk()
            else:
                self._start_intro()

        elif st == LessonState.PRACTICE:
            score = self.session.get_practice_score()
            if self.on_phase_complete:
                self.on_phase_complete("practice", score)
            self._start_posttest()

        elif st == LessonState.POST_TEST:
            score = self.session.get_posttest_score()
            if self.on_phase_complete:
                self.on_phase_complete("posttest", score)
            self._finish_session()

    def _finish_session(self):
        pre = self.session.get_pretest_score()
        post = self.session.get_posttest_score()
        practice = self.session.get_practice_score()

        passed = post >= self.POSTTEST_PASS_SCORE

        # update DB
        if self.session.session_id:
            self.db.end_session(
                session_id=self.session.session_id,
                score=post,
                total_q=len(self.session.posttest_results) + len(self.session.practice_results) + len(self.session.pretest_results),
                correct_q=int((post/100.0)*max(1, len(self.session.posttest_results))) if self.session.posttest_results else 0,
                duration_s=self.session.duration_seconds(),
            )
            self.db.update_progress(self.session.user_id, self.session.lesson["id"], post, passed)

        # rezumat
        self._transition_to(LessonState.SUMMARY)
        summary = (
            f"Rezumat: Pre-test {pre:.0f}%, Practică {practice:.0f}%, Post-test {post:.0f}%.\n"
            f"Timp mediu/răspuns: {self.session.avg_answer_time:.1f}s, Editări medii: {self.session.avg_edits:.1f}.\n"
        )
        summary += "Felicitări! Ai trecut lectia!" if passed else "Bun efort! Mai exersam putin si data viitoare va fi mai usor!"
        self._emit_emotion("excited" if passed else "encouraging", 1.0 if passed else 0.7)
        self._speak(summary, "happy" if passed else "encouraging")

        self._transition_to(LessonState.DONE)
        if self.on_done:
            self.on_done(self.session)

    # ───────────────────────────────────────────────────────────────────
    # Utils
    # ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _calc_srs_quality(is_correct: bool, hints_used: int, time_sec: float,
                          avg_time: float = 30.0) -> int:
        """Mapează performanța → quality SM-2 (0-5)."""
        if not is_correct:
            return 1
        if hints_used >= 2:
            return 2
        if hints_used == 1:
            return 3
        # Corect fără hint: distingem rapid vs. lent
        if time_sec > 0 and avg_time > 0 and time_sec <= avg_time * 0.7:
            return 5
        return 4

    def _split_theory(self, text: str) -> list:
        # split pe paragrafe, dar păstrează paragrafe utile
        parts = [p.strip() for p in (text or "").split("\n")]
        chunks = []
        buf = []
        for p in parts:
            if not p:
                if buf:
                    chunks.append(" ".join(buf).strip())
                    buf = []
                continue
            buf.append(p)
            if len(" ".join(buf)) > 240:
                chunks.append(" ".join(buf).strip())
                buf = []
        if buf:
            chunks.append(" ".join(buf).strip())
        return [c for c in chunks if len(c) > 10]


    # ───────────────────────────────────────────────────────────────────
    # Public helpers for UI
    # ───────────────────────────────────────────────────────────────────

    def next_chunk(self):
        """Avanseaza la urmatorul chunk de teorie (folosit de butonul 'Am inteles')."""
        if not self.session:
            return
        if self.session.state not in (LessonState.LESSON_CHUNK, LessonState.LESSON_INTRO):
            return
        self.session.current_chunk_idx += 1
        self._transition_to(LessonState.LESSON_CHUNK)
        self._show_current_chunk()

    def set_theory_chunks(self, chunks: list):
        """Înlocuiește teoria cu chunk-uri din manualul real (.md).

        Trebuie apelat DUPĂ engine.start(), înainte ca lecția să ajungă la
        faza LESSON_CHUNK (de regulă, imediat după start în MainWindow._on_login).
        """
        if not self.session:
            return
        clean = [c for c in chunks if len(c.strip()) > 10]
        if not clean:
            return
        self.session.theory_chunks = clean
        self.session.current_chunk_idx = 0
        print(f"✅ LessonEngine: {len(clean)} chunk-uri din manual real")

        # Adaptive exercise selection: pentru vizite repetate, ordonăm după skill mastery
        lesson_id = self.session.lesson.get("id", 0)
        try:
            prior_attempts = self.db.conn.execute(
                "SELECT attempts FROM progress WHERE user_id=? AND lesson_id=?",
                (self.session.user_id, lesson_id),
            ).fetchone()
            if prior_attempts and int(prior_attempts["attempts"] or 0) > 0:
                adaptive = self.db.select_adaptive_exercises(
                    self.session.user_id, lesson_id, self.PRACTICE_COUNT
                )
                if adaptive:
                    self.session.practice_exercises = adaptive
                    print(f"🎯 {len(adaptive)} exerciții selectate adaptiv (vizită #{int(prior_attempts['attempts'])+1})")
        except Exception as e:
            print(f"⚠️  Adaptive selection error: {e}")

        # Error bank: prepend exerciții scadente (dacă nu sunt deja incluse de select_adaptive)
        try:
            due = self.db.get_due_exercises(self.session.user_id, lesson_id)
            if due:
                existing_ids = {e["id"] for e in self.session.practice_exercises}
                extras = [e for e in due if e["id"] not in existing_ids]
                if extras:
                    self.session.practice_exercises = extras + self.session.practice_exercises
                    print(f"📅 {len(extras)} exerciții de recuperat din sesiunile anterioare")
        except Exception as e:
            print(f"⚠️  Error bank fetch: {e}")

        # Generare AI — NUMAI dacă lecția chiar are nevoie (nu are exerciții reale)
        if self.deepseek.available:
            lesson_id_bg = self.session.lesson.get("id", 0) if self.session else 0
            has_real = self._has_real_exercises(lesson_id_bg)
            if has_real:
                print(f"⏭️  AI skip: '{self.session.lesson.get('title','')}' are deja exerciții reale")
            else:
                # Delay 12s — lasă UI și modelul să se stabilizeze înainte de Ollama
                t = threading.Timer(12.0, self._generate_exercises_background)
                t.daemon = True
                t.start()

    def _trigger_alt_explanation(self):
        """Afișează un chunk alternativ de teorie după 3 greșeli consecutive.

        Alege chunk-ul următor (circular) față de cel curent, astfel copilul
        vede aceeași temă explicată dintr-un alt paragraf al manualului.
        La n=1 (un singur chunk), dă un recap scurt în loc să repete același chunk.
        """
        chunks = self.session.theory_chunks if self.session else []
        if not chunks:
            # Fără teorie → continuă cu exercițiile
            self._show_current_exercise()
            return

        n = len(chunks)
        current = max(0, min(self.session.current_chunk_idx, n - 1))

        if n == 1:
            # Singur chunk — recap scurt + continuă direct cu exercițiul
            recap = chunks[0][:220].strip()
            self._speak(
                f"Hai să revedem esențialul: {recap}. Încearcă din nou!",
                "encouraging"
            )
            self._show_current_exercise()
            return

        # Chunk alternativ (circular) — setat ÎNAINTE de tranziție
        alt_idx = (current + 1) % n
        self.session.current_chunk_idx = alt_idx   # ← ÎNAINTE de _transition_to

        self._speak(
            "Ai răspuns greșit de trei ori. "
            "Hai să revedem lecția dintr-un alt unghi!", "encouraging"
        )
        # _show_current_chunk() (apelat de _transition_to) afișează și citește alt_idx
        self._transition_to(LessonState.LESSON_CHUNK)

    # ───────────────────────────────────────────────────────────────────
    # AI Exercise Generation
    # ───────────────────────────────────────────────────────────────────

    _PLACEHOLDER_PATTERNS = (
        "Întrebare rapidă din lecția",
        "Exercițiu de practică",
        "Test final",
        "da",  # single-word fallback answers
    )

    def _has_real_exercises(self, lesson_id: int) -> bool:
        """True dacă lecția are deja suficiente exerciții reale (non-placeholder).

        Verificare SQLite <1ms. Previne supraîncălzirea CPU la lecții din manuale
        care au deja 10-30 exerciții practice importate.
        """
        if not lesson_id:
            return False
        try:
            count = self.db.conn.execute(
                """SELECT COUNT(*) FROM exercises
                   WHERE lesson_id = ? AND phase = 'practice'
                     AND length(enunt) >= 30
                     AND enunt NOT LIKE 'Intrebare rapida%'
                     AND enunt NOT LIKE 'Exercitiu de practica%'""",
                (lesson_id,),
            ).fetchone()[0]
            # Dacă are cel puțin 3 exerciții practice reale, nu mai generăm
            return count >= 3
        except Exception:
            return False  # Eroare → lasă AI să decidă

    def _is_placeholder_exercise(self, ex: dict) -> bool:
        """True if exercise was auto-generated as a placeholder (not real content)."""
        enunt = ex.get("enunt", "")
        if len(enunt) < 20:
            return True
        return any(p in enunt for p in self._PLACEHOLDER_PATTERNS)

    def _generate_exercises_background(self):
        """Generate proper exercises from theory chunks using DeepSeek.

        Runs in a background thread. Replaces placeholder exercises in DB + session.
        Called automatically after set_theory_chunks() when DeepSeek is available.
        """
        if not self.session or not self.deepseek.available:
            return

        session = self.session
        lesson  = session.lesson
        lesson_id = lesson["id"]

        # Build theory context from first 4 real chunks
        theory_text = "\n\n".join(session.theory_chunks[:4])[:1000] if session.theory_chunks else ""
        if not theory_text:
            return

        for phase, session_list_attr, count in (
            ("practice",  "practice_exercises",  self.PRACTICE_COUNT),
            ("posttest",  "posttest_exercises",  self.POSTTEST_COUNT),
            ("pretest",   "pretest_exercises",   self.PRETEST_COUNT),
        ):
            current = getattr(session, session_list_attr, [])
            # Skip if already has real exercises
            if current and not all(self._is_placeholder_exercise(e) for e in current):
                continue

            generated = self.deepseek.generate_exercises(
                lesson_title=lesson.get("title", ""),
                grade=lesson.get("grade", 1),
                subject=lesson.get("subject", ""),
                theory=theory_text,
                count=count,
                phase=phase,
                chunk_context=theory_text,
            )
            if not generated:
                continue

            # Remove placeholder exercises (cu write_lock pentru thread-safety)
            with self.db.write_lock:
                self.db.conn.execute(
                    """DELETE FROM exercises
                       WHERE lesson_id=? AND phase=?
                         AND (length(enunt) < 20
                              OR enunt LIKE 'Intrebare rapida%'
                              OR enunt LIKE 'Exercitiu de practica%'
                              OR enunt LIKE 'Test final%')""",
                    (lesson_id, phase),
                )
                self.db.conn.commit()

            # Insert generated exercises
            added = 0
            for ex in generated:
                enunt   = (ex.get("enunt") or "").strip()
                raspuns = (ex.get("raspuns") or "").strip()
                if not enunt or not raspuns:
                    continue
                self.db.add_exercise(
                    lesson_id=lesson_id,
                    phase=phase,
                    enunt=enunt,
                    raspuns=raspuns,
                    hint1=ex.get("hint1"),
                    hint2=ex.get("hint2"),
                    hint3=ex.get("hint3"),
                    explicatie=ex.get("explicatie"),
                    dificultate=int(ex.get("dificultate") or 1),
                )
                added += 1

            if added == 0:
                continue

            # Reload exercises into session (GIL makes list assignment atomic)
            new_exercises = self.db.get_exercises(lesson_id, phase, count)
            setattr(session, session_list_attr, new_exercises)
            print(f"✅ AI: {added} exercitii {phase} generate pentru '{lesson['title']}'")

            # Also regenerate pretest if needed but skip if lesson has already advanced
            if phase == "pretest" and session.state == LessonState.PRE_TEST:
                session.current_exercise_idx = 0