#!/usr/bin/env python3
from __future__ import annotations

"""
md_lesson_player.py

- Exportă clasa: MDLessonPlayer (pentru import din main.py)
- Opțional: mod consolă (python md_lesson_player.py manuale/xxx.md)

Comenzi (consolă):
  n = next chunk
  p = prev chunk
  r = repeat chunk
  s = stop (barge-in)
  ? = quiz (dacă ai llm_tutor injectat)
  q = quit
"""

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

from PyQt6.QtCore import QObject, pyqtSlot, pyqtSignal, QMetaObject, Qt
from PyQt6.QtWidgets import QApplication

from md_library import load_md_chunks
from tts_engine import TTSEngine

try:
    # optional
    from llm_gemini import GeminiTutor
except Exception:
    GeminiTutor = None  # type: ignore


@dataclass
class QuizItem:
    q: str
    a: str
    choices: Optional[List[str]] = None


class MDLessonPlayer(QObject):
    """
    Player reutilizabil în UI (main.py) și în consolă.
    - Nu creează QApplication (asta o faci tu în main.py).
    """

    chunk_changed = pyqtSignal(int, int, str)  # idx, total, text
    error = pyqtSignal(str)

    def __init__(
        self,
        tts: TTSEngine,
        *,
        llm_tutor: Optional[object] = None,
        max_chars: int = 900,
        keep_headings: bool = True,
    ):
        super().__init__()
        self.tts = tts
        self.llm_tutor = llm_tutor
        self.max_chars = max_chars
        self.keep_headings = keep_headings

        self.chunks: List[str] = []
        self.i: int = 0

        # hook TTS signals (dacă există)
        if hasattr(self.tts, "started"):
            self.tts.started.connect(self._on_started)  # type: ignore[attr-defined]
        if hasattr(self.tts, "finished"):
            self.tts.finished.connect(self._on_finished)  # type: ignore[attr-defined]

        self._speaking_text = ""

    # ------------------------- LOAD -------------------------

    def load_file(self, md_path: str | Path) -> int:
        p = Path(md_path)
        if not p.exists():
            msg = f"MD not found: {p}"
            self.error.emit(msg)
            raise FileNotFoundError(msg)

        self.chunks = load_md_chunks(str(p), max_chars=self.max_chars, keep_headings=self.keep_headings)
        self.i = 0
        if not self.chunks:
            msg = "Nu am obținut niciun chunk (verifică filtrele din md_library)."
            self.error.emit(msg)
        else:
            self.chunk_changed.emit(self.i, len(self.chunks), self.chunks[self.i])
        return len(self.chunks)

    def set_chunks(self, chunks: List[str]) -> None:
        self.chunks = chunks or []
        self.i = 0
        if self.chunks:
            self.chunk_changed.emit(self.i, len(self.chunks), self.chunks[self.i])

    # ------------------------- STATE -------------------------

    def has_chunks(self) -> bool:
        return bool(self.chunks)

    def current_index(self) -> int:
        return self.i

    def total_chunks(self) -> int:
        return len(self.chunks)

    def current_text(self) -> str:
        if not self.chunks:
            return ""
        return self.chunks[self.i]

    # ------------------------- TTS CONTROL -------------------------

    @pyqtSlot(str)
    def _on_started(self, text: str):
        self._speaking_text = text

    @pyqtSlot()
    def _on_finished(self):
        pass

    @pyqtSlot()
    def play_current(self):
        if not self.chunks:
            self.error.emit("NO CHUNKS.")
            return
        self.chunk_changed.emit(self.i, len(self.chunks), self.chunks[self.i])
        self.tts.speak(self.chunks[self.i], queue=False)

    @pyqtSlot()
    def stop(self):
        self.tts.stop()

    @pyqtSlot()
    def next(self):
        if not self.chunks:
            return
        if self.i < len(self.chunks) - 1:
            self.i += 1
        self.play_current()

    @pyqtSlot()
    def prev(self):
        if not self.chunks:
            return
        if self.i > 0:
            self.i -= 1
        self.play_current()

    @pyqtSlot()
    def repeat(self):
        self.play_current()

    # ------------------------- QUIZ (optional) -------------------------

    def make_quiz(self, grade: int, subject: str, n: int = 3) -> List[QuizItem]:
        """
        Folosește llm_tutor dacă e injectat și are make_questions(text,...)
        """
        if not self.llm_tutor:
            raise RuntimeError("LLM tutor not set.")
        chunk = self.current_text()
        if not chunk.strip():
            return []

        # așteptăm interfața: tutor.make_questions(text, grade, subject, n) -> list(obj)
        quiz_raw = self.llm_tutor.make_questions(chunk, grade=grade, subject=subject, n=n)  # type: ignore[attr-defined]
        out: List[QuizItem] = []
        for it in quiz_raw:
            out.append(QuizItem(q=getattr(it, "q", ""), a=getattr(it, "a", ""), choices=getattr(it, "choices", None)))
        return out


