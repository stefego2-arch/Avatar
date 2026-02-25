#!/usr/bin/env python3
"""
🔊 SETUP PIPER TTS - VOCE ROMÂNĂ
Rulează acest script O SINGURĂ DATĂ pentru a descărca vocea română.

Necesită: pip install piper-tts requests
Rulare:   python 1_setup_piper_roman.py
"""

import os
import sys
import subprocess
import urllib.request
from pathlib import Path

# ─── Configurare ────────────────────────────────────────────────────────────

VOICES_DIR = Path("piper_voices")  # Directorul unde se salvează vocea

# Vocea română disponibilă pe HuggingFace (Mihai - calitate medie, rapidă)
ROMANIAN_VOICE = {
    "name": "ro_RO-mihai-medium",
    "model_url": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "ro/ro_RO/mihai/medium/ro_RO-mihai-medium.onnx"
    ),
    "config_url": (
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
        "ro/ro_RO/mihai/medium/ro_RO-mihai-medium.onnx.json"
    ),
    "model_file": "ro_RO-mihai-medium.onnx",
    "config_file": "ro_RO-mihai-medium.onnx.json",
}


def print_banner():
    print("=" * 65)
    print("  🔊 SETUP PIPER TTS — VOCE ROMÂNĂ")
    print("=" * 65)
    print()


def check_piper_installed() -> bool:
    """Verifică dacă piper-tts este instalat"""
    try:
        result = subprocess.run(
            ["python", "-c", "import piper; print('ok')"],
            capture_output=True, text=True, timeout=10
        )
        if "ok" in result.stdout:
            print("✅ piper-tts este instalat")
            return True
    except Exception:
        pass

    print("❌ piper-tts nu este instalat!")
    print("   Rulează: pip install piper-tts")
    return False


