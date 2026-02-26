"""
dashboard.py
============
Dashboard progres pentru Avatar Tutor.
Afiseaza grafice si statistici pentru un utilizator ales.

Widget principal: DashboardScreen(QWidget)
    - grafic scor in timp
    - grafic lectii completate per unitate
    - radar skill mastery
    - statistici rapide (streak, medie, lectii azi)
    - buton export PDF
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QGroupBox, QSizePolicy,
    QProgressBar, QDialog, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QPixmap

# Matplotlib embedded in Qt6
import matplotlib
import matplotlib.ticker
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from database import Database


# ── Culori tema ───────────────────────────────────────────────────────────────
C_BG      = "#f0f4f8"
C_CARD    = "white"
C_PRIMARY = "#3498db"
C_SUCCESS = "#27ae60"
C_WARN    = "#e67e22"
C_DANGER  = "#e74c3c"
C_PURPLE  = "#9b59b6"

SUBJECT_COLORS = {
    "Matematica":    "#3498db",
    "Matematică":    "#3498db",
    "Limba Romana":  "#e67e22",
    "Limba Română":  "#e67e22",
}


# ── Minicard statistica ───────────────────────────────────────────────────────

class StatCard(QFrame):
    """Cartonase cu icon + cifra + label."""
    def __init__(self, icon: str, value: str, label: str, color: str = C_PRIMARY, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {color};
                border-radius: 14px;
                padding: 10px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(100)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        lbl_icon = QLabel(icon)
        lbl_icon.setFont(QFont("Segoe UI Emoji", 24))
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_icon.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(lbl_icon)

        self._lbl_val = QLabel(value)
        self._lbl_val.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        self._lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_val.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(self._lbl_val)

        lbl_label = QLabel(label)
        lbl_label.setFont(QFont("Arial", 10))
        lbl_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_label.setStyleSheet("color: rgba(255,255,255,200); background: transparent;")
        layout.addWidget(lbl_label)

        self.setLayout(layout)

    def update_value(self, value: str):
        self._lbl_val.setText(value)


# ── Canvas grafic ─────────────────────────────────────────────────────────────

class ChartCanvas(FigureCanvas):
    def __init__(self, figsize=(5, 3), dpi=90):
        self.fig = Figure(figsize=figsize, dpi=dpi, facecolor=C_BG)
        super().__init__(self.fig)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)


# ── Worker QThread pentru fetch date DB ──────────────────────────────────────

class _DashWorker(QObject):
    """Execută query-urile SQL de dashboard pe un QThread separat."""
    done  = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, db, user_id: int):
        super().__init__()
        self._db  = db
        self._uid = user_id

    def run(self):
        try:
            self.done.emit(self._db.get_dashboard_data(self._uid))
        except Exception as exc:
            self.error.emit(str(exc))


# ── Dashboard principal ───────────────────────────────────────────────────────

class DashboardScreen(QWidget):
    """Ecran dashboard progres utilizator."""

    back_requested = pyqtSignal()   # navigare inapoi la login/meniu

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._user_id: Optional[int] = None
        self._user_name: str = ""
        self._setup_ui()

    # ── Initializare UI ───────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(20, 15, 20, 15)
        root.setSpacing(15)

        # Header
        header = QHBoxLayout()
        btn_back = QPushButton("← Inapoi")
        btn_back.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        btn_back.setStyleSheet(
            "QPushButton { background-color: #7f8c8d; color: white; "
            "border-radius: 8px; padding: 6px 16px; }"
        )
        btn_back.clicked.connect(self.back_requested.emit)
        header.addWidget(btn_back)

        self._lbl_title = QLabel("Progres")
        self._lbl_title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self._lbl_title.setStyleSheet("color: #2c3e50;")
        header.addWidget(self._lbl_title, stretch=1)

        self._btn_export = QPushButton("📄 Export PDF")
        self._btn_export.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._btn_export.setStyleSheet(
            "QPushButton { background-color: #8e44ad; color: white; "
            "border-radius: 8px; padding: 6px 16px; }"
        )
        self._btn_export.clicked.connect(self._export_pdf)
        header.addWidget(self._btn_export)
        root.addLayout(header)

        # ── Scroll area cu tot continutul ────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        content = QWidget()
        content.setStyleSheet(f"background-color: {C_BG};")
        self._content_layout = QVBoxLayout()
        self._content_layout.setSpacing(18)

        # ── Stat cards ────────────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        self._card_lectii   = StatCard("📚", "0", "Lectii parcurse", C_PRIMARY)
        self._card_scor     = StatCard("⭐", "0%", "Scor mediu", C_SUCCESS)
        self._card_streak   = StatCard("🔥", "0", "Zile la rand", C_WARN)
        self._card_timp     = StatCard("⏱", "0 min", "Timp total", C_PURPLE)

        for c in [self._card_lectii, self._card_scor, self._card_streak, self._card_timp]:
            cards_row.addWidget(c)
        self._content_layout.addLayout(cards_row)

        # ── Grafic scor in timp ────────────────────────────────────────────────
        gb_scor = QGroupBox("Scor in timp (ultimele 30 sesiuni)")
        gb_scor.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gb_scor.setStyleSheet(self._card_style())
        vb = QVBoxLayout()
        self._canvas_scor = ChartCanvas(figsize=(7, 3))
        vb.addWidget(self._canvas_scor)
        gb_scor.setLayout(vb)
        self._content_layout.addWidget(gb_scor)

        # ── Grafic lectii per subiect ──────────────────────────────────────────
        mid_row = QHBoxLayout()
        mid_row.setSpacing(14)

        gb_lectii = QGroupBox("Lectii completate per subiect")
        gb_lectii.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gb_lectii.setStyleSheet(self._card_style())
        vb2 = QVBoxLayout()
        self._canvas_lectii = ChartCanvas(figsize=(4, 3))
        vb2.addWidget(self._canvas_lectii)
        gb_lectii.setLayout(vb2)
        mid_row.addWidget(gb_lectii, stretch=1)

        gb_skill = QGroupBox("Stapanire abilitati")
        gb_skill.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gb_skill.setStyleSheet(self._card_style())
        vb3 = QVBoxLayout()
        self._canvas_skill = ChartCanvas(figsize=(4, 3))
        vb3.addWidget(self._canvas_skill)
        gb_skill.setLayout(vb3)
        mid_row.addWidget(gb_skill, stretch=1)

        self._content_layout.addLayout(mid_row)

        # ── Top 5 lectii grele ────────────────────────────────────────────────
        gb_hard = QGroupBox("Lectii cu cel mai mic scor (necesita atentie)")
        gb_hard.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gb_hard.setStyleSheet(self._card_style())
        vb4 = QVBoxLayout()
        self._canvas_hard = ChartCanvas(figsize=(7, 2.5))
        vb4.addWidget(self._canvas_hard)
        gb_hard.setLayout(vb4)
        self._content_layout.addWidget(gb_hard)

        # ── Zone slabe: abilități cu mastery < 50% ───────────────────────────
        gb_weak = QGroupBox("⚠️  Zone slabe — abilitati ce necesita practica suplimentara")
        gb_weak.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gb_weak.setStyleSheet(
            "QGroupBox { background: white; border-radius: 10px; "
            "border: 2px solid #e74c3c; padding: 12px 10px 10px 10px; "
            "font-weight: bold; color: #c0392b; }"
        )
        vb_weak = QVBoxLayout()
        vb_weak.setSpacing(6)
        self._weak_skills_layout = QVBoxLayout()
        self._weak_skills_layout.setSpacing(4)
        self._lbl_no_weak = QLabel("✅ Nicio abilitate slabă! Continuă tot asa!")
        self._lbl_no_weak.setFont(QFont("Arial", 11))
        self._lbl_no_weak.setStyleSheet("color: #27ae60; padding: 4px;")
        self._lbl_no_weak.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._weak_skills_layout.addWidget(self._lbl_no_weak)
        vb_weak.addLayout(self._weak_skills_layout)
        gb_weak.setLayout(vb_weak)
        self._content_layout.addWidget(gb_weak)

        # ── Radar "Profil de Competențe" ─────────────────────────────────────
        gb_radar = QGroupBox("🕸️  Profil de Competențe")
        gb_radar.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        gb_radar.setStyleSheet(self._card_style())
        vb_radar = QVBoxLayout()
        self._canvas_radar = ChartCanvas(figsize=(4, 4))
        vb_radar.addWidget(self._canvas_radar)
        gb_radar.setLayout(vb_radar)
        self._content_layout.addWidget(gb_radar)

        self._content_layout.addStretch()
        content.setLayout(self._content_layout)
        scroll.setWidget(content)
        root.addWidget(scroll, stretch=1)
        self.setLayout(root)

    # ── Date & actualizare ────────────────────────────────────────────────────

    def load_user(self, user_id: int, user_name: str = ""):
        """Incarca datele pentru un utilizator si redeseneaza toate graficele."""
        self._user_id   = user_id
        self._user_name = user_name
        self._lbl_title.setText(f"Progres — {user_name}")
        self._refresh()

    def _refresh(self):
        """Lansează fetch-ul SQL pe un QThread separat pentru a nu bloca UI-ul."""
        if self._user_id is None:
            return
        # Evită lansări multiple simultane
        if hasattr(self, "_dash_thread") and self._dash_thread.isRunning():
            return

        self._dash_thread = QThread()
        self._dash_worker = _DashWorker(self._db, self._user_id)
        self._dash_worker.moveToThread(self._dash_thread)
        self._dash_thread.started.connect(self._dash_worker.run)
        self._dash_worker.done.connect(self._on_data_ready)
        self._dash_worker.done.connect(self._dash_thread.quit)
        self._dash_worker.error.connect(
            lambda e: print(f"⚠️  Dashboard DB error: {e}")
        )
        self._dash_thread.start()

    def _on_data_ready(self, data: dict):
        """Apelat pe main thread după ce QThread-ul a terminat fetch-ul SQL."""
        uid = self._user_id

        # Convertim dict-urile în tuple-uri (compatibil cu metodele de desenare existente)
        sessions = [
            (r["score"], r["duration_s"], r["started_at"], r["lesson_id"], r["subject"])
            for r in data["sessions"]
        ]
        progress = [
            (r["lesson_id"], r["best_score"], r["passed"], r["subject"])
            for r in data["progress"]
        ]
        skills = [
            (r["skill_code"], r["mastery"], r["name"])
            for r in data["skills"]
        ]

        # ── Calcul statistici generale ────────────────────────────────────────
        n_lectii  = sum(1 for p in progress if p[2])  # passed
        valid_sc  = [s[0] for s in sessions if s and s[0] is not None]
        avg_scor  = (sum(valid_sc) / len(valid_sc) * 100) if valid_sc else 0
        total_min = sum(s[1] for s in sessions if s and s[1] is not None) // 60 if sessions else 0
        streak    = self._calc_streak(sessions)

        self._card_lectii.update_value(str(n_lectii))
        self._card_scor.update_value(f"{avg_scor:.0f}%")
        self._card_streak.update_value(str(streak))
        self._card_timp.update_value(f"{total_min} min")

        # ── Competency profile (din skills extinse din DB) ────────────────────
        skills_ext = [
            {
                "skill_code":   r["skill_code"],
                "mastery":      r["mastery"],
                "avg_time":     r.get("avg_time") or 30.0,
                "skill_streak": r.get("skill_streak") or 0,
            }
            for r in data["skills"]
        ]
        competency_profile = self._calc_competency_profile_from(skills_ext)

        # ── Grafice (fiecare izolat: o eroare de grafic nu blochează celelalte) ─
        for draw_fn, arg in [
            (self._draw_score_timeline,     sessions),
            (self._draw_lessons_by_subject, progress),
            (self._draw_skill_bars,         skills),
            (self._draw_hard_lessons,       progress),
            (self._draw_weak_skills,        skills),
            (self._draw_competency_radar,   competency_profile),
        ]:
            try:
                draw_fn(arg)
            except Exception as _e:
                print(f"⚠️  Dashboard chart error in {draw_fn.__name__}: {_e}")

    # ── Grafic 1: scor in timp ────────────────────────────────────────────────

    def _draw_score_timeline(self, sessions):
        fig = self._canvas_scor.fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor("#f8fafc")
        fig.patch.set_facecolor(C_BG)

        if not sessions:
            ax.text(0.5, 0.5, "Nicio sesiune inregistrata", ha="center", va="center",
                    transform=ax.transAxes, color="#aaa", fontsize=12)
            self._canvas_scor.draw()
            return

        last30 = sessions[-30:]
        dates  = []
        scores = []
        subj_labels = []
        for s in last30:
            score, dur, started_at, lid, subj = s
            if score is None:          # sărim sesiunile fără scor
                continue
            try:
                dt = datetime.fromisoformat(started_at[:16])
                dates.append(dt)
            except Exception:
                dates.append(None)
            scores.append(score * 100)
            subj_labels.append(subj or "")

        if not scores:
            ax.text(0.5, 0.5, "Nicio sesiune cu scor inregistrata", ha="center", va="center",
                    transform=ax.transAxes, color="#aaa", fontsize=12)
            self._canvas_scor.draw()
            return

        # x_vals: datetime dacă disponibil, altfel index — aceeași lungime ca scores
        x_vals = [d if d is not None else i for i, d in enumerate(dates)]

        # Separam pe subiecte
        math_x, math_y = [], []
        ro_x, ro_y = [], []
        for x, sc, subj in zip(x_vals, scores, subj_labels):
            if "Mat" in subj:
                math_x.append(x); math_y.append(sc)
            else:
                ro_x.append(x); ro_y.append(sc)

        if math_x:
            ax.plot(math_x, math_y, "o-", color="#3498db", linewidth=2, markersize=5, label="Matematica")
        if ro_x:
            ax.plot(ro_x, ro_y, "s-", color="#e67e22", linewidth=2, markersize=5, label="Romana")

        ax.axhline(y=70, color="#e74c3c", linestyle="--", alpha=0.5, linewidth=1.2)
        ax.set_ylim(0, 105)
        ax.set_ylabel("Scor (%)", fontsize=9)
        ax.tick_params(axis="x", rotation=25, labelsize=7)
        ax.tick_params(axis="y", labelsize=8)
        ax.legend(fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.4)

        fig.tight_layout()
        self._canvas_scor.draw()

    # ── Grafic 2: lectii per subiect ─────────────────────────────────────────

    def _draw_lessons_by_subject(self, progress):
        fig = self._canvas_lectii.fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor("#f8fafc")
        fig.patch.set_facecolor(C_BG)

        if not progress:
            ax.text(0.5, 0.5, "Nicio lectie\nparcursa", ha="center", va="center",
                    transform=ax.transAxes, color="#aaa", fontsize=11)
            self._canvas_lectii.draw()
            return

        counts: dict[str, dict] = {}
        for lid, score, passed, subj in progress:
            s = subj or "Altele"
            if s not in counts:
                counts[s] = {"passed": 0, "failed": 0}
            if passed:
                counts[s]["passed"] += 1
            else:
                counts[s]["failed"] += 1

        subjects = list(counts.keys())
        passed   = [counts[s]["passed"] for s in subjects]
        failed   = [counts[s]["failed"] for s in subjects]

        x = np.arange(len(subjects))
        w = 0.35
        colors_p = [SUBJECT_COLORS.get(s, C_SUCCESS) for s in subjects]

        bars_p = ax.bar(x - w/2, passed, w, color=colors_p, alpha=0.85, label="Trecute")
        bars_f = ax.bar(x + w/2, failed, w, color="#e74c3c", alpha=0.7, label="In lucru")

        ax.set_xticks(x)
        ax.set_xticklabels([s.split()[0] for s in subjects], fontsize=8)
        ax.set_ylabel("Lectii", fontsize=9)
        ax.legend(fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))

        fig.tight_layout()
        self._canvas_lectii.draw()

    # ── Grafic 3: skill mastery bars ─────────────────────────────────────────

    def _draw_skill_bars(self, skills):
        fig = self._canvas_skill.fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor("#f8fafc")
        fig.patch.set_facecolor(C_BG)

        if not skills:
            ax.text(0.5, 0.5, "Nicio abilitate\ninregistrata", ha="center", va="center",
                    transform=ax.transAxes, color="#aaa", fontsize=11)
            self._canvas_skill.draw()
            return

        # Top 8 abilitati (excludem cele cu mastery None)
        top = [s for s in skills if s[1] is not None][:8]
        if not top:
            ax.text(0.5, 0.5, "Nicio abilitate\ninregistrata", ha="center", va="center",
                    transform=ax.transAxes, color="#aaa", fontsize=11)
            self._canvas_skill.draw()
            return
        names   = [s[2] or s[0] for s in top]
        mastery = [min(100, s[1] * 100) for s in top]

        colors = [C_SUCCESS if m >= 70 else C_WARN if m >= 40 else C_DANGER for m in mastery]

        y = np.arange(len(names))
        bars = ax.barh(y, mastery, color=colors, alpha=0.85, height=0.6)

        # Etichete
        for bar, m in zip(bars, mastery):
            ax.text(min(m + 2, 95), bar.get_y() + bar.get_height() / 2,
                    f"{m:.0f}%", va="center", ha="left", fontsize=8, color="#333")

        ax.set_yticks(y)
        ax.set_yticklabels([n[:20] for n in names], fontsize=7)
        ax.set_xlim(0, 105)
        ax.set_xlabel("Stapanire (%)", fontsize=9)
        ax.axvline(70, color="#e74c3c", linestyle="--", alpha=0.5, linewidth=1)
        ax.spines[["top", "right"]].set_visible(False)
        ax.invert_yaxis()

        fig.tight_layout()
        self._canvas_skill.draw()

    # ── Grafic 4: lectii grele ────────────────────────────────────────────────

    def _draw_hard_lessons(self, progress):
        fig = self._canvas_hard.fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor("#f8fafc")
        fig.patch.set_facecolor(C_BG)

        # Lectii cu scor sub 80% (excludem None și 0)
        hard = [(lid, sc, subj) for lid, sc, passed, subj in progress
                if sc is not None and 0 < sc < 0.8]
        hard.sort(key=lambda x: x[1])
        hard = hard[:6]

        if not hard:
            ax.text(0.5, 0.5, "Bravo! Toate lectiile au scor bun.", ha="center", va="center",
                    transform=ax.transAxes, color=C_SUCCESS, fontsize=11, fontweight="bold")
            self._canvas_hard.draw()
            return

        # Fetch titles
        conn = self._db.conn
        lids = [h[0] for h in hard]
        rows = conn.execute(
            f"SELECT id, title FROM lessons WHERE id IN ({','.join('?'*len(lids))})",
            lids
        ).fetchall()
        title_map = {r[0]: r[1] for r in rows}

        names  = [title_map.get(h[0], f"Lectia {h[0]}")[:28] for h in hard]
        scores = [h[1] * 100 for h in hard]
        colors = [SUBJECT_COLORS.get(h[2], C_DANGER) for h in hard]

        x = np.arange(len(names))
        bars = ax.bar(x, scores, color=colors, alpha=0.8, width=0.6)
        ax.axhline(80, color="#2ecc71", linestyle="--", alpha=0.6, linewidth=1.2)
        ax.set_xticks(x)
        ax.set_xticklabels(names, fontsize=7, rotation=15, ha="right")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Scor (%)", fontsize=9)
        ax.spines[["top", "right"]].set_visible(False)

        for bar, sc in zip(bars, scores):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                    f"{sc:.0f}%", ha="center", va="bottom", fontsize=8, color="#333")

        fig.tight_layout()
        self._canvas_hard.draw()

    # ── Zone slabe: abilitati cu mastery < 50% ───────────────────────────────

    def _draw_weak_skills(self, skills):
        """Afișează lista abilităților cu mastery sub 50%, sortate crescător."""
        # Curăță lista anterioară
        while self._weak_skills_layout.count():
            item = self._weak_skills_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        weak = sorted(
            [s for s in skills if s[1] is not None and s[1] < 0.5],
            key=lambda x: x[1],   # cel mai slab primul
        )

        if not weak:
            lbl_ok = QLabel("✅ Nicio abilitate slabă! Continuă tot asa!")
            lbl_ok.setFont(QFont("Arial", 11))
            lbl_ok.setStyleSheet("color: #27ae60; padding: 4px;")
            lbl_ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._weak_skills_layout.addWidget(lbl_ok)
            return

        for skill_code, mastery, name in weak[:10]:   # max 10
            pct = int((mastery or 0) * 100)
            label = name or skill_code

            color = C_DANGER if pct < 30 else C_WARN
            emoji = "🔴" if pct < 30 else "🟠"

            row = QHBoxLayout()
            row.setSpacing(8)

            lbl_name = QLabel(f"{emoji}  {label}")
            lbl_name.setFont(QFont("Arial", 10))
            lbl_name.setStyleSheet("color: #2c3e50;")
            lbl_name.setMinimumWidth(200)
            row.addWidget(lbl_name, stretch=1)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(pct)
            bar.setFixedHeight(16)
            bar.setTextVisible(True)
            bar.setFormat(f"{pct}%")
            bar.setStyleSheet(
                f"QProgressBar {{ border-radius: 7px; background: #f0f0f0; text-align: center; font-size: 10px; }}"
                f"QProgressBar::chunk {{ background: {color}; border-radius: 7px; }}"
            )
            row.addWidget(bar, stretch=2)

            container = QWidget()
            container.setLayout(row)
            self._weak_skills_layout.addWidget(container)

    # ── Radar: Profil de Competențe ───────────────────────────────────────────

    def _calc_competency_profile_from(self, skills_ext: list) -> dict:
        """Calculează 5 scoruri [0..1] pentru radar chart din date pre-fetch-uite."""
        buckets: dict[str, list] = {
            "Matematică":   [],
            "Română":       [],
            "Logică/EN":    [],
            "Viteză":       [],
            "Consistență":  [],
        }
        for r in skills_ext:
            code    = (r.get("skill_code") or "").upper()
            mastery = float(r.get("mastery") or 0.0)
            avg_t   = float(r.get("avg_time") or 30.0)
            streak  = int(r.get("skill_streak") or 0)

            if code.startswith("MATH"):
                buckets["Matematică"].append(mastery)
            elif code.startswith("RO"):
                buckets["Română"].append(mastery)
            elif code.startswith("EN") or "LOGIC" in code:
                buckets["Logică/EN"].append(mastery)

            # Viteză: <15s → 1.0, >60s → 0.0 (linear clamp)
            speed = max(0.0, min(1.0, 1.0 - (avg_t - 15.0) / 45.0))
            buckets["Viteză"].append(speed)

            # Consistență: streak 10+ → 1.0
            buckets["Consistență"].append(min(1.0, streak / 10.0))

        return {k: (sum(v) / len(v) if v else 0.0) for k, v in buckets.items()}

    def _draw_competency_radar(self, profile: dict):
        """Radar/spider chart — profilul de competențe al elevului."""
        import numpy as np
        fig = self._canvas_radar.fig
        fig.clear()

        if not any(v > 0 for v in profile.values()):
            ax = fig.add_subplot(111)
            ax.text(0.5, 0.5, "Date insuficiente\nFă mai multe exerciții!",
                    ha="center", va="center", fontsize=11, color="#7f8c8d")
            ax.axis("off")
            fig.patch.set_facecolor(C_BG)
            self._canvas_radar.draw()
            return

        labels = list(profile.keys())
        values = list(profile.values())
        N = len(labels)

        angles = [n / float(N) * 2 * np.pi for n in range(N)]
        # închide poligonul
        plot_angles = angles + angles[:1]
        plot_values = values + values[:1]

        ax = fig.add_subplot(111, polar=True)
        ax.set_facecolor("#f0f4f8")
        fig.patch.set_facecolor(C_BG)

        # Grilă
        ax.set_ylim(0, 1)
        ax.set_yticks([0.25, 0.5, 0.75, 1.0])
        ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=7, color="#95a5a6")
        ax.set_xticks(angles)
        ax.set_xticklabels(labels, fontsize=9, color="#2c3e50")
        ax.grid(color="#bdc3c7", linestyle="--", alpha=0.5)

        # Zona colorată
        ax.plot(plot_angles, plot_values, "o-", linewidth=2, color="#3498db")
        ax.fill(plot_angles, plot_values, alpha=0.25, color="#3498db")

        ax.set_title("Profil Competențe", fontsize=11, fontweight="bold",
                     pad=18, color="#2c3e50")

        fig.tight_layout()
        self._canvas_radar.draw()

    # ── Streak calc ───────────────────────────────────────────────────────────

    def _calc_streak(self, sessions) -> int:
        if not sessions:
            return 0
        dates = set()
        for s in sessions:
            try:
                d = datetime.fromisoformat(s[2][:10]).date()
                dates.add(d)
            except Exception:
                pass
        if not dates:
            return 0
        today = datetime.now().date()
        streak = 0
        day = today
        while day in dates:
            streak += 1
            day -= timedelta(days=1)
        return streak

    # ── Export PDF ────────────────────────────────────────────────────────────

    def _make_summary_page(self, pdf) -> None:
        """Generează prima pagină text a PDF-ului cu rezumatul săptămânal."""
        uid  = self._user_id
        conn = self._db.conn
        now  = datetime.now()
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        sessions  = conn.execute(
            "SELECT score, duration_s, started_at, lesson_id "
            "FROM sessions WHERE user_id=? ORDER BY started_at",
            (uid,)
        ).fetchall()
        progress  = conn.execute(
            "SELECT p.lesson_id, p.best_score, p.passed, l.title, l.subject "
            "FROM progress p JOIN lessons l ON l.id=p.lesson_id "
            "WHERE p.user_id=?",
            (uid,)
        ).fetchall()

        # Sesiuni din ultimele 7 zile
        recent = [s for s in sessions if s[2] and s[2][:10] >= week_ago]

        n_lectii  = sum(1 for p in progress if p[2])
        valid_sc  = [s[0] for s in sessions if s and s[0] is not None]
        avg_scor  = (sum(valid_sc) / len(valid_sc) * 100) if valid_sc else 0
        total_min = sum(s[1] for s in sessions if s and s[1] is not None) // 60 if sessions else 0
        streak    = self._calc_streak(sessions)

        recent_min  = sum(s[1] for s in recent if s and s[1] is not None) // 60
        recent_sess = len(recent)

        hard_lessons = sorted(
            [p for p in progress if p[1] is not None and p[1] < 0.7],
            key=lambda p: p[1]
        )[:5]

        # Construiește figura A4
        fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
        ax  = fig.add_axes([0.08, 0.05, 0.84, 0.90])
        ax.axis("off")

        y = 0.97
        def txt(text, dy=0.04, size=11, weight="normal", color="black"):
            nonlocal y
            ax.text(0.0, y, text, transform=ax.transAxes,
                    fontsize=size, fontweight=weight, color=color,
                    va="top", wrap=True)
            y -= dy

        txt(f"Raport progres — {self._user_name}", dy=0.06, size=18, weight="bold")
        txt(f"Generat: {now.strftime('%d %B %Y, %H:%M')}",
            dy=0.05, size=11, color="#666666")

        # Linie separator
        ax.plot([0, 1], [y + 0.01, y + 0.01], transform=ax.transAxes,
                color="#3498db", linewidth=1.5, clip_on=False)
        y -= 0.02

        txt("REZUMAT GENERAL", dy=0.04, size=13, weight="bold", color="#2c3e50")
        txt(f"  • Lecții finalizate:   {n_lectii}", size=11)
        txt(f"  • Scor mediu:          {avg_scor:.0f}%", size=11)
        txt(f"  • Timp total studiu:   {total_min} minute", size=11)
        txt(f"  • Streak curent:       {streak} zile consecutive", size=11)
        y -= 0.02

        txt("ULTIMA SĂPTĂMÂNĂ", dy=0.04, size=13, weight="bold", color="#2c3e50")
        txt(f"  • Sesiuni de studiu:   {recent_sess}", size=11)
        txt(f"  • Timp petrecut:       {recent_min} minute", size=11)
        y -= 0.02

        if hard_lessons:
            txt("LECȚII CU DIFICULTĂȚI (scor < 70%)",
                dy=0.04, size=13, weight="bold", color="#e74c3c")
            for p in hard_lessons:
                txt(f"  • {p[3]}  ({p[4]})  —  scor: {p[1]*100:.0f}%", size=11)
        else:
            txt("LECȚII CU DIFICULTĂȚI", dy=0.04, size=13,
                weight="bold", color="#27ae60")
            txt("  Nicio lecție cu scor sub 70%. Excelent! 🎉", size=11)

        y -= 0.02
        ax.plot([0, 1], [y + 0.01, y + 0.01], transform=ax.transAxes,
                color="#d0d8e4", linewidth=0.8, clip_on=False)
        y -= 0.02
        txt("Avatar Tutor — Raport generat automat",
            dy=0.03, size=9, color="#aaaaaa")

        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    def _export_pdf(self):
        if self._user_id is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salveaza raport PDF",
            f"raport_{self._user_name}_{datetime.now().strftime('%Y%m%d')}.pdf",
            "PDF (*.pdf)"
        )
        if not path:
            return

        try:
            from matplotlib.backends.backend_pdf import PdfPages
        except ImportError:
            QMessageBox.warning(self, "Eroare", "matplotlib lipseste.")
            return

        with PdfPages(path) as pdf:
            # Pagina 0: rezumat text (nou)
            self._make_summary_page(pdf)

            # Pagini grafice
            for canvas in [self._canvas_scor, self._canvas_lectii,
                           self._canvas_skill, self._canvas_hard]:
                pdf.savefig(canvas.fig, bbox_inches="tight")

        QMessageBox.information(self, "Export", f"Raport salvat:\n{path}")

    # ── Helper ────────────────────────────────────────────────────────────────

    def _card_style(self) -> str:
        return """
            QGroupBox {
                background-color: white;
                border: 2px solid #d0d8e4;
                border-radius: 12px;
                margin-top: 12px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px; padding: 0 6px;
                color: #2c3e50; font-weight: bold;
            }
        """
