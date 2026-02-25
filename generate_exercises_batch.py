#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys, io
# Forțăm UTF-8 pe stdout/stderr (Windows cp1252 nu redă emoji-urile din module)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

"""
Batch exercise generator — Avatar Tutor
Populare automată exerciții pentru lecțiile cu mai puțin decât target per fază.

Utilizare:
  python generate_exercises_batch.py                          # toate lecțiile
  python generate_exercises_batch.py --subject "Matematică"   # doar matematică
  python generate_exercises_batch.py --grade 3                # doar clasa 3
  python generate_exercises_batch.py --dry-run                # preview fără inserare
  python generate_exercises_batch.py --phase practice         # doar o fază
  python generate_exercises_batch.py --force                  # re-generează chiar dacă există
"""
import argparse, time, sys
from pathlib import Path

from database import Database
from deepseek_client import DeepSeekClient
from md_library import ManualLibrary, load_md_chunks

# ── Configurare ──────────────────────────────────────────────────────────────
TARGET: dict[str, int] = {"pretest": 3, "practice": 8, "posttest": 5}
DELAY_BETWEEN_CALLS    = 4    # secunde între apeluri DeepSeek (rate limiting)
MAX_CHUNKS_CONTEXT     = 3    # câte chunks din manual folosim ca context
CHUNK_MAX_CHARS        = 900
BATCH_SIZE             = 3    # max exerciții per apel DeepSeek
TIMEOUT_OVERRIDE       = 120  # fallback timeout (streaming nu are read timeout)


def get_theory_context(lib: ManualLibrary, lesson: dict,
                       max_chunks: int = MAX_CHUNKS_CONTEXT) -> str:
    """Returnează textul de teorie pentru o lecție (din .md sau din DB fallback)."""
    entry = lib.get_default(lesson["subject"], lesson["grade"])
    if entry:
        md_path = Path(lib.manuals_dir) / entry.file
        if md_path.exists():
            try:
                chunks = load_md_chunks(str(md_path), max_chars=CHUNK_MAX_CHARS)
                if chunks:
                    return "\n\n".join(chunks[:max_chunks])
            except Exception as e:
                print(f"   ⚠️  Nu am putut citi manualul {entry.file}: {e}")
    # fallback: teoria stocată în DB
    return lesson.get("theory") or lesson.get("summary") or ""


def wait_for_cooldown(ds: DeepSeekClient) -> None:
    """Dacă circuit breaker-ul e activ, așteptăm să expire și resetăm starea."""
    remaining = ds._cooldown_until - time.time()
    if remaining > 0:
        print(f"   ⏳ Circuit breaker activ — aștept {remaining:.0f}s...")
        time.sleep(remaining + 1)
        ds._consecutive_timeouts = 0
        ds._cooldown_until = 0.0
        ds._available = None   # forțăm re-verificarea la următorul apel
        print("   ▶️  Reluăm după cooldown")


def generate_in_batches(ds: DeepSeekClient, lesson: dict, theory: str,
                        phase: str, needed: int) -> list:
    """Generează `needed` exerciții în batch-uri de maxim BATCH_SIZE per apel."""
    all_exercises: list = []
    remaining = needed
    batch_num = 0

    while remaining > 0:
        batch_num += 1
        count = min(remaining, BATCH_SIZE)

        wait_for_cooldown(ds)

        if not ds.available:
            print(f"   ❌ DeepSeek indisponibil după cooldown — opresc generarea")
            break

        print(f"   → batch {batch_num}: {count} exerciții"
              f"{' (mai rămân ' + str(remaining - count) + ' după)' if remaining - count > 0 else ''}")

        exercises = ds.generate_exercises(
            lesson_title  = lesson["title"],
            grade         = lesson["grade"],
            subject       = lesson["subject"],
            theory        = theory,
            count         = count,
            phase         = phase,
            chunk_context = theory,
            streaming     = True,   # evită read timeout pe modele lente (8b+)
        )

        if exercises:
            all_exercises.extend(exercises)
            remaining -= len(exercises)
        else:
            print(f"   ⚠️  Batch {batch_num} a returnat 0 exerciții — opresc faza")
            break

        if remaining > 0:
            time.sleep(DELAY_BETWEEN_CALLS)

    return all_exercises


