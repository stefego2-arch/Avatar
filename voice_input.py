"""
voice_input.py
==============
Recunoastere vocala offline cu faster-whisper + sounddevice.
Fara internet, fara cont Azure/Google.
Modelul Whisper "base" (~74 MB) se descarca automat la prima folosire
in: C:/Users/<user>/.cache/huggingface/hub/

Utilizare:
    worker = VoiceInputWorker()
    worker.result_ready.connect(lambda text: answer_input.setText(text))
    worker.error_occurred.connect(lambda msg: print("Eroare:", msg))
    worker.start()
    # ...
    worker.stop()

Modele disponibile (mai mari = mai precis, mai lent):
    "tiny"   ~ 39 MB  - rapid, pentru raspunsuri scurte (numere, cuvinte)
    "base"   ~ 74 MB  - bun pt copii  <-- DEFAULT
    "small"  ~244 MB  - mai precis
    "medium" ~769 MB  - foarte precis (necesita RAM mai mult)
"""
from __future__ import annotations

import io
import os
import time
import tempfile
import threading
import queue
from pathlib import Path
from typing import Optional

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal, QObject, QTimer


# ── Constante ─────────────────────────────────────────────────────────────────
SAMPLE_RATE    = 16000    # Hz - Whisper foloseste 16kHz
RECORD_SECONDS = 5        # durata maxima inregistrare per apasare buton
SILENCE_THRESH = 0.008    # prag amplitudine pentru detectie silenta
SILENCE_SECS   = 1.2      # secunde de silenta dupa care se opreste automat
DEFAULT_MODEL  = "base"   # tiny / base / small / medium


# ── Helper: selectie device input sigur (evita HAP/AMD abort() C++) ──────────

def _find_safe_input_device() -> Optional[int]:
    """
    Găsește primul device de input care NU e HAP/AMD/Virtual.
    Pe sisteme cu drivere Realtek HAP, sd.rec(blocking=True) provoacă
    un abort() C++ prin PortAudio — specificând explicit un device non-HAP evităm bug-ul.

    Returns:
        Index device sau None (= lasăm sistemul să aleagă default-ul non-HAP)
    """
    try:
        import sounddevice as sd
        HAP_SKIP  = ("hap", "amd bluetooth", "virtual", "realtek hd audio output")
        PREFER    = ("microphone", "headset", "headphones", "mic", "g435", "logitech")
        devices   = sd.query_devices()
        candidates: list[tuple[int, int, str]] = []  # (score, idx, name)
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) < 1:
                continue
            name = d["name"].lower()
            if any(k in name for k in HAP_SKIP):
                continue
            score = sum(1 for k in PREFER if k in name)
            candidates.append((score, i, d["name"]))
        if not candidates:
            return None
        candidates.sort(reverse=True)
        chosen = candidates[0]
        print(f"🎙️ Device input ales: [{chosen[1]}] {chosen[2]}")
        return chosen[1]
    except Exception:
        return None


# ── Worker principal ──────────────────────────────────────────────────────────

