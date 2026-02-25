# 🤖 AVATAR TUTOR — Instrucțiuni de setup

## Structura fișierelor

```
📁 proiect/
├── 1_setup_piper_roman.py  ← Rulează PRIMA DATĂ
├── main.py                  ← Aplicația principală
├── database.py              ← Baza de date SQLite
├── deepseek_client.py       ← Client DeepSeek/Ollama
├── tts_engine.py            ← Voce română (Piper)
├── attention_monitor.py     ← Monitorizare atenție (MediaPipe)
├── lesson_engine.py         ← Orchestrator lecție
├── production.db            ← Se creează automat
│
├── 📁 piper_voices/         ← Se creează de 1_setup_piper_roman.py
│   ├── ro_RO-mihai-medium.onnx
│   └── ro_RO-mihai-medium.onnx.json
│
└── 📁 assets/avatar/        ← OPȚIONAL: imagini PNG avatar
    ├── idle.png
    ├── happy.png
    ├── talking.png
    ├── thinking.png
    └── encouraging.png
```

---

## PAȘI DE SETUP (în ordine)

### Pas 1 — Instalează dependențele Python

```bash
pip install PyQt6 opencv-python mediapipe piper-tts requests
```

### Pas 2 — Asigură-te că Ollama rulează

```bash
# Pornește Ollama (dacă nu rulează deja)
ollama serve

# Verifică modelul DeepSeek (într-un terminal nou)
ollama list

# Dacă nu ai deepseek-r1:7b:
ollama pull deepseek-r1:7b
```

### Pas 3 — Descarcă vocea română pentru Piper

```bash
python 1_setup_piper_roman.py
```

Acest script:
- Descarcă automat vocea română (~63 MB de la HuggingFace)
- O salvează în `piper_voices/`
- Testează că sună bine
- Ascultă `test_voce_romana.wav` să verifici calitatea

### Pas 4 — Pornește aplicația

```bash
python main.py
```

---

## PRIMA RULARE

La prima rulare, `database.py` creează automat:
- 4 utilizatori demo (Elev Demo, Maria, Ion, Giorgel)
- Lecții de Matematică și Română pentru clasele 1-2
- Exerciții complete cu hints pentru fiecare lecție

---

## ADAUGĂ LECȚII DIN MANUALELE TALE

Ai manualele convertite în `.md` cu Marker. Adaugă-le în DB:

```python
# import_manual.py — rulează o singură dată
from database import Database
from pathlib import Path

db = Database("production.db")

# Citește manual .md
content = Path("manuale/clasa1_matematica.md").read_text(encoding="utf-8")

# Adaugă lecție
lesson_id = db.create_lesson(
    title="Adunarea cu numere până la 20",
    subject="Matematică",
    grade=1,
    unit=2,
    theory=content[:1000],   # Primele 1000 caractere ca teorie
    summary="Adunăm numere până la 20"
)

# Adaugă exerciții manual sau generează cu DeepSeek:
from deepseek_client import DeepSeekClient
ds = DeepSeekClient()
exercises = ds.generate_exercises(
    "Adunarea până la 20", grade=1, subject="Matematică",
    theory=content[:500], count=10, phase="practice"
)
for ex in exercises:
    db.add_exercise(lesson_id,
        enunt=ex["enunt"], raspuns=ex["raspuns"],
        phase="practice", dificultate=ex["dificultate"],
        hint1=ex.get("hint1"), hint2=ex.get("hint2"),
        hint3=ex.get("hint3"), explicatie=ex.get("explicatie")
    )
print(f"✅ Lecție și {len(exercises)} exerciții adăugate!")
```

---

## AVATAR CU IMAGINI PNG (opțional)

Pune imagini PNG în `assets/avatar/` cu numele:
- `idle.png` — avatar neutru
- `happy.png` — fericit (după răspuns corect)
- `talking.png` — vorbește
- `thinking.png` — se gândește (la hint)
- `encouraging.png` — încurajator (după greșeală)

Dacă imaginile lipsesc, folosește emoji automat.

Poți genera imagini gratuit pe:
- https://www.avaturn.me/
- https://readyplayer.me/
- Sau orice personaj 2D PNG pe fond transparent

---

## REZOLVARE PROBLEME

**Vocea nu se aude:**
- Verifică `piper_voices/` există cu fișierele .onnx
- Rulează din nou `python 1_setup_piper_roman.py`
- Fallback: `pip install gtts` (necesită internet)

**Camera nu funcționează:**
- Verifică că nu e folosită de altă aplicație
- Schimbă `camera_index=0` cu `1` în `main.py → MainWindow._start_attention_monitor()`

**DeepSeek nu răspunde:**
- Verifică `ollama serve` rulează
- Verifică modelul: `ollama list`
- Aplicația funcționează și fără DeepSeek (exerciții pre-generate)

**Eroare la pornire:**
- Verifică că toate fișierele sunt în același director
- Rulează fiecare fișier standalone pentru diagnostic:
  ```bash
  python database.py
  python deepseek_client.py
  python attention_monitor.py
  python tts_engine.py
  ```
