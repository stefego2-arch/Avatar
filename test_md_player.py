from tts_engine import TTSEngine
from md_lesson_player import MDLessonPlayer
from PyQt6.QtWidgets import QApplication
import sys

app = QApplication(sys.argv)

tts = TTSEngine()
player = MDLessonPlayer(tts)

player.load(r"C:\Users\stefan.ionica\PycharmProjects\Avatar\Manuale2_5\Matematica_1105.md")
print("TITLE:", player.lesson.title, "chunks:", player.total())

player.speak_current()
# după 4 secunde, întrerupe și trece la chunkul următor
from PyQt6.QtCore import QTimer
QTimer.singleShot(4000, lambda: player.speak_next())
QTimer.singleShot(9000, app.quit)

app.exec()
