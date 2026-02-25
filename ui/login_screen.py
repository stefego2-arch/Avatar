"""
ui/login_screen.py
==================
LoginScreen — ecran de selectare elev și materie.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from database import Database
from stars_widget import StarsBadge
from ui.styles import BTN_PRIMARY


class LoginScreen(QWidget):
    """Ecran de selectare elev si materie."""
    login_done      = pyqtSignal(dict, str, int)  # user dict, subject, lesson_id
    dashboard_open  = pyqtSignal(int, str)         # user_id, user_name

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self._setup_ui()
        self._load_users()

    def _setup_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(60, 40, 60, 40)
        main_layout.setSpacing(20)

        # Header cu badge stele
        header_row = QHBoxLayout()
        header_row.addStretch()
        self._stars_badge = StarsBadge()
        header_row.addWidget(self._stars_badge)
        main_layout.addLayout(header_row)

        # Titlu
        title = QLabel("Avatar Tutor")
        title.setFont(QFont("Arial", 42, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #2c3e50;")
        main_layout.addWidget(title)

        subtitle = QLabel("Matematică • Limba Română • Clasele 1-5")
        subtitle.setFont(QFont("Arial", 14))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #7f8c8d;")
        main_layout.addWidget(subtitle)

        main_layout.addSpacing(20)

        # Selector elev
        elev_box = QGroupBox("👤 Cine ești?")
        elev_layout = QVBoxLayout()
        self._user_combo = QComboBox()
        self._user_combo.setFont(QFont("Arial", 16))
        self._user_combo.setMinimumHeight(45)
        self._user_combo.currentIndexChanged.connect(self.refresh_stars_badge)
        elev_layout.addWidget(self._user_combo)

        # Adaugă elev nou
        h = QHBoxLayout()
        self._new_name = QLineEdit()
        self._new_name.setPlaceholderText("Nume elev nou...")
        self._new_name.setFont(QFont("Arial", 14))
        self._new_name.setMinimumHeight(40)
        h.addWidget(self._new_name)

        self._new_grade = QComboBox()
        self._new_grade.addItems([
            "Clasa 1", "Clasa 2", "Clasa 3", "Clasa 4", "Clasa 5",
            "Clasa 6 (Engleză)", "Clasa 7 (Engleză)",
            "Clasa 8 (Engleză)", "Clasa 9 (Engleză)",
        ])
        self._new_grade.setFont(QFont("Arial", 14))
        self._new_grade.setMinimumHeight(40)
        h.addWidget(self._new_grade)

        btn_add = QPushButton("➕ Adaugă")
        btn_add.setMinimumHeight(40)
        btn_add.setStyleSheet(BTN_PRIMARY)
        btn_add.clicked.connect(self._add_user)
        h.addWidget(btn_add)

        elev_layout.addLayout(h)
        elev_box.setLayout(elev_layout)
        main_layout.addWidget(elev_box)

        # Selector materie
        materie_box = QGroupBox("📚 Ce vrei să înveți astăzi?")
        materie_layout = QHBoxLayout()
        materie_layout.setSpacing(20)

        btn_math = QPushButton("🔢\nMatematică")
        btn_math.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        btn_math.setMinimumHeight(120)
        btn_math.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #3498db,stop:1 #2980b9);
                color: white; border-radius: 15px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        btn_math.clicked.connect(lambda: self._start("Matematică"))
        materie_layout.addWidget(btn_math)

        btn_ro = QPushButton("📖\nLimba Română")
        btn_ro.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        btn_ro.setMinimumHeight(120)
        btn_ro.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #e74c3c,stop:1 #c0392b);
                color: white; border-radius: 15px;
            }
            QPushButton:hover { background-color: #c0392b; }
        """)
        btn_ro.clicked.connect(lambda: self._start("Limba Română"))
        materie_layout.addWidget(btn_ro)

        btn_en = QPushButton("🇬🇧\nLimba Engleză")
        btn_en.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        btn_en.setMinimumHeight(120)
        btn_en.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #27ae60,stop:1 #1e8449);
                color: white; border-radius: 15px;
            }
            QPushButton:hover { background-color: #1e8449; }
        """)
        btn_en.clicked.connect(lambda: self._start("Limba Engleză"))
        materie_layout.addWidget(btn_en)

        materie_box.setLayout(materie_layout)
        main_layout.addWidget(materie_box)

        # Buton dashboard progres
        btn_progres = QPushButton("📊 Vezi Progresul")
        btn_progres.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        btn_progres.setMinimumHeight(46)
        btn_progres.setStyleSheet(
            "QPushButton { background-color: #8e44ad; color: white; "
            "border-radius: 10px; padding: 8px 20px; } "
            "QPushButton:hover { background-color: #7d3c98; }"
        )
        btn_progres.clicked.connect(self._open_dashboard)
        main_layout.addWidget(btn_progres)

        # Status sistem
        self._status = QLabel("Sistem gata")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setStyleSheet("color: #27ae60; font-size: 12px;")
        main_layout.addWidget(self._status)

        # ElevenLabs quota indicator (ascuns pana la primul fetch)
        self._quota_label = QLabel("")
        self._quota_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._quota_label.setStyleSheet("color: #7f8c8d; font-size: 11px;")
        self._quota_label.hide()
        main_layout.addWidget(self._quota_label)

        main_layout.addStretch()
        self.setLayout(main_layout)

    def _load_users(self):
        self._user_combo.clear()
        for u in self.db.get_all_users():
            self._user_combo.addItem(
                f"{u['name']} (Clasa {u['grade']})",
                userData=u
            )

    def load_md_and_play(self, path: str):
        """Încarcă un fișier .md și îl redă chunk cu chunk."""
        self.avatar.md_player.load_file(path)
        self.avatar.md_player.play_current()

    def _add_user(self):
        name = self._new_name.text().strip()
        if not name:
            return
        grade = self._new_grade.currentIndex() + 1
        self.db.create_user(name, age=grade + 5, grade=grade)
        self._new_name.clear()
        self._load_users()
        # Selectează utilizatorul nou creat
        for i in range(self._user_combo.count()):
            if self._user_combo.itemText(i).startswith(name):
                self._user_combo.setCurrentIndex(i)
                break

    def _start(self, subject: str):
        idx = self._user_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "Eroare", "Selectează un elev!")
            return

        user = self._user_combo.itemData(idx)
        if not user:
            return

        # Găsește prima lecție nepromovată
        next_lesson = self.db.get_next_lesson(user["id"], user["grade"], subject)
        if not next_lesson:
            # Toate promovate — ia prima
            lessons = self.db.get_lessons(user["grade"], subject)
            if not lessons:
                # Fallback pentru Engleză: caută la clasele 6-9 (engleza e grade-agnostică)
                if subject == "Limba Engleză":
                    for eng_grade in [6, 7, 8, 9]:
                        if eng_grade == user["grade"]:
                            continue
                        eng_lesson = self.db.get_next_lesson(user["id"], eng_grade, subject)
                        if not eng_lesson:
                            eng_lessons = self.db.get_lessons(eng_grade, subject)
                            eng_lesson = eng_lessons[0] if eng_lessons else None
                        if eng_lesson:
                            self.db.update_user_active(user["id"])
                            self.login_done.emit(user, subject, int(eng_lesson["id"]))
                            return
                    QMessageBox.warning(self, "Info",
                        "Lecțiile de Limba Engleză nu au fost importate.\n\n"
                        "Rulează din terminal:\n"
                        "  python import_solutions_english.py --level all")
                    return
                QMessageBox.warning(self, "Info",
                    f"Nu există lecții pentru {subject} clasa {user['grade']}.\n"
                    "Adaugă lecții în database.py → _seed_lessons_...")
                return
            next_lesson = lessons[0]

        self.db.update_user_active(user["id"])
        self.login_done.emit(user, subject, int(next_lesson["id"]))

    def refresh_stars_badge(self):
        """Actualizeaza badge-ul cu stelee si streak-ul utilizatorului curent."""
        idx = self._user_combo.currentIndex()
        if idx < 0:
            return
        user = self._user_combo.itemData(idx)
        if user:
            stats = self.db.get_user_stars(user["id"])
            self._stars_badge.update_stats(
                stats.get("total_stars", 0),
                stats.get("streak_days", 0)
            )

    def _open_dashboard(self):
        idx = self._user_combo.currentIndex()
        if idx < 0:
            QMessageBox.warning(self, "Eroare", "Selecteaza un elev!")
            return
        user = self._user_combo.itemData(idx)
        if user:
            self.dashboard_open.emit(user["id"], user["name"])

    def update_status(self, text: str, color: str = "#27ae60"):
        self._status.setText(text)
        self._status.setStyleSheet(f"color: {color}; font-size: 12px;")

    def update_quota(self, chars_used: int, chars_limit: int):
        """Afișează cota ElevenLabs consumată."""
        remaining = chars_limit - chars_used
        pct_used  = chars_used / chars_limit * 100 if chars_limit > 0 else 0
        if pct_used >= 90:
            color = "#e74c3c"
            icon  = "⚠️"
        elif pct_used >= 70:
            color = "#f39c12"
            icon  = "🔶"
        else:
            color = "#27ae60"
            icon  = "🎙️"
        bar_filled = int(pct_used / 5)          # 0-20 blocks
        bar_empty  = 20 - bar_filled
        bar = "█" * bar_filled + "░" * bar_empty
        self._quota_label.setText(
            f"{icon} ElevenLabs: {chars_used:,} / {chars_limit:,} chars  "
            f"[{bar}]  {remaining:,} rămase"
        )
        self._quota_label.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._quota_label.show()
