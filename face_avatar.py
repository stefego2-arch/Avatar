"""
face_avatar.py
==============
FaceAvatarWidget - Avatar cu fata animata, redesenat realist cu QPainter.

Imbunatatiri fata de versiunea anterioara:
  - Chip mai mare (220x270), proportii naturale
  - Piele cu gradient multi-strat (subsurface scattering simulat)
  - Ochi detaliati: sclera, iris gradient, pupila, 2 sclipiri, gene individuale
  - Sperancene cu trasaturi fine (QPainterPath)
  - Buze cu Cupid's bow, highlight buza inferioara
  - Par cu straturi multiple si suvite
  - Gat si umeri
  - Urechi cu detaliu interior
  - Blush radial gradient
  - Umbre sub nas, barbie (ambient occlusion)
  - Animatie clipit + gura 30 FPS
"""
from __future__ import annotations

import math
import random
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSlot
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QFont, QRadialGradient, QLinearGradient, QConicalGradient
)
from PyQt6.QtWidgets import QWidget, QSizePolicy


# ─── Paleta per emotie ───────────────────────────────────────────────────────

EMOTION_PALETTE = {
    "idle":        {"bg": "#e8f4fd", "border": "#2980b9", "label": "Pregatit"},
    "happy":       {"bg": "#e8faf0", "border": "#27ae60", "label": "Bravo!"},
    "talking":     {"bg": "#f3eafc", "border": "#7d3c98", "label": "Asculta..."},
    "thinking":    {"bg": "#fef9e7", "border": "#d4a017", "label": "Hmm..."},
    "encouraging": {"bg": "#fef0e4", "border": "#ca6f1e", "label": "Curaj!"},
    "sad":         {"bg": "#eaecee", "border": "#717d7e", "label": "Nu-i bai!"},
    "excited":     {"bg": "#fefde7", "border": "#d4ac0d", "label": "Fantastic!"},
    "focused":     {"bg": "#e8f8f5", "border": "#148f77", "label": "Concentrat"},
}

EMOTION_FACE = {
    "idle":        {"smile": 0.10, "brow_raise": 0.0,  "brow_angle":  0, "eye_open": 1.00, "blush": False, "pupil": (0, 0)},
    "happy":       {"smile": 0.92, "brow_raise": 0.45, "brow_angle":  5, "eye_open": 1.10, "blush": True,  "pupil": (0,-1)},
    "talking":     {"smile": 0.30, "brow_raise": 0.10, "brow_angle":  0, "eye_open": 1.00, "blush": False, "pupil": (0, 0)},
    "thinking":    {"smile": 0.00, "brow_raise": 0.60, "brow_angle": 12, "eye_open": 0.85, "blush": False, "pupil":(-2,-3)},
    "encouraging": {"smile": 0.65, "brow_raise": 0.30, "brow_angle":  5, "eye_open": 1.10, "blush": True,  "pupil": (0, 0)},
    "sad":         {"smile":-0.75, "brow_raise":-0.35, "brow_angle": -9, "eye_open": 0.75, "blush": False, "pupil": (0, 2)},
    "excited":     {"smile": 1.00, "brow_raise": 0.85, "brow_angle":  8, "eye_open": 1.30, "blush": True,  "pupil": (0,-2)},
    "focused":     {"smile": 0.15, "brow_raise":-0.10, "brow_angle": -3, "eye_open": 1.00, "blush": False, "pupil": (0, 0)},
}

