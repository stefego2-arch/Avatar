"""
ui/avatar_widget.py
===================
AvatarWidget — afișează avatarul cu expresii diferite (emoji fallback sau PNG).
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from md_lesson_player import MDLessonPlayer


class AvatarWidget(QWidget):
    """
    Afișează avatarul cu expresii diferite.
    Folosește emoji + text colorat dacă nu există imagini PNG.
    Pune imagini în assets/avatar/ cu denumirile de mai jos pentru upgrade vizual.
    """

    EMOTIONS = {
        "idle":        ("🤖", "#3498db", "Pregătit"),
        "happy":       ("😄", "#27ae60", "Bravo!"),
        "talking":     ("🗣️", "#8e44ad", "Ascultă..."),
        "thinking":    ("🤔", "#f39c12", "Hmm..."),
        "encouraging": ("💪", "#e67e22", "Curaj!"),
        "sad":         ("😟", "#95a5a6", "Nu-i bai!"),
        "excited":     ("🌟", "#f1c40f", "Fantastic!"),
    }

    def __init__(self, tts):
        super().__init__()
        self.tts = tts
        self._setup_ui()
        self.setFixedSize(200, 220)
        self._emotion = "idle"

        self._assets_dir = Path("assets/avatar")
        self._blink_timer = QTimer()
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start(4000)  # Clipit la fiecare 4 secunde

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Frame pentru avatar
        self._avatar_frame = QFrame()
        self._avatar_frame.setFixedSize(180, 180)
        self._avatar_frame.setStyleSheet(
            "border: 3px solid #3498db; border-radius: 90px;"
            "background-color: #eaf4fd;"
        )

        avatar_inner = QVBoxLayout()
        self._avatar_emoji = QLabel("🤖")
        self._avatar_emoji.setFont(QFont("Segoe UI Emoji", 72))
        self._avatar_emoji.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_inner.addWidget(self._avatar_emoji)
        self._avatar_frame.setLayout(avatar_inner)

        self.md_player = MDLessonPlayer(self.tts)

        # Imagine PNG (dacă există)
        self._avatar_image = QLabel()
        self._avatar_image.setFixedSize(180, 180)
        self._avatar_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_image.hide()

        # Status text
        self._status_label = QLabel("Pregătit")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setFont(QFont("Arial", 10))
        self._status_label.setStyleSheet("color: #7f8c8d;")

        layout.addWidget(self._avatar_frame, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)
        self.setLayout(layout)

    def set_emotion(self, emotion: str):
        """Schimbă expresia avatarului."""
        if emotion not in self.EMOTIONS:
            emotion = "idle"
        self._emotion = emotion
        emoji, color, label = self.EMOTIONS[emotion]

        # Încearcă să încarce imagine PNG
        img_path = self._assets_dir / f"{emotion}.png"
        if img_path.exists():
            pixmap = QPixmap(str(img_path)).scaled(
                170, 170,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._avatar_image.setPixmap(pixmap)
            self._avatar_image.show()
            self._avatar_emoji.hide()
        else:
            self._avatar_emoji.setText(emoji)
            self._avatar_emoji.show()
            self._avatar_image.hide()

        self._avatar_frame.setStyleSheet(
            f"border: 3px solid {color}; border-radius: 90px; background-color: #eaf4fd;"
        )
        self._status_label.setText(label)
        self._status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _blink(self):
        """Animație clipit simplă."""
        if self._emotion == "idle":
            self._avatar_emoji.setText("😑")
            QTimer.singleShot(150, lambda: self._avatar_emoji.setText("🤖"))
