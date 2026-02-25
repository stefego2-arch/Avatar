#!/usr/bin/env python3
"""
md_lesson_player.py
- citește .md
- face chunking inteligent (pe paragrafe + limite de caractere)
- expune next_chunk(), prev_chunk(), current_chunk()
- se leagă la TTSEngine: speak_current(), stop()

Folosește-l din UI ca "mod lectură manual": copilul ascultă chunk-by-chunk,
poți opri (barge-in) și pui întrebări oricând.
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable
import re


def _clean_md(md: str) -> str:
    # scoate code blocks
    md = re.sub(r"```.*?```", "", md, flags=re.DOTALL)
    # scoate inline code
    md = re.sub(r"`([^`]+)`", r"\1", md)
    # scoate imagini/links dar păstrează textul
    md = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)
    # normalize spații
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    md = re.sub(r"[ \t]+", " ", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


def _split_paragraphs(text: str) -> List[str]:
    parts = [p.strip() for p in text.split("\n\n")]
    return [p for p in parts if p]


def _is_heading(p: str) -> bool:
    return bool(re.match(r"^(#{1,6})\s+", p))


def _make_chunks(paragraphs: List[str], max_chars: int, min_chars: int) -> List[str]:
    chunks: List[str] = []
    buf: List[str] = []
    size = 0

    def flush():
        nonlocal buf, size
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf = []
            size = 0

    for p in paragraphs:
        # dacă e heading, încearcă să-l păstrezi cu paragraful următor
        if _is_heading(p):
            if size >= min_chars:
                flush()
            buf.append(p)
            size += len(p) + 2
            continue

        if size + len(p) + 2 <= max_chars:
            buf.append(p)
            size += len(p) + 2
        else:
            # dacă bufferul e prea mic, ia măcar paragraful curent
            if size < min_chars and buf:
                buf.append(p)
                flush()
            else:
                flush()
                buf.append(p)
                size = len(p) + 2

            # dacă paragraful singur e uriaș, îl mai spargem “soft”
            if len(buf[0]) > max_chars:
                big = buf[0]
                buf = []
                size = 0
                for i in range(0, len(big), max_chars):
                    chunks.append(big[i:i+max_chars].strip())

    flush()
    return [c for c in chunks if c]


@dataclass
class MDLesson:
    path: Path
    title: str
    chunks: List[str]


class MDLessonPlayer:
    def __init__(
        self,
        tts_engine,
        max_chars: int = 900,
        min_chars: int = 300,
    ):
        """
        tts_engine: instanța ta TTSEngine (piper_cli)
        max_chars/min_chars: controlează “dimensiunea” unei bucăți citite
        """
        self.tts = tts_engine
        self.max_chars = int(max_chars)
        self.min_chars = int(min_chars)

        self.lesson: Optional[MDLesson] = None
        self.index: int = 0

        # opțional: hook UI
        self.on_index_changed: Optional[Callable[[int, int], None]] = None

    # ── Load ─────────────────────────────────────────────────────────────

    def load(self, md_path: str | Path) -> MDLesson:
        p = Path(md_path)
        raw = p.read_text(encoding="utf-8", errors="ignore")
        cleaned = _clean_md(raw)
        paragraphs = _split_paragraphs(cleaned)
        chunks = _make_chunks(paragraphs, self.max_chars, self.min_chars)

        title = p.stem
        # încearcă să ia primul heading ca titlu
        for par in paragraphs[:5]:
            if _is_heading(par):
                title = re.sub(r"^#{1,6}\s+", "", par).strip() or title
                break

        self.lesson = MDLesson(path=p, title=title, chunks=chunks)
        self.index = 0
        self._notify_index()
        return self.lesson

    # ── Navigation ───────────────────────────────────────────────────────

    def total(self) -> int:
        return len(self.lesson.chunks) if self.lesson else 0

    def current_chunk(self) -> str:
        if not self.lesson or not self.lesson.chunks:
            return ""
        self.index = max(0, min(self.index, len(self.lesson.chunks) - 1))
        return self.lesson.chunks[self.index]

    def next_chunk(self) -> str:
        if not self.lesson:
            return ""
        if self.index < len(self.lesson.chunks) - 1:
            self.index += 1
            self._notify_index()
        return self.current_chunk()

    def prev_chunk(self) -> str:
        if not self.lesson:
            return ""
        if self.index > 0:
            self.index -= 1
            self._notify_index()
        return self.current_chunk()

    def goto(self, idx: int) -> str:
        if not self.lesson:
            return ""
        self.index = max(0, min(int(idx), len(self.lesson.chunks) - 1))
        self._notify_index()
        return self.current_chunk()

    # ── TTS control ──────────────────────────────────────────────────────

    def stop(self):
        self.tts.stop()

    def speak_current(self, queue: bool = False, on_finished: Optional[Callable[[], None]] = None):
        text = self.current_chunk().strip()
        if not text:
            if on_finished:
                on_finished()
            return
        # “barge-in” friendly: oprește și pornește chunkul curent
        self.tts.stop()
        self.tts.speak(text, on_finished=on_finished, queue=queue)

    def speak_next(self, on_finished: Optional[Callable[[], None]] = None):
        self.next_chunk()
        self.speak_current(queue=False, on_finished=on_finished)

    # ── Internals ─────────────────────────────────────────────────────────

    def _notify_index(self):
        if self.on_index_changed and self.lesson:
            try:
                self.on_index_changed(self.index, len(self.lesson.chunks))
            except Exception:
                pass
