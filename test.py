import sys
from PyQt6.QtWidgets import QApplication
from tts_engine import TTSEngine

app = QApplication(sys.argv)

tts = TTSEngine()
print("engine:", tts.engine_name)

tts.speak("Bună! Dacă mă auzi, TTS funcționează corect.")
sys.exit(app.exec())
