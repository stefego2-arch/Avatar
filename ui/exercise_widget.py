"""
ui/exercise_widget.py
=====================
ExerciseWidget — afișează un exercițiu cu input text/choice, scratchpad și butoane hint.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from lesson_engine import QuestionResult
from voice_input import MicButton
from ui.styles import BTN_PRIMARY, BTN_SUCCESS, BTN_WARNING


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
        self.avatar_view.setUrl(QUrl("avatar://localhost/viewer.html"))
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
