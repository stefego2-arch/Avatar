from __future__ import annotations

import time
import threading
from pathlib import Path
from enum import Enum
from collections import deque
from dataclasses import dataclass
from typing import Optional, Callable

import cv2
import numpy as np
import requests
import mediapipe as mp
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks import python as mp_python

# ─────────────────────────────────────────────────────────────────────────────
# Model download (o singură dată)
# ─────────────────────────────────────────────────────────────────────────────

MODEL_DIR = Path("mediapipe_models")
FACE_LANDMARKER_TASK = MODEL_DIR / "face_landmarker.task"

# Model oficial MediaPipe (face_landmarker.task)
FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)

def ensure_face_landmarker_model():
    MODEL_DIR.mkdir(exist_ok=True)
    if FACE_LANDMARKER_TASK.exists() and FACE_LANDMARKER_TASK.stat().st_size > 1024 * 1024:
        return

    print("📥 Download face_landmarker.task ...")
    r = requests.get(FACE_LANDMARKER_URL, timeout=120)
    r.raise_for_status()
    FACE_LANDMARKER_TASK.write_bytes(r.content)
    print(f"✅ Saved: {FACE_LANDMARKER_TASK} ({FACE_LANDMARKER_TASK.stat().st_size/1024/1024:.1f} MB)")


# ─────────────────────────────────────────────────────────────────────────────
# Enumerări / rezultate
# ─────────────────────────────────────────────────────────────────────────────

class AttentionState(Enum):
    FOCUSED    = "focused"      # Privește ecranul, atent
    DISTRACTED = "distracted"   # Cap întors / privire în altă parte
    TIRED      = "tired"        # Ochi închiși / clipit des (aprox.)
    AWAY       = "away"         # Nu e nimeni în față camerei
    UNKNOWN    = "unknown"      # N/A


@dataclass
class FrameAnalysis:
    state: AttentionState = AttentionState.UNKNOWN
    face_detected: bool = False
    head_yaw: float = 0.0
    head_pitch: float = 0.0
    eye_aspect_ratio: float = 1.0
    distraction_seconds: float = 0.0
    needs_intervention: bool = False
    intervention_message: str = ""
    confidence: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Monitor principal
# ─────────────────────────────────────────────────────────────────────────────

