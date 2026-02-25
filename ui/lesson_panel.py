"""
ui/lesson_panel.py
==================
LessonPanel — panoul principal care schimbă conținut în funcție de faza lecției.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget,
)

from lesson_engine import QuestionResult
from ui.exercise_widget import ExerciseWidget
from ui.styles import BTN_PRIMARY, BTN_SUCCESS, BTN_WARNING


class LessonPanel(QWidget):
    """Panoul principal care schimbă conținut în funcție de faza lecției."""
    next_chunk_requested = pyqtSignal()
    free_question_asked  = pyqtSignal(str)
    pause_requested      = pyqtSignal()

    # Semnale forwarded la engine
    answer_submitted = pyqtSignal(str, dict)
    hint_requested   = pyqtSignal()

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
