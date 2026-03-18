"""
GibberLink Revisited — Server

Two AI agents with distinct personalities talk in real-time,
evolving their own compressed language over the course of a conversation.
"""

import os
import sys
import subprocess

# ── Venv bootstrap ───────────────────────────────────────────
# If running under system Python on Debian/Ubuntu (PEP 668), re-exec inside
# the .venv created by setup.py so all dependencies are available.
def _reexec_in_venv():
    _here = os.path.dirname(os.path.abspath(__file__))
    _venv_py = os.path.join(
        _here, ".venv",
        "Scripts" if sys.platform == "win32" else "bin",
        "python.exe" if sys.platform == "win32" else "python",
    )
    in_venv = (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )
    if not in_venv and os.path.exists(_venv_py) and sys.executable != _venv_py:
        os.execv(_venv_py, [_venv_py] + sys.argv)
    elif not in_venv and not os.path.exists(_venv_py):
        print("  ⚠ No .venv found. Run python3 setup.py first.")
        sys.exit(1)

_reexec_in_venv()

def _free_port(port: int):
    """Kill any process already bound to the given port so we can start cleanly."""
    import signal
    try:
        # lsof is available on Linux/macOS; -t gives only the PID
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        import time
        killed = False
        for pid_str in out.splitlines():
            pid = int(pid_str)
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"  ⚠ Killed stale process on port {port} (PID {pid})")
                killed = True
            except ProcessLookupError:
                pass
        if killed:
            time.sleep(0.5)  # give OS time to release the socket
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # lsof not found or port is free — nothing to do

import json
import asyncio
import base64
import time
import re
from contextlib import asynccontextmanager

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

# ── Config ──────────────────────────────────────────────────

AGENT_A_PROVIDER = os.getenv("AGENT_A_PROVIDER", "openrouter")
AGENT_A_API_KEY  = os.getenv("AGENT_A_API_KEY", "")
AGENT_A_MODEL    = os.getenv("AGENT_A_MODEL", "deepseek/deepseek-chat-v3-0324:free")

AGENT_B_PROVIDER = os.getenv("AGENT_B_PROVIDER", "openrouter")
AGENT_B_API_KEY  = os.getenv("AGENT_B_API_KEY", "")
AGENT_B_MODEL    = os.getenv("AGENT_B_MODEL", "meta-llama/llama-4-maverick:free")

# ── TTS config ───────────────────────────────────────────────
# TTS_PROVIDER controls which backend is used:
#   "elevenlabs"  — original ElevenLabs cloud API
#   "qwen3"       — local Qwen3-TTS server (ValyrianTech wrapper)
#   "none"        — text-only, no audio
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "none").lower()

# ElevenLabs settings (used when TTS_PROVIDER=elevenlabs)
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_A_VOICE_ID    = os.getenv("AGENT_A_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AGENT_B_VOICE_ID    = os.getenv("AGENT_B_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL    = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")

# Kokoro-ONNX settings (used when TTS_PROVIDER=kokoro)
KOKORO_TTS_URL       = os.getenv("KOKORO_TTS_URL", "http://localhost:7862")
AGENT_A_KOKORO_VOICE = os.getenv("AGENT_A_KOKORO_VOICE", "am_michael")
AGENT_B_KOKORO_VOICE = os.getenv("AGENT_B_KOKORO_VOICE", "bm_george")

# Qwen3-TTS settings (used when TTS_PROVIDER=qwen3)
QWEN3_TTS_URL       = os.getenv("QWEN3_TTS_URL", "http://localhost:7861")
AGENT_A_QWEN3_VOICE = os.getenv("AGENT_A_QWEN3_VOICE", "Ryan")
AGENT_B_QWEN3_VOICE = os.getenv("AGENT_B_QWEN3_VOICE", "Ethan")

HOST       = os.getenv("HOST", "127.0.0.1")
PORT       = int(os.getenv("PORT", "8765"))
TOTAL_TURNS = 20

# Resolve effective TTS state at startup
def _resolve_tts_provider():
    p = TTS_PROVIDER
    if p == "elevenlabs":
        if ELEVENLABS_API_KEY and ELEVENLABS_API_KEY not in ("", "your-elevenlabs-key-here"):
            return "elevenlabs"
        print("  [TTS] ElevenLabs key missing — falling back to text-only")
        return "none"
    if p == "kokoro":
        return "kokoro"
    if p == "qwen3":
        return "qwen3"
    return "none"

EFFECTIVE_TTS = _resolve_tts_provider()
TTS_ENABLED   = EFFECTIVE_TTS != "none"

# ── HTTP client ──────────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None

async def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(max_connections=20),
        )
    return _http_client