def run(args: argparse.Namespace) -> None:
    db  = Database("production.db")
    ds  = DeepSeekClient()
    lib = ManualLibrary()

    # Creștem timeout-ul (deepseek-r1:8B e lent la JSON structurat)
    ds.TIMEOUT_LONG = TIMEOUT_OVERRIDE

    if not ds.available:
        print("❌ DeepSeek indisponibil. Pornește Ollama: ollama serve")
        sys.exit(1)

    lessons = db.get_lessons(
        grade=args.grade,
        subject=args.subject,
    )
    print(f"📚 {len(lessons)} lecții găsite")

    phases = [args.phase] if args.phase else list(TARGET.keys())
    total_added   = 0
    total_skipped = 0
    total_errors  = 0

    for i, lesson in enumerate(lessons, 1):
        lid   = lesson["id"]
        title = lesson["title"]
        subj  = lesson["subject"]
        grade = lesson["grade"]
        print(f"\n[{i}/{len(lessons)}] {subj} cls{grade}: {title}")

        for phase in phases:
            target   = TARGET[phase]
            existing = db.get_exercises(lid, phase, count=30)
            have     = len(existing)

            if have >= target and not args.force:
                print(f"   {phase}: {have}/{target} ✅ skip")
                total_skipped += 1
                continue

            needed = target - have
            print(f"   {phase}: {have}/{target} — generez {needed} exerciții...")

            if args.dry_run:
                print(f"   [DRY-RUN] ar genera {needed} exerciții")
                continue

            theory = get_theory_context(lib, lesson)
            if not theory:
                print(f"   ⚠️  Nicio teorie disponibilă pentru {subj} cls{grade}, generez generic")

            exercises = generate_in_batches(ds, lesson, theory, phase, needed)

            if not exercises:
                print(f"   ❌ DeepSeek nu a returnat exerciții pentru {phase}")
                total_errors += 1
                time.sleep(DELAY_BETWEEN_CALLS)
                continue

            inserted = 0
            for ex in exercises:
                try:
                    db.add_exercise(
                        lesson_id   = lid,
                        enunt       = ex["enunt"],
                        raspuns     = ex["raspuns"],
                        phase       = phase,
                        type        = "choice" if ex.get("choices") else "text",
                        choices     = ex.get("choices"),
                        hint1       = ex.get("hint1"),
                        hint2       = ex.get("hint2"),
                        hint3       = ex.get("hint3"),
                        explicatie  = ex.get("explicatie"),
                        dificultate = int(ex.get("dificultate", 1)),
                    )
                    inserted  += 1
                    total_added += 1
                except Exception as e:
                    print(f"   ⚠️  Insert error: {e}")
                    total_errors += 1

            print(f"   ✅ {inserted}/{needed} exerciții inserate ({phase})")
            time.sleep(DELAY_BETWEEN_CALLS)

    print(f"\n{'='*55}")
    print(f"TOTAL: {total_added} exerciții inserate | "
          f"{total_skipped} faze sărite | {total_errors} erori")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Batch exercise generator — populare automată DB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemple:
  python generate_exercises_batch.py --dry-run
  python generate_exercises_batch.py --subject "Matematică" --grade 2
  python generate_exercises_batch.py --subject "Limba Română"
  python generate_exercises_batch.py --subject "Limba Engleză" --phase pretest
  python generate_exercises_batch.py  # toate lecțiile sparse
        """,
    )
    parser.add_argument("--subject",
                        help='Filtrează materia (ex: "Matematică", "Limba Română")')
    parser.add_argument("--grade", type=int,
                        help="Filtrează clasa (1-9)")
    parser.add_argument("--phase", choices=["pretest", "practice", "posttest"],
                        help="Procesează doar o fază")
    parser.add_argument("--dry-run", action="store_true",
                        help="Afișează ce ar genera fără a insera nimic")
    parser.add_argument("--force", action="store_true",
                        help="Re-generează chiar dacă există suficiente exerciții")

    run(parser.parse_args())
