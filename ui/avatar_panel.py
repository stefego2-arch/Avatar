"""
ui/avatar_panel.py
==================
AvatarPanel — panoul din stânga cu avatarul 3D, status atenție și mesaje.
"""
from __future__ import annotations

import numpy as np

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QGroupBox, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from attention_monitor import AttentionState


class AvatarPanel(QWidget):
    """Panoul din stânga cu avatarul, status atenție și mesaje."""

    def __init__(self, tts):
        super().__init__()
        self.setFixedWidth(300)
        self.tts = tts
        self._setup_ui()

    def _setup_ui(self):
        # Import tardiv — QWebEngineView trebuie instanțiat după QApplication + AA_ShareOpenGLContexts
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Avatar 3D (WebEngine → viewer.html) ───────────────────────────
        self.avatar_view = QWebEngineView()
        self.avatar_view.setFixedHeight(320)
        self.avatar_view.setUrl(QUrl("avatar://localhost/viewer.html"))
        self.avatar_view.page().setBackgroundColor(Qt.GlobalColor.black)
        self.avatar_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        layout.addWidget(self.avatar_view)

        # Status atenție
        attn_box = QGroupBox("👁️ Atenție")
        attn_layout = QVBoxLayout()

        self._lbl_attention = QLabel("🟢 ATENT")
        self._lbl_attention.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._lbl_attention.setAlignment(Qt.AlignmentFlag.AlignCenter)
        attn_layout.addWidget(self._lbl_attention)

        self._attention_bar = QProgressBar()
        self._attention_bar.setMaximum(100)
        self._attention_bar.setValue(100)
        self._attention_bar.setFormat("%p%")
        self._attention_bar.setMinimumHeight(18)
        # Pornim cu verde (ATENT 100%) — se actualizează live când pornește camera
        self._attention_bar.setStyleSheet(
            "QProgressBar { border-radius: 8px; background: #e8f5e9; }"
            "QProgressBar::chunk { background-color: #27ae60; border-radius: 6px; }"
        )
        attn_layout.addWidget(self._attention_bar)

        self._lbl_camera = QLabel("📷 Cameră inactivă")
        self._lbl_camera.setFont(QFont("Arial", 9))
        self._lbl_camera.setStyleSheet("color: #95a5a6;")
        self._lbl_camera.setAlignment(Qt.AlignmentFlag.AlignCenter)
        attn_layout.addWidget(self._lbl_camera)

        # ── Preview cameră (toggle) ─────────────────────────────────────
        self._camera_preview = QLabel()
        self._camera_preview.setFixedSize(200, 112)   # 16:9 miniatura
        self._camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._camera_preview.setStyleSheet(
            "background-color: #1a1a2e; border-radius: 6px; color: #555;"
        )
        self._camera_preview.setText("[ cameră ]")
        self._camera_preview.hide()
        attn_layout.addWidget(self._camera_preview, alignment=Qt.AlignmentFlag.AlignCenter)

        self._btn_cam_toggle = QPushButton("📷 Arată preview")
        self._btn_cam_toggle.setFont(QFont("Arial", 8))
        self._btn_cam_toggle.setCheckable(True)
        self._btn_cam_toggle.setFixedHeight(24)
        self._btn_cam_toggle.setStyleSheet(
            "QPushButton { background:#dfe6e9; border-radius:5px; padding:2px 6px; }"
            "QPushButton:checked { background:#3498db; color:white; }"
        )
        self._btn_cam_toggle.clicked.connect(self._toggle_camera_preview)
        attn_layout.addWidget(self._btn_cam_toggle)

        # Indicator "Ascultă mereu" — arată că voice barge-in e activ
        self._lbl_always_on = QLabel("🎙️ Ascultă mereu")
        self._lbl_always_on.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_always_on.setFont(QFont("Arial", 9))
        self._lbl_always_on.setStyleSheet("color: #27ae60; padding: 2px;")
        attn_layout.addWidget(self._lbl_always_on)

        attn_box.setLayout(attn_layout)
        layout.addWidget(attn_box)

        # Mesaj avatar
        msg_box = QGroupBox("💬 Avatar")
        msg_layout = QVBoxLayout()
        self._lbl_message = QLabel("Bine ai venit!")
        self._lbl_message.setFont(QFont("Arial", 11))
        self._lbl_message.setWordWrap(True)
        self._lbl_message.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._lbl_message.setMinimumHeight(80)
        self._lbl_message.setStyleSheet("padding: 5px; color: #2c3e50;")
        msg_layout.addWidget(self._lbl_message)
        msg_box.setLayout(msg_layout)
        layout.addWidget(msg_box)

        # Statistici sesiune
        stat_box = QGroupBox("📊 Sesiune")
        stat_layout = QVBoxLayout()
        self._lbl_score = QLabel("Scor: —")
        self._lbl_score.setFont(QFont("Arial", 11))
        stat_layout.addWidget(self._lbl_score)
        self._lbl_time = QLabel("Timp: 0 min")
        self._lbl_time.setFont(QFont("Arial", 11))
        stat_layout.addWidget(self._lbl_time)
        self._lbl_streak = QLabel("Streak: 0 ✓")
        self._lbl_streak.setFont(QFont("Arial", 11))
        stat_layout.addWidget(self._lbl_streak)
        stat_box.setLayout(stat_layout)
        layout.addWidget(stat_box)

        layout.addStretch()
        self.setLayout(layout)

    def set_attention(self, state: AttentionState, pct: float):
        """Actualizează indicatorul de atenție."""
        labels = {
            AttentionState.FOCUSED:    ("🟢 ATENT", "#27ae60"),
            AttentionState.DISTRACTED: ("🟠 DISTRAS", "#f39c12"),
            AttentionState.TIRED:      ("🔵 OBOSIT", "#3498db"),
            AttentionState.AWAY:       ("🔴 ABSENT", "#e74c3c"),
            AttentionState.UNKNOWN:    ("⚪ ...", "#95a5a6"),
        }
        text, color = labels.get(state, ("⚪ ...", "#95a5a6"))
        self._lbl_attention.setText(text)
        self._lbl_attention.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._attention_bar.setValue(int(pct))
        bar_style = f"""
            QProgressBar::chunk {{ background-color: {color}; border-radius: 6px; }}
        """
        self._attention_bar.setStyleSheet(bar_style)

    def set_camera_active(self, active: bool):
        if active:
            self._lbl_camera.setText("📷 Cameră activă")
            self._lbl_camera.setStyleSheet("color: #27ae60;")
            self._btn_cam_toggle.setEnabled(True)
        else:
            self._lbl_camera.setText("📷 Cameră indisponibilă")
            self._lbl_camera.setStyleSheet("color: #95a5a6;")
            self._btn_cam_toggle.setEnabled(False)

    def _toggle_camera_preview(self, checked: bool):
        """Afișează/ascunde preview-ul camerei."""
        if checked:
            self._camera_preview.show()
            self._btn_cam_toggle.setText("📷 Ascunde preview")
        else:
            self._camera_preview.hide()
            self._btn_cam_toggle.setText("📷 Arată preview")

    def set_camera_frame(self, frame_bgr: np.ndarray):
        """Actualizează preview-ul cu frame-ul curent (BGR numpy array).
        Apelat din thread-ul camerei via QTimer.singleShot (thread-safe).
        """
        if not self._camera_preview.isVisible():
            return
        try:
            h, w, ch = frame_bgr.shape
            rgb = frame_bgr[:, :, ::-1].copy()   # BGR → RGB
            qi = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
            px = QPixmap.fromImage(qi).scaled(
                200, 112,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._camera_preview.setPixmap(px)
        except Exception:
            pass

    def set_emotion(self, emotion: str):
        """Controlează animația avatarului 3D prin JS (setTalking)."""
        is_talking = emotion in ("talking", "happy", "correct")
        js = f"if(window.setTalking) window.setTalking({'true' if is_talking else 'false'});"
        try:
            self.avatar_view.page().runJavaScript(js)
        except Exception:
            pass

    def set_mouth_opening(self, volume: float):
        """Trimite volumul RMS către JS pentru lip-sync audio-driven (~30fps)."""
        # Amplificăm volumul — ElevenLabs PCM normalizat are RMS ~0.05-0.15
        scaled = min(1.0, volume * 6.0)
        js = f"if(typeof window.setMouthOpening==='function')window.setMouthOpening({scaled:.3f});"
        try:
            self.avatar_view.page().runJavaScript(js)
        except Exception:
            pass

    def set_message(self, text: str, emotion: str = "talking"):
        """Afișează mesaj avatar și schimbă expresia."""
        self._lbl_message.setText(text)
        self.set_emotion(emotion)

    def update_stats(self, correct: int, total: int, elapsed_s: int, streak: int):
        pct = correct / total * 100 if total > 0 else 0
        self._lbl_score.setText(f"Scor: {correct}/{total} ({pct:.0f}%)")
        minutes = elapsed_s // 60
        self._lbl_time.setText(f"Timp: {minutes} min")
        self._lbl_streak.setText(f"Streak: {streak} ✓")
