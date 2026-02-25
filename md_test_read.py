# test_md_read.py
import sys
from PyQt6.QtWidgets import QApplication
from tts_engine import TTSEngine
from md_lesson_player import MDLessonPlayer

app = QApplication(sys.argv)

tts = TTSEngine()
p = MDLessonPlayer(tts)

ok = p.load_default("Matematică", 3, max_chars=650)
print("load:", ok, "|", p.status())

p.speak_current()

# după 5 secunde: stop + next
from PyQt6.QtCore import QTimer
QTimer.singleShot(5000, p.next_and_speak)
QTimer.singleShot(9000, p.stop)
QTimer.singleShot(9500, app.quit)

app.exec()