class VoiceInputWorker(QThread):
    """
    Inregistreaza audio de la microfon si transcrie cu faster-whisper (offline).

    Mod de functionare:
      - La .start() incepe sa asculte
      - Detecteaza silenta si trimite automat la transcriere
      - Sau la .stop() transcrie ce s-a inregistrat pana atunci
      - Emite result_ready(str) cu textul final

    Semnale:
        result_ready(str)     - text transcris final
        status_changed(str)   - "Ascult...", "Transcriu...", "Gata"
        error_occurred(str)   - mesaj eroare
        listening_started()   - microfon activ
        listening_stopped()   - microfon oprit
    """

    result_ready      = pyqtSignal(str)
    status_changed    = pyqtSignal(str)
    error_occurred    = pyqtSignal(str)
    listening_started = pyqtSignal()
    listening_stopped = pyqtSignal()

    def __init__(self, model_size: str = DEFAULT_MODEL, parent=None):
        super().__init__(parent)
        self._model_size  = model_size
        self._stop_event  = threading.Event()
        self._model       = None   # faster_whisper.WhisperModel (lazy)

    # ── API public ────────────────────────────────────────────────────────────

    def stop(self):
        self._stop_event.set()

    # ── Incarca modelul (prima data dureaza 5-30s + download) ─────────────────

    def _load_model(self):
        if self._model is not None:
            return True
        try:
            from faster_whisper import WhisperModel
            self.status_changed.emit("Se incarca modelul vocal...")
            # compute_type="int8" merge pe orice CPU fara GPU
            self._model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=1,   # evită conflictul OpenMP cu MediaPipe XNNPACK
            )
            return True
        except ImportError:
            self.error_occurred.emit(
                "faster-whisper lipseste!\n"
                "Instaleaza: pip install faster-whisper"
            )
            return False
        except Exception as e:
            self.error_occurred.emit(f"Eroare la incarcarea modelului: {e}")
            return False

    # ── Thread principal ──────────────────────────────────────────────────────

    def run(self):
        try:
            import sounddevice as sd
        except ImportError:
            self.error_occurred.emit("sounddevice lipseste!\npip install sounddevice")
            return

        if not self._load_model():
            return

        self._stop_event.clear()

        # Inregistrare cu detectie silenta automata
        self.status_changed.emit("Ascult...")
        self.listening_started.emit()

        try:
            audio_chunks = []
            silence_chunks = 0
            chunks_per_sec = SAMPLE_RATE // 1024  # ~15 chunk-uri/sec

            _input_dev = _find_safe_input_device()
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32", blocksize=1024,
                                 device=_input_dev) as stream:
                while not self._stop_event.is_set():
                    data, overflowed = stream.read(1024)
                    chunk = data[:, 0]  # mono
                    audio_chunks.append(chunk.copy())

                    # Detectie silenta
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    if rms < SILENCE_THRESH:
                        silence_chunks += 1
                    else:
                        silence_chunks = 0

                    # Oprire automata dupa silenta suficienta (dar minim 0.5s audio)
                    total_secs = len(audio_chunks) * 1024 / SAMPLE_RATE
                    if (silence_chunks >= int(SILENCE_SECS * chunks_per_sec)
                            and total_secs >= 0.5):
                        break

                    # Limita maxima
                    if total_secs >= RECORD_SECONDS:
                        break

        except Exception as e:
            self.error_occurred.emit(f"Eroare microfon: {e}")
            self.listening_stopped.emit()
            return

        self.listening_stopped.emit()

        if not audio_chunks:
            return

        # Transcriere
        self.status_changed.emit("Transcriu...")
        try:
            audio_np = np.concatenate(audio_chunks, axis=0)
            segments, info = self._model.transcribe(
                audio_np,
                language="ro",          # romana
                beam_size=3,
                vad_filter=True,        # filtreaza silenta
                vad_parameters=dict(min_silence_duration_ms=300),
            )
            text = " ".join(s.text.strip() for s in segments).strip()
            if text:
                self.result_ready.emit(text)
                self.status_changed.emit("Gata")
            else:
                self.status_changed.emit("Nu am inteles. Incearca din nou.")
        except Exception as e:
            self.error_occurred.emit(f"Eroare transcriere: {e}")


# ── Controller buton microfon ─────────────────────────────────────────────────

