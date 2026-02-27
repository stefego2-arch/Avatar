"""
daily_quest.py
==============
DailyQuestScreen — ecranul "Misiunea de Azi".

Afișează:
  • exercițiile scadente din SRS (spaced repetition)
  • 1 exercițiu "Boss Fight" din tier 4 (dacă există)
  • streak zilnic + progresul misiunii

Integrare în main.py (exemplu):
    from daily_quest import DailyQuestScreen
    self._daily_quest = DailyQuestScreen(self.db)
    self._daily_quest.quest_start_requested.connect(self._on_quest_start)
    self._stack.addWidget(self._daily_quest)  # index 3

Afișare din login:
    btn_quest.clicked.connect(lambda: self._show_daily_quest())

    def _show_daily_quest(self):
        idx = self._login_screen._user_combo.currentIndex()
        user = self._login_screen._user_combo.itemData(idx)
        if user:
            self._daily_quest.load_for_user(user)
            self._stack.setCurrentIndex(3)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from database import Database


# ─────────────────────────────────────────────────────────────────────────────
# Helper widget: un exercițiu din misiune
# ─────────────────────────────────────────────────────────────────────────────

class QuestExerciseCard(QFrame):
    """Card vizual pentru un exercițiu din misiunea zilnică."""

    def __init__(self, ex: dict, is_boss: bool = False, parent=None):
        super().__init__(parent)
        self.exercise = ex
        self.is_boss = is_boss
        self._done = False
        self._setup_ui()

    def _setup_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        if self.is_boss:
            self.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 #2c0a3e, stop:1 #4a1560);
                    border: 2px solid #9b59b6;
                    border-radius: 12px;
                    padding: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame {
                    background-color: white;
                    border: 2px solid #d0d8e4;
                    border-radius: 12px;
                    padding: 8px;
                }
            """)
        self.setMinimumHeight(70)

        layout = QHBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)

        # Icon
        icon = QLabel("💀" if self.is_boss else "📌")
        icon.setFont(QFont("Segoe UI Emoji", 20))
        icon.setFixedWidth(36)
        layout.addWidget(icon)

        # Text
        text_col = QVBoxLayout()
        enunt = (self.exercise.get("enunt") or "")[:80]
        if len(self.exercise.get("enunt", "")) > 80:
            enunt += "…"

        lbl_enunt = QLabel(enunt)
        lbl_enunt.setFont(QFont("Arial", 12, QFont.Weight.Bold if self.is_boss else QFont.Weight.Normal))
        lbl_enunt.setWordWrap(True)
        if self.is_boss:
            lbl_enunt.setStyleSheet("color: #e8d5f5;")
        text_col.addWidget(lbl_enunt)

        subject = self.exercise.get("subject_name", "")
        grade = self.exercise.get("grade_name", "")
        meta = f"{subject} · {grade}" if subject else ""
        if meta:
            lbl_meta = QLabel(meta)
            lbl_meta.setFont(QFont("Arial", 9))
            lbl_meta.setStyleSheet("color: #7f8c8d;" if not self.is_boss else "color: #c39bd3;")
            text_col.addWidget(lbl_meta)

        layout.addLayout(text_col, stretch=1)

        # Badge dificultate
        tier = int(self.exercise.get("difficulty_tier") or self.exercise.get("dificultate") or 1)
        tier_colors = {1: "#27ae60", 2: "#3498db", 3: "#e67e22", 4: "#9b59b6"}
        tier_labels = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "💀 BOSS"}
        badge = QLabel(tier_labels.get(tier, "⭐"))
        badge.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        badge.setStyleSheet(
            f"background-color: {tier_colors.get(tier, '#95a5a6')}; "
            "color: white; border-radius: 8px; padding: 3px 7px;"
        )
        layout.addWidget(badge)

        # Checkmark (dacă e rezolvat)
        self._check_lbl = QLabel("✅" if self._done else "")
        self._check_lbl.setFont(QFont("Segoe UI Emoji", 16))
        self._check_lbl.setFixedWidth(28)
        layout.addWidget(self._check_lbl)

        self.setLayout(layout)

    def mark_done(self):
        self._done = True
        self._check_lbl.setText("✅")
        self.setStyleSheet(self.styleSheet().replace("white", "#f0fff4").replace("#2c0a3e", "#1a3a1a"))


# ─────────────────────────────────────────────────────────────────────────────
# DailyQuestScreen
# ─────────────────────────────────────────────────────────────────────────────

