"""
stars_widget.py
===============
Widget animatie stele acordate dupa finalizarea unei lectii.

Componente:
  - StarAwardDialog  : popup animat cu 0-3 stele
  - StarsBadge       : widget mic pentru bara de sus (stele totale + streak)
"""
from __future__ import annotations

import math
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint,
    pyqtSignal, QSequentialAnimationGroup, QParallelAnimationGroup,
    QRect
)
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QRadialGradient,
    QLinearGradient, QPixmap
)


# ── Constante vizuale ─────────────────────────────────────────────────────────
STAR_ON_COLOR  = QColor("#f1c40f")   # galben
STAR_OFF_COLOR = QColor("#d5d8dc")   # gri
STAR_GLOW_COLOR = QColor("#f39c12")  # portocaliu
STREAK_COLOR   = QColor("#e67e22")


# ── Widget stea QPainter ──────────────────────────────────────────────────────

class StarWidget(QWidget):
    """O stea desenata cu QPainter. Suporta animatie de scale."""

    def __init__(self, filled: bool = False, size: int = 60, parent=None):
        super().__init__(parent)
        self.filled = filled
        self._scale = 0.0 if filled else 1.0  # 0 → creste animat
        self._glow  = 0.0
        self.setFixedSize(size + 20, size + 20)
        self._size = size

    def set_scale(self, s: float):
        self._scale = s
        self.update()

    def set_glow(self, g: float):
        self._glow = g
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        r  = self._size / 2 * self._scale

        if r < 1:
            return

        # Glow efect
        if self.filled and self._glow > 0:
            glow_r = r * (1 + 0.4 * self._glow)
            grd = QRadialGradient(cx, cy, glow_r)
            grd.setColorAt(0, QColor(241, 196, 15, int(120 * self._glow)))
            grd.setColorAt(1, QColor(241, 196, 15, 0))
            painter.setBrush(QBrush(grd))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                int(cx - glow_r), int(cy - glow_r),
                int(glow_r * 2), int(glow_r * 2)
            )

        # Punctele stelei (5 varfuri)
        points = self._star_points(cx, cy, r, r * 0.4, 5)

        if self.filled:
            # Gradient auriu
            grd2 = QRadialGradient(cx, cy - r * 0.2, r)
            grd2.setColorAt(0, QColor("#ffe066"))
            grd2.setColorAt(0.6, STAR_ON_COLOR)
            grd2.setColorAt(1, STAR_GLOW_COLOR)
            painter.setBrush(QBrush(grd2))
            painter.setPen(QPen(QColor("#d4a017"), 1.5))
        else:
            painter.setBrush(QBrush(STAR_OFF_COLOR))
            painter.setPen(QPen(QColor("#b2bec3"), 1.5))

        from PyQt6.QtGui import QPolygonF
        from PyQt6.QtCore import QPointF
        poly = QPolygonF([QPointF(x, y) for x, y in points])
        painter.drawPolygon(poly)
        painter.end()

    @staticmethod
    def _star_points(cx, cy, r_out, r_in, n):
        pts = []
        for i in range(n * 2):
            angle = math.radians(-90 + i * 180 / n)
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        return pts


# ── Dialog principal ──────────────────────────────────────────────────────────

