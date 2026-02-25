from pathlib import Path
from md_library import sanitize_markdown_for_tts

p = Path("manuale/Matematica_1106.md")
raw = p.read_text(encoding="utf-8", errors="ignore")
clean = sanitize_markdown_for_tts(raw)

print(raw[:800])
print("\n--- CLEAN ---\n")
print(clean[:800])
