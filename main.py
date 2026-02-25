import sys
import os
import io
import json
import time
import logging
import traceback
import faulthandler
from pathlib import Path
from datetime import datetime
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget


import subprocess
# Pornește serverul automat în background
subprocess.Popen(["python", "-m", "http.server", "8000"], cwd="./assets/avatar")

# ── Logging structurat — scrie în avatar_tutor.log + consolă ─────────────────
_LOG_FILE = Path(__file__).parent / "avatar_tutor.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("avatar_tutor")

# faulthandler: prinde crash-uri C++ (SIGSEGV, abort) și scrie stack trace
_FAULT_LOG = open(Path(__file__).parent / "crash_native.log", "a", encoding="utf-8")
faulthandler.enable(file=_FAULT_LOG)
log.info("Avatar Tutor pornit — faulthandler activ, log: %s", _LOG_FILE)

# Forteaza UTF-8 la stdout/stderr pentru a evita erori cp1252 cu emoji pe Windows
if sys.platform.startswith("win") and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Global exception hook — prinde orice excepție neprinsă și o afișează ──────
def _global_excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log.critical("Excepție neprinsă:\n%s", msg)
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        app = QApplication.instance()
        if app:
            QMessageBox.critical(None, "Eroare fatală — Avatar Tutor", msg[:3000])
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _global_excepthook

# Prinde și excepțiile din thread-uri daemon (tts, lesson engine etc.)
import threading
def _thread_excepthook(args):
    _global_excepthook(args.exc_type, args.exc_value, args.exc_traceback)
threading.excepthook = _thread_excepthook

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QStackedWidget, QTextEdit,
    QFrame, QDialog, QLineEdit, QComboBox, QGroupBox, QScrollArea,
    QSizePolicy, QMessageBox, QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QFont, QPixmap, QColor, QPalette, QImage



# ─── Importuri locale ────────────────────────────────────────────────────────

import numpy as np
try:
    import sounddevice as _sd
    _SD_OK = True
except Exception:
    _SD_OK = False

from database import Database
from deepseek_client import DeepSeekClient
from tts_engine import TTSEngine
from attention_monitor import AttentionMonitor, AttentionState
from lesson_engine import LessonEngine, LessonState, QuestionResult
from md_lesson_player import MDLessonPlayer
from md_library import ManualLibrary, load_md_chunks
from voice_input import MicButton, CommandListener
from dashboard import DashboardScreen
from stars_widget import StarAwardDialog, StarsBadge


# ─── Stiluri globale ─────────────────────────────────────────────────────────

STYLE_MAIN = """
QMainWindow { background-color: #f0f4f8; }
QWidget { font-family: Arial, sans-serif; }

QPushButton {
    border-radius: 10px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:disabled { background-color: #ccc; color: #888; }

QGroupBox {
    border: 2px solid #d0d8e4;
    border-radius: 10px;
    margin-top: 10px;
    padding: 10px;
    background-color: white;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #2c3e50;
    font-weight: bold;
}

QLineEdit {
    border: 2px solid #d0d8e4;
    border-radius: 8px;
    padding: 6px;
    font-size: 18px;
}
QLineEdit:focus { border: 2px solid #3498db; }

QProgressBar {
    border: 2px solid #d0d8e4;
    border-radius: 8px;
    text-align: center;
    background-color: #f0f4f8;
}
QProgressBar::chunk { background-color: #3498db; border-radius: 6px; }
"""

BTN_PRIMARY = """
    QPushButton {
        background-color: #3498db; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #2980b9; }
"""
BTN_SUCCESS = """
    QPushButton {
        background-color: #27ae60; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #229954; }
"""
BTN_WARNING = """
    QPushButton {
        background-color: #f39c12; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #e67e22; }
"""
BTN_DANGER = """
    QPushButton {
        background-color: #e74c3c; color: white;
        border-radius: 10px; padding: 10px;
    }
    QPushButton:hover { background-color: #c0392b; }
"""


# ═══════════════════════════════════════════════════════════════════════════
# WIDGET AVATAR (imagine + expresie)
# ═══════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════
# ECRAN LOGIN / SELECTARE ELEV
# ═══════════════════════════════════════════════════════════════════════════

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
                # Fallback pentru Engleză: caută la clasele 6-9 (engleза e grade-agnostică)
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


# ═══════════════════════════════════════════════════════════════════════════
# WIDGET EXERCIȚIU
# ═══════════════════════════════════════════════════════════════════════════

