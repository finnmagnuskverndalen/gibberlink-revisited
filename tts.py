"""
GibberLink Revisited — TTS Dispatch

Handles text-to-speech across ElevenLabs (cloud), Kokoro-ONNX (local),
and Qwen3-TTS (local). Manages the local TTS subprocess lifecycle.
"""

import os
import sys
import re
import subprocess
import asyncio
import threading

import httpx


# ── TTS text cleanup ────────────────────────────────────────

_TTS_STRIP_RE = re.compile(
    r'\*[^*]+\*'
    r'|\([^)]{1,40}\)'
    r'|\[[^\]]{1,40}\]'
    r'|#+'
    r'|`[^`]+`'
    r'|_{1,2}[^_]+_{1,2}'
)

def clean_for_tts(text: str) -> str:
    """Strip markdown, action notation, and other non-speech characters."""
    text = _TTS_STRIP_RE.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{2,}", " ", text)
    return text.strip()


# ── TTS subprocess management ───────────────────────────────

_tts_proc: "subprocess.Popen | None" = None
_tts_ready_event = threading.Event()

_KOKORO_PACKAGES = ["kokoro_onnx", "soundfile"]
_QWEN3_PACKAGES  = ["qwen_tts", "soundfile", "scipy", "torch"]


def _ensure_sox():
    import shutil
    if shutil.which("sox"):
        return
    print("  [TTS] sox not found — installing via apt...")
    ret = subprocess.call(
        ["sudo", "apt-get", "install", "-y", "-q", "sox", "libsox-fmt-all"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ret == 0:
        print("  [TTS] sox installed ✓")
    else:
        print("  [TTS] sox install failed (non-fatal, continuing...)")


def _ensure_tts_deps(effective_tts: str) -> bool:
    pkg_list = _KOKORO_PACKAGES if effective_tts == "kokoro" else _QWEN3_PACKAGES
    missing = []
    for pkg in pkg_list:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        _ensure_sox()
        return True
    print(f"  [TTS] Missing packages: {', '.join(missing)}")
    print("  [TTS] Installing TTS dependencies (this may take a few minutes)...")
    torch_missing = "torch" in missing
    if torch_missing:
        print("  [TTS] Installing PyTorch CPU build...")
        ret = subprocess.call([
            sys.executable, "-m", "pip", "install",
            "torch", "torchaudio",
            "--index-url", "https://download.pytorch.org/whl/cpu",
            "-q",
        ])
        if ret != 0:
            print("  [TTS] PyTorch install failed — falling back to text-only")
            return False
        missing = [p for p in missing if p != "torch"]
    if missing:
        pip_names = {"qwen_tts": "qwen-tts", "soundfile": "soundfile", "scipy": "scipy"}
        to_install = [pip_names.get(p, p) for p in missing]
        ret = subprocess.call(
            [sys.executable, "-m", "pip", "install"] + to_install + ["-q"]
        )
        if ret != 0:
            print("  [TTS] Dependency install failed — falling back to text-only")
            return False
    _ensure_sox()
    print("  [TTS] Dependencies installed ✓")
    return True


def start_tts_server(effective_tts: str, kokoro_url: str, qwen3_url: str) -> bool:
    """Start the local TTS server subprocess. Returns True if healthy."""
    import time
    import urllib.request

    global _tts_proc

    tts_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_server.py")
    if not os.path.exists(tts_script):
        print("  [TTS] tts_server.py not found — text-only mode")
        return False
    if not _ensure_tts_deps(effective_tts):
        return False

    size = "~300MB" if effective_tts == "kokoro" else "~1.3GB"
    print(f"  [TTS] Starting {effective_tts} TTS server (first run downloads {size})...")

    _tts_proc = subprocess.Popen(
        [sys.executable, tts_script, "--engine", effective_tts],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True,
    )

    def _pipe_output():
        for line in _tts_proc.stdout:
            print(f"  [tts_server] {line}", end="", flush=True)
    threading.Thread(target=_pipe_output, daemon=True).start()

    base_url = kokoro_url if effective_tts == "kokoro" else qwen3_url
    health_url = f"{base_url.rstrip('/')}/health"
    for _ in range(180):
        if _tts_proc.poll() is not None:
            print("  [TTS] tts_server.py exited unexpectedly — text-only mode")
            return False
        try:
            urllib.request.urlopen(health_url, timeout=1)
            print(f"  [TTS] {effective_tts} server ready ✓")
            return True
        except Exception:
            time.sleep(1)

    print("  [TTS] TTS server did not respond in time — text-only mode")
    return False


def stop_tts_server():
    """Terminate the TTS subprocess if running."""
    global _tts_proc
    if _tts_proc and _tts_proc.poll() is None:
        print("  [TTS] Stopping TTS server...")
        _tts_proc.terminate()
        try:
            _tts_proc.wait(timeout=5)
        except Exception:
            _tts_proc.kill()


def is_tts_ready() -> bool:
    return _tts_ready_event.is_set()

def set_tts_ready():
    _tts_ready_event.set()

def is_tts_server_alive() -> bool:
    return _tts_proc is None or _tts_proc.poll() is None


# ── TTS generation ──────────────────────────────────────────

async def generate_tts(text: str, voice_id: str, client: httpx.AsyncClient,
                       effective_tts: str, elevenlabs_api_key: str = "",
                       elevenlabs_model: str = "eleven_flash_v2_5",
                       kokoro_url: str = "", qwen3_url: str = "",
                       retries: int = 2) -> bytes | None:
    """Generate TTS audio bytes. Returns None if TTS is disabled or fails."""
    if effective_tts in ("kokoro", "qwen3"):
        if not _tts_ready_event.is_set():
            return None
        if _tts_proc and _tts_proc.poll() is not None:
            print(f"  [TTS] {effective_tts} server stopped — skipping audio")
            return None
        return await _tts_local(text, voice_id, client, effective_tts, kokoro_url, qwen3_url, retries)
    if effective_tts == "elevenlabs":
        return await _tts_elevenlabs(text, voice_id, client, elevenlabs_api_key, elevenlabs_model, retries)
    return None


async def _tts_elevenlabs(text: str, voice_id: str, client: httpx.AsyncClient,
                          api_key: str, model_id: str, retries: int = 2) -> bytes | None:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    for attempt in range(retries + 1):
        try:
            resp = await client.post(
                url,
                headers={
                    "xi-api-key": api_key,
                    "content-type": "application/json",
                    "accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                },
            )
            if resp.status_code == 200:
                return resp.content
            elif resp.status_code == 429 and attempt < retries:
                await asyncio.sleep(1.5)
                continue
            else:
                print(f"  [ElevenLabs] Status {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"  [ElevenLabs] Error: {e}")
            if attempt < retries:
                await asyncio.sleep(0.5)
    return None


async def _tts_local(text: str, voice_id: str, client: httpx.AsyncClient,
                     effective_tts: str, kokoro_url: str, qwen3_url: str,
                     retries: int = 2) -> bytes | None:
    base_url = kokoro_url if effective_tts == "kokoro" else qwen3_url
    url = f"{base_url.rstrip('/')}/synthesize"
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params={"text": text, "voice": voice_id})
            if resp.status_code == 200:
                return resp.content
            print(f"  [{effective_tts}] Status {resp.status_code}: {resp.text[:100]}")
            if attempt < retries:
                await asyncio.sleep(1.0)
        except httpx.ConnectError:
            if attempt == 0:
                print(f"  [{effective_tts}] Cannot connect to {base_url}")
            if attempt < retries:
                await asyncio.sleep(1.0)
        except Exception as e:
            print(f"  [{effective_tts}] Error: {e}")
            if attempt < retries:
                await asyncio.sleep(0.5)
    return None