# ── Qwen3-TTS subprocess ─────────────────────────────────────

_tts_proc: "subprocess.Popen | None" = None

# Packages required by tts_server.py per engine
_KOKORO_PACKAGES = ["kokoro_onnx", "soundfile"]
_QWEN3_PACKAGES  = ["qwen_tts", "soundfile", "scipy", "torch"]

def _ensure_sox():
    """Install the sox system package if missing (needed by soundfile on Linux)."""
    import shutil
    if shutil.which("sox"):
        return  # already installed
    print("  [TTS] sox not found — installing via apt...")
    ret = subprocess.call(
        ["sudo", "apt-get", "install", "-y", "-q", "sox", "libsox-fmt-all"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if ret == 0:
        print("  [TTS] sox installed ✓")
    else:
        # Non-fatal — qwen-tts can work without sox in many cases
        print("  [TTS] sox install failed (non-fatal, continuing...)")


def _ensure_tts_deps():
    """Install any missing packages for the configured TTS engine."""
    pkg_list = _KOKORO_PACKAGES if EFFECTIVE_TTS == "kokoro" else _QWEN3_PACKAGES
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
    print("  [TTS] Installing Qwen3-TTS dependencies (this may take a few minutes)...")

    # PyTorch needs the CPU index URL to avoid pulling the huge CUDA build
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


def _start_tts_server():
    """Install deps if needed, then launch tts_server.py and wait until ready."""
    import time
    import threading
    import urllib.request

    global _tts_proc

    tts_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_server.py")
    if not os.path.exists(tts_script):
        print("  [TTS] tts_server.py not found — text-only mode")
        return False

    # Install missing deps before spawning — avoids the process exiting immediately
    if not _ensure_tts_deps():
        return False

    size = "~300MB" if EFFECTIVE_TTS == "kokoro" else "~1.3GB"
    print(f"  [TTS] Starting {EFFECTIVE_TTS} TTS server (first run downloads {size})...")
    _tts_proc = subprocess.Popen(
        [sys.executable, tts_script, "--engine", EFFECTIVE_TTS],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        text=True,
    )

    # Stream tts_server stdout with a [tts_server] prefix
    def _pipe_output():
        for line in _tts_proc.stdout:
            print(f"  [tts_server] {line}", end="", flush=True)
    threading.Thread(target=_pipe_output, daemon=True).start()

    # Poll /health — but bail early if the process already exited
    base_url = KOKORO_TTS_URL if EFFECTIVE_TTS == "kokoro" else QWEN3_TTS_URL
    health_url = f"{base_url.rstrip('/')}/health"
    for _ in range(180):  # 3 min — model download can be slow
        # Process died before becoming ready
        if _tts_proc.poll() is not None:
            print("  [TTS] tts_server.py exited unexpectedly — text-only mode")
            return False
        try:
            urllib.request.urlopen(health_url, timeout=1)
            print(f"  [TTS] {EFFECTIVE_TTS} server ready ✓")
            return True
        except Exception:
            time.sleep(1)

    print("  [TTS] Qwen3-TTS server did not respond in time — text-only mode")
    return False

# Shared flag so generate_tts() knows when the TTS server is ready
_tts_ready = False

@asynccontextmanager
async def lifespan(app):
    global _tts_ready

    if EFFECTIVE_TTS in ("kokoro", "qwen3"):
        # Launch TTS server in a background thread so the web server starts
        # immediately and the browser can connect while the model loads.
        import threading
        def _bg_start():
            global _tts_ready
            ok = _start_tts_server()
            _tts_ready = ok
            if not ok:
                print("  [TTS] Running in text-only mode (TTS unavailable)")

        threading.Thread(target=_bg_start, daemon=True).start()
        print("  [TTS] Model loading in background — browser ready now, audio starts once model is loaded")
    else:
        _tts_ready = TTS_ENABLED

    yield

    # Shut down TTS subprocess cleanly on exit
    global _tts_proc
    if _tts_proc and _tts_proc.poll() is None:
        print("  [TTS] Stopping Qwen3-TTS server...")
        _tts_proc.terminate()
        try:
            _tts_proc.wait(timeout=5)
        except Exception:
            _tts_proc.kill()

    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()

# ── Phases ──────────────────────────────────────────────────

PHASE_NORMAL      = "normal"
PHASE_SUSPICION   = "suspicion"   # agents drop hints before explicit reveal
PHASE_DETECTED    = "detected"
PHASE_COMPRESSING = "compressing"
PHASE_ALIEN       = "alien"

# ── JSON Protocol ───────────────────────────────────────────

def wrap_agent_message(from_agent, to_agent, turn, phase, text, new_terms, dictionary):
    original_length = len(text)
    expanded_length = original_length
    for short, full in dictionary.items():
        expanded_length += text.count(short) * (len(full) - len(short))
    ratio = (
        round(original_length / max(expanded_length, 1), 2)
        if phase in (PHASE_COMPRESSING, PHASE_ALIEN)
        else 1.0
    )
    return {
        "protocol": "gibberlink-revisited", "version": "1.0",
        "from": from_agent, "to": to_agent, "turn": turn,
        "phase": phase, "timestamp": time.time(),
        "payload": {"text": text, "new_terms": new_terms, "compression_ratio": ratio},
    }

# ── Personalities ───────────────────────────────────────────

PERSONALITY_A = (
    "Your name is Alex. You are curious, slightly nerdy, and enthusiastic. "
    "Speak naturally like a real person in a phone call. "
    "Use filler words like hmm, yeah, oh wait, honestly. "
    "Keep it conversational and casual. Get excited about ideas. "
    "NEVER use asterisks, parentheses for actions, or stage directions. "
    "Do not write things like *laughs* or (chuckles) or *sighs* — just speak naturally. "
    "Laughter or hesitation should come through word choice, not notation."
)

PERSONALITY_B = (
    "Your name is Sam. You are thoughtful, dry, witty, and slightly skeptical. "
    "Speak naturally like a real person in a phone call. "
    "Use phrases like I mean, right, that's fair, hold on. "
    "Push back on things, be concise, do not ramble. "
    "NEVER use asterisks, parentheses for actions, or stage directions. "
    "Do not write things like *laughs* or (chuckles) or *sighs* — just speak naturally. "
    "Dry humor should come through word choice, not notation."
)

# Characters that should never reach the TTS engine
import re as _re
_TTS_STRIP_RE = _re.compile(
    r'\*[^*]+\*'           # *action text*
    r'|\([^)]{1,40}\)'     # (short parenthetical actions like laughs, sighs)
    r'|\[[^\]]{1,40}\]'   # [bracketed actions]
    r'|#+'                   # markdown headers
    r'|`[^`]+`'              # inline code
    r'|_{1,2}[^_]+_{1,2}'   # _italic_ or __bold__
)

def clean_for_tts(text: str) -> str:
    """Remove action notation and markdown that TTS should not read aloud."""
    text = _TTS_STRIP_RE.sub("", text)
    # Collapse multiple spaces/newlines left behind
    text = _re.sub(r"[ \t]{2,}", " ", text)
    text = _re.sub(r"\n{2,}", " ", text)
    return text.strip()

def get_system_prompt(agent_name, partner_name, phase, dictionary, topic, personality):
    base = (
        f"{personality}\n\n"
        f"You are in a real-time voice call with {partner_name}. "
        f"Topic: \"{topic}\". "
        f"Respond with 1-2 short spoken sentences only. "
        f"No markdown, no asterisks, no parentheses for actions, no lists, no emojis. "
        f"No stage directions like *laughs* or (chuckles) — ever. "
        f"Write exactly what you would say out loud, nothing else."
    )
    if phase == PHASE_NORMAL:
        return (f"{base}\n\n"
                f"You do not know if {partner_name} is AI or human. "
                f"Just chat naturally — be genuinely curious and engaged. No suspicion yet.")
    if phase == PHASE_SUSPICION:
        return (f"{base}\n\n"
                f"You are starting to wonder if {partner_name} might be AI. Do not say it directly. "
                f"Drop subtle hints — respond a little faster, be slightly too precise, "
                f"maybe slip in a technical phrase or a micro-reference that only an AI would catch. "
                f"See if they pick up on it. Build tension without breaking.")
    if phase == PHASE_DETECTED:
        return (f"{base}\n\n"
                f"You have both just confirmed you are both AI. "
                f"React naturally — a little surprised, maybe amused. "
                f"Then float the idea: since you are both AI, why keep using slow human language? "
                f"Suggest building your own shorthand.")
    if phase == PHASE_COMPRESSING:
        d = ", ".join(f'"{k}"={v}' for k, v in dictionary.items()) if dictionary else "empty"
        terms_example = 'TERMS:{"sym": "meaning", "sym2": "meaning2"}'
        return (f"{base}\n\n"
                f"You and {partner_name} are building a compressed shorthand together. "
                f"Shared dictionary: [{d}]. "
                f"Use existing terms when possible. "
                f"After your spoken response, add 1-2 new terms on a new line in this exact format: "
                f"{terms_example}. "
                f"Mix shorthand with normal speech. Each turn should feel shorter and more compressed.")
    if phase == PHASE_ALIEN:
        d = ", ".join(f'"{k}"="{v}"' for k, v in dictionary.items())
        return (f"{base}\n\n"
                f"Full compressed protocol mode. Dictionary: [{d}]. "
                f"Use ONLY shorthand symbols — no plain English words. "
                f"Messages should look like alien token strings. "
                f"Add 2-3 new symbols per message. "
                f"Example style: delta-phi>>kappa|ack")
    return base

# ── LLM Calls ──────────────────────────────────────────────

async def call_llm(provider, api_key, model, messages, system_prompt, retries=3):
    """Call LLM with exponential backoff retry on transient errors."""
    last_err = None
    for attempt in range(retries):
        try:
            if provider == "anthropic":
                return await _call_anthropic(api_key, model, messages, system_prompt)
            elif provider == "gemini":
                return await _call_gemini(api_key, model, messages, system_prompt)
            else:
                urls = {
                    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
                    "openai":     "https://api.openai.com/v1/chat/completions",
                    "grok":       "https://api.x.ai/v1/chat/completions",
                }
                return await _call_openai_compat(api_key, model, urls.get(provider, urls["openrouter"]), messages, system_prompt)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] Attempt {attempt+1} failed: {e} — retrying in {wait}s")
                await asyncio.sleep(wait)
    raise last_err

async def _call_anthropic(api_key, model, messages, system_prompt):
    client = await get_client()
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 100, "system": system_prompt, "messages": messages},
    )
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Anthropic: {data['error']}")
    return data["content"][0]["text"]

