"""
tts_engine.py
=============
TTS Engine:
  1. ElevenLabs (Andreea, multilingual-v2) — dacă API key configurat
  2. Piper CLI (ro_RO-mihai-medium) — fallback offline
Redare audio via sounddevice (fiabil pe Windows/Bluetooth).
"""
from __future__ import annotations

import sys
import hashlib
import shutil
import threading
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, Callable, Deque
from collections import deque

from PyQt6.QtCore import QTimer, QObject, pyqtSignal


AVATAR_MESSAGES = {
    "welcome": [
        "Buna! Sunt prietenul tau de invatare. Hai sa incepem!",
        "Salut! Astazi invatam pas cu pas. Esti gata?",
    ],
    "attention": [
        "Hei, esti cu mine?",
        "Hai sa ne uitam impreuna la exercitiu.",
    ],
}

def get_message(key: str, fallback: str = "") -> str:
    msgs = AVATAR_MESSAGES.get(key) or []
    if not msgs:
        return fallback
    return msgs[len(key) % len(msgs)]


def _find_romanian_model() -> tuple[Optional[Path], Optional[Path]]:
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import piper_config
        model = Path(piper_config.PIPER_MODEL_PATH)
        config = Path(piper_config.PIPER_CONFIG_PATH)
        if model.exists() and config.exists():
            return model, config
    except Exception:
        pass
    for d in [Path(__file__).parent / "piper_voices",
              Path.cwd() / "piper_voices",
              Path.home() / "piper_voices"]:
        if not d.exists():
            continue
        for f in d.glob("*.onnx"):
            cfg = f.with_suffix(".onnx.json")
            if cfg.exists():
                return f, cfg
    return None, None


def _pcm_to_wav(path: str, pcm_bytes: bytes, sample_rate: int = 22050,
               channels: int = 1, sampwidth: int = 2):
    """Write raw PCM bytes to a valid WAV file using only stdlib struct."""
    import struct
    data_len = len(pcm_bytes)
    with open(path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_len))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))                          # PCM
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", sample_rate * channels * sampwidth))
        f.write(struct.pack("<H", channels * sampwidth))
        f.write(struct.pack("<H", sampwidth * 8))
        f.write(b"data")
        f.write(struct.pack("<I", data_len))
        f.write(pcm_bytes)