# ======================================================================
# Console runner (doar dacă rulezi fișierul direct)
# ======================================================================

def _print_chunk(idx: int, total: int, text: str):
    print("\n" + "=" * 90)
    print(f"CHUNK {idx + 1}/{total}")
    print("=" * 90)
    print(text.strip().replace("\n", " ")[:1200])
    print()


def _input_thread(player: MDLessonPlayer, app: QApplication):
    print("\nComenzi: [n]ext [p]rev [r]epeat [s]top [?]quiz [q]uit\n")
    while True:
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            cmd = "q"

        if cmd == "n":
            QMetaObject.invokeMethod(player, "next", Qt.ConnectionType.QueuedConnection)
        elif cmd == "p":
            QMetaObject.invokeMethod(player, "prev", Qt.ConnectionType.QueuedConnection)
        elif cmd == "r":
            QMetaObject.invokeMethod(player, "repeat", Qt.ConnectionType.QueuedConnection)
        elif cmd == "s":
            QMetaObject.invokeMethod(player, "stop", Qt.ConnectionType.QueuedConnection)
            print("(stopped)")
        elif cmd == "?":
            try:
                quiz = player.make_quiz(grade=3, subject="Matematică", n=3)
                print("\n🧠 Întrebări:")
                for i, it in enumerate(quiz, 1):
                    print(f"\n{i}) {it.q}")
                    if it.choices:
                        print("   " + " / ".join(it.choices))
                    print(f"   (Răspuns: {it.a})")
            except Exception as e:
                print(f"❌ Quiz error: {e}")
        elif cmd == "q":
            QMetaObject.invokeMethod(player, "stop", Qt.ConnectionType.QueuedConnection)
            QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)
            break
        else:
            print("Comenzi valide: n / p / r / s / ? / q")


def main():
    if len(sys.argv) < 2:
        print("Usage: python md_lesson_player.py manuale/Matematica_1106.md")
        sys.exit(1)

    md_path = Path(sys.argv[1])
    if not md_path.exists():
        print(f"File not found: {md_path}")
        sys.exit(1)

    app = QApplication(sys.argv)

    tts = TTSEngine()
    print("engine:", getattr(tts, "engine_name", "unknown"))

    tutor = None
    if GeminiTutor is not None:
        try:
            tutor = GeminiTutor()  # dacă ai modulul pregătit
        except Exception:
            tutor = None

    player = MDLessonPlayer(tts, llm_tutor=tutor)

    def _on_chunk(idx: int, total: int, text: str):
        _print_chunk(idx, total, text)

    player.chunk_changed.connect(_on_chunk)
    player.error.connect(lambda msg: print("❌", msg))

    count = player.load_file(md_path)
    print(f"Loaded chunks: {count} from {md_path.name}")

    th = threading.Thread(target=_input_thread, args=(player, app), daemon=True)
    th.start()

    QMetaObject.invokeMethod(player, "play_current", Qt.ConnectionType.QueuedConnection)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