class DailyQuestScreen(QWidget):
    """Ecranul 'Misiunea de Azi'.

    Semnale:
        quest_start_requested(user_id, lesson_id) — utilizatorul vrea să înceapă
            lecția care conține exercițiul scadent
        back_requested — înapoi la login
    """
    quest_start_requested = pyqtSignal(int, int)   # user_id, lesson_id
    back_requested = pyqtSignal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._user: Optional[dict] = None
        self._quest_exercises: list[dict] = []
        self._boss_exercise: Optional[dict] = None
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main = QVBoxLayout()
        main.setContentsMargins(30, 20, 30, 20)
        main.setSpacing(16)

        # ── Header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()

        btn_back = QPushButton("← Înapoi")
        btn_back.setStyleSheet(
            "QPushButton { background: #ecf0f1; border-radius: 8px; padding: 8px 14px; }"
            "QPushButton:hover { background: #d5dbdb; }"
        )
        btn_back.clicked.connect(self.back_requested.emit)
        header.addWidget(btn_back)
        header.addStretch()

        self._lbl_date = QLabel(date.today().strftime("🗓️  %d %B %Y"))
        self._lbl_date.setFont(QFont("Arial", 11))
        self._lbl_date.setStyleSheet("color: #7f8c8d;")
        header.addWidget(self._lbl_date)
        main.addLayout(header)

        # ── Titlu ───────────────────────────────────────────────────────────
        lbl_title = QLabel("🎯 Misiunea de Azi")
        lbl_title.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #2c3e50;")
        main.addWidget(lbl_title)

        self._lbl_subtitle = QLabel("Se încarcă…")
        self._lbl_subtitle.setFont(QFont("Arial", 13))
        self._lbl_subtitle.setStyleSheet("color: #7f8c8d;")
        main.addWidget(self._lbl_subtitle)

        # ── Progres misiune ──────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setMinimumHeight(22)
        self._progress_bar.setFormat("Misiune %p% completă")
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #d0d8e4; border-radius: 10px;
                background: #f0f4f8; text-align: center;
                color: #2c3e50; font-weight: bold; font-size: 11px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 #f39c12, stop:1 #e74c3c);
                border-radius: 8px;
            }
        """)
        main.addWidget(self._progress_bar)

        # ── Streak + Stele ──────────────────────────────────────────────────
        stats_row = QHBoxLayout()

        self._lbl_streak = QLabel("🔥 Streak: —")
        self._lbl_streak.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self._lbl_streak.setStyleSheet(
            "background-color: #fff3cd; border-radius: 10px; padding: 8px 16px; color: #856404;"
        )
        stats_row.addWidget(self._lbl_streak)

        self._lbl_stars = QLabel("⭐ Stele: —")
        self._lbl_stars.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self._lbl_stars.setStyleSheet(
            "background-color: #d1f0fb; border-radius: 10px; padding: 8px 16px; color: #0c5460;"
        )
        stats_row.addWidget(self._lbl_stars)

        stats_row.addStretch()
        main.addLayout(stats_row)

        # ── Exerciții SRS ───────────────────────────────────────────────────
        srs_box = QGroupBox("📌 De recuperat (Spaced Repetition)")
        srs_box.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self._srs_layout = QVBoxLayout()
        self._srs_layout.setSpacing(8)
        self._lbl_no_srs = QLabel("🎉 Niciun exercițiu de recuperat azi! Excelent!")
        self._lbl_no_srs.setFont(QFont("Arial", 12))
        self._lbl_no_srs.setStyleSheet("color: #27ae60; padding: 10px;")
        self._lbl_no_srs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._srs_layout.addWidget(self._lbl_no_srs)
        srs_box.setLayout(self._srs_layout)

        # Scroll dacă sunt multe exerciții
        srs_scroll = QScrollArea()
        srs_scroll.setWidgetResizable(True)
        srs_scroll.setMaximumHeight(280)
        srs_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        srs_inner = QWidget()
        srs_inner.setLayout(self._srs_layout)
        srs_scroll.setWidget(srs_inner)
        srs_outer = QVBoxLayout()
        srs_outer.addWidget(srs_scroll)
        srs_box.setLayout(srs_outer)
        main.addWidget(srs_box)

        # ── Boss Fight ───────────────────────────────────────────────────────
        self._boss_box = QGroupBox("💀 Boss Fight — Exercițiu de Elită")
        self._boss_box.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self._boss_box.setStyleSheet("""
            QGroupBox {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #1a0a2e, stop:1 #2d1554);
                border: 2px solid #9b59b6;
                border-radius: 12px;
                color: #e8d5f5;
            }
            QGroupBox::title { color: #c39bd3; }
        """)
        self._boss_layout = QVBoxLayout()
        self._lbl_no_boss = QLabel("Boss disponibil după ce termini câteva lecții!")
        self._lbl_no_boss.setFont(QFont("Arial", 11))
        self._lbl_no_boss.setStyleSheet("color: #8e7aaa; padding: 8px;")
        self._lbl_no_boss.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._boss_layout.addWidget(self._lbl_no_boss)
        self._boss_box.setLayout(self._boss_layout)
        main.addWidget(self._boss_box)

        # ── Buton Start ──────────────────────────────────────────────────────
        self._btn_start = QPushButton("🚀 Începe Misiunea!")
        self._btn_start.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self._btn_start.setMinimumHeight(60)
        self._btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #e74c3c, stop:1 #c0392b);
                color: white; border-radius: 14px;
            }
            QPushButton:hover { background-color: #c0392b; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self._btn_start.clicked.connect(self._start_quest)
        self._btn_start.setEnabled(False)
        main.addWidget(self._btn_start)

        # Buton "Lecție nouă" — dacă nu sunt exerciții SRS
        self._btn_new_lesson = QPushButton("📚 Lecție Nouă în schimb")
        self._btn_new_lesson.setFont(QFont("Arial", 13))
        self._btn_new_lesson.setMinimumHeight(46)
        self._btn_new_lesson.setStyleSheet(
            "QPushButton { background-color: #3498db; color: white; "
            "border-radius: 10px; padding: 8px; } "
            "QPushButton:hover { background-color: #2980b9; }"
        )
        self._btn_new_lesson.clicked.connect(self.back_requested.emit)
        self._btn_new_lesson.hide()
        main.addWidget(self._btn_new_lesson)

        main.addStretch()
        self.setLayout(main)

    # ── Date ──────────────────────────────────────────────────────────────────

    def load_for_user(self, user: dict):
        """Încarcă misiunea zilnică pentru utilizatorul dat."""
        self._user = user
        user_id = user.get("id", 0)
        grade = user.get("grade", 1)

        # Actualizează data
        self._lbl_date.setText(date.today().strftime("🗓️  %d %B %Y"))

        # Streak + stele
        try:
            stats = self.db.get_user_stars(user_id)
            streak = stats.get("streak_days", 0)
            stars = stats.get("total_stars", 0)
            self._lbl_streak.setText(f"🔥 Streak: {streak} {'zi' if streak == 1 else 'zile'}")
            self._lbl_stars.setText(f"⭐ Stele: {stars}")
        except Exception:
            pass

        # Exerciții SRS scadente (toate lecțiile, nu doar una)
        try:
            srs_exercises = self._get_all_due_exercises(user_id, limit=5)
        except Exception:
            srs_exercises = []

        # Boss fight: exercițiu cu tier 4 sau dificultate 4 din lecțiile trecute
        try:
            boss = self._get_boss_exercise(user_id, grade)
        except Exception:
            boss = None

        self._quest_exercises = srs_exercises
        self._boss_exercise = boss

        self._populate_ui(srs_exercises, boss)

    def _get_all_due_exercises(self, user_id: int, limit: int = 5) -> list[dict]:
        """Returnează exercițiile SRS scadente din TOATE lecțiile, nu doar una."""
        today = date.today().isoformat()
        rows = self.db.conn.execute(
            """SELECT e.*, l.title AS lesson_title, l.subject AS subject_name,
                      ('Clasa ' || l.grade) AS grade_name, l.id AS lesson_id_ref
               FROM exercises e
               JOIN user_exercise_stats s ON s.exercise_id = e.id
               JOIN lessons l ON l.id = e.lesson_id
               WHERE s.user_id = ?
                 AND s.retry_after IS NOT NULL
                 AND s.retry_after <= ?
               ORDER BY s.wrong_count DESC, e.dificultate ASC
               LIMIT ?""",
            (user_id, today, limit),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            import json
            if d.get("choices"):
                try: d["choices"] = json.loads(d["choices"])
                except Exception: pass
            result.append(d)
        return result

    def _get_boss_exercise(self, user_id: int, grade: int) -> Optional[dict]:
        """Caută un exercițiu de elită (tier 4 / dificultate 4) din lecțiile studiate."""
        rows = self.db.conn.execute(
            """SELECT e.*, l.title AS lesson_title, l.subject AS subject_name,
                      ('Clasa ' || l.grade) AS grade_name, l.id AS lesson_id_ref
               FROM exercises e
               JOIN lessons l ON l.id = e.lesson_id
               JOIN progress p ON p.lesson_id = l.id AND p.user_id = ?
               WHERE (e.difficulty_tier = 4 OR e.dificultate = 4)
                 AND p.passed = 1
               ORDER BY RANDOM()
               LIMIT 1""",
            (user_id,),
        ).fetchall()
        if rows:
            d = dict(rows[0])
            import json
            if d.get("choices"):
                try: d["choices"] = json.loads(d["choices"])
                except Exception: pass
            return d

        # Fallback: cel mai greu exercițiu din lecțiile trecute
        rows2 = self.db.conn.execute(
            """SELECT e.*, l.title AS lesson_title, l.subject AS subject_name,
                      ('Clasa ' || l.grade) AS grade_name, l.id AS lesson_id_ref
               FROM exercises e
               JOIN lessons l ON l.id = e.lesson_id
               JOIN progress p ON p.lesson_id = l.id AND p.user_id = ?
               WHERE p.passed = 1 AND e.dificultate >= 3
               ORDER BY e.dificultate DESC, RANDOM()
               LIMIT 1""",
            (user_id,),
        ).fetchall()
        if rows2:
            d = dict(rows2[0])
            import json
            if d.get("choices"):
                try: d["choices"] = json.loads(d["choices"])
                except Exception: pass
            return d
        return None

    def _populate_ui(self, srs: list[dict], boss: Optional[dict]):
        """Populează UI-ul cu exercițiile găsite."""
        # Curăță widget-urile existente
        while self._srs_layout.count():
            item = self._srs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self._boss_layout.count():
            item = self._boss_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total = len(srs) + (1 if boss else 0)

        if srs:
            self._lbl_subtitle.setText(
                f"Ai {len(srs)} exerciți{'u' if len(srs)==1 else 'i'} de recuperat "
                f"{'+ 1 Boss Fight' if boss else ''}. Poți face asta!"
            )
            for ex in srs:
                card = QuestExerciseCard(ex, is_boss=False)
                self._srs_layout.addWidget(card)
            self._btn_start.setEnabled(True)
            self._btn_new_lesson.hide()
        else:
            no_srs = QLabel("🎉 Niciun exercițiu de recuperat azi! Excelent!")
            no_srs.setFont(QFont("Arial", 12))
            no_srs.setStyleSheet("color: #27ae60; padding: 10px;")
            no_srs.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._srs_layout.addWidget(no_srs)
            if boss:
                self._lbl_subtitle.setText("Ești la zi! Ești gata pentru Boss Fight?")
                self._btn_start.setEnabled(True)
                self._btn_new_lesson.hide()
            else:
                self._lbl_subtitle.setText("Ești complet la zi! Începe o lecție nouă.")
                self._btn_start.setEnabled(False)
                self._btn_new_lesson.show()

        if boss:
            boss_card = QuestExerciseCard(boss, is_boss=True)
            self._boss_layout.addWidget(boss_card)

            lbl_boss_hint = QLabel(
                "💡 Boss Fight-ul te testează cu cel mai greu exercițiu disponibil. "
                "Rezolvă-l și primești bonus de stele!"
            )
            lbl_boss_hint.setFont(QFont("Arial", 9))
            lbl_boss_hint.setWordWrap(True)
            lbl_boss_hint.setStyleSheet("color: #8e7aaa; padding: 4px 8px;")
            self._boss_layout.addWidget(lbl_boss_hint)
        else:
            no_boss = QLabel("Boss disponibil după ce termini câteva lecții!")
            no_boss.setFont(QFont("Arial", 11))
            no_boss.setStyleSheet("color: #8e7aaa; padding: 8px;")
            no_boss.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._boss_layout.addWidget(no_boss)

        # Progres bar
        self._progress_bar.setValue(0)
        self._progress_bar.setMaximum(max(1, total))

        # Update buton
        if total > 0:
            self._btn_start.setText(
                f"🚀 Începe Misiunea! ({total} exerciți{'u' if total==1 else 'i'})"
            )

    def _start_quest(self):
        """Pornește misiunea: navighează la prima lecție cu exerciții scadente."""
        if not self._user:
            return

        user_id = self._user.get("id", 0)

        # Găsește lesson_id din primul exercițiu SRS sau Boss
        lesson_id = None
        if self._quest_exercises:
            lesson_id = self._quest_exercises[0].get("lesson_id_ref") or \
                        self._quest_exercises[0].get("lesson_id")
        elif self._boss_exercise:
            lesson_id = self._boss_exercise.get("lesson_id_ref") or \
                        self._boss_exercise.get("lesson_id")

        if lesson_id:
            self.quest_start_requested.emit(int(user_id), int(lesson_id))
        else:
            self.back_requested.emit()

    def update_progress(self, completed: int, total: int):
        """Actualizează bara de progres pe măsură ce exercițiile se rezolvă."""
        if total > 0:
            pct = int(completed / total * 100)
            self._progress_bar.setValue(pct)
            if pct >= 100:
                self._btn_start.setText("✅ Misiune completă! Bravo!")
                self._btn_start.setStyleSheet(
                    "QPushButton { background-color: #27ae60; color: white; "
                    "border-radius: 14px; font-size: 16px; font-weight: bold; }"
                )