class StarAwardDialog(QDialog):
    """
    Dialog animat care arata stelee obtinute la finalul lectiei.

    Utilizare:
        dlg = StarAwardDialog(stars=2, streak=5, parent=self)
        dlg.exec()
    """

    def __init__(
        self,
        stars: int = 0,
        streak: int = 0,
        lesson_title: str = "",
        score_pct: float = 0.0,
        parent=None,
    ):
        super().__init__(parent)
        self._stars_count = max(0, min(3, stars))
        self._streak      = streak
        self._lesson_title = lesson_title
        self._score_pct    = score_pct
        self._star_widgets: list[StarWidget] = []

        self.setWindowTitle("Bravo!")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #1a1a2e, stop:1 #16213e);
                border-radius: 20px;
            }
        """)
        self._setup_ui()
        # Start animatie dupa 200ms
        QTimer.singleShot(200, self._animate_stars)

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(18)

        # Titlu
        if self._stars_count == 3:
            title_text = "Excelent! Perfect!"
            title_color = "#f1c40f"
        elif self._stars_count == 2:
            title_text = "Bravo! Foarte bine!"
            title_color = "#27ae60"
        elif self._stars_count == 1:
            title_text = "Bine! Poti mai mult!"
            title_color = "#3498db"
        else:
            title_text = "Incearca din nou!"
            title_color = "#e74c3c"

        lbl_title = QLabel(title_text)
        lbl_title.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet(f"color: {title_color}; background: transparent;")
        layout.addWidget(lbl_title)

        # Lectia
        if self._lesson_title:
            lbl_lesson = QLabel(self._lesson_title)
            lbl_lesson.setFont(QFont("Arial", 12))
            lbl_lesson.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_lesson.setStyleSheet("color: #aaa; background: transparent;")
            layout.addWidget(lbl_lesson)

        # Scor
        lbl_score = QLabel(f"Scor: {self._score_pct:.0f}%")
        lbl_score.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        lbl_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_score.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(lbl_score)

        # Stele
        stars_row = QHBoxLayout()
        stars_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stars_row.setSpacing(15)
        for i in range(3):
            filled = i < self._stars_count
            sw = StarWidget(filled=filled, size=70)
            self._star_widgets.append(sw)
            stars_row.addWidget(sw)
        layout.addLayout(stars_row)

        # Streak
        if self._streak > 0:
            streak_txt = f"🔥 {self._streak} {'zile' if self._streak > 1 else 'zi'} la rand!"
            lbl_streak = QLabel(streak_txt)
            lbl_streak.setFont(QFont("Arial", 14, QFont.Weight.Bold))
            lbl_streak.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl_streak.setStyleSheet(
                f"color: {STREAK_COLOR.name()}; background: transparent;"
            )
            layout.addWidget(lbl_streak)

        # Mesaj motivational
        msgs = {
            3: ["Esti un geniu! Continua asa!", "Perfect! Nimic de corectat!"],
            2: ["Foarte bine! Mai exerseaza putin!", "Aproape perfect!"],
            1: ["Bun inceput! Practica duce la perfectiune!", "Mai incearca, te descurci!"],
            0: ["Nu renunta! Fiecare incercare te face mai bun!", "Incearca din nou!"],
        }
        import random
        msg = random.choice(msgs[self._stars_count])
        lbl_msg = QLabel(msg)
        lbl_msg.setFont(QFont("Arial", 12))
        lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet("color: #bdc3c7; background: transparent;")
        layout.addWidget(lbl_msg)

        # Buton
        btn = QPushButton("Continua! →")
        btn.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        btn.setMinimumHeight(48)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border-radius: 12px;
                padding: 8px 24px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

        self.setLayout(layout)

    def _animate_stars(self):
        """Apare fiecare stea pe rand cu animatie de scale."""
        delay = 0
        for i, sw in enumerate(self._star_widgets):
            if not sw.filled:
                sw._scale = 1.0
                continue
            sw._scale = 0.0
            QTimer.singleShot(delay, lambda w=sw: self._pop_star(w))
            delay += 350

    def _pop_star(self, sw: StarWidget):
        """Animeaza o stea: creste de la 0 la 1.3 si revine la 1."""
        steps = 16
        for step in range(steps + 1):
            t = step / steps
            # ease out elastic-ish
            if t < 0.6:
                scale = t / 0.6 * 1.35
            else:
                scale = 1.35 - (t - 0.6) / 0.4 * 0.35
            glow = max(0, 1.0 - t * 1.5)
            QTimer.singleShot(step * 20, lambda s=scale, g=glow, w=sw: (
                w.set_scale(s), w.set_glow(g)
            ))


# ── Badge mic pentru header ───────────────────────────────────────────────────

class StarsBadge(QWidget):
    """
    Widget compact afisand: ⭐ 42  🔥 5
    Se plaseaza in header-ul ecranului de login sau al lectiei.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        self._lbl_stars = QLabel("⭐ 0")
        self._lbl_stars.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self._lbl_stars.setStyleSheet("color: #f1c40f;")
        layout.addWidget(self._lbl_stars)

        self._lbl_streak = QLabel("🔥 0")
        self._lbl_streak.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self._lbl_streak.setStyleSheet("color: #e67e22;")
        layout.addWidget(self._lbl_streak)

        self.setLayout(layout)
        self.setStyleSheet(
            "background-color: rgba(0,0,0,60); border-radius: 12px;"
        )

    def update_stats(self, total_stars: int, streak_days: int):
        self._lbl_stars.setText(f"⭐ {total_stars}")
        self._lbl_streak.setText(f"🔥 {streak_days}")
