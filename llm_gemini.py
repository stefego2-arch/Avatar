# llm_gemini.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv

# Google GenAI SDK (Gemini Developer API)
from google import genai


def _compact(text: str, max_chars: int = 3500) -> str:
    """Taie textul pentru prompt: fără să rupă urât propozițiile."""
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    # încearcă să tai la ultimul punct
    last = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    return cut[: last + 1].strip() if last > 200 else cut.strip()


@dataclass
class QuizItem:
    q: str
    a: str
    choices: Optional[List[str]] = None


class GeminiTutor:
    def __init__(self):
        load_dotenv()

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Lipsește GEMINI_API_KEY (pune-l în .env).")

        self.model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout_s = int(os.getenv("GEMINI_TIMEOUT_S", "25"))

        # API key explicit (merge și pe env auto-pickup, dar așa e clar)
        self.client = genai.Client(api_key=api_key)  # :contentReference[oaicite:3]{index=3}

    def make_questions(
        self,
        lesson_text: str,
        *,
        grade: int,
        subject: str,
        n: int = 3,
        difficulty: str = "ușor",
    ) -> List[QuizItem]:
        """
        Generează întrebări STRICT din fragment.
        Return: list[QuizItem]
        """
        snippet = _compact(lesson_text)

        prompt = f"""
Ești un tutor pentru copii (clasa {grade}). Materia: {subject}.
Generează EXACT {n} întrebări bazate DOAR pe textul de mai jos.
Cerințe:
- limbaj simplu, pe înțelesul unui copil
- dificultate: {difficulty}
- fiecare întrebare are și răspunsul corect scurt
- opțional: pentru 1-2 întrebări, include 3 variante (A/B/C) + indică răspunsul corect
- NU inventa informații care nu apar în text

Returnează în format strict:

Q1: ...
A1: ...
CHOICES1: A) ... | B) ... | C) ...   (opțional)
---
Q2: ...
A2: ...
(etc)

TEXT:
\"\"\"{snippet}\"\"\"
""".strip()

        # generate_content
        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        out = (resp.text or "").strip()
        return self._parse_quiz(out)

    def check_answer(
        self,
        question: str,
        correct_answer: str,
        student_answer: str,
        *,
        grade: int,
        subject: str,
    ) -> str:
        """
        Feedback scurt: corect/greșit + explicație de 1-2 propoziții, fără rușinare.
        """
        prompt = f"""
Ești un tutor blând pentru clasa {grade} ({subject}).
Întrebare: {question}
Răspuns corect: {correct_answer}
Răspuns elev: {student_answer}

Spune dacă e corect sau nu și explică în 1-2 propoziții, foarte simplu.
""".strip()

        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return (resp.text or "").strip()

    @staticmethod
    def _parse_quiz(text: str) -> List[QuizItem]:
        items: List[QuizItem] = []
        blocks = [b.strip() for b in text.split("---") if b.strip()]
        for b in blocks:
            q = a = ""
            choices = None
            for line in b.splitlines():
                line = line.strip()
                if line.startswith("Q"):
                    q = line.split(":", 1)[1].strip() if ":" in line else line
                elif line.startswith("A"):
                    a = line.split(":", 1)[1].strip() if ":" in line else line
                elif line.upper().startswith("CHOICES"):
                    raw = line.split(":", 1)[1].strip() if ":" in line else ""
                    parts = [p.strip() for p in raw.split("|") if p.strip()]
                    choices = parts if parts else None
            if q and a:
                items.append(QuizItem(q=q, a=a, choices=choices))
        return items
