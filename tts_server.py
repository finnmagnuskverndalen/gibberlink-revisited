"""
GibberLink Revisited — TTS Server

Serves either Kokoro-ONNX or Qwen3-TTS via a simple HTTP API.
Started automatically by server.py based on TTS_PROVIDER in .env.

Endpoint:
    GET /synthesize?text=Hello+world&voice=am_michael  → WAV bytes
    GET /health                                         → {"status":"ok"}
    GET /voices                                         → {"voices":[...]}
"""

import argparse
import io
import os
import sys
import numpy as np
from scipy.io import wavfile

from dotenv import load_dotenv
load_dotenv()

# ── Args ─────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--engine", choices=["kokoro", "qwen3"], default=None,
                    help="TTS engine to use (defaults to TTS_PROVIDER in .env)")
parser.add_argument("--port", type=int, default=None)
args = parser.parse_args()

# Resolve engine and port from args or .env
ENGINE = args.engine or os.getenv("TTS_PROVIDER", "kokoro").lower()
if ENGINE not in ("kokoro", "qwen3"):
    ENGINE = "kokoro"

def _default_port():
    if ENGINE == "kokoro":
        url = os.getenv("KOKORO_TTS_URL", "http://localhost:7862")
    else:
        url = os.getenv("QWEN3_TTS_URL", "http://localhost:7861")
    try:
        return int(url.rstrip("/").split(":")[-1])
    except ValueError:
        return 7862 if ENGINE == "kokoro" else 7861

PORT = args.port or _default_port()

# ── Dependency check ─────────────────────────────────────────
def _check_deps():
    missing = []
    required = {
        "kokoro": ["kokoro_onnx", "soundfile"],
        "qwen3":  ["qwen_tts", "soundfile", "scipy", "torch"],
    }
    for pkg in required[ENGINE]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        pip_map = {"kokoro_onnx": "kokoro-onnx", "qwen_tts": "qwen-tts"}
        pip_names = [pip_map.get(p, p) for p in missing]
        print(f"\n  ✗ Missing packages: {', '.join(missing)}")
        print(f"  Install with: pip install {' '.join(pip_names)}\n")
        sys.exit(1)

_check_deps()

# ── FastAPI ───────────────────────────────────────────────────
try:
    from fastapi import FastAPI, Query
    from fastapi.responses import Response
    import uvicorn
except ImportError:
    print("  ✗ fastapi/uvicorn missing — pip install fastapi uvicorn")
    sys.exit(1)

app = FastAPI(title=f"GibberLink TTS — {ENGINE}")

# ── Engine: Kokoro-ONNX ───────────────────────────────────────
if ENGINE == "kokoro":
    from kokoro_onnx import Kokoro

    print(f"\n  Loading Kokoro-ONNX (~300MB download on first run)...")
    _kokoro = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
    print("  ✓ Kokoro ready\n")

    VOICES = [
        "am_adam", "am_michael", "bm_george", "bm_lewis",
        "af_heart", "af_bella", "bf_emma", "bf_isabella",
        "af_nicole", "af_sky", "am_echo", "bm_daniel",
    ]

    def _synthesize(text: str, voice: str) -> tuple[np.ndarray, int]:
        if voice not in VOICES:
            voice = "am_michael"
        samples, sr = _kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
        return samples, sr

# ── Engine: Qwen3-TTS ─────────────────────────────────────────
else:
    import torch
    from qwen_tts import Qwen3TTSModel

    MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    print(f"\n  Loading {MODEL_ID} (~1.3GB download on first run)...")
    print("  Note: running on CPU (float32) for hardware compatibility")
    _qwen = Qwen3TTSModel.from_pretrained(
        MODEL_ID, device_map="cpu", dtype=torch.float32,
    )
    print("  ✓ Qwen3-TTS ready\n")

    VOICES = [
        "Vivian", "Ryan", "Aiden", "Cherry", "Ethan",
        "Serena", "Ada", "Nova", "Aria", "Axel",
        "Ember", "Miles", "Luna", "Leo", "Aurora", "Echo",
    ]

    def _synthesize(text: str, voice: str) -> tuple[np.ndarray, int]:
        voice = voice.strip().capitalize()
        if voice not in VOICES:
            voice = "Ryan"
        wavs, sr = _qwen.generate_custom_voice(text=text, language="English", speaker=voice)
        return wavs[0], sr


# ── Shared audio helper ───────────────────────────────────────
def _to_wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    audio_int16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    wavfile.write(buf, sr, audio_int16)
    return buf.getvalue()


# ── Routes ────────────────────────────────────────────────────
@app.get("/synthesize")
async def synthesize(
    text:  str = Query(...),
    voice: str = Query("am_michael" if ENGINE == "kokoro" else "Ryan"),
):
    try:
        samples, sr = _synthesize(text, voice)
        return Response(content=_to_wav_bytes(samples, sr), media_type="audio/wav")
    except Exception as e:
        print(f"  [TTS] Error: {e}")
        return Response(content=b"", status_code=500)

@app.get("/health")
async def health():
    return {"status": "ok", "engine": ENGINE}

@app.get("/voices")
async def voices():
    return {"voices": VOICES}


# ── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"  TTS server ({ENGINE}) on http://localhost:{PORT}")
    print(f"  Test: curl 'http://localhost:{PORT}/synthesize?text=Hello&voice={VOICES[0]}' --output test.wav\n")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")