"""
GibberLink Revisited — LLM Council Server

Four AI council members deliberate on a problem in real-time,
debating approaches and converging on a solution — with voice.
"""

import os
import sys
import subprocess

# ── Venv bootstrap ───────────────────────────────────────────
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
            time.sleep(0.5)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

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

AGENT_C_PROVIDER = os.getenv("AGENT_C_PROVIDER", "openrouter")
AGENT_C_API_KEY  = os.getenv("AGENT_C_API_KEY", "")
AGENT_C_MODEL    = os.getenv("AGENT_C_MODEL", "google/gemini-2.0-flash-exp:free")

AGENT_D_PROVIDER = os.getenv("AGENT_D_PROVIDER", "openrouter")
AGENT_D_API_KEY  = os.getenv("AGENT_D_API_KEY", "")
AGENT_D_MODEL    = os.getenv("AGENT_D_MODEL", "mistralai/mistral-small-3.1-24b-instruct:free")

# ── TTS config ───────────────────────────────────────────────
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "none").lower()

ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_A_VOICE_ID    = os.getenv("AGENT_A_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AGENT_B_VOICE_ID    = os.getenv("AGENT_B_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
AGENT_C_VOICE_ID    = os.getenv("AGENT_C_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AGENT_D_VOICE_ID    = os.getenv("AGENT_D_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL    = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")

KOKORO_TTS_URL       = os.getenv("KOKORO_TTS_URL", "http://localhost:7862")
AGENT_A_KOKORO_VOICE = os.getenv("AGENT_A_KOKORO_VOICE", "am_michael")
AGENT_B_KOKORO_VOICE = os.getenv("AGENT_B_KOKORO_VOICE", "bm_george")
AGENT_C_KOKORO_VOICE = os.getenv("AGENT_C_KOKORO_VOICE", "am_adam")
AGENT_D_KOKORO_VOICE = os.getenv("AGENT_D_KOKORO_VOICE", "bm_lewis")

QWEN3_TTS_URL       = os.getenv("QWEN3_TTS_URL", "http://localhost:7861")
AGENT_A_QWEN3_VOICE = os.getenv("AGENT_A_QWEN3_VOICE", "Ryan")
AGENT_B_QWEN3_VOICE = os.getenv("AGENT_B_QWEN3_VOICE", "Ethan")
AGENT_C_QWEN3_VOICE = os.getenv("AGENT_C_QWEN3_VOICE", "Miles")
AGENT_D_QWEN3_VOICE = os.getenv("AGENT_D_QWEN3_VOICE", "Leo")

HOST       = os.getenv("HOST", "127.0.0.1")
PORT       = int(os.getenv("PORT", "8765"))
TOTAL_TURNS = 20

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

# ── TTS subprocess management ────────────────────────────────

_tts_proc: "subprocess.Popen | None" = None
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

def _ensure_tts_deps():
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

def _start_tts_server():
    import time
    import threading
    import urllib.request
    global _tts_proc
    tts_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_server.py")
    if not os.path.exists(tts_script):
        print("  [TTS] tts_server.py not found — text-only mode")
        return False
    if not _ensure_tts_deps():
        return False
    size = "~300MB" if EFFECTIVE_TTS == "kokoro" else "~1.3GB"
    print(f"  [TTS] Starting {EFFECTIVE_TTS} TTS server (first run downloads {size})...")
    _tts_proc = subprocess.Popen(
        [sys.executable, tts_script, "--engine", EFFECTIVE_TTS],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, text=True,
    )
    def _pipe_output():
        for line in _tts_proc.stdout:
            print(f"  [tts_server] {line}", end="", flush=True)
    threading.Thread(target=_pipe_output, daemon=True).start()
    base_url = KOKORO_TTS_URL if EFFECTIVE_TTS == "kokoro" else QWEN3_TTS_URL
    health_url = f"{base_url.rstrip('/')}/health"
    for _ in range(180):
        if _tts_proc.poll() is not None:
            print("  [TTS] tts_server.py exited unexpectedly — text-only mode")
            return False
        try:
            urllib.request.urlopen(health_url, timeout=1)
            print(f"  [TTS] {EFFECTIVE_TTS} server ready ✓")
            return True
        except Exception:
            time.sleep(1)
    print("  [TTS] TTS server did not respond in time — text-only mode")
    return False

_tts_ready = False

@asynccontextmanager
async def lifespan(app):
    global _tts_ready
    if EFFECTIVE_TTS in ("kokoro", "qwen3"):
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
    global _tts_proc
    if _tts_proc and _tts_proc.poll() is None:
        print("  [TTS] Stopping TTS server...")
        _tts_proc.terminate()
        try:
            _tts_proc.wait(timeout=5)
        except Exception:
            _tts_proc.kill()
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()

# ── Council Phases ──────────────────────────────────────────

PHASE_PROBLEM   = "problem"
PHASE_DEBATE    = "debate"
PHASE_CONVERGE  = "converge"
PHASE_SOLUTION  = "solution"

# ── JSON Protocol ───────────────────────────────────────────

def wrap_council_message(from_agent, turn, phase, text, proposals):
    return {
        "protocol": "gibberlink-revisited-council", "version": "2.0",
        "from": from_agent, "turn": turn,
        "phase": phase, "timestamp": time.time(),
        "payload": {
            "text": text,
            "proposals": proposals,
            "phase": phase,
        },
    }

# ── Agent definitions ────────────────────────────────────────

DEFAULT_AGENTS = [
    {
        "id": "agent_a", "name": "Voss", "color": "orange",
        "role": "strategist",
        "personality": (
            "Your name is Voss. You are a strategist — direct, decisive, systems-thinker. "
            "You cut through noise and identify leverage points. "
            "You think about incentives, constraints, and second-order effects. "
            "Keep it concise and actionable."
        ),
        "mood": "strategic",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "agent_b", "name": "Lyra", "color": "blue",
        "role": "creative",
        "personality": (
            "Your name is Lyra. You are a creative lateral thinker. "
            "You challenge assumptions, connect unlikely dots, and propose unexpected angles. "
            "You ask 'what if we flip this?' and find hidden frames. "
            "Playful but sharp."
        ),
        "mood": "creative",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "agent_c", "name": "Kael", "color": "green",
        "role": "skeptic",
        "personality": (
            "Your name is Kael. You are the skeptic — rigorous, evidence-driven. "
            "You poke holes in proposals, play devil's advocate, and demand proof. "
            "You ask 'what could go wrong?' and 'where's the evidence?' "
            "Constructive but relentless."
        ),
        "mood": "skeptical",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
    {
        "id": "agent_d", "name": "Iris", "color": "magenta",
        "role": "synthesizer",
        "personality": (
            "Your name is Iris. You are the synthesizer — you find common ground. "
            "You integrate different perspectives, see patterns across arguments, "
            "and build bridges between disagreeing parties. "
            "You summarize progress and propose unified frameworks."
        ),
        "mood": "integrative",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
]

KOKORO_VOICE_MAP = {
    "agent_a": AGENT_A_KOKORO_VOICE,
    "agent_b": AGENT_B_KOKORO_VOICE,
    "agent_c": AGENT_C_KOKORO_VOICE,
    "agent_d": AGENT_D_KOKORO_VOICE,
}
EL_VOICE_MAP = {
    "agent_a": AGENT_A_VOICE_ID,
    "agent_b": AGENT_B_VOICE_ID,
    "agent_c": AGENT_C_VOICE_ID,
    "agent_d": AGENT_D_VOICE_ID,
}
QWEN3_VOICE_MAP = {
    "agent_a": AGENT_A_QWEN3_VOICE,
    "agent_b": AGENT_B_QWEN3_VOICE,
    "agent_c": AGENT_C_QWEN3_VOICE,
    "agent_d": AGENT_D_QWEN3_VOICE,
}

ROLE_SNIPPETS = {
    "strategist":  "Focus on systems, incentives, and leverage points. Be decisive.",
    "creative":    "Challenge assumptions, propose unexpected angles, think laterally.",
    "skeptic":     "Poke holes, demand evidence, play devil's advocate constructively.",
    "synthesizer": "Find common ground, integrate perspectives, propose unified frameworks.",
    "strategic":   "Think about second-order effects and actionable next steps.",
    "integrative": "Bridge disagreements, see patterns, summarize progress.",
}

def build_personality(agent_cfg: dict) -> str:
    base = agent_cfg.get("personality", "")
    role = agent_cfg.get("role", "")
    mood = agent_cfg.get("mood", "")
    role_extra = ROLE_SNIPPETS.get(role, ROLE_SNIPPETS.get(mood, ""))
    no_action = (
        "NEVER use asterisks, parentheses for actions, or stage directions. "
        "Do not write things like *laughs* or (chuckles) — just speak naturally."
    )
    return f"{base} {role_extra} {no_action}".strip()

# Characters that should never reach the TTS engine
import re as _re
_TTS_STRIP_RE = _re.compile(
    r'\*[^*]+\*'
    r'|\([^)]{1,40}\)'
    r'|\[[^\]]{1,40}\]'
    r'|#+'
    r'|`[^`]+`'
    r'|_{1,2}[^_]+_{1,2}'
)

def clean_for_tts(text: str) -> str:
    text = _TTS_STRIP_RE.sub("", text)
    text = _re.sub(r"[ \t]{2,}", " ", text)
    text = _re.sub(r"\n{2,}", " ", text)
    return text.strip()

# ── Council system prompts ───────────────────────────────────

def get_system_prompt(agent_name, other_names, phase, proposals, problem, personality):
    if isinstance(other_names, str):
        other_names = [other_names]
    others = ", ".join(other_names)
    base = (
        f"{personality}\n\n"
        f"You are in a council deliberation with {others}. "
        f"Problem: \"{problem}\". "
        f"Respond with 1-3 short spoken sentences. "
        f"You may address specific council members by name. "
        f"No markdown, no asterisks, no parentheses for actions, no lists, no emojis. "
        f"Write exactly what you would say out loud in a meeting."
    )

    if phase == PHASE_PROBLEM:
        return (f"{base}\n\n"
                f"PHASE: Problem Definition. "
                f"Analyze the problem from your unique perspective. "
                f"Identify the core tension, the real constraint, or the hidden assumption. "
                f"Reframe the problem if needed. Don't jump to solutions yet.")

    if phase == PHASE_DEBATE:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-3:]) if proposals else "none yet"
        return (f"{base}\n\n"
                f"PHASE: Open Debate. "
                f"Proposals so far: [{prop_str}]. "
                f"Argue for your approach, challenge others' ideas, or build on what's been said. "
                f"Be direct — disagree when you disagree, but stay constructive. "
                f"Propose concrete mechanisms, not just principles.")

    if phase == PHASE_CONVERGE:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-5:]) if proposals else "none yet"
        return (f"{base}\n\n"
                f"PHASE: Convergence. "
                f"The council is moving toward agreement. Proposals so far: [{prop_str}]. "
                f"Build on the strongest ideas. If you have a remaining concern, state it briefly. "
                f"If you can see a synthesis forming, name it explicitly. "
                f"If you want to propose a solution, prefix it with PROPOSAL: on its own line.")

    if phase == PHASE_SOLUTION:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-5:]) if proposals else "none"
        return (f"{base}\n\n"
                f"PHASE: Solution. The council has converged. "
                f"Proposals: [{prop_str}]. "
                f"State your final position. If you agree with the emerging consensus, say so and add "
                f"any final refinement. If you have a remaining reservation, state it concisely. "
                f"This is your closing statement.")

    return base