def download_file(url: str, dest: Path, label: str):
    """Descarcă un fișier cu progress bar simplu"""
    print(f"\n📥 Descărcare {label}...")
    print(f"   URL: {url}")
    print(f"   Destinație: {dest}")

    if dest.exists():
        print(f"   ⏭️  Deja există! ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
        return True

    try:
        downloaded = [0]
        total_size = [0]

        def progress(block_num, block_size, total):
            total_size[0] = total
            downloaded[0] = block_num * block_size
            if total > 0:
                pct = min(100, downloaded[0] * 100 / total)
                mb_done = downloaded[0] / 1024 / 1024
                mb_total = total / 1024 / 1024
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                print(f"\r   [{bar}] {pct:.0f}% — {mb_done:.1f}/{mb_total:.1f} MB",
                      end="", flush=True)

        urllib.request.urlretrieve(url, dest, reporthook=progress)
        print()  # newline după progress bar
        print(f"   ✅ Descărcat! ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
        return True

    except Exception as e:
        print(f"\n   ❌ Eroare la descărcare: {e}")
        print()
        print("   💡 Dacă nu merge automat, descarcă manual:")
        print(f"      {url}")
        print(f"      și pune fișierul în: {VOICES_DIR}/")
        if dest.exists():
            dest.unlink()  # Șterge fișier incomplet
        return False


def test_voice():
    """Testează vocea după instalare — suportă API v1.2 și v1.4"""
    print("\n🧪 Test voce română...")

    model_path  = VOICES_DIR / ROMANIAN_VOICE["model_file"]
    config_path = VOICES_DIR / ROMANIAN_VOICE["config_file"]
    test_file   = Path("test_voce_romana.wav")
    test_text   = "Bună ziua! Mă numesc Avatar Tutor. Hai să învățăm împreună!"

    # ── API nou: piper-tts >= 1.4.x ─────────────────────────────────────────
    try:
        from piper.voice import PiperVoice
        import wave

        print("   Folosesc API piper v1.4+")
        # IMPORTANT: în 1.4.x trebuie model + config
        voice = PiperVoice.load(str(model_path), str(config_path))

        fh = None
        with wave.open(str(test_file), "wb") as wav_file:
            wrote_any = False
            for chunk in voice.synthesize(test_text):
                if not wrote_any:
                    # Setează WAV params din primul chunk
                    wav_file.setframerate(chunk.sample_rate)
                    wav_file.setsampwidth(chunk.sample_width)
                    wav_file.setnchannels(chunk.sample_channels)
                    wrote_any = True
                wav_file.writeframes(chunk.audio_int16_bytes)

        size_kb = test_file.stat().st_size // 1024
        if size_kb <= 1:
            print(f"   ❌ Audio generat dar pare gol: {test_file} ({size_kb} KB)")
            return False

        print(f"   ✅ Audio generat: {test_file} ({size_kb} KB)")
        return True

    except ImportError:
        pass
    except Exception as e:
        print(f"   ⚠️  API v1.4 eroare: {e}")

    # ── API vechi: piper-tts <= 1.2.x ───────────────────────────────────────
    try:
        from piper import PiperVoice
        import wave

        print("   Folosesc API piper v1.2")
        voice = PiperVoice.load(
            str(model_path),
            config_path=str(config_path),
            use_cuda=False
        )

        sample_rate = getattr(voice.config, "sample_rate", 22050)
        with wave.open(str(test_file), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            voice.synthesize(test_text, wav_file)

        size_kb = test_file.stat().st_size // 1024
        if size_kb <= 1:
            print(f"   ❌ Audio generat dar pare gol: {test_file} ({size_kb} KB)")
            return False

        print(f"   ✅ Audio generat: {test_file} ({size_kb} KB)")
        return True

    except ImportError:
        print("   ❌ Nicio variantă de API piper nu funcționează")
        return False
    except Exception as e:
        print(f"   ❌ Eroare: {e}")
        return False



def save_config():
    """Salvează configurația pentru celelalte scripturi"""
    config_content = f'''# AUTO-GENERAT de 1_setup_piper_roman.py
# Configurare Piper TTS pentru proiect

PIPER_VOICES_DIR = "{VOICES_DIR.absolute()}"
PIPER_MODEL_FILE = "{ROMANIAN_VOICE["model_file"]}"
PIPER_CONFIG_FILE = "{ROMANIAN_VOICE["config_file"]}"
PIPER_MODEL_PATH = "{VOICES_DIR.absolute() / ROMANIAN_VOICE["model_file"]}"
PIPER_CONFIG_PATH = "{VOICES_DIR.absolute() / ROMANIAN_VOICE["config_file"]}"
'''
    config_path = Path("piper_config.py")
    config_path.write_text(config_content, encoding="utf-8")
    print(f"\n💾 Configurație salvată în: {config_path}")


def main():
    print_banner()

    # 1. Verifică piper instalat
    if not check_piper_installed():
        sys.exit(1)

    # 2. Creează directorul pentru voci
    VOICES_DIR.mkdir(exist_ok=True)
    print(f"\n📁 Director voci: {VOICES_DIR.absolute()}")

    # 3. Descarcă modelul (.onnx)
    ok1 = download_file(
        ROMANIAN_VOICE["model_url"],
        VOICES_DIR / ROMANIAN_VOICE["model_file"],
        "Model voce română (Mihai, ~63MB)"
    )

    # 4. Descarcă configurația (.json)
    ok2 = download_file(
        ROMANIAN_VOICE["config_url"],
        VOICES_DIR / ROMANIAN_VOICE["config_file"],
        "Config voce română"
    )

    if not ok1 or not ok2:
        print("\n❌ Descărcarea a eșuat. Vezi instrucțiunile manuale de mai sus.")
        sys.exit(1)

    # 5. Salvează configurația
    save_config()

    # 6. Test
    success = test_voice()

    print()
    print("=" * 65)
    if success:
        print("  🎉 SETUP COMPLET!")
        print()
        print("  Pași următori:")
        print("  1. Ascultă 'test_voce_romana.wav'")
        print("  2. Dacă sună bine, rulează: python main.py")
    else:
        print("  ⚠️  Setup parțial — vocea e descărcată dar testul a eșuat.")
        print("     Încearcă totuși: python main.py")
    print("=" * 65)


if __name__ == "__main__":
    main()