# ─── Culori piele ────────────────────────────────────────────────────────────
SKIN_BASE     = QColor(255, 213, 170)   # bej cald
SKIN_HIGHLIGHT= QColor(255, 235, 205)   # luminos
SKIN_SHADOW   = QColor(205, 150, 100)   # umbra calda
SKIN_DEEP     = QColor(175, 110,  65)   # umbra adanca (margini)
SKIN_BLUSH    = QColor(230, 130, 120)   # roz obraz
LIP_COLOR     = QColor(190,  80,  80)   # buze
LIP_DARK      = QColor(150,  50,  50)   # linie buze
LIP_LIGHT     = QColor(230, 130, 130)   # highlight buza inferioara
EYE_WHITE     = QColor(245, 248, 250)   # sclera
IRIS_OUTER    = QColor( 50,  90, 140)   # albastru-gri exterior iris
IRIS_MID      = QColor( 70, 130, 180)   # albastru mijloc
IRIS_INNER    = QColor( 30,  60, 100)   # inel interior iris
PUPIL_COLOR   = QColor( 20,  15,  10)   # pupila aproape neagra
BROW_COLOR    = QColor( 80,  50,  25)   # culoare spranceana
HAIR_BASE     = QColor( 70,  40,  10)   # par baza
HAIR_LIGHT    = QColor(120,  75,  30)   # par suvita luminoasa
HAIR_DARK     = QColor( 40,  20,   5)   # par umbra