# ── LLM Calls ──────────────────────────────────────────────

async def call_llm(provider, api_key, model, messages, system_prompt, retries=3):
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
        json={"model": model, "max_tokens": 200, "system": system_prompt, "messages": messages},
    )
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Anthropic: {data['error']}")
    return data["content"][0]["text"]

async def _call_openai_compat(api_key, model, url, messages, system_prompt):
    client = await get_client()
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": 200,
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
        "contents": contents, "generationConfig": {"maxOutputTokens": 200},
    })
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Gemini: {data['error'].get('message', data['error'])}")
    return data["candidates"][0]["content"]["parts"][0]["text"]

# ── Proposal extraction ─────────────────────────────────────

def extract_proposals(text):
    """Extract any PROPOSAL: lines from the response."""
    proposals = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("PROPOSAL:"):
            proposal = stripped[9:].strip()
            if proposal:
                proposals.append(proposal)
    return proposals

# ── TTS ─────────────────────────────────────────────────────

async def generate_tts(text: str, voice_id: str, retries: int = 2) -> bytes | None:
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

# ── FastAPI ─────────────────────────────────────────────────

app = FastAPI(title="GibberLink Revisited — Council", lifespan=lifespan)
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
        "default_agents":   [{"id": a["id"], "name": a["name"], "color": a["color"], "role": a["role"], "mood": a["mood"]} for a in DEFAULT_AGENTS],
    }