class TTSEngine(QObject):
    started       = pyqtSignal(str)
    finished      = pyqtSignal()
    quota_updated = pyqtSignal(int, int)   # chars_used, chars_limit

    def __init__(self):
        super().__init__()

        self._speaking     = False
        self._on_finished_callback: Optional[Callable[[], None]] = None
        self._temp_files: Deque[str] = deque(maxlen=30)
        self._queue: Deque[tuple[str, Optional[Callable[[], None]]]] = deque()
        self._queue_lock   = threading.Lock()
        self._queue_enabled = True
        self._engine_name  = "none"
        self._piper_exe    = None
        self._model_path: Optional[Path] = None
        self._config_path: Optional[Path] = None

        # sounddevice stop event
        self._sd_stop_event = threading.Event()

        # Selecteaza dispozitivul audio optim
        self._audio_device = None   # None = default sistem
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            out_devs = [(i, d) for i, d in enumerate(devs) if d["max_output_channels"] > 0]
            print("Dispozitive audio output:")
            for i, d in out_devs:
                print(f"  [{i}] {d['name']}")
            # Implicit: None = default sistem (intotdeauna valid pe Windows).
            # Exceptie doar pentru casti Logitech G-series cunoscute.
            LOGITECH = ["G435", "G533", "G733", "G Pro", "G432", "G332"]
            BLOCK = {"hap", "virtual"}
            chosen_idx = None
            chosen_name = "default (system)"
            for model in LOGITECH:
                for i, d in out_devs:
                    n = d["name"].lower()
                    if model.lower() in n and not any(bl in n for bl in BLOCK):
                        chosen_idx = i
                        chosen_name = d["name"]
                        break
                if chosen_idx is not None:
                    break
            self._audio_device = chosen_idx
            print(f"Audio ales: {chosen_name} (idx={chosen_idx})")
        except Exception as e:
            print(f"sounddevice init: {e}")

        # ElevenLabs state — key pool
        self._el_key_pool: list  = []           # toate cheile valide din .env
        self._el_key_idx:  int   = 0            # index cheie activă curentă
        self._el_low_threshold: int = 500       # caractere minime rămase înainte de rotație
        self._el_api_key: Optional[str] = None  # cheia activă (sync cu pool[idx])
        self._el_voice_id: Optional[str] = None
        self._el_model: str = "eleven_multilingual_v2"
        self._el_cache_dir: Optional[Path] = None
        self._el_chars_used: int = 0
        self._el_chars_limit: int = 10_000

        # Try ElevenLabs first; always init Piper too (offline fallback)
        self._init_elevenlabs()
        self._init_piper_cli()  # sets engine_name only if still "none"

    # ── ElevenLabs helpers ────────────────────────────────────────────────────

    def _check_el_quota_sync(self, api_key: str) -> tuple:
        """Returnează (used, limit) pentru o cheie ElevenLabs.
        La eroare de rețea: (0, 10_000) — presupunem cheie validă cu cotă plină.
        Dacă răspunsul indică cheie invalidă (401/403): (10_000, 10_000) → sărită.
        """
        try:
            import urllib.request, json, urllib.error
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/user/subscription",
                headers={"xi-api-key": api_key, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            return int(data.get("character_count", 0)), int(data.get("character_limit", 10_000))
        except Exception as _e:
            import urllib.error as _ue
            if isinstance(_e, _ue.HTTPError) and _e.code in (401, 403):
                # Cheie invalidă / expirată → tratăm ca epuizată
                return 10_000, 10_000
            # Eroare de rețea / timeout → presupunem cheie validă cu cotă disponibilă
            return 0, 10_000

    def _discover_el_voice(self, api_key: str, voice_name: str) -> tuple:
        """Returnează (voice_id, chosen_name) sau (None, None) la eroare."""
        try:
            import urllib.request, json
            req = urllib.request.Request(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            voices = data.get("voices", [])
            for v in voices:
                if v.get("name", "").lower() == voice_name.lower():
                    return v["voice_id"], v["name"]
            if voices:
                preferred = ["jessica", "alice", "sarah", "matilda", "laura", "lily"]
                by_name = {v["name"].lower(): v for v in voices}
                for pref in preferred:
                    if pref in by_name:
                        print(f"TTS ElevenLabs: '{voice_name}' indisponibila, folosesc '{by_name[pref]['name']}'")
                        return by_name[pref]["voice_id"], by_name[pref]["name"]
                print(f"TTS ElevenLabs: '{voice_name}' indisponibila, folosesc '{voices[0]['name']}'")
                return voices[0]["voice_id"], voices[0]["name"]
            return None, None
        except Exception as e:
            print(f"TTS ElevenLabs voice discovery: {e}")
            return None, None

    def _rotate_el_key(self, reason: str = ""):
        """Rotim la următoarea cheie cu cotă suficientă. Dacă nu mai sunt → Piper."""
        pool = self._el_key_pool
        if not pool:
            self._engine_name = "piper"
            print(f"TTS ElevenLabs → Piper permanent {reason}")
            return
        for offset in range(1, len(pool)):
            next_idx = (self._el_key_idx + offset) % len(pool)
            next_key = pool[next_idx]
            used, limit = self._check_el_quota_sync(next_key)
            remaining = limit - used
            if remaining >= self._el_low_threshold:
                self._el_key_idx    = next_idx
                self._el_api_key    = next_key
                self._el_chars_used  = used
                self._el_chars_limit = limit
                print(f"🔄 ElevenLabs: rotit la cheia {next_idx + 1}/{len(pool)} "
                      f"(rămân {remaining} chars) {reason}")
                return
        # Toate cheile epuizate
        self._engine_name = "piper"
        print(f"⚠️  ElevenLabs: toate cheile epuizate → Piper permanent {reason}")

    def _init_elevenlabs(self):
        """Inițializează ElevenLabs cu pool de chei din .env/.elevenlabs_config."""
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import elevenlabs_config as elc

            all_keys = getattr(elc, "ELEVENLABS_API_KEYS", [])
            if not all_keys:
                single = (getattr(elc, "ELEVENLABS_API_KEY", "") or "").strip()
                all_keys = [single] if single else []
            all_keys = [k.strip() for k in all_keys if k and k.strip()]
            if not all_keys:
                return

            voice_name        = getattr(elc, "ELEVENLABS_VOICE_NAME", "Jessica")
            self._el_model    = getattr(elc, "ELEVENLABS_MODEL", "eleven_multilingual_v2")
            self._el_low_threshold = getattr(elc, "ELEVENLABS_LOW_THRESHOLD", 500)
            cache_dir_name    = getattr(elc, "ELEVENLABS_CACHE_DIR", "tts_cache")

            cache_dir = Path(__file__).parent / cache_dir_name
            cache_dir.mkdir(exist_ok=True)
            self._el_cache_dir = cache_dir

            # ── Verifică cota fiecărei chei ──────────────────────────────────
            print(f"TTS ElevenLabs: verificare {len(all_keys)} cheie(i)...")
            valid: list = []   # [(key, used, limit)]
            for key in all_keys:
                used, limit = self._check_el_quota_sync(key)
                remaining = limit - used
                tag = "..."+key[-8:]
                if remaining >= self._el_low_threshold:
                    print(f"   {tag} ✅  {used}/{limit}  (rămân {remaining})")
                    valid.append((key, used, limit))
                else:
                    print(f"   {tag} ⚠️  {used}/{limit}  (rămân {remaining}) — cotă insuficientă, o sar")

            if not valid:
                print("TTS ElevenLabs: nicio cheie cu cotă suficientă → Piper")
                return

            # Sortăm descrescător după caractere rămase (cel mai mult = primul)
            valid.sort(key=lambda x: x[2] - x[1], reverse=True)
            self._el_key_pool = [k[0] for k in valid]
            self._el_key_idx  = 0
            best_key, used, limit = valid[0]
            self._el_api_key    = best_key
            self._el_chars_used  = used
            self._el_chars_limit = limit

            # ── Descoperă voice_id ────────────────────────────────────────────
            voice_id, chosen_name = self._discover_el_voice(best_key, voice_name)
            if not voice_id:
                print("TTS ElevenLabs: nicio voce disponibila.")
                return

            self._el_voice_id  = voice_id
            self._engine_name  = "elevenlabs"
            remaining_best = limit - used
            print(f"TTS ElevenLabs OK: voce={chosen_name} ({voice_id}), model={self._el_model}")
            print(f"   Cheie activă: ...{best_key[-8:]}  "
                  f"({used}/{limit}, rămân {remaining_best})"
                  + (f"  |  {len(self._el_key_pool)} chei în pool" if len(self._el_key_pool) > 1 else ""))

        except Exception as e:
            print(f"TTS ElevenLabs init: {e} — folosesc Piper")

    def _init_piper_cli(self):
        model, cfg = _find_romanian_model()
        if model is None or cfg is None:
            print("TTS: Nu gasesc modelul Piper.")
            return
        piper = shutil.which("piper")
        if not piper:
            scripts = Path(sys.executable).parent
            cand = scripts / ("piper.exe" if sys.platform.startswith("win") else "piper")
            if cand.exists():
                piper = str(cand)
        if not piper:
            print("TTS: Nu gasesc piper CLI.")
            return
        self._piper_exe   = piper
        self._model_path  = model
        self._config_path = cfg
        if self._engine_name == "none":
            self._engine_name = "piper_cli"
        print(f"TTS Piper CLI OK: {self._piper_exe}")
        print(f"   Model: {self._model_path.name}")

    # ── API public ────────────────────────────────────────────────────────

    def fetch_quota_async(self):
        """Fetch ElevenLabs quota info for active key; emits quota_updated(used, limit)."""
        if self._engine_name != "elevenlabs" or not self._el_api_key:
            return
        active_key = self._el_api_key   # capturăm cheia activă la momentul apelului

        def _fetch():
            try:
                import urllib.request, json
                req = urllib.request.Request(
                    "https://api.elevenlabs.io/v1/user/subscription",
                    headers={"xi-api-key": active_key, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                used  = int(data.get("character_count", 0))
                limit = int(data.get("character_limit", self._el_chars_limit))
                # Actualizăm starea doar dacă cheia e încă cea activă
                if self._el_api_key == active_key:
                    self._el_chars_used  = used
                    self._el_chars_limit = limit
                QTimer.singleShot(0, lambda: self.quota_updated.emit(used, limit))
            except Exception as e:
                print(f"ElevenLabs quota fetch: {e}")

        threading.Thread(target=_fetch, daemon=True).start()

    @property
    def available(self) -> bool:
        return self._engine_name != "none"

    @property
    def engine_name(self) -> str:
        return self._engine_name

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, float(volume)))

    def is_speaking(self) -> bool:
        return self._speaking

    def stop(self):
        with self._queue_lock:
            self._queue.clear()
        self._sd_stop_event.set()
        self._speaking = False

    def speak(self, text: str, on_finished: Optional[Callable[[], None]] = None, queue: bool = True):
        if not text.strip() or not self.available:
            if on_finished:
                on_finished()
            return
        if queue and self._queue_enabled and self._speaking:
            with self._queue_lock:
                self._queue.append((text, on_finished))
            return
        self._on_finished_callback = on_finished
        try:
            self.started.emit(text)
        except Exception:
            pass
        thread = threading.Thread(target=self._synthesize_and_play, args=(text,), daemon=True)
        thread.start()

    def speak_sync(self, text: str, timeout: float = 30.0):
        done = threading.Event()
        self.speak(text, on_finished=done.set, queue=False)
        done.wait(timeout=timeout)

    # ── Internal ──────────────────────────────────────────────────────────

    def _synthesize_and_play(self, text: str):
        self._speaking = True
        try:
            wav_path = None
            if self._engine_name == "elevenlabs":
                wav_path = self._synthesize_elevenlabs(text)
                if not wav_path and self._piper_exe:
                    print("ElevenLabs esuat, folosesc Piper fallback")
                    wav_path = self._synthesize_to_wav(text)
            else:
                wav_path = self._synthesize_to_wav(text)
            if not wav_path:
                self._speaking = False
                QTimer.singleShot(0, self._finish)
                return
            self._play_wav_sounddevice(wav_path)
        except Exception as e:
            print(f"TTS eroare: {e}")
            self._speaking = False
            QTimer.singleShot(0, self._finish)

    # ElevenLabs sample rate for pcm_22050 format
    _EL_SR = 22050

    def _synthesize_elevenlabs(self, text: str) -> Optional[str]:
        """Call ElevenLabs API → PCM → WAV (no pydub/ffmpeg needed)."""
        if not self._el_api_key or not self._el_voice_id:
            return None
        import urllib.request, json

        # Cache key: hash of text+voice+model (cache as .wav directly)
        cache_key = hashlib.md5(
            f"{self._el_voice_id}:{self._el_model}:{text}".encode("utf-8")
        ).hexdigest()
        cache_path = self._el_cache_dir / f"{cache_key}.wav" if self._el_cache_dir else None

        if cache_path and cache_path.exists() and cache_path.stat().st_size > 1024:
            return str(cache_path)  # already WAV — play directly

        # Request raw PCM (16-bit signed, mono, 22050 Hz) — no MP3 conversion needed!
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{self._el_voice_id}"
            f"?output_format=pcm_22050"
        )
        payload = json.dumps({
            "text": text,
            "model_id": self._el_model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "xi-api-key": self._el_api_key,
                "Content-Type": "application/json",
                "Accept": "audio/pcm",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                pcm_bytes = resp.read()
        except Exception as e:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                print(f"ElevenLabs API {e.code}: cheie invalidă/cotă epuizată — rotez cheia")
                self._rotate_el_key(f"(HTTP {e.code})")
            else:
                print(f"ElevenLabs API eroare: {e}")
            return None

        if len(pcm_bytes) < 512:
            print(f"ElevenLabs: raspuns prea scurt ({len(pcm_bytes)} bytes) — cota epuizata?")
            return None

        # Write WAV using only stdlib (no pydub / ffmpeg)
        out_path = str(cache_path) if cache_path else tempfile.mktemp(suffix=".wav", prefix="tts_el_")
        _pcm_to_wav(out_path, pcm_bytes, sample_rate=self._EL_SR)
        if not cache_path:
            self._temp_files.append(out_path)

        # Track chars consumed by this API call (cache hits don't cost quota)
        self._el_chars_used += len(text)
        u, l = self._el_chars_used, self._el_chars_limit
        QTimer.singleShot(0, lambda: self.quota_updated.emit(u, l))

        # Rotire proactivă: dacă rămân < threshold → pregătim cheia următoare
        remaining = l - u
        if remaining < self._el_low_threshold and len(self._el_key_pool) > 1:
            print(f"⚠️  ElevenLabs: cotă scăzută ({remaining} chars) — rotez proactiv la cheia următoare")
            self._rotate_el_key("(cotă scăzută)")

        return out_path

    def _synthesize_to_wav(self, text: str) -> Optional[str]:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="tts_")
        tmp_path = tmp.name
        tmp.close()
        self._temp_files.append(tmp_path)

        cmd = [
            self._piper_exe,
            "--model",  str(self._model_path),
            "--config", str(self._config_path),
            "--output_file", tmp_path,
        ]
        p = subprocess.run(cmd, input=text.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if p.returncode != 0:
            print("Piper eroare:", p.stderr.decode("utf-8", errors="ignore")[:200])
            return None
        if Path(tmp_path).stat().st_size <= 1024:
            return None
        return tmp_path

    def _play_wav_sounddevice(self, path: str):
        """Reda WAV cu sounddevice - fiabil pe orice dispozitiv Windows."""
        try:
            import wave
            import numpy as np
            import sounddevice as sd

            with wave.open(path, "rb") as wf:
                sr    = wf.getframerate()
                nc    = wf.getnchannels()
                sw    = wf.getsampwidth()
                data  = wf.readframes(wf.getnframes())

            dtype_map = {1: np.int8, 2: np.int16, 4: np.int32}
            dtype = dtype_map.get(sw, np.int16)
            audio = np.frombuffer(data, dtype=dtype).astype(np.float32)
            audio /= float(np.iinfo(dtype).max)

            if nc > 1:
                audio = audio.reshape(-1, nc)

            self._sd_stop_event.clear()

            # Redare cu callback pe blocuri - permite stop() rapid
            block = 2048

            def _make_callback_and_done():
                idx  = [0]
                done = threading.Event()
                def callback(outdata, frames, time, status):
                    if self._sd_stop_event.is_set():
                        outdata[:] = 0
                        raise sd.CallbackStop()
                    start = idx[0]
                    end   = start + frames
                    chunk = audio[start:end]
                    if len(chunk) < frames:
                        outdata[:len(chunk)] = chunk.reshape(-1, nc) if nc > 1 else chunk.reshape(-1, 1)
                        outdata[len(chunk):] = 0
                        raise sd.CallbackStop()
                    outdata[:] = chunk.reshape(-1, nc) if nc > 1 else chunk.reshape(-1, 1)
                    idx[0] = end
                return callback, done

            # Incearca device ales; daca esueaza, fallback la None (default sistem)
            devices_to_try = [self._audio_device]
            if self._audio_device is not None:
                devices_to_try.append(None)

            played = False
            for dev in devices_to_try:
                self._sd_stop_event.clear()   # reset la fiecare încercare
                callback, done = _make_callback_and_done()
                try:
                    with sd.OutputStream(samplerate=sr, channels=nc,
                                          dtype="float32", blocksize=block,
                                          device=dev,
                                          callback=callback, finished_callback=done.set):
                        done.wait()
                    played = True
                    break
                except Exception as e:
                    print(f"Eroare redare audio (device={dev}): {e}")

        except Exception as e:
            print(f"Eroare redare audio: {e}")
        finally:
            self._speaking = False
            QTimer.singleShot(0, self._finish)

    def _finish(self):
        try:
            self.finished.emit()
        except Exception:
            pass
        cb = self._on_finished_callback
        self._on_finished_callback = None
        if cb:
            try:
                cb()
            except Exception:
                pass
        next_item = None
        with self._queue_lock:
            if self._queue:
                next_item = self._queue.popleft()
        if next_item:
            text, cb2 = next_item
            self.speak(text, on_finished=cb2, queue=False)
