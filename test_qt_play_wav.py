import sys, wave, math, struct
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices

# generez un beep wav
wav_path = "beep.wav"
sr = 44100
dur = 0.5
freq = 440.0

with wave.open(wav_path, "w") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(sr)
    for n in range(int(sr * dur)):
        s = int(0.2 * 32767 * math.sin(2 * math.pi * freq * n / sr))
        w.writeframes(struct.pack("<h", s))

app = QApplication(sys.argv)

player = QMediaPlayer()
out = QAudioOutput()
player.setAudioOutput(out)

# selectează explicit device Realtek dacă vrei:
for dev in QMediaDevices.audioOutputs():
    if "Realtek" in dev.description():
        out.setDevice(dev)
        print("Using:", dev.description())
        break

player.setSource(QUrl.fromLocalFile(wav_path))
player.play()

QTimer.singleShot(1500, app.quit)
sys.exit(app.exec())
