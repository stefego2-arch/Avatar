import sys
import os
# Previne conflictele OpenMP/MKL/BLAS între ctranslate2 (Whisper) și MediaPipe (XNNPACK).
# Trebuie setat ÎNAINTE de orice import nativ.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
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


# ── Avatar scheme — înregistrare ÎNAINTE de QApplication (obligatoriu) ───────
# Înlocuiește subprocess.Popen(["python","-m","http.server","8000"]) cu o schemă
# URL personalizată (avatar://) servită direct din memorie, fără port de rețea.
from PyQt6.QtWebEngineCore import QWebEngineUrlScheme as _QWebEngineUrlScheme
_sch = _QWebEngineUrlScheme(b"avatar")
_sch.setFlags(
    _QWebEngineUrlScheme.Flag.SecureScheme |
    _QWebEngineUrlScheme.Flag.LocalScheme  |
    _QWebEngineUrlScheme.Flag.LocalAccessAllowed
)
_QWebEngineUrlScheme.registerScheme(_sch)

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

# ── Componente UI din pachetul ui/ ───────────────────────────────────────────
from ui.styles import BTN_PRIMARY, BTN_SUCCESS, BTN_WARNING, BTN_DANGER
from ui.avatar_widget   import AvatarWidget
from ui.login_screen    import LoginScreen
from ui.exercise_widget import ExerciseWidget
from ui.avatar_panel    import AvatarPanel
from ui.lesson_panel    import LessonPanel


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

# BTN_PRIMARY, BTN_SUCCESS, BTN_WARNING, BTN_DANGER sunt importate din ui/styles.py

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

        # 3. Încărcăm URL-ul via schema avatar:// (nu mai e necesar http.server)
        self.avatar_view.setUrl(QUrl("avatar://localhost/viewer.html"))

        # Ajustăm dimensiunea să fie pătrat sau bust
        self.avatar_view.setFixedSize(400, 400)

        # Dezactivăm scrollbar-ul și context menu (opțional, pentru aspect curat)
        self.avatar_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        self.avatar_view.setUrl(QUrl("avatar://localhost/viewer.html"))

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
            # Delay: lasă MediaPipe/XNNPACK să se inițializeze complet înainte de ctranslate2
            time.sleep(20)
            try:
                from faster_whisper import WhisperModel
                print("[whisper-prewarm] Se încarcă modelul 'base'...")
                _model = WhisperModel(
                    "base", device="cpu", compute_type="int8",
                    cpu_threads=1,   # evită conflictul OpenMP cu MediaPipe
                )
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

    # Instalează handler-ul pentru schema avatar:// (servește assets/avatar/ fără port)
    from PyQt6.QtWebEngineCore import QWebEngineProfile
    from ui.avatar_scheme import AvatarSchemeHandler
    _avatar_handler = AvatarSchemeHandler()
    QWebEngineProfile.defaultProfile().installUrlSchemeHandler(b"avatar", _avatar_handler)

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
