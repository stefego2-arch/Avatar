from pathlib import Path
import re

MANUALE_DIR = Path("manuale")  # folderul tău

def guess_subject(name: str) -> str:
    n = name.lower()
    if "matematica" in n:
        return "Matematică"
    if "romana" in n or "comunicare_in_limba_romana" in n or "limba_si_literatura_romana" in n:
        return "Limba Română"
    return "Necunoscut"

def guess_grade_from_name(name: str) -> int | None:
    # încearcă să prindă "clasa_3", "clasa3", "cls_4" etc.
    n = name.lower()
    m = re.search(r"(clasa|cls)[ _-]*([1-5])", n)
    if m:
        return int(m.group(2))
    return None

def main():
    if not MANUALE_DIR.exists():
        print("Nu există folderul:", MANUALE_DIR.resolve())
        return

    files = sorted(MANUALE_DIR.glob("*.md"))
    print("MD count:", len(files))
    for f in files[:30]:
        subj = guess_subject(f.name)
        grade = guess_grade_from_name(f.name)
        print(f"- {f.name} | {subj} | grade={grade}")

if __name__ == "__main__":
    main()