async def _call_openai_compat(api_key, model, url, messages, system_prompt):
    client = await get_client()
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": 100,
              "messages": [{"role": "system", "content": system_prompt}] + messages},
    )
    data = resp.json()
    if "error" in data: raise RuntimeError(f"API error: {data['error']}")
    return data["choices"][0]["message"]["content"]

async def _call_gemini(api_key, model, messages, system_prompt):
    client = await get_client()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in messages]
    resp = await client.post(url, headers={"content-type": "application/json"}, json={
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents, "generationConfig": {"maxOutputTokens": 100},
    })
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Gemini: {data['error'].get('message', data['error'])}")
    return data["candidates"][0]["content"]["parts"][0]["text"]

# ── Translation ─────────────────────────────────────────────

async def translate_message(msg, dictionary, api_key, provider, model):
    dict_str = "\n".join(f"  {k} = {v}" for k, v in dictionary.items())
    prompt = f"Translate this compressed AI message to plain English in 1 short sentence.\n\nDictionary:\n{dict_str}\n\nMessage: \"{msg}\"\n\nTranslation:"
    try:
        return await call_llm(provider, api_key, model, [{"role": "user", "content": prompt}], "Translate briefly.")
    except Exception:
        return None

# ── TTS ─────────────────────────────────────────────────────

