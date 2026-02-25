#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

def clean_text_for_md(t: str) -> str:
    t = t.replace("\r", "")
    # normalize whitespace
    t = re.sub(r"[ \t]+", " ", t)
    # drop page headers/footers-ish lines: very short, repeated, page numbers
    lines = []
    for line in t.split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        if re.fullmatch(r"\d{1,4}", s):   # page number only
            continue
        if len(s) <= 2:
            continue
        lines.append(s)
    t = "\n".join(lines)
    # collapse many blank lines
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t

def pdf_to_md_lite(pdf_path: Path, out_md: Path) -> int:
    try:
        import fitz  # PyMuPDF
    except Exception:
        raise SystemExit("Instalează: pip install pymupdf")

    doc = fitz.open(pdf_path)
    parts = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        txt = page.get_text("text")  # best-effort plain text
        if txt and txt.strip():
            parts.append(txt)

    raw = "\n".join(parts)
    raw = clean_text_for_md(raw)

    # Minimal MD: păstrăm paragrafele
    out_md.write_text(raw, encoding="utf-8")
    return len(raw)

def main():
    base = Path(".")
    pdf_dir = base / "manuale_main"
    md_dir  = base / "manuale"
    md_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        print("Nu am găsit PDF-uri în manuale_pdf/")
        return

    for pdf in pdfs:
        out = md_dir / (pdf.stem + ".md")
        n = pdf_to_md_lite(pdf, out)
        print(f"OK: {pdf.name} -> {out.name} (chars={n})")

if __name__ == "__main__":
    main()