class FaceAvatarWidget(QWidget):
    """Avatar realist animat - QPainter."""

    WIDGET_W = 220
    WIDGET_H = 270

    def __init__(self, tts=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WIDGET_W, self.WIDGET_H)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.tts = tts

        self._emotion  = "idle"
        self._face     = dict(EMOTION_FACE["idle"])
        self._prev_face    = dict(self._face)
        self._target_face  = dict(self._face)
        self._transition_t = 1.0     # 0..1, 1=done

        # Clipit
        self._blink_state  = 1.0     # 1=deschis, 0=inchis
        self._is_blinking  = False
        self._blink_frame  = 0
        self._blink_frames = 0
        self._next_blink   = random.randint(18, 55)
        self._blink_count  = 0

        # Gura
        self._mouth_open   = 0.0
        self._talking      = False
        self._mouth_phase  = 0.0

        # Tema
        self._bg_color     = "#e8f4fd"
        self._border_color = "#2980b9"
        self._label_text   = "Pregatit"

        # Timere
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start(33)   # ~30 FPS

        self._mouth_timer = QTimer(self)
        self._mouth_timer.timeout.connect(self._animate_mouth)

        if tts is not None:
            try:
                tts.started.connect(self._on_tts_started)
                tts.finished.connect(self._on_tts_finished)
            except Exception:
                pass

    # ── API public ────────────────────────────────────────────────────────

    def set_emotion(self, emotion: str):
        if emotion not in EMOTION_FACE:
            emotion = "idle"
        if emotion == self._emotion:
            return
        self._emotion = emotion
        pal = EMOTION_PALETTE.get(emotion, EMOTION_PALETTE["idle"])
        self._label_text   = pal["label"]
        self._border_color = pal["border"]
        self._bg_color     = pal["bg"]
        self._prev_face    = dict(self._face)
        self._target_face  = dict(EMOTION_FACE[emotion])
        self._transition_t = 0.0
        if emotion == "talking":
            self._start_talking()
        elif self._talking:
            self._stop_talking()

    def set_talking(self, talking: bool):
        if talking:
            self._start_talking()
        else:
            self._stop_talking()

    @pyqtSlot(str)
    def _on_tts_started(self, _text: str):
        self._start_talking()

    @pyqtSlot()
    def _on_tts_finished(self):
        self._stop_talking()

    def _start_talking(self):
        self._talking = True
        self._mouth_phase = 0.0
        if not self._mouth_timer.isActive():
            self._mouth_timer.start(75)

    def _stop_talking(self):
        self._talking = False
        self._mouth_timer.stop()
        self._mouth_open = 0.0

    # ── Tick animatie ─────────────────────────────────────────────────────

    def _tick(self):
        # Tranzitie emotie (ease-in-out)
        if self._transition_t < 1.0:
            self._transition_t = min(1.0, self._transition_t + 0.12)
            t = self._ease_inout(self._transition_t)
            for key in self._target_face:
                pv = self._prev_face.get(key, self._target_face[key])
                tv = self._target_face[key]
                if isinstance(tv, (int, float)):
                    self._face[key] = pv + (tv - pv) * t
                else:
                    self._face[key] = tv if t > 0.5 else pv

        # Clipit
        if not self._is_blinking:
            self._blink_count += 1
            if self._blink_count >= self._next_blink:
                self._is_blinking = True
                self._blink_frames = 0
                self._next_blink   = random.randint(18, 55)
                self._blink_count  = 0
        else:
            self._blink_frames += 1
            total = 10
            half  = 4
            if self._blink_frames <= half:
                self._blink_state = 1.0 - self._blink_frames / half
            elif self._blink_frames <= total:
                self._blink_state = (self._blink_frames - half) / (total - half)
            else:
                self._blink_state = 1.0
                self._is_blinking = False

        self.update()

    def _animate_mouth(self):
        self._mouth_phase += 0.38
        base  = 0.5 + 0.5 * math.sin(self._mouth_phase)
        noise = random.uniform(-0.12, 0.12)
        self._mouth_open = max(0.0, min(1.0, base + noise))

    @staticmethod
    def _ease_inout(t: float) -> float:
        return t * t * (3.0 - 2.0 * t)

    # ── Paint ─────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        W, H = self.width(), self.height()
        cx   = W // 2
        cy   = H // 2 - 5

        # Fundal
        bg = QLinearGradient(0, 0, 0, H)
        bg.setColorAt(0, QColor(self._bg_color).lighter(108))
        bg.setColorAt(1, QColor(self._bg_color).darker(105))
        p.fillRect(0, 0, W, H, QBrush(bg))

        cfg = self._face

        # Ordine desenare (back-to-front)
        self._draw_neck_shoulders(p, cx, cy)
        self._draw_hair_back(p, cx, cy)
        self._draw_ears(p, cx, cy)
        self._draw_face_base(p, cx, cy)
        self._draw_face_shading(p, cx, cy)
        self._draw_hair_front(p, cx, cy)
        self._draw_eyebrows(p, cx, cy, cfg)
        self._draw_eyes(p, cx, cy, cfg)
        self._draw_nose(p, cx, cy)
        self._draw_mouth(p, cx, cy, cfg)
        if cfg.get("blush"):
            self._draw_blush(p, cx, cy)
        self._draw_label(p, W, H)
        p.end()

    # ── Componente desenare ───────────────────────────────────────────────

    def _draw_neck_shoulders(self, p, cx, cy):
        """Gat si umeri."""
        neck_w = 34
        neck_h = 35
        neck_x = cx - neck_w // 2
        neck_y = cy + 82

        # Gat
        g = QLinearGradient(neck_x, neck_y, neck_x + neck_w, neck_y)
        g.setColorAt(0, SKIN_SHADOW)
        g.setColorAt(0.35, SKIN_BASE)
        g.setColorAt(0.65, SKIN_HIGHLIGHT)
        g.setColorAt(1, SKIN_SHADOW)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(neck_x, neck_y, neck_w, neck_h), 6, 6)

        # Umeri
        shoulder_y = neck_y + neck_h - 8
        spath = QPainterPath()
        spath.moveTo(cx - neck_w // 2 - 2, shoulder_y)
        spath.cubicTo(cx - 50, shoulder_y + 5, cx - 70, shoulder_y + 20, cx - 90, shoulder_y + 28)
        spath.lineTo(cx + 90, shoulder_y + 28)
        spath.cubicTo(cx + 70, shoulder_y + 20, cx + 50, shoulder_y + 5, cx + neck_w // 2 + 2, shoulder_y)
        spath.closeSubpath()
        sg = QLinearGradient(cx - 90, shoulder_y, cx + 90, shoulder_y)
        sg.setColorAt(0, SKIN_SHADOW.darker(110))
        sg.setColorAt(0.5, SKIN_BASE)
        sg.setColorAt(1, SKIN_SHADOW.darker(110))
        p.setBrush(QBrush(sg))
        p.drawPath(spath)

    def _draw_hair_back(self, p, cx, cy):
        """Strat de par din spate (sub cap)."""
        p.setPen(Qt.PenStyle.NoPen)

        # Calota mare
        hpath = QPainterPath()
        hpath.moveTo(cx - 78, cy + 15)
        hpath.cubicTo(cx - 82, cy - 20, cx - 75, cy - 92, cx, cy - 100)
        hpath.cubicTo(cx + 75, cy - 92, cx + 82, cy - 20, cx + 78, cy + 15)
        hpath.closeSubpath()
        g = QLinearGradient(cx - 80, cy - 100, cx + 80, cy + 15)
        g.setColorAt(0, HAIR_LIGHT)
        g.setColorAt(0.4, HAIR_BASE)
        g.setColorAt(1, HAIR_DARK)
        p.setBrush(QBrush(g))
        p.drawPath(hpath)

        # Bucle laterale
        for side in (-1, 1):
            lpath = QPainterPath()
            bx = cx + side * 74
            lpath.moveTo(bx, cy - 10)
            lpath.cubicTo(bx + side * 12, cy - 30, bx + side * 15, cy + 10, bx, cy + 30)
            lpath.cubicTo(bx - side * 5, cy + 15, bx - side * 5, cy, bx, cy - 10)
            p.setBrush(QBrush(HAIR_DARK))
            p.drawPath(lpath)

    def _draw_ears(self, p, cx, cy):
        """Urechi cu detaliu."""
        for side in (-1, 1):
            ex = cx + side * 72
            ey = cy + 8

            # Urechea exterioara
            ear_g = QRadialGradient(ex + side * 3, ey, 16)
            ear_g.setColorAt(0, SKIN_BASE.lighter(108))
            ear_g.setColorAt(1, SKIN_SHADOW)
            p.setBrush(QBrush(ear_g))
            p.setPen(QPen(SKIN_SHADOW, 1.5))
            p.drawEllipse(QRectF(ex - 10, ey - 18, 20, 34))

            # Detaliu interior (antehelix)
            p.setPen(QPen(SKIN_SHADOW.darker(115), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            inner = QPainterPath()
            inner.moveTo(ex + side * 2, ey - 10)
            inner.cubicTo(ex + side * 5, ey, ex + side * 4, ey + 10, ex + side * 2, ey + 14)
            p.drawPath(inner)

    def _draw_face_base(self, p, cx, cy):
        """Fata - forma de baza cu gradient radial."""
        rx, ry = 72, 85
        # Gradient piele: lumina venind din stanga sus
        grad = QRadialGradient(cx - rx * 0.25, cy - ry * 0.30, max(rx, ry) * 1.6)
        grad.setColorAt(0.00, SKIN_HIGHLIGHT)
        grad.setColorAt(0.35, SKIN_BASE)
        grad.setColorAt(0.70, QColor(230, 175, 120))
        grad.setColorAt(1.00, SKIN_DEEP)

        p.setPen(QPen(QColor(self._border_color).darker(120), 2.5))
        p.setBrush(QBrush(grad))

        # Forma fata: elipsa usor mai ingusta la barbie
        fpath = QPainterPath()
        fpath.moveTo(cx, cy - ry)
        fpath.cubicTo(cx + rx + 8, cy - ry, cx + rx, cy + ry * 0.3, cx + rx * 0.65, cy + ry)
        fpath.cubicTo(cx + rx * 0.3, cy + ry + 10, cx - rx * 0.3, cy + ry + 10, cx - rx * 0.65, cy + ry)
        fpath.cubicTo(cx - rx, cy + ry * 0.3, cx - rx - 8, cy - ry, cx, cy - ry)
        fpath.closeSubpath()
        p.drawPath(fpath)

    def _draw_face_shading(self, p, cx, cy):
        """Umbre subtile pe fata (ambient occlusion simulat)."""
        p.setPen(Qt.PenStyle.NoPen)

        # Umbra sub nas
        nos_sh = QRadialGradient(cx, cy + 22, 18)
        nos_sh.setColorAt(0, QColor(180, 110, 70, 55))
        nos_sh.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(nos_sh))
        p.drawEllipse(QRectF(cx - 18, cy + 14, 36, 20))

        # Umbra barbie / mandibula
        chin_sh = QRadialGradient(cx, cy + 78, 30)
        chin_sh.setColorAt(0, QColor(180, 110, 70, 40))
        chin_sh.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(chin_sh))
        p.drawEllipse(QRectF(cx - 30, cy + 65, 60, 25))

        # Umbra laterala (mandibula stanga/dreapta)
        for side in (-1, 1):
            side_sh = QRadialGradient(cx + side * 62, cy + 20, 28)
            side_sh.setColorAt(0, QColor(160, 100, 60, 50))
            side_sh.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(side_sh))
            p.drawEllipse(QRectF(cx + side * 62 - 28, cy + 5, 56, 35))

    def _draw_hair_front(self, p, cx, cy):
        """Par in fata (freza, suvite)."""
        p.setPen(Qt.PenStyle.NoPen)
        ry = 85

        # Freza principala
        freza = QPainterPath()
        freza.moveTo(cx - 72, cy - ry * 0.5)
        freza.cubicTo(cx - 60, cy - ry - 18, cx - 20, cy - ry - 22, cx, cy - ry - 16)
        freza.cubicTo(cx + 20, cy - ry - 22, cx + 60, cy - ry - 18, cx + 72, cy - ry * 0.5)
        freza.cubicTo(cx + 55, cy - ry - 8, cx + 30, cy - ry - 12, cx + 10, cy - ry - 6)
        freza.cubicTo(cx - 10, cy - ry - 12, cx - 40, cy - ry - 8, cx - 72, cy - ry * 0.5)
        freza.closeSubpath()
        fg = QLinearGradient(cx - 70, cy - ry - 22, cx + 70, cy - ry + 5)
        fg.setColorAt(0, HAIR_LIGHT)
        fg.setColorAt(0.5, HAIR_BASE)
        fg.setColorAt(1, HAIR_DARK)
        p.setBrush(QBrush(fg))
        p.drawPath(freza)

        # Suvite de lumina pe par
        p.setPen(QPen(HAIR_LIGHT.lighter(130), 1.5))
        for dx in [-20, 0, 20]:
            sx = cx + dx
            sy = cy - ry - 15
            strand = QPainterPath()
            strand.moveTo(sx, sy)
            strand.cubicTo(sx + 5, sy - 8, sx + 8, sy - 15, sx + 3, sy - 22)
            p.drawPath(strand)

    def _draw_eyebrows(self, p, cx, cy, cfg):
        """Sprancene cu trasaturi fine."""
        brow_raise = cfg.get("brow_raise", 0.0)
        brow_angle = cfg.get("brow_angle", 0)

        for side in (-1, 1):
            bx = cx + side * 26
            by = cy - 38 - brow_raise * 9

            angle_rad = math.radians(brow_angle * side)

            # Spranceana principala - traseu gros
            bw = 22
            bh =  4
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)

            x1 = bx - bw / 2 * cos_a
            y1 = by + bw / 2 * sin_a
            x2 = bx + bw / 2 * cos_a
            y2 = by - bw / 2 * sin_a
            ctrl_x = bx
            ctrl_y = by - bh - 2

            bpath = QPainterPath()
            bpath.moveTo(x1, y1)
            bpath.quadTo(ctrl_x, ctrl_y, x2, y2)

            # Gradient grosime spranceana (mai groasa la coada)
            for width, alpha in [(4.0, 200), (3.0, 160), (2.0, 100), (1.5, 60)]:
                p.setPen(QPen(QColor(BROW_COLOR.red(), BROW_COLOR.green(),
                                     BROW_COLOR.blue(), alpha),
                              width, Qt.PenStyle.SolidLine,
                              Qt.PenCapStyle.RoundCap,
                              Qt.PenJoinStyle.RoundJoin))
                p.drawPath(bpath)

            # Suvite fine de par in spranceana
            p.setPen(QPen(QColor(BROW_COLOR.red(), BROW_COLOR.green(),
                                  BROW_COLOR.blue(), 120), 1.0,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for i in range(5):
                t = i / 4.0
                hx = x1 + (x2 - x1) * t
                hy = y1 + (y2 - y1) * t
                ox = -sin_a * 4
                oy = -cos_a * 4
                strand = QPainterPath()
                strand.moveTo(hx - ox * 0.3, hy - oy * 0.3)
                strand.lineTo(hx + ox * 0.7, hy + oy * 0.7)
                p.drawPath(strand)

    def _draw_eyes(self, p, cx, cy, cfg):
        """Ochi detaliati: sclera, iris gradient, pupila, 2 sclipiri, gene."""
        eye_open = cfg.get("eye_open", 1.0) * self._blink_state
        px, py   = cfg.get("pupil", (0, 0))

        for side in (-1, 1):
            ex = cx + side * 26
            ey = cy - 12

            ew = 24    # latime ochi
            eh = max(1.5, 20 * eye_open)   # inaltime (clipit)

            # Umbra socket ochi
            p.setPen(Qt.PenStyle.NoPen)
            sock_g = QRadialGradient(ex, ey, ew)
            sock_g.setColorAt(0, QColor(160, 100, 60, 0))
            sock_g.setColorAt(0.7, QColor(140,  80, 40, 30))
            sock_g.setColorAt(1,   QColor(120,  60, 20, 60))
            p.setBrush(QBrush(sock_g))
            p.drawEllipse(QRectF(ex - ew * 0.7, ey - eh * 0.7, ew * 1.4, eh * 1.4))

            # Sclera (albul ochiului)
            p.setPen(QPen(QColor(160, 120, 90, 180), 1.0))
            p.setBrush(QBrush(EYE_WHITE))
            p.drawEllipse(QRectF(ex - ew / 2, ey - eh / 2, ew, eh))

            if eye_open > 0.12:
                # --- Iris gradient ---
                iris_r = min(8.5, eh * 0.45)
                iris_x = ex + px * min(0.5, iris_r * 0.15)
                iris_y = ey + py * min(0.5, iris_r * 0.12)

                # Iris exterior (inel inchis)
                ig = QRadialGradient(iris_x - iris_r * 0.25, iris_y - iris_r * 0.25, iris_r * 2.2)
                ig.setColorAt(0.00, IRIS_MID.lighter(120))
                ig.setColorAt(0.45, IRIS_MID)
                ig.setColorAt(0.70, IRIS_OUTER)
                ig.setColorAt(0.88, IRIS_INNER)
                ig.setColorAt(1.00, IRIS_INNER.darker(130))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(ig))
                p.drawEllipse(QRectF(iris_x - iris_r, iris_y - iris_r, iris_r * 2, iris_r * 2))

                # Pupila
                pur = iris_r * 0.52
                pg = QRadialGradient(iris_x - pur * 0.2, iris_y - pur * 0.2, pur * 1.8)
                pg.setColorAt(0, QColor(35, 25, 15))
                pg.setColorAt(1, PUPIL_COLOR)
                p.setBrush(QBrush(pg))
                p.drawEllipse(QRectF(iris_x - pur, iris_y - pur, pur * 2, pur * 2))

                # Sclipire primara (mare)
                p.setBrush(QBrush(QColor(255, 255, 255, 220)))
                p.drawEllipse(QRectF(iris_x - pur * 0.25,
                                     iris_y - iris_r * 0.75,
                                     iris_r * 0.45, iris_r * 0.35))
                # Sclipire secundara (mica)
                p.setBrush(QBrush(QColor(255, 255, 255, 140)))
                p.drawEllipse(QRectF(iris_x + pur * 0.45,
                                     iris_y + iris_r * 0.15,
                                     iris_r * 0.22, iris_r * 0.18))

            # Pleoapa superioara (linie groasa + umbra)
            if eye_open > 0.08:
                p.setPen(QPen(QColor(60, 35, 20, 200), 2.8,
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawArc(QRectF(ex - ew / 2, ey - eh / 2, ew, eh), 0, 180 * 16)

                # Gene superioare (linii scurte)
                p.setPen(QPen(QColor(50, 30, 15, 180), 1.2,
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                for i in range(7):
                    angle = math.radians(20 + i * 20)
                    gx = ex - (ew / 2) * math.cos(angle)
                    gy = ey - (eh / 2) * abs(math.sin(angle))
                    dir_x = -math.cos(angle) * 0.3
                    dir_y = -abs(math.sin(angle)) * 0.9 - 0.5
                    length = 4.5 + abs(math.sin(angle)) * 2
                    p.drawLine(QPointF(gx, gy),
                               QPointF(gx + dir_x * length, gy + dir_y * length))

            # Pleoapa inferioara subtila
            p.setPen(QPen(QColor(160, 110, 80, 80), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(ex - ew / 2, ey - eh / 2, ew, eh), 0, -180 * 16)

    def _draw_nose(self, p, cx, cy):
        """Nas realist cu bridge, narile si umbre."""
        p.setBrush(Qt.BrushStyle.NoBrush)

        # Highlight pe bridge
        p.setPen(QPen(QColor(255, 230, 200, 90), 2.0,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx + 1, cy - 8), QPointF(cx + 1, cy + 10))

        # Forma nas (profil)
        p.setPen(QPen(SKIN_SHADOW.darker(110), 1.3,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        npath = QPainterPath()
        npath.moveTo(cx - 1, cy - 5)
        npath.cubicTo(cx + 4, cy + 5, cx + 10, cy + 12, cx + 11, cy + 18)
        npath.cubicTo(cx + 7, cy + 22, cx + 2, cy + 22, cx, cy + 21)
        p.drawPath(npath)
        npath2 = QPainterPath()
        npath2.moveTo(cx, cy + 21)
        npath2.cubicTo(cx - 2, cy + 22, cx - 7, cy + 22, cx - 11, cy + 18)
        npath2.cubicTo(cx - 10, cy + 12, cx - 4, cy + 5, cx - 1, cy - 5)
        p.drawPath(npath2)

        # Narile
        p.setPen(QPen(SKIN_SHADOW.darker(130), 1.2))
        p.setBrush(QBrush(QColor(SKIN_SHADOW.darker(120))))
        for side in (-1, 1):
            p.drawEllipse(QRectF(cx + side * 6 - 4, cy + 16, 8, 6))

        # Highlight varf nas
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(255, 240, 220, 100)))
        p.drawEllipse(QRectF(cx - 4, cy + 12, 8, 7))

    def _draw_mouth(self, p, cx, cy, cfg):
        """Gura cu Cupid's bow, highlight buza inferioara."""
        smile = cfg.get("smile", 0.0)
        mo    = self._mouth_open

        my = cy + 42    # Y centrul gurii
        mw = 28         # semilargime
        curve = smile * 13   # pozitiv=zambesc, negativ=trist

        if mo > 0.05:
            # ── Gura deschisa ──────────────────────────────────────────────
            open_h = mo * 16 + 2

            # Interiorul (cavitatea bucala)
            interior = QPainterPath()
            interior.moveTo(cx - mw + 3, my)
            interior.quadTo(cx, my - curve, cx + mw - 3, my)
            interior.cubicTo(cx + mw + 2, my + open_h * 0.5,
                             cx + mw * 0.5, my + open_h,
                             cx, my + open_h * 0.9 + curve * 0.2)
            interior.cubicTo(cx - mw * 0.5, my + open_h,
                             cx - mw - 2, my + open_h * 0.5,
                             cx - mw + 3, my)
            interior.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(60, 20, 20)))
            p.drawPath(interior)

            # Dinti (daca deschisa suficient)
            if mo > 0.28:
                p.setBrush(QBrush(QColor(248, 246, 240)))
                tooth_h = min(open_h * 0.45, 9)
                p.drawRoundedRect(
                    QRectF(cx - mw + 6, my + 1, (mw - 6) * 2, tooth_h),
                    2.5, 2.5
                )
                # Linie despartitoare dinti
                p.setPen(QPen(QColor(200, 195, 185, 120), 0.8))
                p.drawLine(QPointF(cx, my + 1), QPointF(cx, my + tooth_h))

            # Buza superioara (deasupra gurii deschise)
            p.setPen(Qt.PenStyle.NoPen)
            upper = QPainterPath()
            upper.moveTo(cx - mw + 2, my)
            # Cupid's bow
            upper.cubicTo(cx - mw * 0.5, my - 5 - curve, cx - mw * 0.15, my - 8 - curve,
                          cx, my - 7 - curve)
            upper.cubicTo(cx + mw * 0.15, my - 8 - curve, cx + mw * 0.5, my - 5 - curve,
                          cx + mw - 2, my)
            upper.quadTo(cx, my - curve + 2, cx - mw + 2, my)
            upper.closeSubpath()
            p.setBrush(QBrush(LIP_COLOR))
            p.drawPath(upper)

        else:
            # ── Gura inchisa ───────────────────────────────────────────────
            # Buza superioara cu Cupid's bow
            upper = QPainterPath()
            upper.moveTo(cx - mw + 2, my)
            upper.cubicTo(cx - mw * 0.5, my - 5 - curve,
                          cx - mw * 0.15, my - 8 - curve, cx, my - 7 - curve)
            upper.cubicTo(cx + mw * 0.15, my - 8 - curve,
                          cx + mw * 0.5, my - 5 - curve, cx + mw - 2, my)
            upper.lineTo(cx, my - curve * 0.3)
            upper.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(LIP_COLOR.darker(108)))
            p.drawPath(upper)

            # Buza inferioara
            lower = QPainterPath()
            lower.moveTo(cx - mw + 2, my)
            lower.cubicTo(cx - mw * 0.6, my + 7 - curve * 0.3,
                          cx + mw * 0.6, my + 7 - curve * 0.3, cx + mw - 2, my)
            lower.quadTo(cx, my + 5 - curve * 0.2, cx - mw + 2, my)
            lower.closeSubpath()
            p.setBrush(QBrush(LIP_COLOR))
            p.drawPath(lower)

            # Highlight buza inferioara
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(240, 170, 160, 120)))
            p.drawEllipse(QRectF(cx - 8, my + 2 - curve * 0.3, 16, 5))

        # Linie gurii
        p.setPen(QPen(LIP_DARK, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        lpath = QPainterPath()
        lpath.moveTo(cx - mw + 2, my)
        lpath.quadTo(cx, my - curve, cx + mw - 2, my)
        p.drawPath(lpath)

        # Gropituri zambet
        if smile > 0.35:
            p.setPen(QPen(SKIN_SHADOW.darker(115), 1.4))
            for side in (-1, 1):
                dx = side * (mw - 1)
                dim = QPainterPath()
                dim.moveTo(cx + dx, my - 2)
                dim.cubicTo(cx + dx + side * 4, my + 3, cx + dx + side * 3, my + 8, cx + dx, my + 7)
                p.drawPath(dim)

    def _draw_blush(self, p, cx, cy):
        """Roz pe obraji (radial gradient)."""
        p.setPen(Qt.PenStyle.NoPen)
        for side in (-1, 1):
            bx = cx + side * 44
            by = cy + 22
            bg = QRadialGradient(bx, by, 22)
            bg.setColorAt(0, QColor(SKIN_BLUSH.red(), SKIN_BLUSH.green(),
                                    SKIN_BLUSH.blue(), 90))
            bg.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(bg))
            p.drawEllipse(QRectF(bx - 22, by - 14, 44, 28))

    def _draw_label(self, p, W, H):
        p.setPen(QPen(QColor(self._border_color).darker(110)))
        p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        p.drawText(QRectF(0, H - 22, W, 20),
                   Qt.AlignmentFlag.AlignCenter, self._label_text)