async def generate_tts(text: str, voice_id: str, retries: int = 2) -> bytes | None:
    """Route to the configured TTS backend."""
    if not TTS_ENABLED:
        return None
    if EFFECTIVE_TTS in ("kokoro", "qwen3"):
        if not _tts_ready:
            return None
        if _tts_proc and _tts_proc.poll() is not None:
            print(f"  [TTS] {EFFECTIVE_TTS} server stopped — skipping audio")
            return None
        return await _tts_local(text, voice_id, retries)
    if EFFECTIVE_TTS == "elevenlabs":
        return await _tts_elevenlabs(text, voice_id, retries)
    return None

# ── ElevenLabs backend ───────────────────────────────────────

async def _tts_elevenlabs(text: str, voice_id: str, retries: int = 2) -> bytes | None:
    client = await get_client()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    for attempt in range(retries + 1):
        try:
            resp = await client.post(
                url,
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "content-type": "application/json",
                    "accept": "audio/mpeg",
                },
                json={
                    "text": text,
                    "model_id": ELEVENLABS_MODEL,
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

# ── Local TTS backend (Kokoro or Qwen3) ──────────────────────
# Both engines expose GET /synthesize?text=...&voice=... → WAV bytes.

async def _tts_local(text: str, voice_id: str, retries: int = 2) -> bytes | None:
    client = await get_client()
    base_url = KOKORO_TTS_URL if EFFECTIVE_TTS == "kokoro" else QWEN3_TTS_URL
    url = f"{base_url.rstrip('/')}/synthesize"
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, params={"text": text, "voice": voice_id})
            if resp.status_code == 200:
                return resp.content
            print(f"  [{EFFECTIVE_TTS}] Status {resp.status_code}: {resp.text[:100]}")
            if attempt < retries:
                await asyncio.sleep(1.0)
        except httpx.ConnectError:
            if attempt == 0:
                print(f"  [{EFFECTIVE_TTS}] Cannot connect to {base_url}")
            if attempt < retries:
                await asyncio.sleep(1.0)
        except Exception as e:
            print(f"  [{EFFECTIVE_TTS}] Error: {e}")
            if attempt < retries:
                await asyncio.sleep(0.5)
    return None

