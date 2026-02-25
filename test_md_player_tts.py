import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from tts_engine import TTSEngine
from md_lesson_player import MDLessonPlayer

MANUALE_DIR = Path("manuale")

app = QApplication(sys.argv)

tts = TTSEngine()
player = MDLessonPlayer(tts, max_chars=900, min_chars=300)

md_files = sorted(MANUALE_DIR.glob("*.md"))
if not md_files:
    print("Nu am găsit .md în", MANUALE_DIR.resolve())
    sys.exit(0)

path = md_files[0]
print("Load:", path.name)
lesson = player.load(path)
print("Title:", lesson.title, "chunks:", player.total())

print("STEP1: speak chunk 1")
player.speak_current()

def step2():
    print("STEP2: stop + speak next")
    player.stop()
    player.speak_next()

QTimer.singleShot(4500, step2)
QTimer.singleShot(12000, app.quit)

app.exec()
