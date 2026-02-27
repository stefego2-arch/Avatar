"""
add_grade4_math.py — adauga 5 lectii de Matematica pentru clasa a 4-a
Rulare: python add_grade4_math.py
"""
import sys
import sqlite3
import json
from pathlib import Path

# Forteaza UTF-8 pe stdout (Windows terminal poate folosi cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = Path(__file__).parent / "production.db"

LESSONS = [
    {
        "title": "Adunarea și scăderea numerelor pana la 1.000.000",
        "subject": "Matematică",
        "grade": 4,
        "unit": 1,
        "order_in_unit": 3,
        "theory": (
            "📚 Adunarea și scăderea numerelor pana la 1.000.000\n\n"
            "Reguli:\n"
            "1. Scriem numerele unul sub altul, cifrele pe aceeași coloană\n"
            "2. Adunăm sau scădem de la dreapta la stânga\n"
            "3. La adunare: dacă suma depășește 9, scriem ultima cifră și reținem restul\n"
            "4. La scădere: dacă nu putem scădea, împrumutăm de la cifra vecină\n\n"
            "📌 Exemplu adunare:\n"
            "  345.000 + 254.000 = 599.000\n\n"
            "📌 Exemplu scădere:\n"
            "  700.000 - 123.456 = 576.544\n\n"
            "✅ Verificare scădere: dacă a - b = c, atunci c + b = a"
        ),
        "summary": "Adunarea și scăderea numerelor mari pana la 1.000.000",
        "objectives": "Efectuarea operațiilor de adunare și scădere cu numere pana la 1.000.000; Rezolvarea de probleme",
        "exercises": [
            {
                "type": "text", "phase": "pretest", "dificultate": 4,
                "enunt": "245.000 + 135.000 = ?",
                "raspuns": "380000",
                "hint1": "Aduna unitatile de mii: 245 + 135",
                "hint2": "245 + 135 = 380, deci 245.000 + 135.000 = 380.000",
                "explicatie": "245.000 + 135.000 = 380.000"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "123.456 + 234.567 = ?",
                "raspuns": "358023",
                "hint1": "Aduna cifra cu cifra de la dreapta la stanga",
                "hint2": "6+7=13 (scriem 3, retinem 1); 5+6+1=12 (scriem 2, retinem 1)...",
                "explicatie": "123.456 + 234.567 = 358.023"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "700.000 - 234.567 = ?",
                "raspuns": "465433",
                "hint1": "Scade cifra cu cifra, imprumutand cand e nevoie",
                "hint2": "700.000 - 234.567 — scadem de la cifra unităților spre stânga",
                "explicatie": "700.000 - 234.567 = 465.433"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "O scoala are 12.450 de elevi si o alta scoala are 8.325 elevi. Cati elevi sunt in total?",
                "raspuns": "20775",
                "hint1": "Aduna numarul de elevi: 12.450 + 8.325",
                "hint2": "12.000 + 8.000 = 20.000; 450 + 325 = 775",
                "explicatie": "12.450 + 8.325 = 20.775 elevi total"
            },
            {
                "type": "text", "phase": "posttest", "dificultate": 5,
                "enunt": "756.234 - 345.678 = ?",
                "raspuns": "410556",
                "hint1": "Scade cifra cu cifra de la dreapta la stanga",
                "hint2": "4-8: imprumutam, 14-8=6; urmatorii: 3-1-7, imprumutam...",
                "explicatie": "756.234 - 345.678 = 410.556"
            },
        ],
    },
    {
        "title": "Înmulțirea numerelor naturale",
        "subject": "Matematică",
        "grade": 4,
        "unit": 1,
        "order_in_unit": 4,
        "theory": (
            "📚 Înmulțirea numerelor naturale\n\n"
            "Termenii: Factor × Factor = Produs\n\n"
            "Proprietăți:\n"
            "• Comutativitate: a × b = b × a\n"
            "• Asociativitate: (a × b) × c = a × (b × c)\n"
            "• Distributivitate: a × (b + c) = a×b + a×c\n\n"
            "📌 Înmulțire cu o cifră:\n"
            "  246 × 7 = 1.722\n"
            "  (6×7=42, reținem 4; 4×7+4=32, reținem 3; 2×7+3=17)\n\n"
            "📌 Înmulțire cu număr de două cifre:\n"
            "  123 × 45 = 5.535\n"
            "  123 × 5 = 615 și 123 × 40 = 4.920, total 5.535"
        ),
        "summary": "Înmulțirea numerelor naturale cu una și două cifre",
        "objectives": "Înmulțirea numerelor cu o cifră și două cifre; Proprietățile înmulțirii; Rezolvarea de probleme",
        "exercises": [
            {
                "type": "text", "phase": "pretest", "dificultate": 3,
                "enunt": "234 × 6 = ?",
                "raspuns": "1404",
                "hint1": "Inmulteste fiecare cifra: 4×6, 3×6, 2×6",
                "hint2": "4×6=24 (scriem 4, retinem 2); 3×6+2=20 (scriem 0, retinem 2); 2×6+2=14",
                "explicatie": "234 × 6 = 1.404"
            },
            {
                "type": "choice", "phase": "practice", "dificultate": 3,
                "enunt": "7 × 8 = ?",
                "raspuns": "56",
                "choices": json.dumps(["54", "56", "58", "63"]),
                "hint1": "Tabla inmultirii cu 7 sau cu 8",
                "hint2": "7 × 8 = 7 + 7 + 7 + 7 + 7 + 7 + 7 + 7 = 56",
                "explicatie": "7 × 8 = 56 (tabla inmultirii)"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "352 × 4 = ?",
                "raspuns": "1408",
                "hint1": "Inmulteste pe rand: 2×4, 5×4, 3×4",
                "hint2": "2×4=8; 5×4=20 (scriem 0, retinem 2); 3×4+2=14",
                "explicatie": "352 × 4 = 1.408"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "O clasa are 28 de elevi. Fiecare elev a cumparat 12 caiete. Cate caiete au cumparat in total?",
                "raspuns": "336",
                "hint1": "Inmulteste 28 × 12",
                "hint2": "28×10=280; 28×2=56; 280+56=336",
                "explicatie": "28 × 12 = 336 de caiete"
            },
            {
                "type": "text", "phase": "posttest", "dificultate": 5,
                "enunt": "125 × 24 = ?",
                "raspuns": "3000",
                "hint1": "Calculeaza 125×20 si 125×4, apoi aduna",
                "hint2": "125×20=2.500; 125×4=500; 2.500+500=3.000",
                "explicatie": "125 × 24 = 3.000"
            },
        ],
    },
    {
        "title": "Împărțirea numerelor naturale",
        "subject": "Matematică",
        "grade": 4,
        "unit": 1,
        "order_in_unit": 5,
        "theory": (
            "📚 Împărțirea numerelor naturale\n\n"
            "Termenii: Deîmpărțit ÷ Împărțitor = Cât (rest R)\n\n"
            "✅ Proba împărțirii: Cât × Împărțitor + Rest = Deîmpărțit\n\n"
            "⚠️ Important: Restul este ÎNTOTDEAUNA mai mic decât împărțitorul!\n\n"
            "📌 Împărțire fără rest:\n"
            "  756 ÷ 4 = 189\n"
            "  Proba: 189 × 4 = 756 ✓\n\n"
            "📌 Împărțire cu rest:\n"
            "  857 ÷ 3 = 285, rest 2\n"
            "  Proba: 285 × 3 + 2 = 857 ✓\n\n"
            "📌 Proprietăți:\n"
            "  • a ÷ 1 = a\n"
            "  • a ÷ a = 1 (dacă a ≠ 0)\n"
            "  • 0 ÷ a = 0"
        ),
        "summary": "Împărțirea numerelor naturale cu rest și fără rest",
        "objectives": "Efectuarea împărțirii; Proba împărțirii; Rezolvarea de probleme cu împărțire",
        "exercises": [
            {
                "type": "text", "phase": "pretest", "dificultate": 3,
                "enunt": "84 ÷ 4 = ?",
                "raspuns": "21",
                "hint1": "Cat face 8 ÷ 4? Apoi 4 ÷ 4?",
                "hint2": "8÷4=2; 4÷4=1; deci 84÷4=21",
                "explicatie": "84 ÷ 4 = 21 (proba: 21×4=84)"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "756 ÷ 6 = ?",
                "raspuns": "126",
                "hint1": "Imparte: 7÷6=1 rest 1; 15÷6=2 rest 3; 36÷6=6",
                "hint2": "Cifrele rezultatului: 1, 2, 6 → 126",
                "explicatie": "756 ÷ 6 = 126 (proba: 126×6=756)"
            },
            {
                "type": "choice", "phase": "practice", "dificultate": 4,
                "enunt": "288 ÷ 9 = ?",
                "raspuns": "32",
                "choices": json.dumps(["28", "32", "36", "42"]),
                "hint1": "Incearca: 9×30=270, 288-270=18, 18÷9=2",
                "hint2": "9×32=288. Verifica: 9×30=270, 9×2=18, 270+18=288",
                "explicatie": "288 ÷ 9 = 32 (proba: 32×9=288)"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "O livada are 840 de meri plantati in 7 randuri egale. Cati meri sunt intr-un rand?",
                "raspuns": "120",
                "hint1": "Imparte 840 la 7",
                "hint2": "840÷7: 8÷7=1 rest 1; 14÷7=2; 0÷7=0 → 120",
                "explicatie": "840 ÷ 7 = 120 de meri intr-un rand"
            },
            {
                "type": "text", "phase": "posttest", "dificultate": 5,
                "enunt": "1.248 ÷ 8 = ?",
                "raspuns": "156",
                "hint1": "Imparte: 12÷8=1 rest 4; 44÷8=5 rest 4; 48÷8=6",
                "hint2": "Cifrele rezultatului: 1, 5, 6 → 156",
                "explicatie": "1.248 ÷ 8 = 156 (proba: 156×8=1.248)"
            },
        ],
    },
    {
        "title": "Figuri geometrice - Perimetru și Arie",
        "subject": "Matematică",
        "grade": 4,
        "unit": 2,
        "order_in_unit": 1,
        "theory": (
            "📚 Figuri geometrice - Perimetru și Arie\n\n"
            "📐 PĂTRATUL (toate laturile egale - latura = l):\n"
            "  • Perimetru: P = 4 × l\n"
            "  • Arie: A = l × l\n\n"
            "📏 DREPTUNGHIUL (lungime = L, lățime = l):\n"
            "  • Perimetru: P = 2 × L + 2 × l = 2 × (L + l)\n"
            "  • Arie: A = L × l\n\n"
            "📐 TRIUNGHIUL (laturile a, b, c):\n"
            "  • Perimetru: P = a + b + c\n\n"
            "Unități de măsură:\n"
            "  • Lungime: mm, cm, m, km\n"
            "  • Arie: mm², cm², m², km²"
        ),
        "summary": "Calculul perimetrului și ariei pentru pătrat, dreptunghi și triunghi",
        "objectives": "Aplicarea formulelor pentru perimetru și arie; Rezolvarea de probleme geometrice",
        "exercises": [
            {
                "type": "choice", "phase": "pretest", "dificultate": 3,
                "enunt": "Perimetrul unui pătrat cu latura de 5 cm este:",
                "raspuns": "20",
                "choices": json.dumps(["15", "20", "25", "30"]),
                "hint1": "Perimetrul patratului = 4 × latura",
                "hint2": "P = 4 × 5 = 20 cm",
                "explicatie": "P = 4 × l = 4 × 5 = 20 cm"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 3,
                "enunt": "Un dreptunghi are lungimea de 8 cm și lățimea de 5 cm. Care este perimetrul?",
                "raspuns": "26",
                "hint1": "P = 2 × L + 2 × l",
                "hint2": "P = 2×8 + 2×5 = 16 + 10 = 26 cm",
                "explicatie": "P = 2 × (8+5) = 2 × 13 = 26 cm"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "Un dreptunghi are lungimea de 12 m și lățimea de 7 m. Care este aria?",
                "raspuns": "84",
                "hint1": "Aria dreptunghiului = Lungime × Lățime",
                "hint2": "A = 12 × 7 = ?",
                "explicatie": "A = L × l = 12 × 7 = 84 m²"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "Un pătrat are perimetrul de 36 cm. Care este latura pătratului?",
                "raspuns": "9",
                "hint1": "Perimetru = 4 × latura, deci latura = Perimetru ÷ 4",
                "hint2": "latura = 36 ÷ 4 = ?",
                "explicatie": "latura = P ÷ 4 = 36 ÷ 4 = 9 cm"
            },
            {
                "type": "text", "phase": "posttest", "dificultate": 5,
                "enunt": "Un teren dreptunghiular are lungimea de 15 m și lățimea de 8 m. Care este perimetrul terenului?",
                "raspuns": "46",
                "hint1": "P = 2 × (L + l)",
                "hint2": "P = 2 × (15 + 8) = 2 × 23 = ?",
                "explicatie": "P = 2 × (15 + 8) = 2 × 23 = 46 m"
            },
        ],
    },
    {
        "title": "Unități de măsură",
        "subject": "Matematică",
        "grade": 4,
        "unit": 2,
        "order_in_unit": 2,
        "theory": (
            "📚 Unități de măsură\n\n"
            "📏 LUNGIME:\n"
            "  1 km = 1.000 m  |  1 m = 100 cm  |  1 cm = 10 mm\n\n"
            "⚖️ MASĂ:\n"
            "  1 t = 1.000 kg  |  1 kg = 1.000 g\n\n"
            "⏰ TIMP:\n"
            "  1 an = 12 luni = 365 zile (366 în an bisect)\n"
            "  1 zi = 24 ore  |  1 oră = 60 minute  |  1 minut = 60 secunde\n\n"
            "🧴 CAPACITATE:\n"
            "  1 l = 10 dl = 100 cl = 1.000 ml\n\n"
            "📌 Transformări utile:\n"
            "  3 km = 3.000 m    |    250 cm = 2 m 50 cm\n"
            "  5 ore = 300 min   |    2 kg 500 g = 2.500 g"
        ),
        "summary": "Unități de măsură pentru lungime, masă, timp și capacitate",
        "objectives": "Cunoașterea unităților de măsură; Efectuarea de transformări; Rezolvarea de probleme",
        "exercises": [
            {
                "type": "choice", "phase": "pretest", "dificultate": 3,
                "enunt": "1 km = ? m",
                "raspuns": "1000",
                "choices": json.dumps(["10", "100", "1000", "10000"]),
                "hint1": "km = kilometru; m = metru. kilo = 1.000",
                "hint2": "1 km are 1.000 de metri",
                "explicatie": "1 km = 1.000 m (kilo = 1.000)"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 3,
                "enunt": "2 ore și 30 de minute = ? minute",
                "raspuns": "150",
                "hint1": "O ora = 60 de minute. Cat fac 2 ore?",
                "hint2": "2 × 60 = 120 minute + 30 minute = ?",
                "explicatie": "2 ore = 120 min; 120 + 30 = 150 minute"
            },
            {
                "type": "choice", "phase": "practice", "dificultate": 4,
                "enunt": "3 kg = ? g",
                "raspuns": "3000",
                "choices": json.dumps(["30", "300", "3000", "30000"]),
                "hint1": "1 kg = 1.000 g",
                "hint2": "3 kg = 3 × 1.000 g = ?",
                "explicatie": "3 kg = 3 × 1.000 = 3.000 g"
            },
            {
                "type": "text", "phase": "practice", "dificultate": 4,
                "enunt": "Un tren parcurge 240 km în 2 ore. Câți km parcurge în 1 oră?",
                "raspuns": "120",
                "hint1": "Imparte distanta totala la numarul de ore",
                "hint2": "240 ÷ 2 = ?",
                "explicatie": "240 ÷ 2 = 120 km pe ora"
            },
            {
                "type": "text", "phase": "posttest", "dificultate": 4,
                "enunt": "Maria cumpara 2 kg si 500 g de mere. Câte grame de mere cumpara?",
                "raspuns": "2500",
                "hint1": "Transforma 2 kg in grame, apoi aduna 500 g",
                "hint2": "2 kg = 2.000 g; 2.000 + 500 = ?",
                "explicatie": "2 kg = 2.000 g; 2.000 + 500 = 2.500 g"
            },
        ],
    },
]


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    total_lessons = 0
    total_exercises = 0

    for lesson in LESSONS:
        # Check if lesson already exists (by title + grade + subject)
        cur.execute(
            "SELECT id FROM lessons WHERE title=? AND grade=? AND subject=?",
            (lesson["title"], lesson["grade"], lesson["subject"]),
        )
        existing = cur.fetchone()
        if existing:
            lesson_id = existing[0]
            print(f"[SKIP] Lectie existenta: {lesson['title']} (id={lesson_id})")
        else:
            cur.execute(
                """INSERT INTO lessons
                       (title, subject, grade, unit, order_in_unit, theory, summary, objectives)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lesson["title"], lesson["subject"], lesson["grade"],
                    lesson["unit"], lesson["order_in_unit"],
                    lesson["theory"], lesson["summary"], lesson["objectives"],
                ),
            )
            lesson_id = cur.lastrowid
            total_lessons += 1
            print(f"[ADD]  Lectie noua: {lesson['title']} (id={lesson_id})")

        for ex in lesson["exercises"]:
            cur.execute(
                "SELECT id FROM exercises WHERE lesson_id=? AND enunt=?",
                (lesson_id, ex["enunt"]),
            )
            if cur.fetchone():
                print(f"       [skip] exercitiu existent: {ex['enunt'][:50]}")
                continue
            cur.execute(
                """INSERT INTO exercises
                       (lesson_id, type, phase, enunt, raspuns, choices,
                        hint1, hint2, hint3, explicatie, dificultate, skill_codes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    lesson_id, ex["type"], ex["phase"], ex["enunt"], ex["raspuns"],
                    ex.get("choices"),
                    ex.get("hint1"), ex.get("hint2"), ex.get("hint3"),
                    ex.get("explicatie"), ex["dificultate"],
                    '["mat_grade4"]',
                ),
            )
            total_exercises += 1
            print(f"       [add]  [{ex['phase']:8s}] {ex['enunt'][:50]}")

    conn.commit()
    conn.close()
    print(f"\nDone! {total_lessons} lectii si {total_exercises} exercitii adaugate pentru Matematica cls. 4.")


if __name__ == "__main__":
    main()