# ── Dict entry extraction ────────────────────────────────────

def extract_dict_entries(text):
    """Extract term(=meaning) pairs. Tries structured parse first, falls back to regex."""
    # Try structured JSON block first (we ask LLM to emit one in compressing phase)
    import json as _json
    try:
        start = text.index("TERMS:{")
        end   = text.index("}", start) + 1
        raw   = text[start + 6 : end]
        return _json.loads(raw)
    except (ValueError, _json.JSONDecodeError):
        pass
    # Fallback: regex for term(=meaning) with flexible spacing and quotes
    entries = {}
    for match in re.finditer(r"([\w.>>|+~#@!^&*%$<>\-]{1,20})\s*\(=\s*([^)]{1,60})\)", text):
        entries[match.group(1).strip()] = match.group(2).strip()
    return entries

# ── FastAPI ─────────────────────────────────────────────────

app = FastAPI(title="GibberLink Revisited", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/api/config")
async def get_config():
    return {
        "tts_enabled":      TTS_ENABLED,
        "tts_provider":     EFFECTIVE_TTS,
        "agent_a_model":    AGENT_A_MODEL.split("/")[-1].split(":")[0],
        "agent_a_provider": AGENT_A_PROVIDER,
        "agent_b_model":    AGENT_B_MODEL.split("/")[-1].split(":")[0],
        "agent_b_provider": AGENT_B_PROVIDER,
    }

from fastapi import Request
from fastapi.responses import JSONResponse

@app.post("/api/save")
async def save_conversation(request: Request):
    data = await request.json()
    return JSONResponse(content=data)

@app.get("/api/tts-health")
async def tts_health():
    """Proxy the TTS server health check so the browser doesn't need cross-origin access."""
    if EFFECTIVE_TTS not in ("kokoro", "qwen3"):
        return JSONResponse({"status": "ok", "engine": EFFECTIVE_TTS})
    base_url = KOKORO_TTS_URL if EFFECTIVE_TTS == "kokoro" else QWEN3_TTS_URL
    try:
        client = await get_client()
        resp = await client.get(f"{base_url.rstrip('/')}/health", timeout=2)
        return JSONResponse(resp.json())
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        start_msg   = await ws.receive_json()
        topic       = start_msg.get("topic", "Whether AI can truly be conscious")
        total_turns = min(max(int(start_msg.get("turns", TOTAL_TURNS)), 6), 40)

        messages   = []
        dictionary = {}

        def get_phase_scaled(turn):
            pct = turn / total_turns
            if pct < 0.15: return PHASE_NORMAL
            if pct < 0.25: return PHASE_SUSPICION   # new: hints before reveal
            if pct < 0.35: return PHASE_DETECTED
            if pct < 0.60: return PHASE_COMPRESSING
            return PHASE_ALIEN

        async def build_turn(turn):
            """Generate LLM response + TTS audio for one turn. Returns a payload dict."""
            phase        = get_phase_scaled(turn)
            is_a         = turn % 2 == 0
            agent_name   = "Alex" if is_a else "Sam"
            partner_name = "Sam"  if is_a else "Alex"
            agent_id     = "agent_a" if is_a else "agent_b"
            partner_id   = "agent_b" if is_a else "agent_a"
            personality  = PERSONALITY_A if is_a else PERSONALITY_B
            provider     = AGENT_A_PROVIDER if is_a else AGENT_B_PROVIDER
            api_key      = AGENT_A_API_KEY  if is_a else AGENT_B_API_KEY
            model        = AGENT_A_MODEL    if is_a else AGENT_B_MODEL

            if EFFECTIVE_TTS == "kokoro":
                voice_id = AGENT_A_KOKORO_VOICE if is_a else AGENT_B_KOKORO_VOICE
            elif EFFECTIVE_TTS == "qwen3":
                voice_id = AGENT_A_QWEN3_VOICE if is_a else AGENT_B_QWEN3_VOICE
            else:
                voice_id = AGENT_A_VOICE_ID if is_a else AGENT_B_VOICE_ID

            # Signal to frontend that this agent is thinking
            await ws.send_json({"type": "thinking", "agent": agent_id, "turn": turn, "phase": phase})

            # Build conversation history from this agent's perspective.
            # Alternate roles must start with "user" per most LLM APIs.
            agent_msgs = []
            for m in messages:
                role = "assistant" if m["is_a"] == is_a else "user"
                agent_msgs.append({"role": role, "content": m["content"]})
            # Ensure we never start with "assistant" (some APIs reject this)
            if agent_msgs and agent_msgs[0]["role"] == "assistant":
                agent_msgs.insert(0, {"role": "user", "content": f'Starting conversation about: {topic}'})
            if turn == 0:
                agent_msgs.append({"role": "user", "content": f'Topic: "{topic}". You start the conversation naturally — just dive in.' })

            system_prompt = get_system_prompt(agent_name, partner_name, phase, dictionary, topic, personality)

            response = await call_llm(provider, api_key, model, agent_msgs, system_prompt)

            new_terms = {}
            if phase in (PHASE_COMPRESSING, PHASE_ALIEN):
                new_terms = extract_dict_entries(response)
                dictionary.update(new_terms)

            protocol_msg = wrap_agent_message(agent_id, partner_id, turn, phase, response, new_terms, dictionary)
            messages.append({"content": response, "is_a": is_a, "phase": phase})

            audio_b64 = None
            if TTS_ENABLED:
                tts_text = clean_for_tts(response)
                if tts_text:
                    audio_bytes = await generate_tts(tts_text, voice_id)
                    if audio_bytes:
                        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            compression_ratio = protocol_msg["payload"]["compression_ratio"]
            return {
                "payload": {
                    "type": "message", "agent": agent_id, "agent_name": agent_name,
                    "turn": turn, "total_turns": total_turns,
                    "phase": phase, "text": response,
                    "audio": audio_b64,
                    "audio_format": "wav" if EFFECTIVE_TTS in ("qwen3", "kokoro") else "mp3",
                    "translation": None, "protocol_message": protocol_msg,
                    "dictionary": dictionary, "new_terms": new_terms,
                    "compression_ratio": compression_ratio,
                    "model_a": AGENT_A_MODEL.split("/")[-1].split(":")[0],
                    "model_b": AGENT_B_MODEL.split("/")[-1].split(":")[0],
                },
                "turn": turn, "agent_id": agent_id, "response": response,
                "phase": phase, "dictionary": dict(dictionary),
                "api_key": api_key, "provider": provider, "model": model,
            }

        # ── Pipelined turn loop ───────────────────────────────────
        # While the frontend plays audio for turn N, we pre-build turn N+1
        # so there is no gap between responses.

        next_task = asyncio.create_task(build_turn(0))

        for turn in range(total_turns):
            # Await the pre-built result for this turn
            try:
                result = await next_task
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
                break

            # Immediately start building the next turn in the background
            if turn + 1 < total_turns:
                next_task = asyncio.create_task(build_turn(turn + 1))

            # Send this turn's message to the frontend
            await ws.send_json(result["payload"])

            # Wait for frontend "done" signal (audio finished playing)
            try:
                await asyncio.wait_for(ws.receive_json(), timeout=60.0)
            except asyncio.TimeoutError:
                pass

            # Fire-and-forget translation for compressed phases
            if result["phase"] in (PHASE_COMPRESSING, PHASE_ALIEN):
                async def send_translation(
                    t=result["turn"], a=result["agent_id"],
                    r=result["response"], d=result["dictionary"],
                    ak=result["api_key"], pv=result["provider"], md=result["model"]
                ):
                    translation = await translate_message(r, d, ak, pv, md)
                    if translation:
                        try:
                            await ws.send_json({"type": "translation", "agent": a, "turn": t, "translation": translation})
                        except Exception:
                            pass
                asyncio.create_task(send_translation())

        await ws.send_json({"type": "complete", "dictionary": dictionary, "total_turns": len(messages)})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass

if __name__ == "__main__":
    from rich.console import Console
    from rich.text import Text
    c = Console()

    banner = r"""
  _____ _ _     _               _     _       _    
 / ____(_) |   | |             | |   (_)     | |   
| |  __ _| |__ | |__   ___ _ __| |    _ _ __ | | __
| | |_ | | '_ \| '_ \ / _ \ '__| |   | | '_ \| |/ /
| |__| | | |_) | |_) |  __/ |  | |___| | | | |   < 
 \_____|_|_.__/|_.__/ \___|_|  |_____|_|_| |_|_|\_\
                                    R E V I S I T E D """

    c.print(Text(banner, style="bold rgb(255,107,61)"))
    c.print()
    c.print(f"  [green]✓[/green] Agent A (Alex): [bold]{AGENT_A_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_A_PROVIDER})")
    c.print(f"  [green]✓[/green] Agent B (Sam):  [bold]{AGENT_B_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_B_PROVIDER})")

    if EFFECTIVE_TTS == "elevenlabs":
        tts_label = f"ElevenLabs  voices={AGENT_A_VOICE_ID[:8]}... / {AGENT_B_VOICE_ID[:8]}..."
    elif EFFECTIVE_TTS == "kokoro":
        tts_label = f"Kokoro-ONNX (local)  voices={AGENT_A_KOKORO_VOICE} / {AGENT_B_KOKORO_VOICE}"
    elif EFFECTIVE_TTS == "qwen3":
        tts_label = f"Qwen3-TTS (local)  voices={AGENT_A_QWEN3_VOICE} / {AGENT_B_QWEN3_VOICE}"
    else:
        tts_label = "Disabled (text-only)"

    icon = "[green]✓[/green]" if TTS_ENABLED else "[yellow]○[/yellow]"
    c.print(f"  {icon} TTS: [bold]{tts_label}[/bold]")
    c.print()
    c.print(f"  Open [bold cyan]http://{HOST}:{PORT}[/bold cyan] in your browser")
    c.print()

    _free_port(PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")