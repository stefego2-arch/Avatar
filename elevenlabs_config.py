# elevenlabs_config.py
# Citește configurarea ElevenLabs din .env (suportă pool de chei multiple)
# Adaugă/modifică cheile în .env: ELEVENLABS_KEY_1, ELEVENLABS_KEY_2, ...

import os
from pathlib import Path

# ── Încarcă .env dacă python-dotenv e disponibil ─────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    # Fără python-dotenv: parsăm manual .env (fără dependință extra)
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                if _k.strip() not in os.environ:   # nu suprascrie variabile deja setate
                    os.environ[_k.strip()] = _v.strip()


def _get_el_keys() -> list[str]:
    """Returnează toate cheile ElevenLabs non-goale definite în .env.

    Scanează KEY_1..KEY_10 și tolerează goluri (nu se oprește la primul slot gol).
    """
    keys: list[str] = []
    for i in range(1, 11):   # KEY_1 … KEY_10, tolerant la goluri
        key = os.environ.get(f"ELEVENLABS_KEY_{i}", "").strip()
        if key:
            keys.append(key)
    # Backward-compat: cheia veche ELEVENLABS_API_KEY
    old_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if old_key and old_key not in keys:
        keys.append(old_key)
    return keys


# ── Variabile publice (importate de tts_engine.py) ───────────────────────────
ELEVENLABS_API_KEYS: list[str] = _get_el_keys()
ELEVENLABS_API_KEY:  str       = ELEVENLABS_API_KEYS[0] if ELEVENLABS_API_KEYS else ""  # backward-compat

ELEVENLABS_VOICE_NAME:   str = os.environ.get("ELEVENLABS_VOICE_NAME", "Jessica")
ELEVENLABS_MODEL:        str = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
ELEVENLABS_CACHE_DIR:    str = os.environ.get("ELEVENLABS_CACHE_DIR", "tts_cache")
ELEVENLABS_LOW_THRESHOLD: int = int(os.environ.get("ELEVENLABS_LOW_THRESHOLD", "500"))