class AttentionMonitor:
    """
    Monitorizează atenția elevului folosind MediaPipe Tasks FaceLandmarker.

    Callbacks:
        on_intervention(msg: str)
        on_state_change(state: AttentionState)
        on_frame(frame_bgr: np.ndarray)  # frame adnotat (BGR) pentru preview UI
    """

    # Praguri (tune după testare)
    YAW_THRESHOLD   = 25.0
    PITCH_THRESHOLD = 20.0
    EAR_THRESHOLD   = 0.22

    DISTRACTION_WARN_SEC  = 4.0
    DISTRACTION_PAUSE_SEC = 10.0
    AWAY_WARN_SEC         = 5.0

    SMOOTHING_FRAMES = 20

    def __init__(self, camera_index: int = 0):
        self.camera_index = camera_index

        # Thread / camera
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None

        # Timing / smoothing
        self._state_buffer: deque[AttentionState] = deque(maxlen=self.SMOOTHING_FRAMES)
        self._distraction_start: Optional[float] = None
        self._away_start: Optional[float] = None
        self._last_intervention_time: float = 0.0
        self.INTERVENTION_COOLDOWN = 15.0

        # Result curent
        self.last_analysis = FrameAnalysis()

        # Callbacks
        self.on_intervention: Optional[Callable[[str], None]] = None
        self.on_state_change: Optional[Callable[[AttentionState], None]] = None
        self.on_frame: Optional[Callable[[np.ndarray], None]] = None

        # Stats
        self.stats = {
            "total_frames": 0,
            "focused_frames": 0,
            "distracted_frames": 0,
            "away_frames": 0,
            "tired_frames": 0,
            "interventions": 0,
        }

        # MediaPipe Tasks init
        ensure_face_landmarker_model()
        self._landmarker = self._create_landmarker()
        self._last_ts_ms = 0  # VIDEO mode cere timestamp monoton crescător

    def _create_landmarker(self):
        BaseOptions = mp_python.BaseOptions
        FaceLandmarker = mp_vision.FaceLandmarker
        FaceLandmarkerOptions = mp_vision.FaceLandmarkerOptions
        RunningMode = mp_vision.RunningMode

        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(FACE_LANDMARKER_TASK)),
            running_mode=RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            # output_face_blendshapes=False,
            # output_facial_transformation_matrixes=False,
        )
        return FaceLandmarker.create_from_options(options)

    # ─────────────────────────────────────────────────────────────────────────
    # Control
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Pornește monitorizarea. Returnează True dacă a reușit."""
        if self.running:
            return True

        self._cap = cv2.VideoCapture(self.camera_index)
        if not self._cap.isOpened():
            print(f"⚠️  AttentionMonitor: Camera {self.camera_index} indisponibilă")
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self._cap.set(cv2.CAP_PROP_FPS, 30)

        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("✅ AttentionMonitor pornit (FaceLandmarker tasks)")
        return True

    def stop(self):
        """Oprește monitorizarea."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap:
            self._cap.release()
            self._cap = None
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception:
                pass
        print("🛑 AttentionMonitor oprit")

    def get_attention_percent(self) -> float:
        total = self.stats["total_frames"]
        if total <= 0:
            return 100.0
        return (self.stats["focused_frames"] / total) * 100.0

    # ─────────────────────────────────────────────────────────────────────────
    # Loop thread
    # ─────────────────────────────────────────────────────────────────────────

    def _loop(self):
        while self.running:
            ret, frame = self._cap.read() if self._cap else (False, None)
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)

            analysis = self._analyze_frame(frame)
            self.last_analysis = analysis

            # stats
            self.stats["total_frames"] += 1
            if analysis.state == AttentionState.FOCUSED:
                self.stats["focused_frames"] += 1
            elif analysis.state == AttentionState.DISTRACTED:
                self.stats["distracted_frames"] += 1
            elif analysis.state == AttentionState.AWAY:
                self.stats["away_frames"] += 1
            elif analysis.state == AttentionState.TIRED:
                self.stats["tired_frames"] += 1

            # callbacks
            if self.on_state_change:
                try:
                    self.on_state_change(analysis.state)
                except Exception:
                    pass

            if analysis.needs_intervention and self.on_intervention:
                now = time.time()
                if now - self._last_intervention_time > self.INTERVENTION_COOLDOWN:
                    self._last_intervention_time = now
                    self.stats["interventions"] += 1
                    try:
                        self.on_intervention(analysis.intervention_message)
                    except Exception:
                        pass

            if self.on_frame:
                try:
                    annotated = self._annotate_frame(frame, analysis)
                    self.on_frame(annotated)
                except Exception:
                    pass

    # ─────────────────────────────────────────────────────────────────────────
    # Analiză
    # ─────────────────────────────────────────────────────────────────────────

    def _next_timestamp_ms(self) -> int:
        now = int(time.time() * 1000)
        # VIDEO mode cere monotonic increasing
        if now <= self._last_ts_ms:
            now = self._last_ts_ms + 1
        self._last_ts_ms = now
        return now

    def _analyze_frame(self, frame_bgr: np.ndarray) -> FrameAnalysis:
        result = FrameAnalysis()

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        ts_ms = self._next_timestamp_ms()
        det = self._landmarker.detect_for_video(mp_image, ts_ms)

        # AWAY (no face)
        if not det.face_landmarks:
            result.face_detected = False
            result.state = AttentionState.AWAY

            if self._away_start is None:
                self._away_start = time.time()
            else:
                result.distraction_seconds = time.time() - self._away_start
                if result.distraction_seconds >= self.AWAY_WARN_SEC:
                    result.needs_intervention = True
                    result.intervention_message = self._get_away_message(result.distraction_seconds)

            self._distraction_start = None
            self._state_buffer.append(AttentionState.AWAY)
            result.confidence = self._buffer_confidence(result.state)
            return result

        # Face detected
        self._away_start = None
        result.face_detected = True
        landmarks = det.face_landmarks[0]  # list[NormalizedLandmark]
        h, w = frame_bgr.shape[:2]

        result.head_yaw = self._calc_yaw(landmarks, w, h)
        result.head_pitch = self._calc_pitch(landmarks, w, h)
        result.eye_aspect_ratio = self._calc_ear(landmarks, w, h)

        # classify
        if result.eye_aspect_ratio < self.EAR_THRESHOLD:
            raw_state = AttentionState.TIRED
        elif abs(result.head_yaw) > self.YAW_THRESHOLD or abs(result.head_pitch) > self.PITCH_THRESHOLD:
            raw_state = AttentionState.DISTRACTED
        else:
            raw_state = AttentionState.FOCUSED

        self._state_buffer.append(raw_state)
        result.state = self._smoothed_state(raw_state)
        result.confidence = self._buffer_confidence(result.state)

        # distraction timer
        if result.state in (AttentionState.DISTRACTED, AttentionState.TIRED):
            if self._distraction_start is None:
                self._distraction_start = time.time()
            else:
                result.distraction_seconds = time.time() - self._distraction_start
                if result.distraction_seconds >= self.DISTRACTION_PAUSE_SEC:
                    result.needs_intervention = True
                    result.intervention_message = self._get_distracted_long_message()
                elif result.distraction_seconds >= self.DISTRACTION_WARN_SEC:
                    result.needs_intervention = True
                    result.intervention_message = self._get_distracted_short_message()
        else:
            self._distraction_start = None

        return result

    def _smoothed_state(self, fallback: AttentionState) -> AttentionState:
        if len(self._state_buffer) < 5:
            return fallback
        counts = {}
        for s in self._state_buffer:
            counts[s] = counts.get(s, 0) + 1
        return max(counts, key=counts.get)

    def _buffer_confidence(self, state: AttentionState) -> float:
        if not self._state_buffer:
            return 0.0
        c = sum(1 for s in self._state_buffer if s == state)
        return c / len(self._state_buffer)

    # ─────────────────────────────────────────────────────────────────────────
    # Geometrie (folosește aceiași indici ca FaceMesh; modelul returnează 468 pts)
    # ─────────────────────────────────────────────────────────────────────────

    def _calc_yaw(self, lm, w: int, h: int) -> float:
        """Yaw aproximativ din poziția vârfului nasului față de centrul nărilor."""
        try:
            nose_left  = np.array([lm[33].x * w,  lm[33].y * h], dtype=np.float32)
            nose_right = np.array([lm[263].x * w, lm[263].y * h], dtype=np.float32)
            nose_tip   = np.array([lm[1].x * w,   lm[1].y * h], dtype=np.float32)

            center = (nose_left + nose_right) / 2.0
            diff = nose_tip[0] - center[0]
            width = nose_right[0] - nose_left[0]
            if abs(width) < 1.0:
                return 0.0
            return float((diff / width) * 90.0)
        except Exception:
            return 0.0

    def _calc_pitch(self, lm, w: int, h: int) -> float:
        """Pitch aproximativ din raportul nas-frunte-bărbie."""
        try:
            forehead = np.array([lm[10].x * w,  lm[10].y * h], dtype=np.float32)
            chin     = np.array([lm[152].x * w, lm[152].y * h], dtype=np.float32)
            nose_tip = np.array([lm[1].x * w,   lm[1].y * h], dtype=np.float32)

            face_h = chin[1] - forehead[1]
            if abs(face_h) < 1.0:
                return 0.0
            nose_ratio = (nose_tip[1] - forehead[1]) / face_h
            return float((nose_ratio - 0.6) * 100.0)
        except Exception:
            return 0.0

    def _calc_ear(self, lm, w: int, h: int) -> float:
        """
        EAR (Eye Aspect Ratio) aproximativ — folosit ca indicator pentru oboseală/ochi închiși.
        NOTE: e o euristică; tune pragurile pe lumină/cameră.
        """
        try:
            def pt(i):
                return np.array([lm[i].x * w, lm[i].y * h], dtype=np.float32)

            def ear(p1, p2, p3, p4, p5, p6):
                A = np.linalg.norm(pt(p2) - pt(p6))
                B = np.linalg.norm(pt(p3) - pt(p5))
                C = np.linalg.norm(pt(p1) - pt(p4))
                return float((A + B) / (2.0 * C)) if C > 1e-6 else 1.0

            # stâng: 362, 385, 387, 263, 373, 380
            # drept: 33, 160, 158, 133, 153, 144
            ear_left  = ear(362, 385, 387, 263, 373, 380)
            ear_right = ear(33,  160, 158, 133, 153, 144)
            return float((ear_left + ear_right) / 2.0)
        except Exception:
            return 1.0

    # ─────────────────────────────────────────────────────────────────────────
    # UI annotate
    # ─────────────────────────────────────────────────────────────────────────

    def _annotate_frame(self, frame: np.ndarray, analysis: FrameAnalysis) -> np.ndarray:
        img = frame.copy()

        colors = {
            AttentionState.FOCUSED:    (0, 200, 0),
            AttentionState.DISTRACTED: (0, 165, 255),
            AttentionState.TIRED:      (255, 165, 0),
            AttentionState.AWAY:       (0, 0, 255),
            AttentionState.UNKNOWN:    (128, 128, 128),
        }
        color = colors.get(analysis.state, (128, 128, 128))

        cv2.rectangle(img, (0, 0), (img.shape[1]-1, img.shape[0]-1), color, 4)

        labels = {
            AttentionState.FOCUSED:    "ATENT ✓",
            AttentionState.DISTRACTED: "DISTRAS",
            AttentionState.TIRED:      "OBOSIT",
            AttentionState.AWAY:       "ABSENT",
            AttentionState.UNKNOWN:    "...",
        }
        label = labels.get(analysis.state, "?")
        cv2.putText(img, f"{label}  conf:{analysis.confidence:.2f}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        if analysis.distraction_seconds > 1.0:
            cv2.putText(img, f"{analysis.distraction_seconds:.0f}s", (10, 58),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        if analysis.face_detected:
            info = [
                f"Yaw:   {analysis.head_yaw:+.0f}",
                f"Pitch: {analysis.head_pitch:+.0f}",
                f"EAR:   {analysis.eye_aspect_ratio:.2f}",
            ]
            y0 = img.shape[0] - 70
            for i, t in enumerate(info):
                cv2.putText(img, t, (10, y0 + i * 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 1)

        return img

    # ─────────────────────────────────────────────────────────────────────────
    # Mesaje intervenție
    # ─────────────────────────────────────────────────────────────────────────

    def _get_distracted_short_message(self) -> str:
        return "Hei! Ești cu mine? Hai să continuăm! 😊"

    def _get_distracted_long_message(self) -> str:
        import random
        messages = [
            "Vino înapoi! Avem ceva interesant de văzut! 🌟",
            "Pauză scurtă? Hai să reluăm când ești gata! 😊",
            "Atenție te rog! E ceva important acum! 📚",
            "Te aștept! Apasă butonul când ești pregătit! ⏯️",
        ]
        return random.choice(messages)

    def _get_away_message(self, seconds: float) -> str:
        if seconds < 15:
            return "Hei, unde ești? Te aștept! 👀"
        return "Lecția este în pauză. Apasă oricând să continuăm! ⏸️"


# ─────────────────────────────────────────────────────────────────────────────
# 2026 add-on: engagement signals (fără LLM)
# ─────────────────────────────────────────────────────────────────────────────

class EngagementTracker:
    """Agregă semnale locale pentru 'engagement' (0..1) + recomandare."""

    def __init__(self):
        self._last_interaction_ts = time.time()
        self._recent_states: deque[AttentionState] = deque(maxlen=90)  # ~3s la 30fps
        self._recent_interactions: deque[float] = deque(maxlen=50)

    def report_attention_state(self, state: AttentionState):
        self._recent_states.append(state)

    def report_interaction(self, kind: str = "answer"):
        now = time.time()
        self._last_interaction_ts = now
        self._recent_interactions.append(now)

    def compute(self) -> dict:
        now = time.time()
        if not self._recent_states:
            return {"score": 1.0, "recommendation": "ok"}

        focused = sum(1 for s in self._recent_states if s == AttentionState.FOCUSED)
        distracted = sum(1 for s in self._recent_states if s == AttentionState.DISTRACTED)
        away = sum(1 for s in self._recent_states if s == AttentionState.AWAY)
        tired = sum(1 for s in self._recent_states if s == AttentionState.TIRED)
        total = len(self._recent_states)

        att = (focused - 0.6*distracted - 1.0*away - 0.3*tired) / max(1, total)
        att = max(0.0, min(1.0, att))

        idle_sec = now - self._last_interaction_ts
        interact_penalty = min(0.4, idle_sec / 30.0)
        score = max(0.0, min(1.0, att - interact_penalty))

        if away > total * 0.5 or score < 0.35:
            rec = "pause"
        elif score < 0.55:
            rec = "offer_hint"
        else:
            rec = "ok"

        return {
            "score": score,
            "attention_component": att,
            "idle_sec": idle_sec,
            "recommendation": rec,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Test standalone
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🧪 Test AttentionMonitor (FaceLandmarker tasks) — Apasă Q să ieși\n")

    monitor = AttentionMonitor(camera_index=0)

    def on_intervention(msg: str):
        print(f"\n🤖 AVATAR: {msg}\n")

    monitor.on_intervention = on_intervention

    # Ca să evităm cv2.imshow din thread, folosim un buffer comun
    _latest_frame = {"img": None}
    _lock = threading.Lock()

    def on_frame(img: np.ndarray):
        with _lock:
            _latest_frame["img"] = img

    monitor.on_frame = on_frame

    def on_state(state: AttentionState):
        symbols = {
            AttentionState.FOCUSED: "🟢",
            AttentionState.DISTRACTED: "🟠",
            AttentionState.TIRED: "🔵",
            AttentionState.AWAY: "🔴",
            AttentionState.UNKNOWN: "⚪",
        }
        print(f"\r  Stare: {symbols.get(state, '⚪')} {state.value:<10} "
              f"att:{monitor.get_attention_percent():5.1f}%",
              end="", flush=True)

    monitor.on_state_change = on_state

    if not monitor.start():
        print("Nu s-a putut porni monitorul. Verifică camera.")
        raise SystemExit(1)

    try:
        while True:
            with _lock:
                img = _latest_frame["img"]
            if img is not None:
                cv2.imshow("Attention Monitor Test", img)
            key = cv2.waitKey(15) & 0xFF
            if key == ord("q"):
                break
    finally:
        monitor.stop()
        cv2.destroyAllWindows()

    print("\n\n📊 STATISTICI SESIUNE:")
    print(f"   Atenție medie: {monitor.get_attention_percent():.0f}%")
    print(f"   Intervenții:   {monitor.stats['interventions']}")
