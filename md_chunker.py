# md_chunker.py
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional

def _clean_md(text: str) -> str:
    # remove code blocks
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    # drop images/links markdown to plain text
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    # strip headings markers but keep text
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    # collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def chunk_text(md_text: str, max_chars: int = 700) -> List[str]:
    t = _clean_md(md_text)
    paras = [p.strip() for p in t.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""

    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                chunks.append(buf)
                buf = ""
            # if paragraph too big, split by sentences
            if len(p) > max_chars:
                sents = re.split(r"(?<=[\.\!\?])\s+", p)
                tmp = ""
                for s in sents:
                    if len(tmp) + len(s) + 1 <= max_chars:
                        tmp = (tmp + " " + s).strip()
                    else:
                        if tmp:
                            chunks.append(tmp)
                        tmp = s.strip()
                if tmp:
                    chunks.append(tmp)
            else:
                chunks.append(p)

    if buf:
        chunks.append(buf)

    # safety: remove tiny chunks
    chunks = [c for c in chunks if len(c.strip()) >= 20]
    return chunks

@dataclass
class MDChunkPlayer:
    chunks: List[str]
    idx: int = 0

    def current(self) -> Optional[str]:
        if not self.chunks:
            return None
        self.idx = max(0, min(self.idx, len(self.chunks) - 1))
        return self.chunks[self.idx]

    def next_chunk(self) -> Optional[str]:
        if not self.chunks:
            return None
        self.idx = min(self.idx + 1, len(self.chunks) - 1)
        return self.current()

    def prev_chunk(self) -> Optional[str]:
        if not self.chunks:
            return None
        self.idx = max(self.idx - 1, 0)
        return self.current()

    def progress(self) -> tuple[int, int]:
        return (self.idx + 1, len(self.chunks))