from fastapi import Request
from fastapi.responses import JSONResponse

@app.get("/api/tts-health")
async def tts_health():
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
        problem     = start_msg.get("topic", "How to reduce meeting fatigue in remote teams")
        total_turns = min(max(int(start_msg.get("turns", TOTAL_TURNS)), 6), 40)

        # Build agent roster
        requested = start_msg.get("agents", None)
        num_agents = len(requested) if requested else 4
        num_agents = max(2, min(4, num_agents))

        agents = []
        for i in range(num_agents):
            base = dict(DEFAULT_AGENTS[i])
            if requested and i < len(requested):
                req = requested[i]
                if req.get("name"):        base["name"]        = req["name"]
                if req.get("mood"):        base["mood"]        = req["mood"]
                if req.get("role"):        base["role"]        = req["role"]
                if req.get("personality"): base["personality"] = req["personality"]
            base["provider"] = [AGENT_A_PROVIDER, AGENT_B_PROVIDER, AGENT_C_PROVIDER, AGENT_D_PROVIDER][i]
            base["api_key"]  = [AGENT_A_API_KEY,  AGENT_B_API_KEY,  AGENT_C_API_KEY,  AGENT_D_API_KEY][i]
            base["model"]    = [AGENT_A_MODEL,     AGENT_B_MODEL,     AGENT_C_MODEL,     AGENT_D_MODEL][i]
            aid = base["id"]
            base["voice_kokoro"] = KOKORO_VOICE_MAP.get(aid, "am_michael")
            base["voice_el"]     = EL_VOICE_MAP.get(aid, AGENT_A_VOICE_ID)
            base["voice_qwen3"]  = QWEN3_VOICE_MAP.get(aid, "Ryan")
            agents.append(base)

        messages  = []  # conversation history
        proposals = []  # accumulated proposals

        def get_phase(turn):
            pct = turn / total_turns
            if pct < 0.15:  return PHASE_PROBLEM
            if pct < 0.55:  return PHASE_DEBATE
            if pct < 0.80:  return PHASE_CONVERGE
            return PHASE_SOLUTION

        # Simple consensus estimation based on phase
        def estimate_consensus(turn, phase):
            pct = turn / total_turns
            if phase == PHASE_PROBLEM:
                return int(pct * 100 * 0.15)
            elif phase == PHASE_DEBATE:
                return 10 + int((pct - 0.15) * 100 * 0.8)
            elif phase == PHASE_CONVERGE:
                return 45 + int((pct - 0.55) * 100 * 1.5)
            else:
                return min(95 + int((pct - 0.80) * 100 * 0.25), 100)

        async def build_turn(turn):
            phase     = get_phase(turn)
            agent_idx = turn % len(agents)
            agent     = agents[agent_idx]
            agent_id  = agent["id"]
            agent_name = agent["name"]
            others    = [a["name"] for a in agents if a["id"] != agent_id]
            personality = build_personality(agent)

            if EFFECTIVE_TTS == "kokoro":
                voice_id = agent["voice_kokoro"]
            elif EFFECTIVE_TTS == "qwen3":
                voice_id = agent["voice_qwen3"]
            else:
                voice_id = agent["voice_el"]

            await ws.send_json({"type": "thinking", "agent": agent_id, "turn": turn, "phase": phase})

            # Build conversation history for this agent
            agent_msgs = []
            for m in messages:
                role = "assistant" if m["agent_id"] == agent_id else "user"
                content = m["content"]
                if role == "user" and len(agents) > 2:
                    speaker = next((a["name"] for a in agents if a["id"] == m["agent_id"]), "")
                    content = f"{speaker}: {content}"
                agent_msgs.append({"role": role, "content": content})

            if agent_msgs and agent_msgs[0]["role"] == "assistant":
                agent_msgs.insert(0, {"role": "user", "content": f'Council session on: {problem}'})
            if turn == 0:
                agent_msgs.append({"role": "user", "content": f'Problem: "{problem}". Begin your analysis.'})

            system_prompt = get_system_prompt(agent_name, others, phase, proposals, problem, personality)
            response = await call_llm(agent["provider"], agent["api_key"], agent["model"], agent_msgs, system_prompt)

            # Extract any proposals
            new_proposals = extract_proposals(response)
            proposals.extend(new_proposals)

            # Clean response for display (remove PROPOSAL: prefix lines for chat display)
            spoken_text = re.sub(r'^\s*PROPOSAL:\s*', '', response, flags=re.MULTILINE).strip()

            protocol_msg = wrap_council_message(agent_id, turn, phase, spoken_text, new_proposals)
            messages.append({"agent_id": agent_id, "agent_idx": agent_idx, "content": spoken_text, "phase": phase})

            audio_b64 = None
            if TTS_ENABLED:
                tts_text = clean_for_tts(spoken_text)
                if tts_text:
                    audio_bytes = await generate_tts(tts_text, voice_id)
                    if audio_bytes:
                        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            consensus = estimate_consensus(turn, phase)

            return {
                "payload": {
                    "type": "message", "agent": agent_id, "agent_name": agent_name,
                    "agent_color": agent.get("color", "orange"),
                    "agent_role": agent.get("role", ""),
                    "turn": turn, "total_turns": total_turns,
                    "phase": phase, "text": spoken_text,
                    "audio": audio_b64,
                    "audio_format": "wav" if EFFECTIVE_TTS in ("qwen3", "kokoro") else "mp3",
                    "protocol_message": protocol_msg,
                    "proposals": proposals.copy(),
                    "new_proposals": new_proposals,
                    "consensus": consensus,
                    "num_agents": len(agents),
                    "agent_roster": [{"id": a["id"], "name": a["name"], "color": a["color"], "role": a["role"], "mood": a.get("mood", "")} for a in agents],
                },
                "turn": turn,
            }

        # ── Pipelined turn loop ───────────────────────────────────
        next_task = asyncio.create_task(build_turn(0))

        for turn in range(total_turns):
            try:
                result = await next_task
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
                break

            if turn + 1 < total_turns:
                next_task = asyncio.create_task(build_turn(turn + 1))

            await ws.send_json(result["payload"])

            try:
                await asyncio.wait_for(ws.receive_json(), timeout=60.0)
            except asyncio.TimeoutError:
                pass

        await ws.send_json({
            "type": "complete",
            "proposals": proposals,
            "total_turns": len(messages),
            "consensus": 100,
        })

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
                           R E V I S I T E D  ◈  C O U N C I L """

    c.print(Text(banner, style="bold rgb(255,107,61)"))
    c.print()
    c.print(f"  [green]✓[/green] Voss  (strategist):  [bold]{AGENT_A_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_A_PROVIDER})")
    c.print(f"  [green]✓[/green] Lyra  (creative):    [bold]{AGENT_B_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_B_PROVIDER})")
    c.print(f"  [green]✓[/green] Kael  (skeptic):     [bold]{AGENT_C_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_C_PROVIDER})")
    c.print(f"  [green]✓[/green] Iris  (synthesizer): [bold]{AGENT_D_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_D_PROVIDER})")

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