class MicButton(QObject):
    """
    Leaga un QPushButton de VoiceInputWorker.
    La apasare porneste inregistrarea, la terminare pune textul in QLineEdit.
    """

    text_ready = pyqtSignal(str)

    def __init__(self, button, line_edit, model_size: str = DEFAULT_MODEL,
                 parent=None):
        super().__init__(parent)
        self._btn       = button
        self._edit      = line_edit
        self._worker: Optional[VoiceInputWorker] = None
        self._model_size = model_size

        # Stilizare initiala
        self._update_btn_style("idle")
        button.setCheckable(True)
        button.clicked.connect(self._toggle)

    # ── Slot-uri ──────────────────────────────────────────────────────────────

    def _toggle(self, checked: bool):
        if checked:
            self._start()
        else:
            self._stop()

    def _start(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = VoiceInputWorker(model_size=self._model_size)
        self._worker.result_ready.connect(self._on_result)
        self._worker.status_changed.connect(self._on_status)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.listening_started.connect(
            lambda: self._update_btn_style("listening")
        )
        self._worker.listening_stopped.connect(
            lambda: self._update_btn_style("processing")
        )
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(4000)
        self._worker = None
        self._update_btn_style("idle")
        self._btn.setChecked(False)
        self._edit.setPlaceholderText("Scrie raspunsul tau...")

    def _on_result(self, text: str):
        self._edit.setText(text)
        self.text_ready.emit(text)
        self._stop()

    def _on_status(self, msg: str):
        self._edit.setPlaceholderText(f"... {msg}")

    def _on_error(self, msg: str):
        from PyQt6.QtWidgets import QMessageBox
        self._stop()
        QMessageBox.warning(None, "Microfon / Voce", msg)

    # ── Stiluri buton ─────────────────────────────────────────────────────────

    def _update_btn_style(self, state: str):
        styles = {
            "idle": (
                "🎤 Vorbeste",
                "QPushButton { background-color: #27ae60; color: white; "
                "border-radius: 10px; padding: 8px 14px; font-weight: bold; "
                "font-size: 14px; } "
                "QPushButton:hover { background-color: #219a52; }"
            ),
            "listening": (
                "🔴 Ascult...",
                "QPushButton { background-color: #e74c3c; color: white; "
                "border-radius: 10px; padding: 8px 14px; font-weight: bold; "
                "font-size: 14px; }"
            ),
            "processing": (
                "⏳ Transcriu...",
                "QPushButton { background-color: #f39c12; color: white; "
                "border-radius: 10px; padding: 8px 14px; font-weight: bold; "
                "font-size: 14px; }"
            ),
        }
        label, style = styles.get(state, styles["idle"])
        self._btn.setText(label)
        self._btn.setStyleSheet(style)

    def cleanup(self):
        """Apeleaza la inchiderea ferestrei."""
        self._stop()


# ── Barge-in: ascultare continuă de comenzi vocale ───────────────────────────

class CommandListener(QThread):
    """
    Ascultă în fundal comenzi vocale scurte din partea copilului.

    Funcționează continuu pe durata lecției (loop 2s):
      - Înregistrează un bloc scurt de audio
      - Dacă există voce (RMS > prag), transcrie cu Whisper "tiny"
      - Detectează cuvinte cheie române și emite command_detected

    Comenzi recunoscute:
      "stop" / "taci" / "opreste"       → command_detected("stop")
      "nu inteleg" / "explica" / "repeta" → command_detected("re_explain")
      "pauza"                           → command_detected("pause")

    Semnale:
        command_detected(str) - "stop" | "re_explain" | "pause"
    """

    command_detected = pyqtSignal(str)

    # Timp de înregistrare per ferestră (secunde)
    _WINDOW_SECS   = 2.5
    # Prag RMS sub care fereastra e considerată goală (zgomot de fond)
    _VOICE_THRESH  = 0.005

    # Cuvinte cheie pentru fiecare comandă (fără diacritice, lowercase)
    _CMD_STOP = {
        "stop", "taci", "opreste", "opri", "gata", "destul",
    }
    _CMD_EXPLAIN = {
        "nu inteleg", "nu stiu", "explica", "mai explica",
        "repeta", "din nou", "iarasi", "nu am inteles",
        "nu pricep", "incearca din nou", "mai spune",
    }
    _CMD_PAUSE = {
        "pauza", "asteapta", "stand by", "moment",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active     = threading.Event()   # set() = ascultă, clear() = în pauză
        self._stop_event = threading.Event()   # set() = oprire totală
        self._model      = None

    # ── API public ────────────────────────────────────────────────────────────

    def start_listening(self):
        """Activează ascultarea (poate fi apelat și după pauze)."""
        self._active.set()
        if not self.isRunning():
            self._stop_event.clear()
            self.start()

    def stop_listening(self):
        """Dezactivează temporar ascultarea (fără a opri thread-ul)."""
        self._active.clear()

    def cleanup(self):
        """Oprire completă — apelează la închiderea ferestrei."""
        self._stop_event.set()
        self._active.set()   # deblocăm wait-ul ca să se poată opri
        self.wait(3000)

    # ── Normalizare text ──────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """Elimină diacritice și normalizează la lowercase."""
        t = text.lower().strip()
        for src, dst in [
            ("ă", "a"), ("â", "a"), ("î", "i"),
            ("ș", "s"), ("ş", "s"), ("ț", "t"), ("ţ", "t"),
        ]:
            t = t.replace(src, dst)
        return t

    def _detect_command(self, text: str) -> Optional[str]:
        """Returnează comanda detectată sau None."""
        n = self._normalize(text)
        for kw in self._CMD_STOP:
            if kw in n:
                return "stop"
        for kw in self._CMD_EXPLAIN:
            if kw in n:
                return "re_explain"
        for kw in self._CMD_PAUSE:
            if kw in n:
                return "pause"
        return None

    # ── Thread principal ──────────────────────────────────────────────────────

    def run(self):
        try:
            import sounddevice as sd
        except ImportError:
            print("CommandListener: sounddevice lipsește")
            return

        # Încărcăm modelul "tiny" (~39 MB, rapid)
        # "auto" = ctranslate2 alege tipul optim pentru CPU (nu face abort pe AVX2 lips)
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel("tiny", device="cpu", compute_type="auto")
            print("🎙️ CommandListener: model 'tiny' încărcat (auto)")
        except Exception as e:
            print(f"CommandListener: nu pot încărca modelul — {e}")
            return

        n_samples = int(SAMPLE_RATE * self._WINDOW_SECS)

        while not self._stop_event.is_set():
            # Pauză dacă nu suntem activi
            if not self._active.is_set():
                self._active.wait(timeout=0.5)
                continue

            # Înregistrează un bloc de _WINDOW_SECS secunde
            try:
                _input_dev = _find_safe_input_device()
                audio = sd.rec(
                    n_samples,
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    device=_input_dev,
                    blocking=True,
                )
                if self._stop_event.is_set():
                    break

                chunk = audio[:, 0]
                rms = float(np.sqrt(np.mean(chunk ** 2)))

                # Ignoră ferestre fără voce
                if rms < self._VOICE_THRESH:
                    continue

                # Transcrie
                segments, _ = self._model.transcribe(
                    chunk,
                    language="ro",
                    beam_size=1,       # viteza maximă pentru comenzi
                    vad_filter=True,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
                if not text:
                    continue

                cmd = self._detect_command(text)
                if cmd:
                    print(f"🎙️ Comandă vocală detectată: '{text}' → {cmd}")
                    QTimer.singleShot(0, lambda c=cmd: self.command_detected.emit(c))

            except Exception as e:
                if not self._stop_event.is_set():
                    print(f"CommandListener loop eroare: {e}")
                    time.sleep(0.5)


# ── find_vosk_model pastrat pentru compatibilitate (returneaza None) ──────────

def find_vosk_model(base_dir=None):
    """Pastrat pentru compatibilitate cu main.py. Nu mai e necesar."""
    return None