class ExerciseWidget(QWidget):
    """Afișează un exercițiu cu input și butoane hint."""
    answer_submitted = pyqtSignal(str, dict)  # răspuns, timp_sec
    hint_requested   = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._start_time = time.time()
        self._edit_count = 0
        self._current_exercise = None
        self._is_composition: bool = False
        self._drafts: dict = {}
        self._setup_ui()
        # Conecteaza butonul microfon dupa ce UI-ul e gata
        self._mic_ctrl = MicButton(
            button=self._btn_mic,
            line_edit=self._answer_input,
            model_size="base",   # tiny/base/small/medium - se descarca automat
        )

    def setup_avatar(self):
        """Configurează și returnează containerul pentru avatarul 3D."""
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtCore import QUrl

        self.avatar_view = QWebEngineView()
        # Setăm o înălțime fixă pentru a nu împinge restul elementelor afară din ecran
        self.avatar_view.setFixedHeight(300)
        self.avatar_view.setUrl(QUrl("http://localhost:8000/viewer.html"))
        self.avatar_view.page().setBackgroundColor(Qt.GlobalColor.transparent)

        # Eliminăm marginile inutile ale webview-ului
        self.avatar_view.setStyleSheet("background: transparent; border-radius: 15px;")
        return self.avatar_view

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # Header: număr exercițiu + progress
        h = QHBoxLayout()
        self._lbl_nr = QLabel("Exercițiu 1/8")
        self._lbl_nr.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self._lbl_nr.setStyleSheet("color: #7f8c8d;")
        h.addWidget(self._lbl_nr)
        h.addStretch()

        self._lbl_phase = QLabel("PRACTICĂ")
        self._lbl_phase.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._lbl_phase.setStyleSheet(
            "background-color: #3498db; color: white;"
            "padding: 4px 10px; border-radius: 8px;"
        )
        h.addWidget(self._lbl_phase)
        layout.addLayout(h)

        self._progress = QProgressBar()
        self._progress.setMaximum(100)
        self._progress.setValue(0)
        self._progress.setMinimumHeight(18)
        self._progress.setFormat("%p%")
        self._progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #b2dfdb;
                border-radius: 8px;
                text-align: center;
                background-color: #e8f5e9;
                color: #2e7d32;
                font-size: 10px;
            }
            QProgressBar::chunk {
                background-color: #27ae60;
                border-radius: 7px;
            }
        """)
        layout.addWidget(self._progress)

        # Enunț
        self._enunt_box = QGroupBox("📝 Problema")
        enunt_layout = QVBoxLayout()
        self._lbl_enunt = QLabel()
        self._lbl_enunt.setFont(QFont("Arial", 26, QFont.Weight.Bold))
        self._lbl_enunt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_enunt.setWordWrap(True)
        self._lbl_enunt.setMinimumHeight(120)
        self._lbl_enunt.setStyleSheet(
            "background-color: #fafbfc; border-radius: 10px; padding: 20px;"
        )
        enunt_layout.addWidget(self._lbl_enunt)

        # Variante (multiple choice) — ascunse implicit
        self._choices_widget = QWidget()
        choices_layout = QHBoxLayout()
        choices_layout.setSpacing(10)
        self._choice_buttons = []
        for _ in range(4):
            btn = QPushButton()
            btn.setFont(QFont("Arial", 14, QFont.Weight.Bold))
            btn.setMinimumHeight(55)
            btn.setStyleSheet(BTN_PRIMARY)
            btn.clicked.connect(lambda checked, b=btn: self._submit_choice(b.text()))
            choices_layout.addWidget(btn)
            self._choice_buttons.append(btn)
        self._choices_widget.setLayout(choices_layout)
        self._choices_widget.hide()
        enunt_layout.addWidget(self._choices_widget)

        self._enunt_box.setLayout(enunt_layout)
        layout.addWidget(self._enunt_box)

        # ── Spațiu de lucru (calcule, necunoscute, schițe) ───────────────────
        self._scratch_label = QLabel("✏️  Spațiu de lucru — scrie calculele și necunoscutele:")
        self._scratch_label.setFont(QFont("Arial", 11))
        self._scratch_label.setStyleSheet("color: #555; padding: 2px 0 1px 0;")
        layout.addWidget(self._scratch_label)

        # Butoane template pentru scratchpad (x=?, adunare, scădere, pas)
        self._scratch_templates = QWidget()
        tmpl_layout = QHBoxLayout()
        tmpl_layout.setContentsMargins(0, 0, 0, 4)
        tmpl_layout.setSpacing(6)
        for lbl, tmpl in [
            ("x = ?",     "x = ?\n"),
            ("A + B = ?", "  __ + __ = __\n"),
            ("A − B = ?", "  __ - __ = __\n"),
            ("Pas →",     "Pas 1: \n"),
        ]:
            tb = QPushButton(lbl)
            tb.setFont(QFont("Arial", 9))
            tb.setFixedHeight(24)
            tb.setStyleSheet(
                "QPushButton { background:#fffacd; border:1px solid #c8a030; "
                "border-radius:4px; padding:2px 8px; color:#555; } "
                "QPushButton:hover { background:#fff0a0; }"
            )
            tb.clicked.connect(lambda checked, t=tmpl: self._insert_scratch_template(t))
            tmpl_layout.addWidget(tb)
        tmpl_layout.addStretch()
        self._scratch_templates.setLayout(tmpl_layout)
        layout.addWidget(self._scratch_templates)

        self._scratch_pad = QTextEdit()
        self._scratch_pad.setPlaceholderText(
            "Scrie aici calculele, necunoscutele, schița...\n"
            "Exemplu:\n  Necunoscuta: x = ?\n  x + 5 = 12 → x = 12 - 5 = 7"
        )
        self._scratch_pad.setFont(QFont("Arial", 13))
        self._scratch_pad.setMinimumHeight(200)
        self._scratch_pad.setMaximumHeight(350)
        self._scratch_pad.setStyleSheet(
            "QTextEdit { background-color: #fffef0; border: 1px solid #c8b96e; "
            "border-radius: 8px; padding: 8px; }"
        )
        layout.addWidget(self._scratch_pad)
        self._scratch_pad.textChanged.connect(self._on_scratch_draft_save)

        # Input răspuns text
        self._input_widget = QWidget()
        inp_layout = QVBoxLayout()
        lbl_final = QLabel("✅  Răspunsul final:")
        lbl_final.setFont(QFont("Arial", 11))
        lbl_final.setStyleSheet("color: #555; padding: 2px 0 1px 0;")
        inp_layout.addWidget(lbl_final)
        self._answer_input = QLineEdit()
        self._answer_input.setPlaceholderText("Scrie răspunsul final...")
        self._answer_input.setFont(QFont("Arial", 22))
        self._answer_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._answer_input.setMinimumHeight(60)
        self._answer_input.returnPressed.connect(self._submit_text)
        self._edit_count = 0
        self._answer_input.textEdited.connect(self._on_text_edited)
        inp_layout.addWidget(self._answer_input)
        self._input_widget.setLayout(inp_layout)
        layout.addWidget(self._input_widget)

        # Butoane acțiuni
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._btn_hint = QPushButton("💡 Hint")
        self._btn_hint.setMinimumHeight(50)
        self._btn_hint.setFont(QFont("Arial", 13))
        self._btn_hint.setStyleSheet(BTN_WARNING)
        self._btn_hint.clicked.connect(self.hint_requested.emit)
        btn_layout.addWidget(self._btn_hint)

        # Buton microfon (stilizat de MicButton dupa initializare)
        self._btn_mic = QPushButton("🎤 Vorbeste")
        self._btn_mic.setMinimumHeight(50)
        self._btn_mic.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self._btn_mic.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; "
            "border-radius: 10px; padding: 8px 14px; font-weight: bold; }"
        )
        btn_layout.addWidget(self._btn_mic)

        self._btn_submit = QPushButton("✅ Verifică")
        self._btn_submit.setMinimumHeight(50)
        self._btn_submit.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self._btn_submit.setStyleSheet(BTN_SUCCESS)
        self._btn_submit.clicked.connect(self._submit_text)
        btn_layout.addWidget(self._btn_submit, stretch=2)

        layout.addLayout(btn_layout)

        # Feedback
        self._feedback_frame = QFrame()
        self._feedback_frame.setMinimumHeight(70)
        self._feedback_frame.setStyleSheet(
            "background-color: #f0f4f8; border-radius: 10px; padding: 10px;"
        )
        fb_layout = QHBoxLayout()
        self._feedback_icon = QLabel()
        self._feedback_icon.setFont(QFont("Segoe UI Emoji", 32))
        fb_layout.addWidget(self._feedback_icon)
        self._feedback_text = QLabel()
        self._feedback_text.setFont(QFont("Arial", 14))
        self._feedback_text.setWordWrap(True)
        fb_layout.addWidget(self._feedback_text, stretch=1)
        self._feedback_frame.setLayout(fb_layout)
        self._feedback_frame.hide()
        layout.addWidget(self._feedback_frame)

        layout.addStretch()
        self.setLayout(layout)

    def show_exercise(self, ex: dict, idx: int, total: int):
        """Afișează un exercițiu nou."""
        self._current_exercise = ex
        self._start_time = time.time()
        self._edit_count = 0
        self._feedback_frame.hide()

        # Header
        self._lbl_nr.setText(f"Exercițiu {idx}/{total}")
        self._progress.setValue(int((idx - 1) / total * 100))

        # Faza
        phase_labels = {
            "pretest": ("PRE-TEST", "#9b59b6"),
            "practice": ("PRACTICĂ", "#3498db"),
            "posttest": ("TEST FINAL", "#e67e22"),
        }
        phase = ex.get("phase", "practice")
        plabel, pcolor = phase_labels.get(phase, ("PRACTICĂ", "#3498db"))
        self._lbl_phase.setText(plabel)
        self._lbl_phase.setStyleSheet(
            f"background-color: {pcolor}; color: white;"
            "padding: 4px 10px; border-radius: 8px;"
        )

        # Enunț
        self._lbl_enunt.setText(ex.get("enunt", ""))

        # Tip exercițiu
        ex_type = ex.get("type", "text")
        choices = ex.get("choices", [])

        if ex_type == "choice" and choices:
            self._choices_widget.show()
            self._input_widget.hide()
            self._btn_submit.hide()
            # Ascunde spațiul de lucru la multiple choice
            self._scratch_label.hide()
            self._scratch_templates.hide()
            self._scratch_pad.hide()
            for i, btn in enumerate(self._choice_buttons):
                if i < len(choices):
                    btn.setText(str(choices[i]))
                    btn.show()
                    btn.setEnabled(True)
                    btn.setStyleSheet(BTN_PRIMARY)
                else:
                    btn.hide()
        else:
            self._choices_widget.hide()
            self._input_widget.show()
            self._btn_submit.show()
            self._answer_input.clear()
            self._answer_input.setEnabled(True)
            self._btn_submit.setEnabled(True)

            # ─ Detectăm exerciții de compunere ──────────────────────────────
            enunt_lower = ex.get("enunt", "").lower()
            _COMP_KW = ("compun", "compozi", "povestir", "descriere",
                        "text din câteva", "câteva enunțuri",
                        "alcătuiește un text", "redactează", "scrie un text")
            self._is_composition = any(kw in enunt_lower for kw in _COMP_KW)

            if self._is_composition:
                # Scratchpad devine zona de răspuns principal
                self._answer_input.hide()
                self._scratch_pad.setMaximumHeight(16777215)   # unlimited
                self._scratch_label.setText("✏️  Scrie compunerea ta:")
                self._scratch_label.show()
                self._scratch_templates.hide()
                self._scratch_pad.show()
                # Restaurare draft dacă există
                ex_id = str(ex.get("id", ""))
                if ex_id and ex_id in self._drafts:
                    self._scratch_pad.setPlainText(self._drafts[ex_id])
                else:
                    self._scratch_pad.clear()
                self._scratch_pad.setPlaceholderText(
                    "Scrie compunerea ta aici...\nPoți folosi mai multe rânduri."
                )
                QTimer.singleShot(100, self._scratch_pad.setFocus)
            else:
                self._is_composition = False
                self._answer_input.show()
                self._scratch_pad.setMaximumHeight(350)
                self._scratch_label.setText(
                    "✏️  Spațiu de lucru — scrie calculele și necunoscutele:"
                )
                # Arată și curăță spațiul de lucru la exerciții text obișnuite
                self._scratch_label.show()
                self._scratch_templates.show()
                self._scratch_pad.show()
                self._scratch_pad.clear()
                QTimer.singleShot(100, self._answer_input.setFocus)

        # Hints disponibile
        hints_available = any(ex.get(f"hint{i}") for i in range(1, 4))
        self._btn_hint.setEnabled(hints_available)

    def show_result(self, result: QuestionResult):
        """Afișează feedback pentru răspunsul dat."""
        if result.is_correct:
            self._feedback_icon.setText("✅")
            self._feedback_frame.setStyleSheet(
                "background-color: #d4edda; border: 2px solid #27ae60; border-radius: 10px; padding: 10px;"
            )
            self._feedback_text.setText(result.feedback)
        else:
            self._feedback_icon.setText("❌")
            self._feedback_frame.setStyleSheet(
                "background-color: #fdecea; border: 2px solid #e74c3c; border-radius: 10px; padding: 10px;"
            )
            self._feedback_text.setText(result.feedback)

        self._feedback_frame.show()

        # Dezactivează input
        self._answer_input.setEnabled(False)
        self._btn_submit.setEnabled(False)
        for btn in self._choice_buttons:
            btn.setEnabled(False)

    def show_hint(self, hint_text: str, hint_nr: int):
        """Afișează un hint."""
        icons = {1: "💡", 2: "🔍", 3: "🎯"}
        self._feedback_icon.setText(icons.get(hint_nr, "💡"))
        self._feedback_text.setText(f"Indiciu {hint_nr}: {hint_text}")
        self._feedback_frame.setStyleSheet(
            "background-color: #fff3cd; border: 2px solid #f39c12; border-radius: 10px; padding: 10px;"
        )
        self._feedback_frame.show()

    def _insert_scratch_template(self, text: str):
        """Inserează un template de calcul în scratchpad la poziția curentă."""
        from PyQt6.QtGui import QTextCursor
        cursor = self._scratch_pad.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self._scratch_pad.setTextCursor(cursor)
        self._scratch_pad.setFocus()

    def activate_scratchpad(self, task_text: str = ""):
        """Afișează și focusează scratchpad-ul activ (apelat de engine la chunk TASK)."""
        self._scratch_label.show()
        self._scratch_templates.show()
        self._scratch_pad.show()
        self._scratch_pad.clear()
        if task_text:
            self._scratch_pad.setPlaceholderText(
                "Scrie pașii de rezolvare...\n"
                "Exemplu:  x = ?   sau   3 + __ = 5   sau   Pas 1: ..."
            )
        self._scratch_pad.setFocus()

    def _on_scratch_draft_save(self):
        """Salvează automat textul de compunere ca draft la fiecare modificare."""
        if not self._is_composition or not self._current_exercise:
            return
        ex_id = str(self._current_exercise.get("id", ""))
        if ex_id:
            self._drafts[ex_id] = self._scratch_pad.toPlainText()

    def _on_text_edited(self, _):
        # proxy pentru "ezitare": multe editari = nesiguranță
        try:
            self._edit_count += 1
        except Exception:
            self._edit_count = 1

    def _submit_text(self):
        if self._is_composition:
            ans = self._scratch_pad.toPlainText().strip()
        else:
            ans = self._answer_input.text().strip()
        if not ans:
            if self._is_composition:
                self._scratch_pad.setFocus()
            else:
                self._answer_input.setFocus()
            return
        elapsed = time.time() - self._start_time
        self.answer_submitted.emit(ans, {"time_sec": elapsed, "edits": float(getattr(self, "_edit_count", 0))})

    def _submit_choice(self, choice: str):
        elapsed = time.time() - self._start_time
        self.answer_submitted.emit(choice, {"time_sec": elapsed, "edits": float(getattr(self, "_edit_count", 0))})


# ═══════════════════════════════════════════════════════════════════════════
# PANOU AVATAR + ATENȚIE (stânga)
# ═══════════════════════════════════════════════════════════════════════════

class AvatarPanel(QWidget):
    """Panoul din stânga cu avatarul, status atenție și mesaje."""

    def __init__(self, tts):
        super().__init__()
        self.setFixedWidth(300)
        self.tts = tts
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # ── Avatar 3D (WebEngine → viewer.html) ───────────────────────────
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtCore import QUrl
        self.avatar_view = QWebEngineView()
        self.avatar_view.setFixedHeight(320)
        self.avatar_view.setUrl(QUrl("http://localhost:8000/viewer.html"))
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


# ═══════════════════════════════════════════════════════════════════════════
# PANOUL PRINCIPAL DE LECȚIE (dreapta)
# ═══════════════════════════════════════════════════════════════════════════

class LessonPanel(QWidget):
    """Panoul principal care schimbă conținut în funcție de faza lecției."""
    next_chunk_requested = pyqtSignal()
    free_question_asked  = pyqtSignal(str)
    pause_requested      = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)

        # Titlu lecție
        header = QHBoxLayout()
        self._lbl_lesson_title = QLabel("—")
        self._lbl_lesson_title.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self._lbl_lesson_title.setStyleSheet("color: #2c3e50;")
        header.addWidget(self._lbl_lesson_title)
        header.addStretch()

        self._lbl_phase_big = QLabel("")
        self._lbl_phase_big.setFont(QFont("Arial", 13, QFont.Weight.Bold))
        self._lbl_phase_big.setStyleSheet("color: #7f8c8d;")
        header.addWidget(self._lbl_phase_big)

        btn_pause = QPushButton("⏸️ Pauză")
        btn_pause.setStyleSheet(BTN_WARNING)
        btn_pause.setMaximumWidth(90)
        btn_pause.clicked.connect(self.pause_requested.emit)
        header.addWidget(btn_pause)

        layout.addLayout(header)

        # Stack cu conținut
        self._stack = QStackedWidget()

        # ── Page 0: Text lecție ──
        self._page_text = QWidget()
        pt_layout = QVBoxLayout()

        self._text_area = QTextEdit()
        self._text_area.setReadOnly(True)
        self._text_area.setFont(QFont("Arial", 15))
        self._text_area.setStyleSheet(
            "background-color: white; border: 2px solid #d0d8e4; border-radius: 10px; padding: 10px;"
        )
        pt_layout.addWidget(self._text_area)

        btn_row = QHBoxLayout()
        # Întrebare liberă
        self._free_q_input = QLineEdit()
        self._free_q_input.setPlaceholderText("Ai o întrebare? Scrie aici...")
        self._free_q_input.setFont(QFont("Arial", 13))
        self._free_q_input.setMinimumHeight(40)
        self._free_q_input.returnPressed.connect(self._ask_free_question)
        btn_row.addWidget(self._free_q_input, stretch=3)

        btn_ask = QPushButton("🙋 Întreabă")
        btn_ask.setStyleSheet(BTN_PRIMARY)
        btn_ask.setMinimumHeight(40)
        btn_ask.clicked.connect(self._ask_free_question)
        btn_row.addWidget(btn_ask)

        self._btn_next_chunk = QPushButton("✅ Am înțeles! Continuă →")
        self._btn_next_chunk.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self._btn_next_chunk.setMinimumHeight(50)
        self._btn_next_chunk.setStyleSheet(BTN_SUCCESS)
        self._btn_next_chunk.clicked.connect(self.next_chunk_requested.emit)
        pt_layout.addLayout(btn_row)
        pt_layout.addWidget(self._btn_next_chunk)
        self._page_text.setLayout(pt_layout)
        self._stack.addWidget(self._page_text)   # index 0

        # ── Page 1: Exercițiu ──
        self._exercise_widget = ExerciseWidget()
        self._stack.addWidget(self._exercise_widget)   # index 1

        # ── Page 2: Pauza ──
        self._page_pause = QWidget()
        pause_layout = QVBoxLayout()
        pause_layout.addStretch()
        lbl_pause = QLabel("⏸️ Lecție în pauză")
        lbl_pause.setFont(QFont("Arial", 28, QFont.Weight.Bold))
        lbl_pause.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pause_layout.addWidget(lbl_pause)
        btn_resume = QPushButton("▶️ Continuă")
        btn_resume.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        btn_resume.setMinimumHeight(70)
        btn_resume.setStyleSheet(BTN_SUCCESS)
        btn_resume.clicked.connect(self.pause_requested.emit)  # resume = același semnal
        pause_layout.addWidget(btn_resume, alignment=Qt.AlignmentFlag.AlignCenter)
        pause_layout.addStretch()
        self._page_pause.setLayout(pause_layout)
        self._stack.addWidget(self._page_pause)  # index 2

        # ── Page 3: Sumar ──
        self._page_summary = QWidget()
        summ_layout = QVBoxLayout()
        self._lbl_summary = QLabel()
        self._lbl_summary.setFont(QFont("Arial", 15))
        self._lbl_summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_summary.setWordWrap(True)
        summ_layout.addStretch()
        summ_layout.addWidget(self._lbl_summary)
        self._btn_back = QPushButton("🏠 Înapoi la meniu")
        self._btn_back.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self._btn_back.setMinimumHeight(60)
        self._btn_back.setStyleSheet(BTN_PRIMARY)
        summ_layout.addWidget(self._btn_back, alignment=Qt.AlignmentFlag.AlignCenter)
        summ_layout.addStretch()
        self._page_summary.setLayout(summ_layout)
        self._stack.addWidget(self._page_summary)  # index 3

        layout.addWidget(self._stack)
        self.setLayout(layout)

        # Conectează exercițiu
        self._exercise_widget.answer_submitted.connect(self._forward_answer)
        self._exercise_widget.hint_requested.connect(self._forward_hint)

    # ── Semnale forwarded la engine ───────────────────────────────────────────
    answer_submitted = pyqtSignal(str, dict)
    hint_requested   = pyqtSignal()

    def activate_scratchpad(self, task_text: str = ""):
        self._exercise_widget.activate_scratchpad(task_text)
        self._stack.setCurrentIndex(1)

    def _forward_answer(self, ans: str, meta: dict):
        self.answer_submitted.emit(ans, meta)

    def _forward_hint(self):
        self.hint_requested.emit()

    def _ask_free_question(self):
        q = self._free_q_input.text().strip()
        if q:
            self._free_q_input.clear()
            self.free_question_asked.emit(q)

    # ── Metode publice ────────────────────────────────────────────────────────

    def set_lesson_title(self, title: str, subject: str):
        self._lbl_lesson_title.setText(f"{title}")
        self._lbl_phase_big.setText(subject)

    def set_phase_label(self, text: str):
        self._lbl_phase_big.setText(text)

    def show_text(self, text: str, show_next_btn: bool = True):
        """Afișează text de lecție."""
        self._text_area.setPlainText(text)
        self._btn_next_chunk.setVisible(show_next_btn)
        self._stack.setCurrentIndex(0)

    def show_exercise(self, ex: dict, idx: int, total: int):
        """Afișează un exercițiu."""
        self._exercise_widget.show_exercise(ex, idx, total)
        self._stack.setCurrentIndex(1)

    def show_exercise_result(self, result: QuestionResult):
        self._exercise_widget.show_result(result)

    def show_hint(self, hint_text: str, hint_nr: int):
        self._exercise_widget.show_hint(hint_text, hint_nr)

    def show_pause(self):
        self._stack.setCurrentIndex(2)

    def show_summary(self, text: str, on_back):
        self._lbl_summary.setText(text)
        self._btn_back.clicked.connect(on_back)
        self._stack.setCurrentIndex(3)


# ═══════════════════════════════════════════════════════════════════════════
# FEREASTRA PRINCIPALĂ
# ═══════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """Fereastra principală care combină toate componentele."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("🤖 Avatar Tutor")
        self.resize(1200, 750)
        self.setStyleSheet(STYLE_MAIN)

        # ── Inițializare servicii ──────────────────────────────────────────
        print("🚀 Pornire Avatar Tutor...")

        self.db = Database("production.db")
        self.deepseek = DeepSeekClient()
        self.tts = TTSEngine()
        #Sincronizează avatarul cu vorbirea (buleți "talking" în timp ce se redă audio)
        try:
            self.tts.finished.connect(lambda: self._avatar_panel.set_emotion("idle"))
        except Exception:
            pass

        # Lip-sync timer: citește current_volume din TTS și trimite la avatar ~30fps
        self._lip_sync_timer = QTimer(self)
        self._lip_sync_timer.timeout.connect(self._update_lip_sync)
        self._lip_sync_timer.start(33)   # 33ms ≈ 30 cadre/secundă
        self.attention = AttentionMonitor(camera_index=0)

        self.engine = LessonEngine(self.db, self.deepseek, self.tts)
        #self._connect_engine_callbacks()

        # Barge-in: ascultare continuă de comenzi vocale în timpul lecției
        self._cmd_listener = CommandListener()
        self._cmd_listener.command_detected.connect(self._on_voice_command)

        # Pre-warm Whisper model în background (evită lag + HuggingFace request la primul click)
        self._prewarm_whisper()

        # Stare sesiune curentă
        self._current_user = None
        self._session_start = None
        self._is_paused = False

        # ── UI ────────────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Ecran login
        self._login_screen = LoginScreen(self.db)
        self._login_screen.login_done.connect(self._on_login)
        self._stack.addWidget(self._login_screen)   # index 0

        # Ecran lecție
        lesson_widget = QWidget()
        lesson_layout = QHBoxLayout()
        lesson_layout.setContentsMargins(0, 0, 0, 0)
        lesson_layout.setSpacing(0)

        self._avatar_panel = AvatarPanel(self.tts)
        self._avatar_panel.setStyleSheet("background-color: #eef2f7; border-right: 1px solid #d0d8e4;")
        lesson_layout.addWidget(self._avatar_panel)

        self.tts.started.connect(lambda _t: self._avatar_panel.set_emotion("talking"))

        self._lesson_panel = LessonPanel()
        lesson_layout.addWidget(self._lesson_panel, stretch=1)

        lesson_widget.setLayout(lesson_layout)
        self._stack.addWidget(lesson_widget)   # index 1

        # Ecran dashboard progres
        self._dashboard = DashboardScreen(self.db)
        self._dashboard.back_requested.connect(self._show_login)
        self._stack.addWidget(self._dashboard)   # index 2

        self._connect_engine_callbacks()

        # Conectam semnalul de deschidere dashboard din login
        self._login_screen.dashboard_open.connect(self._on_dashboard_open)

        # ── Conectare semnale UI → Engine ─────────────────────────────────
        self._lesson_panel.answer_submitted.connect(
            lambda ans, t: self.engine.submit_answer(ans, t)
        )
        self._lesson_panel.hint_requested.connect(self.engine.request_hint)
        self._lesson_panel.next_chunk_requested.connect(self.engine.next_chunk)
        self._lesson_panel.free_question_asked.connect(self.engine.ask_free_question)
        self._lesson_panel.pause_requested.connect(self._toggle_pause)

        # ── Timer pentru atenție și statistici ────────────────────────────
        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self._update_stats)
        self._stats_timer.start(5000)  # La fiecare 5 secunde

        # ── Pornire cameră ─────────────────────────────────────────────────
        self._start_attention_monitor()

        # Conecta quota ElevenLabs la indicator din login
        self.tts.quota_updated.connect(self._login_screen.update_quota)
        if self.tts.engine_name == "elevenlabs":
            # Fetch asincron la pornire (dupa 2s ca sa nu blocheze UI-ul)
            QTimer.singleShot(2000, self.tts.fetch_quota_async)

        # Status în login
        status_parts = []
        status_parts.append(f"TTS: {self.tts.engine_name}")
        status_parts.append(f"DeepSeek: {'✅' if self.deepseek.available else '⚠️'}")
        status_parts.append(f"Camera: {'✅' if self.attention.running else '⚠️'}")
        self._login_screen.update_status(" | ".join(status_parts))

        print("✅ Avatar Tutor pornit!")

    # ── Callbacks engine ──────────────────────────────────────────────────────

    def setup_avatar(self):
        # 1. Crearea widget-ului
        self.avatar_view = QWebEngineView()

        # 2. Setări vizuale (facem fundalul transparent ca să se potrivească cu app-ul)
        self.avatar_view.page().setBackgroundColor(self.palette().color(self.backgroundRole()))

        # 3. Încărcăm URL-ul
        # Atenție: Serverul python -m http.server 8000 trebuie să fie pornit!
        self.avatar_view.setUrl(QUrl("http://localhost:8000/viewer.html"))

        # Ajustăm dimensiunea să fie pătrat sau bust
        self.avatar_view.setFixedSize(400, 400)

        # Dezactivăm scrollbar-ul și context menu (opțional, pentru aspect curat)
        self.avatar_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        import time
        # Adăugăm un timestamp la final (?t=123456) pentru a forța reîncărcarea
        timestamp = int(time.time())
        self.avatar_view.setUrl(QUrl(f"http://localhost:8000/viewer.html"))

        return self.avatar_view

    def _connect_engine_callbacks(self):
        """Leagă callbacks-urile engine-ului la UI."""
        self.engine.on_state_change = self._on_state_change
        self.engine.on_show_text = self._on_show_text
        self.engine.on_show_exercise = self._on_show_exercise
        self.engine.on_show_hint = self._on_show_hint
        self.engine.on_exercise_result = self._on_exercise_result
        self.engine.on_phase_complete = self._on_phase_complete
        self.engine.on_avatar_message = self._on_avatar_message
        self.engine.on_done = self._on_lesson_done
        lesson_panel = getattr(self, "_lesson_panel", None)
        if lesson_panel:
            self.engine.on_show_scratchpad = lesson_panel.activate_scratchpad

    @pyqtSlot(object)
    def _on_state_change(self, state: LessonState):
        labels = {
            LessonState.PRE_TEST:     "📝 Pre-test",
            LessonState.LESSON_INTRO: "📖 Lecție",
            LessonState.LESSON_CHUNK: "📖 Lecție",
            LessonState.MICRO_QUIZ:   "❓ Mini-quiz",
            LessonState.PRACTICE:     "✏️ Exerciții",
            LessonState.POST_TEST:    "🎯 Test final",
            LessonState.SUMMARY:      "📊 Rezumat",
            LessonState.PAUSED:       "⏸️ Pauză",
        }
        label = labels.get(state, "")
        QTimer.singleShot(0, lambda: self._lesson_panel.set_phase_label(label))

    def _on_show_text(self, text: str):
        QTimer.singleShot(0, lambda: self._lesson_panel.show_text(text))

    def _on_show_exercise(self, ex: dict, idx: int, total: int):
        QTimer.singleShot(0, lambda: self._lesson_panel.show_exercise(ex, idx, total))

    def _on_show_hint(self, hint: str, nr: int):
        QTimer.singleShot(0, lambda: self._lesson_panel.show_hint(hint, nr))

    # ── Sound effects ─────────────────────────────────────────────────────────

    def _play_feedback_sound(self, correct: bool, streak: int = 0):
        """Sunet scurt de feedback: ding la corect, buzz la greșit, melodie la streak >=3."""
        if not _SD_OK:
            return
        try:
            sr = 22050
            if correct:
                if streak >= 3:
                    # Mică melodie ascendentă la streak
                    freqs, dur = [523, 659, 784], 0.10   # Do-Mi-Sol
                else:
                    freqs, dur = [660, 880], 0.09         # ding scurt
                total_len = int(sr * (dur * len(freqs) + 0.08))
                audio = np.zeros(total_len)
                for i, f in enumerate(freqs):
                    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
                    tone = 0.40 * np.sin(2 * np.pi * f * t) * np.exp(-5 * t)
                    start = int(i * sr * dur)
                    audio[start: start + len(tone)] += tone
            else:
                # Buzz descendent pentru greșit
                t = np.linspace(0, 0.18, int(sr * 0.18), endpoint=False)
                audio = 0.28 * np.sin(2 * np.pi * 220 * t) * np.exp(-9 * t)
            _sd.play(audio.astype(np.float32), samplerate=sr, blocking=False)
        except Exception:
            pass

    def _update_lip_sync(self):
        """Citit de QTimer la ~30fps — trimite volumul curent TTS către avatar JS."""
        if hasattr(self, '_avatar_panel'):
            vol = self.tts.current_volume if self.tts.is_speaking() else 0.0
            self._avatar_panel.set_mouth_opening(vol)

    def _prewarm_whisper(self):
        """Preîncarcă modelul faster-whisper în background la pornire.
        Evită lag-ul + request-ul HuggingFace la primul click pe 'Vorbeste'."""
        import threading

        def _load():
            try:
                from faster_whisper import WhisperModel
                print("[whisper-prewarm] Se încarcă modelul 'base'...")
                _model = WhisperModel("base", device="cpu", compute_type="int8")
                print("[whisper-prewarm] ✅ Model încărcat — gata pentru voce")
            except Exception as e:
                print(f"[whisper-prewarm] ⚠️  Nu s-a putut preîncărca: {e}")

        t = threading.Thread(target=_load, daemon=True, name="whisper-prewarm")
        t.start()

    def _on_exercise_result(self, result: QuestionResult):
        QTimer.singleShot(0, lambda: self._lesson_panel.show_exercise_result(result))
        streak = self.engine.session.correct_streak if (self.engine and self.engine.session) else 0
        self._play_feedback_sound(result.is_correct, streak)

    def _on_phase_complete(self, phase: str, score: float):
        print(f"   Faza {phase}: {score:.0f}%")

    def _on_avatar_message(self, text: str, emotion: str):
        QTimer.singleShot(0, lambda: self._avatar_panel.set_message(text, emotion))

    def _on_lesson_done(self, session):
        """Sesiunea de lectie s-a terminat."""
        score = session.get_posttest_score()
        practice_score = session.get_practice_score()
        duration = session.duration_seconds() // 60
        user_id   = self._current_user.get("id", 0)
        lesson_id = session.lesson.get("id", 0)

        # Acorda stele si actualizeaza streak
        stars  = self.db.award_stars(user_id, lesson_id, score / 100.0)
        streak = self.db.update_streak(user_id)

        passed = "TRECUT!" if score >= 75 else "Continua sa exersezi!"
        emoji  = "" if score >= 75 else ""

        summary_text = (
            f"{emoji} Lectie terminata!\n\n"
            f"Lectie: {session.lesson['title']}\n"
            f"Elev: {self._current_user.get('name', '?')}\n"
            f"Durata: {duration} minute\n\n"
            f"Practica: {practice_score:.0f}%\n"
            f"Test final: {score:.0f}%\n\n"
            f"{passed}"
        )

        # Afiseaza animatia de stele, apoi summary-ul
        def _show_stars_then_summary():
            dlg = StarAwardDialog(
                stars=stars,
                streak=streak,
                lesson_title=session.lesson.get("title", ""),
                score_pct=score,
                parent=self,
            )
            dlg.exec()   # blocant pana utilizatorul apasa Continue
            # Dupa dialog, afiseaza summary-ul
            self._lesson_panel.show_summary(summary_text, on_back=self._go_home)

        QTimer.singleShot(800, _show_stars_then_summary)

    # ── Login și navigare ─────────────────────────────────────────────────────

    def _on_login(self, user: dict, subject: str, lesson_id: int):
        """Utilizatorul a selectat elev + materie."""
        try:
            self.tts.stop()                      # oprește audio din lecția anterioară
            self._current_user = user
            self._session_start = time.time()

            lesson = self.db.get_lesson(lesson_id)
            if not lesson:
                QMessageBox.warning(self, "Eroare", "Lecția nu a putut fi încărcată.")
                return

            # Actualizează UI-ul de lecție
            self._lesson_panel.set_lesson_title(lesson["title"], subject)
            self._avatar_panel.set_message(f"Bine ai venit, {user['name']}!", "happy")

            # Afișează ecranul de lecție
            self._stack.setCurrentIndex(1)

            # Activează barge-in vocal (HAP driver bug rezolvat cu _find_safe_input_device)
            self._cmd_listener.start_listening()

            # Pornește engine (cu teorie din DB)
            self.engine.start(user_id=user["id"], lesson_id=lesson_id)

            # ── Upgrade: înlocuiește teoria cu chunks din manualul real ──────
            # GUARD: dacă lecția are teorie proprie bine structurată (>= 100 chars),
            # NU suprascriem cu tot manualul. Lecțiile hardcodate (ex. Numerele 0–5)
            # au teoria lor proprie — manualul complet ar adăuga 150+ chunk-uri irelevante.
            try:
                session_lesson = self.engine.session.lesson if self.engine.session else None
                own_theory = session_lesson.get("theory", "") if session_lesson else ""
                theory_is_own = len(own_theory.strip()) >= 100

                if theory_is_own:
                    # Lecție cu teorie proprie — folosim chunk-urile setate de engine.start(),
                    # dar tot apelăm set_theory_chunks() pentru a declanșa DeepSeek background.
                    own_chunks = self.engine.session.theory_chunks if self.engine.session else []
                    if own_chunks:
                        self.engine.set_theory_chunks(own_chunks)
                    print(
                        f"📚 Lecție cu teorie proprie ({len(own_theory)} chars, "
                        f"{len(own_chunks)} chunk-uri) — nu se suprascrie cu manualul."
                    )
                else:
                    lib = ManualLibrary(base_dir=Path(__file__).parent)
                    entry = lib.get_default(subject, user["grade"])
                    if entry:
                        md_path = lib.manuals_dir / entry.file
                        if md_path.exists():
                            chunks = load_md_chunks(str(md_path), max_chars=900)
                            if chunks:
                                self.engine.set_theory_chunks(chunks)
                                print(
                                    f"📖 Manual real: {entry.file} "
                                    f"({len(chunks)} chunk-uri, publisher: {entry.publisher})"
                                )
                        else:
                            print(f"⚠️  Manual {entry.file} nu există în manuale/")
                    else:
                        print(f"⚠️  Niciun manual default pentru {subject} clasa {user['grade']}")
            except Exception as e:
                print(f"⚠️  ManualLibrary eroare (continui cu teorie din DB): {e}")

        except Exception:
            err = traceback.format_exc()
            print(f"❌ CRASH în _on_login:\n{err}")
            QMessageBox.critical(
                self, "Eroare la deschiderea lecției",
                f"A apărut o eroare la încărcarea lecției:\n\n{err[:2000]}\n\n"
                "Detalii complete în crash.log"
            )
            self._stack.setCurrentIndex(0)  # revino la login

    def _go_home(self):
        """Revino la ecranul de login."""
        self._show_login()

    def _show_login(self):
        """Afiseaza ecranul de login."""
        self.tts.stop()                          # oprește orice audio în curs
        self._cmd_listener.stop_listening()
        self._stack.setCurrentIndex(0)
        self._login_screen._load_users()
        self._login_screen.refresh_stars_badge()

    def _on_voice_command(self, cmd: str):
        """Handler pentru comenzile vocale din CommandListener (barge-in)."""
        if self._stack.currentIndex() != 1:
            return   # Comenzile funcționează doar în ecranul de lecție

        if cmd == "stop":
            self.tts.stop()
            self._avatar_panel.set_message("Ok, m-am oprit.", "idle")

        elif cmd == "re_explain":
            self.tts.stop()
            # Re-afișează și re-citește chunk-ul curent
            session = self.engine.session
            if session and session.theory_chunks:
                idx = min(session.current_chunk_idx, len(session.theory_chunks) - 1)
                chunk = session.theory_chunks[idx]
                self._lesson_panel.show_text(
                    f"📚 Repetăm:\n\n{chunk}", show_next_btn=True
                )
                self.tts.speak(chunk)
                self._avatar_panel.set_message("Îți mai explic o dată!", "encouraging")

        elif cmd == "pause":
            self._toggle_pause()

    def _on_dashboard_open(self, user_id: int, user_name: str):
        """Deschide dashboard-ul de progres pentru utilizatorul selectat."""
        self._dashboard.load_user(user_id, user_name)
        self._stack.setCurrentIndex(2)

    def _toggle_pause(self):
        """Pauza/resume lecție."""
        if not self.engine.session:
            return

        if self.engine.session.state == LessonState.PAUSED:
            self.engine.resume()
        else:
            self.engine.pause()
            self._lesson_panel.show_pause()

    # ── Atenție cameră ────────────────────────────────────────────────────────

    def _start_attention_monitor(self):
        """Pornește monitorizarea atenției."""
        self.attention.on_intervention = self._on_attention_intervention
        self.attention.on_state_change = self._on_attention_state_change
        # Preview cameră — actualizat thread-safe via QTimer
        self.attention.on_frame = lambda frame: QTimer.singleShot(
            0, lambda f=frame: self._avatar_panel.set_camera_frame(f)
        )

        camera_ok = self.attention.start()
        self._avatar_panel.set_camera_active(camera_ok)

    def _on_attention_state_change(self, state: AttentionState):
        """Actualizează UI-ul de atenție (din thread camera)."""
        pct = self.attention.get_attention_percent()
        QTimer.singleShot(0, lambda: self._avatar_panel.set_attention(state, pct))

    def _on_attention_intervention(self, message: str):
        """Avatar intervine când elevul e distras (din thread camera)."""
        # Trimite la UI prin QTimer (thread-safe)
        QTimer.singleShot(0, lambda: self._avatar_panel.set_message(message, "encouraging"))
        # TTS citește mesajul (thread-safe prin TTSEngine)
        if self._stack.currentIndex() == 1:  # Doar dacă suntem în lecție
            self.tts.speak(message)

    # ── Statistici ────────────────────────────────────────────────────────────

    def _update_stats(self):
        """Actualizează statisticile afișate (la fiecare 5 secunde)."""
        if not self.engine.session or self._stack.currentIndex() != 1:
            return

        session = self.engine.session
        all_results = (session.pretest_results +
                      session.practice_results +
                      session.posttest_results)

        total = len(all_results)
        correct = sum(1 for r in all_results if r.is_correct)
        elapsed = session.duration_seconds()
        streak = session.correct_streak

        self._avatar_panel.update_stats(correct, total, elapsed, streak)

    # ── Cleanup la închidere ──────────────────────────────────────────────────

    def keyPressEvent(self, event):
        # "Barge-in" rapid: Space oprește vocea și pune cursor în întrebarea liberă
        try:
            if event.key() == Qt.Key.Key_Space and self.tts.is_speaking():
                self.tts.stop()
                # focus pe input întrebări dacă suntem în lecție
                if self._stack.currentIndex() == 1:
                    try:
                        self._lesson_panel._free_q_input.setFocus()
                    except Exception:
                        pass
                return
        except Exception:
            pass
        super().keyPressEvent(event)

    def closeEvent(self, event):
        print("Inchidere Avatar Tutor...")
        # Opreste barge-in listener
        try:
            self._cmd_listener.cleanup()
        except Exception:
            pass
        # Opreste microfonul daca e activ
        lesson_panel = getattr(self, "_lesson_panel", None)
        if lesson_panel:
            ew = getattr(lesson_panel, "_exercise_widget", None)
            if ew and ew._mic_ctrl:
                ew._mic_ctrl.cleanup()
        self.attention.stop()
        self.tts.stop()
        self.db.close()
        event.accept()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    # Asigură directoarele necesare
    Path("assets/avatar").mkdir(parents=True, exist_ok=True)
    Path("audio_lessons").mkdir(exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Font default mai mare
    font = QFont("Arial", 11)
    app.setFont(font)

    window = MainWindow()
    window.show()

    # Mesaj de bun venit la pornire
    QTimer.singleShot(1500, lambda: window.tts.speak(
        "Bun venit la Avatar Tutor! Selectează elevul și materia să începem!"
    ) if window.tts.available else None)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
