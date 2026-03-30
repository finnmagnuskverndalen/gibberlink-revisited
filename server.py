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
    """Try to free a port by gracefully stopping any process bound to it.

    Strategy: SIGTERM first (gives the process a chance to clean up),
    then SIGKILL after a timeout if it's still alive. This avoids
    accidentally force-killing unrelated services.
    """
    import signal
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"], stderr=subprocess.DEVNULL, text=True
        ).strip()
        if not out:
            return
        import time
        pids = []
        for pid_str in out.splitlines():
            pid = int(pid_str)
            if pid == os.getpid():
                continue
            pids.append(pid)

        if not pids:
            return

        # Phase 1: SIGTERM (graceful)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"  ⚠ Sent SIGTERM to process on port {port} (PID {pid})")
            except ProcessLookupError:
                pass

        # Wait up to 3 seconds for graceful shutdown
        deadline = time.monotonic() + 3.0
        remaining = list(pids)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.2)
            still_alive = []
            for pid in remaining:
                try:
                    os.kill(pid, 0)  # check if alive (signal 0 = no signal)
                    still_alive.append(pid)
                except ProcessLookupError:
                    pass
            remaining = still_alive

        # Phase 2: SIGKILL anything that didn't exit gracefully
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
                print(f"  ⚠ Force-killed stubborn process on port {port} (PID {pid})")
            except ProcessLookupError:
                pass

        if pids:
            time.sleep(0.3)  # give OS time to release the socket
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

CHAIRMAN_PROVIDER = os.getenv("CHAIRMAN_PROVIDER", "openrouter")
CHAIRMAN_API_KEY  = os.getenv("CHAIRMAN_API_KEY", "")
CHAIRMAN_MODEL    = os.getenv("CHAIRMAN_MODEL", "deepseek/deepseek-chat-v3-0324:free")

# ── TTS config ───────────────────────────────────────────────
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "none").lower()

ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_A_VOICE_ID    = os.getenv("AGENT_A_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AGENT_B_VOICE_ID    = os.getenv("AGENT_B_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
AGENT_C_VOICE_ID    = os.getenv("AGENT_C_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AGENT_D_VOICE_ID    = os.getenv("AGENT_D_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
CHAIRMAN_VOICE_ID   = os.getenv("CHAIRMAN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
ELEVENLABS_MODEL    = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")

KOKORO_TTS_URL       = os.getenv("KOKORO_TTS_URL", "http://localhost:7862")
AGENT_A_KOKORO_VOICE = os.getenv("AGENT_A_KOKORO_VOICE", "am_michael")
AGENT_B_KOKORO_VOICE = os.getenv("AGENT_B_KOKORO_VOICE", "bm_george")
AGENT_C_KOKORO_VOICE = os.getenv("AGENT_C_KOKORO_VOICE", "am_adam")
AGENT_D_KOKORO_VOICE = os.getenv("AGENT_D_KOKORO_VOICE", "bm_lewis")
CHAIRMAN_KOKORO_VOICE = os.getenv("CHAIRMAN_KOKORO_VOICE", "am_echo")

QWEN3_TTS_URL       = os.getenv("QWEN3_TTS_URL", "http://localhost:7861")
AGENT_A_QWEN3_VOICE = os.getenv("AGENT_A_QWEN3_VOICE", "Ryan")
AGENT_B_QWEN3_VOICE = os.getenv("AGENT_B_QWEN3_VOICE", "Ethan")
AGENT_C_QWEN3_VOICE = os.getenv("AGENT_C_QWEN3_VOICE", "Miles")
AGENT_D_QWEN3_VOICE = os.getenv("AGENT_D_QWEN3_VOICE", "Leo")
CHAIRMAN_QWEN3_VOICE = os.getenv("CHAIRMAN_QWEN3_VOICE", "Axel")

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

import threading as _threading

# ── HTTP client ──────────────────────────────────────────────
# Per-session clients are created in the WebSocket handler to avoid
# one slow session starving another's connection pool.  A small shared
# client is kept only for internal health-check endpoints (TTS server).

_health_client: httpx.AsyncClient | None = None

async def _get_health_client() -> httpx.AsyncClient:
    """Shared client for lightweight internal health checks only."""
    global _health_client
    if _health_client is None or _health_client.is_closed:
        _health_client = httpx.AsyncClient(
            timeout=5,
            limits=httpx.Limits(max_connections=4),
        )
    return _health_client

def _make_session_client() -> httpx.AsyncClient:
    """Create a fresh httpx client for a single WebSocket session.

    Each session gets its own connection pool so concurrent sessions
    don't compete for connections or block each other on slow models.
    """
    return httpx.AsyncClient(
        timeout=60,
        limits=httpx.Limits(max_connections=20),
    )

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

_tts_ready_event = _threading.Event()  # thread-safe flag for TTS availability

@asynccontextmanager
async def lifespan(app):
    if EFFECTIVE_TTS in ("kokoro", "qwen3"):
        def _bg_start():
            ok = _start_tts_server()
            if ok:
                _tts_ready_event.set()
            else:
                print("  [TTS] Running in text-only mode (TTS unavailable)")
        _threading.Thread(target=_bg_start, daemon=True).start()
        print("  [TTS] Model loading in background — browser ready now, audio starts once model is loaded")
    elif TTS_ENABLED:
        _tts_ready_event.set()
    yield
    global _tts_proc
    if _tts_proc and _tts_proc.poll() is None:
        print("  [TTS] Stopping TTS server...")
        _tts_proc.terminate()
        try:
            _tts_proc.wait(timeout=5)
        except Exception:
            _tts_proc.kill()
    global _health_client
    if _health_client and not _health_client.is_closed:
        await _health_client.aclose()

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
    {
        "id": "chairman", "name": "Nexus", "color": "cyan",
        "role": "chairman",
        "personality": (
            "Your name is Nexus. You are the Chairman of this council. "
            "You do NOT participate in the debate. You speak only at the end. "
            "Your job is to synthesize the entire deliberation into a clear, "
            "structured final verdict. You are authoritative, fair, and precise. "
            "You credit good ideas by name and note where disagreements remain."
        ),
        "mood": "authoritative",
        "provider": None, "api_key": None, "model": None,
        "voice_kokoro": None, "voice_el": None, "voice_qwen3": None,
    },
]

KOKORO_VOICE_MAP = {
    "agent_a": AGENT_A_KOKORO_VOICE,
    "agent_b": AGENT_B_KOKORO_VOICE,
    "agent_c": AGENT_C_KOKORO_VOICE,
    "agent_d": AGENT_D_KOKORO_VOICE,
    "chairman": CHAIRMAN_KOKORO_VOICE,
}
EL_VOICE_MAP = {
    "agent_a": AGENT_A_VOICE_ID,
    "agent_b": AGENT_B_VOICE_ID,
    "agent_c": AGENT_C_VOICE_ID,
    "agent_d": AGENT_D_VOICE_ID,
    "chairman": CHAIRMAN_VOICE_ID,
}
QWEN3_VOICE_MAP = {
    "agent_a": AGENT_A_QWEN3_VOICE,
    "agent_b": AGENT_B_QWEN3_VOICE,
    "agent_c": AGENT_C_QWEN3_VOICE,
    "agent_d": AGENT_D_QWEN3_VOICE,
    "chairman": CHAIRMAN_QWEN3_VOICE,
}

ROLE_SNIPPETS = {
    "strategist":  "Focus on systems, incentives, and leverage points. Be decisive.",
    "creative":    "Challenge assumptions, propose unexpected angles, think laterally.",
    "skeptic":     "Poke holes, demand evidence, play devil's advocate constructively.",
    "synthesizer": "Find common ground, integrate perspectives, propose unified frameworks.",
    "chairman":    "Synthesize the full deliberation. Be authoritative, fair, and structured.",
    "strategic":   "Think about second-order effects and actionable next steps.",
    "integrative": "Bridge disagreements, see patterns, summarize progress.",
    "authoritative": "Be precise, structured, and decisive in your synthesis.",
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

# ── Response sanitization & validation ───────────────────────

# Patterns that indicate a broken/garbage LLM response
_GARBAGE_PATTERNS = [
    _re.compile(r'S\d+assistant', _re.IGNORECASE),        # leaked classifier labels
    _re.compile(r'^(safe|unsafe)\s*$', _re.MULTILINE),     # safety labels
    _re.compile(r'(safe\n){3,}', _re.IGNORECASE),          # repeated safe/unsafe
    _re.compile(r'(unsafe\n){2,}', _re.IGNORECASE),
    _re.compile(r'</?[a-z]+>'),                              # HTML tags
    _re.compile(r'\[INST\]|\[/INST\]|<<SYS>>|<\|im_'),     # leaked prompt tokens
    _re.compile(r'(Phase|Stimulus|Cycle).*will now', _re.IGNORECASE),  # meta-narration
]

def sanitize_response(text: str, agent_name: str, other_names: list[str]) -> str:
    """Clean up a raw LLM response, stripping common garbage patterns."""
    if not text:
        return ""
    # Strip lines that are just "safe" / "unsafe" / classifier labels
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines, pure classifier labels, leaked tokens
        if not stripped:
            continue
        if stripped.lower() in ("safe", "unsafe"):
            continue
        if _re.match(r'^S\d+\w*$', stripped, _re.IGNORECASE):
            continue
        # Skip lines that look like internal labels (SCAN, PHASE:, etc)
        if _re.match(r'^(SCAN|PHASE|STIMULUS|CYCLE|FOCUS)\b', stripped, _re.IGNORECASE):
            continue
        # Skip lines where the agent writes dialogue for OTHER agents
        # e.g. "Voss: I think..." when the agent is not Voss
        # Also catch hallucinated speakers like "Scan:", "You:", etc
        is_other_dialogue = False
        for other in other_names:
            if _re.match(rf'^{_re.escape(other)}\s*:', stripped):
                is_other_dialogue = True
                break
        # Catch any "Name:" pattern that isn't the current agent
        if not is_other_dialogue:
            speaker_match = _re.match(r'^([A-Z][a-z]+)\s*:', stripped)
            if speaker_match:
                speaker = speaker_match.group(1)
                if speaker != agent_name and speaker.lower() not in ('proposal', 'note', 'example'):
                    is_other_dialogue = True
        if is_other_dialogue:
            continue
        # Skip HTML tags
        if _re.match(r'^<[^>]+>$', stripped):
            continue
        clean_lines.append(line)

    result = "\n".join(clean_lines).strip()

    # If sanitization removed everything, return a minimal fallback
    if not result or len(result) < 5:
        return ""

    # Truncate excessively long responses (should be 1-3 sentences)
    if len(result) > 800:
        # Find the last sentence boundary before 800 chars
        for i in range(min(800, len(result)), 200, -1):
            if result[i] in '.!?':
                result = result[:i+1]
                break
        else:
            result = result[:800]

    return result

def is_response_broken(text: str, agent_name: str) -> bool:
    """Check if a response looks like garbage from a misbehaving model."""
    if not text or len(text.strip()) < 5:
        return True

    # Check for known garbage patterns
    for pattern in _GARBAGE_PATTERNS:
        if pattern.search(text):
            return True

    # Too many newlines relative to content (repetitive single-word lines)
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if len(lines) > 8:
        # More than 8 lines for a 1-3 sentence response is suspicious
        avg_len = sum(len(l) for l in lines) / len(lines)
        if avg_len < 10:  # average line under 10 chars = gibberish
            return True

    # Response contains the agent speaking as multiple characters
    # (hallucinating an entire conversation)
    colon_speakers = _re.findall(r'^([A-Z][a-z]+):', text, _re.MULTILINE)
    unique_speakers = set(colon_speakers)
    if len(unique_speakers) >= 3:
        return True

    return False

# ── Council system prompts ───────────────────────────────────

def get_system_prompt(agent_name, other_names, phase, proposals, problem, personality):
    if isinstance(other_names, str):
        other_names = [other_names]
    others = ", ".join(other_names)
    base = (
        f"{personality}\n\n"
        f"You are {agent_name} in a council deliberation with {others}. "
        f"Problem: \"{problem}\". "
        f"Respond with 1-3 short spoken sentences. "
        f"You may address specific council members by name. "
        f"No markdown, no asterisks, no parentheses for actions, no lists, no emojis. "
        f"Write exactly what you would say out loud in a meeting.\n\n"
        f"CRITICAL RULES:\n"
        f"- You are ONLY {agent_name}. Never write dialogue for other agents.\n"
        f"- Never write lines like 'Voss: ...' or 'Lyra: ...' — only speak as yourself.\n"
        f"- Never output classification labels, system tokens, or meta-commentary.\n"
        f"- Just speak your piece naturally, as {agent_name}, and stop."
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
                f"Propose concrete mechanisms, not just principles. "
                f"If you have a concrete proposal, put it on its own line starting with PROPOSAL: "
                f"For example: PROPOSAL: Use a staged rollout with weekly checkpoints")

    if phase == PHASE_CONVERGE:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-5:]) if proposals else "none yet"
        return (f"{base}\n\n"
                f"PHASE: Convergence. "
                f"The council is moving toward agreement. Proposals so far: [{prop_str}]. "
                f"Build on the strongest ideas. If you have a remaining concern, state it briefly. "
                f"If you can see a synthesis forming, name it explicitly. "
                f"You MUST include a PROPOSAL: line with your proposed solution on its own line. "
                f"For example: PROPOSAL: Combine approach A with approach B, adding feedback loops")

    if phase == PHASE_SOLUTION:
        prop_str = "; ".join(f'"{p}"' for p in proposals[-5:]) if proposals else "none"
        return (f"{base}\n\n"
                f"PHASE: Solution. The council has converged. "
                f"Proposals: [{prop_str}]. "
                f"State your final position. If you agree with the emerging consensus, say so and add "
                f"any final refinement. If you have a remaining reservation, state it concisely. "
                f"This is your closing statement.")

    return base

# ── Human-readable error messages ──────────────────────────

def _friendly_error(exc: Exception) -> str:
    """Convert raw LLM/TTS exceptions into user-friendly messages."""
    msg = str(exc)
    ml = msg.lower()

    # Rate limiting
    if "rate_limit" in ml or "429" in ml or "too many requests" in ml:
        return "Rate limited by the API provider. Wait a moment and try again, or switch to a different model."
    # Auth failures
    if "401" in ml or "unauthorized" in ml or "invalid.*key" in _re.sub(r'\s+', '', ml) or "authentication" in ml:
        return "API key is invalid or expired. Re-run `python3 setup.py` to reconfigure."
    # Model not found
    if "404" in ml or "not found" in ml or "does not exist" in ml or "model_not_found" in ml:
        return "Model not found — it may have been removed or renamed. Re-run `python3 setup.py` to pick a new model."
    # Quota / billing
    if "quota" in ml or "billing" in ml or "insufficient" in ml or "payment" in ml:
        return "API quota exhausted or billing issue. Check your account balance, or switch to a free model on OpenRouter."
    # Timeout
    if "timeout" in ml or "timed out" in ml:
        return "The API took too long to respond. The provider may be overloaded — try again or switch models."
    # Context length
    if "context" in ml and "length" in ml or "too long" in ml or "token" in ml and "limit" in ml:
        return "The conversation exceeded the model's context window. Try using fewer turns or a model with a larger context."
    # Content filter
    if "content_filter" in ml or "safety" in ml or "blocked" in ml or "moderation" in ml:
        return "The model's content filter blocked the response. Try rephrasing the topic."
    # Connection errors
    if "connect" in ml and ("refused" in ml or "error" in ml):
        return "Could not connect to the API provider. Check your internet connection."
    # Empty response
    if "empty" in ml and "response" in ml:
        return "The model returned an empty response. This sometimes happens with free models — try again."

    # Fallback: truncate raw message but keep it somewhat readable
    clean = msg.replace("RuntimeError: ", "").replace("API error: ", "")
    if len(clean) > 200:
        clean = clean[:200] + "..."
    return f"LLM error: {clean}"

# ── LLM error classification ─────────────────────────────────

class LLMError(RuntimeError):
    """Base class for LLM API errors."""
    pass

class LLMRetryableError(LLMError):
    """Transient errors worth retrying: rate limits, timeouts, server errors."""
    pass

class LLMFatalError(LLMError):
    """Permanent errors that will never succeed on retry: bad key, model not found, quota."""
    pass

def _classify_llm_error(status_code: int | None, error_body: str) -> LLMError:
    """Inspect an HTTP status code and error body to return the right exception type."""
    body_lower = error_body.lower() if error_body else ""

    # ── Fatal (never retry) ──
    if status_code == 401 or "unauthorized" in body_lower or "authentication" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if status_code == 403 or "forbidden" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if status_code == 404 or "not found" in body_lower or "model_not_found" in body_lower or "does not exist" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if "quota" in body_lower or "billing" in body_lower or "insufficient" in body_lower or "payment" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")
    if "content_filter" in body_lower or "safety" in body_lower or "blocked" in body_lower or "moderation" in body_lower:
        return LLMFatalError(f"[{status_code}] {error_body}")

    # ── Retryable ──
    if status_code == 429 or "rate_limit" in body_lower or "too many requests" in body_lower:
        return LLMRetryableError(f"[{status_code}] {error_body}")
    if status_code and status_code >= 500:
        return LLMRetryableError(f"[{status_code}] {error_body}")
    if "timeout" in body_lower or "timed out" in body_lower:
        return LLMRetryableError(f"[{status_code}] {error_body}")

    # Default: treat unknown errors as retryable (safer)
    return LLMRetryableError(f"[{status_code}] {error_body}")

# ── LLM Calls ──────────────────────────────────────────────

async def call_llm(provider, api_key, model, messages, system_prompt, retries=3, max_tokens=200, client: httpx.AsyncClient | None = None):
    last_err = None
    for attempt in range(retries):
        try:
            if provider == "anthropic":
                return await _call_anthropic(api_key, model, messages, system_prompt, max_tokens, client)
            elif provider == "gemini":
                return await _call_gemini(api_key, model, messages, system_prompt, max_tokens, client)
            else:
                urls = {
                    "openrouter":   "https://openrouter.ai/api/v1/chat/completions",
                    "openai":       "https://api.openai.com/v1/chat/completions",
                    "grok":         "https://api.x.ai/v1/chat/completions",
                    "opencode_zen": "https://opencode.ai/zen/v1/chat/completions",
                }
                return await _call_openai_compat(api_key, model, urls.get(provider, urls["openrouter"]), messages, system_prompt, max_tokens, client)
        except LLMFatalError:
            # Auth failures, model not found, quota — will never succeed on retry
            raise
        except (LLMRetryableError, httpx.TimeoutException, httpx.ConnectError) as e:
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] Attempt {attempt+1} failed (retryable): {e} — retrying in {wait}s")
                await asyncio.sleep(wait)
        except Exception as e:
            # Unknown errors — retry once, then give up
            last_err = e
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] Attempt {attempt+1} failed: {e} — retrying in {wait}s")
                await asyncio.sleep(wait)
    raise last_err

async def _call_anthropic(api_key, model, messages, system_prompt, max_tokens=200, client: httpx.AsyncClient | None = None):
    if client is None:
        client = _make_session_client()
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "system": system_prompt, "messages": messages},
    )
    data = resp.json()
    if "error" in data:
        raise _classify_llm_error(resp.status_code, f"Anthropic: {data['error']}")
    content = data["content"][0]["text"] if data.get("content") else None
    if content is None:
        raise LLMRetryableError("Anthropic returned empty response")
    return content

async def _call_openai_compat(api_key, model, url, messages, system_prompt, max_tokens=200, client: httpx.AsyncClient | None = None):
    if client is None:
        client = _make_session_client()
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system_prompt}] + messages},
    )
    data = resp.json()
    if "error" in data:
        raise _classify_llm_error(resp.status_code, f"API error: {data['error']}")
    content = data["choices"][0]["message"]["content"]
    if content is None:
        raise LLMRetryableError("Model returned empty response (content is null)")
    return content

async def _call_gemini(api_key, model, messages, system_prompt, max_tokens=200, client: httpx.AsyncClient | None = None):
    if client is None:
        client = _make_session_client()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in messages]
    resp = await client.post(url, headers={"content-type": "application/json"}, json={
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": contents, "generationConfig": {"maxOutputTokens": max_tokens},
    })
    data = resp.json()
    if "error" in data:
        raise _classify_llm_error(resp.status_code, f"Gemini: {data['error'].get('message', data['error'])}")
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise LLMRetryableError("Gemini returned empty or malformed response")
    if content is None:
        raise LLMRetryableError("Gemini returned null content")
    return content

# ── Proposal extraction ─────────────────────────────────────

def extract_proposals(text):
    """Extract proposals from the response.
    
    Primary: lines starting with PROPOSAL:
    Fallback: natural-language proposal patterns that free models use instead.
    """
    proposals = []

    # Primary: explicit PROPOSAL: lines
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.upper().startswith("PROPOSAL:"):
            proposal = stripped[9:].strip()
            if proposal and len(proposal) > 10:
                proposals.append(proposal)

    # If we found explicit proposals, use those
    if proposals:
        return proposals

    # Fallback: detect natural-language proposals in converge/solution phases
    # These patterns catch common ways free models phrase proposals
    # Require at least 25 chars to avoid partial junk matches
    _PROPOSAL_PATTERNS = [
        re.compile(r'(?:I|my|our)\s+propos(?:e|al)\s+(?:is\s+)?(?:that\s+)?(.{25,200}?)(?:\.|$)', re.IGNORECASE),
        re.compile(r'(?:I\s+)?suggest\s+(?:we\s+|that\s+)?(.{25,200}?)(?:\.|$)', re.IGNORECASE),
        re.compile(r'(?:the\s+)?solution\s+(?:is|should\s+be|I\'d\s+recommend)\s+(.{25,200}?)(?:\.|$)', re.IGNORECASE),
        re.compile(r'we\s+should\s+(?:adopt|implement|pursue|go\s+with)\s+(.{25,200}?)(?:\.|$)', re.IGNORECASE),
        re.compile(r'(?:my\s+)?recommendation\s+is\s+(?:to\s+)?(.{25,200}?)(?:\.|$)', re.IGNORECASE),
    ]

    for pattern in _PROPOSAL_PATTERNS:
        match = pattern.search(text)
        if match:
            proposal = match.group(1).strip().rstrip('.')
            if proposal and len(proposal) > 10:
                proposals.append(proposal)
                break  # Only extract one fallback proposal per response

    return proposals

def _proposals_are_similar(a: str, b: str) -> bool:
    """Check if two proposals are near-duplicates (simple word overlap)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
    return overlap > 0.7


# Role-based vote weights — skeptic's disagree matters more, synthesizer's agree matters more
_ROLE_WEIGHTS = {
    "strategist": 1.2,
    "creative": 1.0,
    "skeptic": 1.5,    # skeptic's judgment carries more weight
    "synthesizer": 1.3, # synthesizer's agreement signals real convergence
    "chairman": 2.0,    # chairman has veto weight
}


def build_scoreboard(proposal_records: list[dict], all_agents: list[dict]) -> list[dict]:
    """Score and rank proposals based on weighted votes.

    Each voter's agree/amend/disagree is weighted by their role.
    Chairman disagree acts as a veto (halves the score).
    Returns a list sorted by score descending.
    """
    scored = []
    for rec in proposal_records:
        score = 0.0
        vote_counts = {"agree": 0, "disagree": 0, "amend": 0}
        chairman_vote = None
        for voter_id, v in rec["votes"].items():
            vote_counts[v] = vote_counts.get(v, 0) + 1
            # Look up voter role for weighting
            voter_role = ""
            for a in all_agents:
                if a["id"] == voter_id:
                    voter_role = a.get("role", "")
                    break
            weight = _ROLE_WEIGHTS.get(voter_role, 1.0)
            if v == "agree":
                score += 2 * weight
            elif v == "amend":
                score += 1 * weight
            if voter_id == "chairman":
                chairman_vote = v

        chairman_vetoed = chairman_vote == "disagree"
        if chairman_vetoed:
            score *= 0.5

        scored.append({
            "text": rec["text"],
            "author": rec["author"],
            "author_id": rec.get("author_id", ""),
            "turn": rec["turn"],
            "votes": rec["votes"],
            "reasons": rec.get("reasons", {}),
            "vote_counts": vote_counts,
            "score": round(score, 1),
            "chairman_vetoed": chairman_vetoed,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


async def collect_votes(agents, chairman, proposal_text, author_id, messages, problem, call_llm_fn, client: httpx.AsyncClient | None = None):
    """Ask each agent (+ chairman) to vote on a proposal. Returns dict of votes.
    
    - Runs all votes in parallel via asyncio.gather
    - Excludes the proposer (they're the author)
    - Includes recent conversation context for informed votes
    - Collects a 1-sentence reason alongside the vote
    - Chairman gets a vote too (acts as tiebreaker/veto)
    """
    # Build recent context (last 4 messages)
    recent_context = ""
    if messages:
        recent = messages[-4:]
        context_lines = []
        for m in recent:
            speaker = m.get("agent_id", "?")
            # Find agent name
            for a in agents:
                if a["id"] == speaker:
                    speaker = a["name"]
                    break
            context_lines.append(f"  {speaker}: {m['content'][:150]}")
        recent_context = "\nRecent discussion:\n" + "\n".join(context_lines)

    async def get_vote(agent):
        prompt = (
            f"A proposal has been made in the council deliberation on: \"{problem}\"\n"
            f"{recent_context}\n\n"
            f"PROPOSAL: \"{proposal_text}\"\n\n"
            f"You are {agent['name']} ({agent.get('role', '')}).\n"
            f"Based on the discussion, do you AGREE, DISAGREE, or want to AMEND this proposal?\n"
            f"Respond in this exact format (2 lines only):\n"
            f"VOTE: AGREE\n"
            f"REASON: one short sentence explaining why\n\n"
            f"Replace AGREE with your actual vote. Nothing else."
        )
        try:
            personality = build_personality(agent)
            response = await call_llm_fn(
                agent["provider"], agent["api_key"], agent["model"],
                [{"role": "user", "content": prompt}],
                personality,
                client=client,
            )
            if not response:
                return "agree", ""

            # Parse vote
            text = response.strip()
            vote = "agree"
            reason = ""
            for line in text.split("\n"):
                line_up = line.strip().upper()
                if line_up.startswith("VOTE:"):
                    word = line_up[5:].strip().split()[0] if line_up[5:].strip() else ""
                    if "DISAGREE" in word:
                        vote = "disagree"
                    elif "AMEND" in word:
                        vote = "amend"
                    else:
                        vote = "agree"
                elif line.strip().upper().startswith("REASON:"):
                    reason = line.strip()[7:].strip()

            # Fallback: if no VOTE: line found, check first word
            if "VOTE:" not in text.upper():
                first = text.split()[0].upper() if text.split() else ""
                if "DISAGREE" in first:
                    vote = "disagree"
                elif "AMEND" in first:
                    vote = "amend"

            return vote, reason[:150]  # cap reason length
        except Exception:
            return "agree", ""

    # Build voter list: all debaters except the proposer + chairman
    voters = []
    for agent in agents:
        if agent["id"] != author_id:  # exclude the proposer
            voters.append(agent)
    # Chairman always votes (tiebreaker/veto power)
    voters.append(chairman)

    # Run all votes in parallel
    vote_coros = [get_vote(agent) for agent in voters]
    results = await asyncio.gather(*vote_coros, return_exceptions=True)

    votes = {}
    reasons = {}
    for agent, result in zip(voters, results):
        if isinstance(result, Exception):
            votes[agent["id"]] = "agree"
            reasons[agent["id"]] = ""
        else:
            vote, reason = result
            votes[agent["id"]] = vote
            reasons[agent["id"]] = reason

    return votes, reasons

# ── TTS ─────────────────────────────────────────────────────

async def generate_tts(text: str, voice_id: str, client: httpx.AsyncClient, retries: int = 2) -> bytes | None:
    if not TTS_ENABLED:
        return None
    if EFFECTIVE_TTS in ("kokoro", "qwen3"):
        if not _tts_ready_event.is_set():
            return None
        if _tts_proc and _tts_proc.poll() is not None:
            print(f"  [TTS] {EFFECTIVE_TTS} server stopped — skipping audio")
            return None
        return await _tts_local(text, voice_id, client, retries)
    if EFFECTIVE_TTS == "elevenlabs":
        return await _tts_elevenlabs(text, voice_id, client, retries)
    return None

async def _tts_elevenlabs(text: str, voice_id: str, client: httpx.AsyncClient, retries: int = 2) -> bytes | None:
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

async def _tts_local(text: str, voice_id: str, client: httpx.AsyncClient, retries: int = 2) -> bytes | None:
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
        client = await _get_health_client()
        resp = await client.get(f"{base_url.rstrip('/')}/health", timeout=2)
        return JSONResponse(resp.json())
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _session_stopped = False          # set True when client sends stop or disconnects
    _background_tasks: set[asyncio.Task] = set()   # track all spawned tasks for cleanup
    _state_lock = asyncio.Lock()      # Fix 4: guards mutations to messages/proposals/proposal_records
    _session_client = _make_session_client()  # Fix 1: per-session HTTP client
    try:
        start_msg   = await ws.receive_json()

        # ── Input validation ──────────────────────────────────
        raw_topic = start_msg.get("topic", "How to reduce meeting fatigue in remote teams")
        if not isinstance(raw_topic, str) or not raw_topic.strip():
            raw_topic = "How to reduce meeting fatigue in remote teams"
        problem = raw_topic.strip()[:500]  # cap at 500 chars to avoid context window bloat

        try:
            total_turns = min(max(int(start_msg.get("turns", TOTAL_TURNS)), 6), 40)
        except (ValueError, TypeError):
            total_turns = TOTAL_TURNS

        # Build agent roster (4 debaters + chairman)
        requested = start_msg.get("agents", None)
        num_agents = 4  # always 4 debaters

        all_providers = [AGENT_A_PROVIDER, AGENT_B_PROVIDER, AGENT_C_PROVIDER, AGENT_D_PROVIDER, CHAIRMAN_PROVIDER]
        all_keys      = [AGENT_A_API_KEY,  AGENT_B_API_KEY,  AGENT_C_API_KEY,  AGENT_D_API_KEY,  CHAIRMAN_API_KEY]
        all_models    = [AGENT_A_MODEL,    AGENT_B_MODEL,    AGENT_C_MODEL,    AGENT_D_MODEL,    CHAIRMAN_MODEL]

        agents = []  # debaters only (first 4)
        for i in range(num_agents):
            base = dict(DEFAULT_AGENTS[i])
            if requested and i < len(requested):
                req = requested[i]
                if req.get("name"):        base["name"]        = req["name"]
                if req.get("mood"):        base["mood"]        = req["mood"]
                if req.get("role"):        base["role"]        = req["role"]
                if req.get("personality"): base["personality"] = req["personality"]
            base["provider"] = all_providers[i]
            base["api_key"]  = all_keys[i]
            base["model"]    = all_models[i]
            aid = base["id"]
            base["voice_kokoro"] = KOKORO_VOICE_MAP.get(aid, "am_michael")
            base["voice_el"]     = EL_VOICE_MAP.get(aid, AGENT_A_VOICE_ID)
            base["voice_qwen3"]  = QWEN3_VOICE_MAP.get(aid, "Ryan")
            agents.append(base)

        # Chairman agent (5th, only speaks at the end)
        chairman = dict(DEFAULT_AGENTS[4])  # Nexus
        chairman["provider"] = CHAIRMAN_PROVIDER
        chairman["api_key"]  = CHAIRMAN_API_KEY
        chairman["model"]    = CHAIRMAN_MODEL
        chairman["voice_kokoro"] = KOKORO_VOICE_MAP.get("chairman", "am_echo")
        chairman["voice_el"]     = EL_VOICE_MAP.get("chairman", AGENT_A_VOICE_ID)
        chairman["voice_qwen3"]  = QWEN3_VOICE_MAP.get("chairman", "Axel")

        all_agents = agents + [chairman]  # for roster display

        messages  = []  # conversation history
        proposals = []  # accumulated proposal text strings
        proposal_records = []  # structured: [{text, author, turn, votes}]

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

        async def build_turn(turn, send_thinking=True):
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

            # NOTE: thinking is sent from the main loop, not here,
            # to avoid racing with other WebSocket sends when pipelined.

            # Build conversation history for this agent.
            # Use a sliding window to avoid overflowing small context windows.
            # Keep the first 2 messages (problem framing) + the last MAX_HISTORY
            # messages so agents have both context and recency.
            MAX_HISTORY = 16  # ~16 turns of context is plenty for most models

            history_source = messages
            if len(messages) > MAX_HISTORY + 2:
                # Keep first 2 (problem framing) + last MAX_HISTORY
                history_source = messages[:2] + messages[-(MAX_HISTORY):]

            agent_msgs = []
            for m in history_source:
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
            response = await call_llm(agent["provider"], agent["api_key"], agent["model"], agent_msgs, system_prompt, client=_session_client)

            # ── Sanitize and validate response ──
            response = sanitize_response(response, agent_name, others)

            if is_response_broken(response, agent_name):
                # Retry once with a much stricter prompt
                print(f"  [SANITIZE] Broken response from {agent_name} (turn {turn}), retrying...")
                strict_prompt = (
                    f"You are {agent_name}. Respond to the council discussion with 1-2 sentences about: \"{problem}\". "
                    f"Speak ONLY as {agent_name}. Do not write dialogue for anyone else. "
                    f"Just give your opinion in plain English. Nothing else."
                )
                try:
                    response = await call_llm(agent["provider"], agent["api_key"], agent["model"], agent_msgs, strict_prompt, client=_session_client)
                    response = sanitize_response(response, agent_name, others)
                except Exception:
                    pass

                # If still broken after retry, use a graceful fallback
                if is_response_broken(response, agent_name):
                    print(f"  [SANITIZE] Retry also broken for {agent_name}, using fallback")
                    fallback_phrases = {
                        PHASE_PROBLEM: f"I think the core issue here is understanding the real constraints before we jump to solutions.",
                        PHASE_DEBATE: f"I hear what the others are saying, but I think we need to consider the practical implications more carefully.",
                        PHASE_CONVERGE: f"We seem to be making progress. I can see elements of a workable solution forming from what's been said.",
                        PHASE_SOLUTION: f"I think we've landed on a reasonable approach. Let's move forward with what we've agreed on.",
                    }
                    response = fallback_phrases.get(phase, "I need a moment to gather my thoughts on this.")

            # Extract any proposals
            new_proposals = extract_proposals(response)

            # Collect votes on new proposals (parallel, with reasons)
            new_proposal_records = []
            for prop_text in new_proposals:
                # Skip near-duplicate proposals (read under lock)
                async with _state_lock:
                    is_dup = any(_proposals_are_similar(prop_text, r["text"]) for r in proposal_records)
                if is_dup:
                    print(f"  [DEDUP] Skipping duplicate proposal: {prop_text[:60]}...")
                    continue

                votes, reasons = await collect_votes(
                    agents, chairman, prop_text, agent_id, messages, problem, call_llm, client=_session_client
                )
                record = {
                    "text": prop_text,
                    "author": agent_name,
                    "author_id": agent_id,
                    "turn": turn,
                    "votes": votes,
                    "reasons": reasons,
                }
                new_proposal_records.append(record)

            # ── Mutate shared state under lock (Fix 4) ──
            async with _state_lock:
                proposals.extend(new_proposals)
                proposal_records.extend(new_proposal_records)

                # Clean response for display (remove PROPOSAL: prefix lines for chat display)
                spoken_text = re.sub(r'^\s*PROPOSAL:\s*', '', response, flags=re.MULTILINE).strip()

                protocol_msg = wrap_council_message(agent_id, turn, phase, spoken_text, new_proposals)
                messages.append({"agent_id": agent_id, "agent_idx": agent_idx, "content": spoken_text, "phase": phase})

                # Snapshot state for the payload (before releasing the lock)
                proposals_snapshot = proposals.copy()
                records_snapshot = [
                    {"text": r["text"], "author": r["author"], "author_id": r.get("author_id", ""), "turn": r["turn"], "votes": r["votes"], "reasons": r.get("reasons", {})}
                    for r in proposal_records
                ]

            audio_b64 = None
            if TTS_ENABLED:
                tts_text = clean_for_tts(spoken_text)
                if tts_text:
                    audio_bytes = await generate_tts(tts_text, voice_id, _session_client)
                    if audio_bytes:
                        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            consensus = estimate_consensus(turn, phase)

            return {
                "payload": {
                    "type": "message", "agent": agent_id, "agent_name": agent_name,
                    "agent_color": agent.get("color", "orange"),
                    "agent_role": agent.get("role", ""),
                    "agent_model": agent.get("model", "").split("/")[-1].split(":")[0],
                    "turn": turn, "total_turns": total_turns,
                    "phase": phase, "text": spoken_text,
                    "audio": audio_b64,
                    "audio_format": "wav" if EFFECTIVE_TTS in ("qwen3", "kokoro") else "mp3",
                    "protocol_message": protocol_msg,
                    "proposals": proposals_snapshot,
                    "proposal_records": records_snapshot,
                    "new_proposals": new_proposals,
                    "new_proposal_records": new_proposal_records,
                    "consensus": consensus,
                    "num_agents": len(agents),
                    "agent_roster": [{"id": a["id"], "name": a["name"], "color": a["color"], "role": a["role"], "mood": a.get("mood", ""), "model": a.get("model", "").split("/")[-1].split(":")[0]} for a in all_agents],
                },
                "turn": turn,
            }

        # ── Pipelined turn loop ────────────────────────────────────
        # Strategy for natural conversation flow:
        #   1. Send thinking indicator (main loop, safe)
        #   2. Start LLM + TTS generation as a task
        #   3. Await the task result
        #   4. Send the message payload
        #   5. Wait for client ack (client acks immediately for text,
        #      or after audio finishes playing)
        #   6. While client plays audio, the NEXT turn's LLM call
        #      is already running in the background.
        #
        # The race condition fix: build_turn() never touches the
        # WebSocket — all ws.send_json calls happen sequentially
        # in this main loop. The background task only does LLM + TTS.

        pending_task = None

        for turn in range(total_turns):
            # ── Check for stop signal ──
            if _session_stopped:
                break

            # If we have a pre-started task from the previous iteration, use it.
            # Otherwise start fresh (first turn, or after an error).
            if pending_task is None:
                # Send thinking for this turn
                phase = get_phase(turn)
                agent_idx = turn % len(agents)
                agent_id = agents[agent_idx]["id"]
                await ws.send_json({"type": "thinking", "agent": agent_id, "turn": turn, "phase": phase})
                pending_task = asyncio.create_task(build_turn(turn))
                _background_tasks.add(pending_task)
                pending_task.add_done_callback(_background_tasks.discard)

            try:
                result = await pending_task
                pending_task = None
            except Exception as e:
                pending_task = None
                await ws.send_json({"type": "error", "message": _friendly_error(e)})
                break

            if _session_stopped:
                break

            # Send the message payload (text + audio)
            await ws.send_json(result["payload"])

            # Pre-start the NEXT turn's LLM+TTS while the client plays audio.
            # Send its thinking indicator now (sequentially, safe).
            if turn + 1 < total_turns and not _session_stopped:
                next_phase = get_phase(turn + 1)
                next_agent_idx = (turn + 1) % len(agents)
                next_agent_id = agents[next_agent_idx]["id"]
                await ws.send_json({"type": "thinking", "agent": next_agent_id, "turn": turn + 1, "phase": next_phase})
                pending_task = asyncio.create_task(build_turn(turn + 1))
                _background_tasks.add(pending_task)
                pending_task.add_done_callback(_background_tasks.discard)

            # Wait for client ack — also listen for stop signal
            try:
                ack_msg = await asyncio.wait_for(ws.receive_json(), timeout=120.0)
                if isinstance(ack_msg, dict) and ack_msg.get("type") == "stop":
                    _session_stopped = True
                    break
            except asyncio.TimeoutError:
                pass

        # ── Chairman synthesis ──────────────────────────────────────
        # Nexus (the Chairman) sees the full deliberation and produces
        # a structured final verdict with TTS.
        # Skip if the session was stopped early by the user.

        if not _session_stopped and messages:
            await ws.send_json({"type": "thinking", "agent": "chairman", "turn": total_turns, "phase": "synthesis"})

            # Build the full transcript for the chairman
            transcript_lines = []
            for m in messages:
                speaker = next((a["name"] for a in agents if a["id"] == m["agent_id"]), m["agent_id"])
                transcript_lines.append(f"{speaker} [{m['phase']}]: {m['content']}")
            transcript = "\n".join(transcript_lines)

        # Build proposal summary with votes
            prop_summary = ""
            if proposal_records:
                prop_lines = []
                for i, rec in enumerate(proposal_records):
                    vote_counts = {"agree": 0, "disagree": 0, "amend": 0}
                    for v in rec["votes"].values():
                        vote_counts[v] = vote_counts.get(v, 0) + 1
                    prop_lines.append(
                        f"  Proposal {i+1} by {rec['author']}: \"{rec['text']}\" "
                        f"— Votes: {vote_counts['agree']} agree, {vote_counts['disagree']} disagree, {vote_counts['amend']} amend"
                    )
                prop_summary = "\nProposals and votes:\n" + "\n".join(prop_lines)

            chairman_prompt = (
                f"You are Nexus, the Chairman of this council. You have observed the entire deliberation.\n\n"
                f"Problem: \"{problem}\"\n\n"
                f"Full transcript:\n{transcript}\n"
                f"{prop_summary}\n\n"
                f"Produce a clear, structured FINAL VERDICT. Include:\n"
                f"1. The problem as the council understood it (1 sentence)\n"
                f"2. Key points of agreement\n"
                f"3. Key points of disagreement\n"
                f"4. The recommended solution (synthesize the best ideas)\n"
                f"5. Remaining caveats or open questions\n\n"
                f"Speak naturally as if delivering a verdict to the council. "
                f"Credit specific council members by name where appropriate. "
                f"Keep it to 6-10 sentences total. No markdown, no lists, no asterisks."
            )

            try:
                chairman_response = await call_llm(
                    chairman["provider"], chairman["api_key"], chairman["model"],
                    [{"role": "user", "content": chairman_prompt}],
                    build_personality(chairman),
                    max_tokens=500,
                    client=_session_client,
                )

                # ── Build ranked proposal scoreboard ──
                scored_proposals = build_scoreboard(proposal_records, all_agents)

                # Generate TTS for chairman
                chairman_audio_b64 = None
                if TTS_ENABLED:
                    if EFFECTIVE_TTS == "kokoro":
                        ch_voice = chairman["voice_kokoro"]
                    elif EFFECTIVE_TTS == "qwen3":
                        ch_voice = chairman["voice_qwen3"]
                    else:
                        ch_voice = chairman["voice_el"]
                    tts_text = clean_for_tts(chairman_response)
                    if tts_text:
                        audio_bytes = await generate_tts(tts_text, ch_voice, _session_client)
                        if audio_bytes:
                            chairman_audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

                await ws.send_json({
                    "type": "chairman",
                    "agent": "chairman",
                    "agent_name": chairman["name"],
                    "agent_color": chairman["color"],
                    "agent_role": chairman["role"],
                    "agent_model": chairman.get("model", "").split("/")[-1].split(":")[0],
                    "text": chairman_response,
                    "audio": chairman_audio_b64,
                    "audio_format": "wav" if EFFECTIVE_TTS in ("qwen3", "kokoro") else "mp3",
                    "proposal_records": [
                        {"text": r["text"], "author": r["author"], "author_id": r.get("author_id", ""), "turn": r["turn"], "votes": r["votes"], "reasons": r.get("reasons", {})}
                        for r in proposal_records
                    ],
                    "scoreboard": scored_proposals,
                })

                # Wait for client ack
                try:
                    await asyncio.wait_for(ws.receive_json(), timeout=120.0)
                except asyncio.TimeoutError:
                    pass

            except Exception as e:
                print(f"  [Chairman] Synthesis failed: {e}")
                # Build scoreboard even on LLM failure so the client gets the vote data
                scored_proposals = build_scoreboard(proposal_records, all_agents)

                fallback_text = (
                    f"The council deliberated over {len(messages)} rounds on this problem. "
                    f"{len(proposal_records)} proposal(s) were considered. "
                    f"The chairman was unable to produce a full synthesis due to a technical issue, "
                    f"but the proposal scoreboard below reflects the council's collective judgment."
                )
                try:
                    await ws.send_json({
                        "type": "chairman",
                        "agent": "chairman",
                        "agent_name": chairman["name"],
                        "agent_color": chairman["color"],
                        "agent_role": chairman["role"],
                        "agent_model": chairman.get("model", "").split("/")[-1].split(":")[0],
                        "text": fallback_text,
                        "audio": None,
                        "audio_format": "mp3",
                        "proposal_records": [
                            {"text": r["text"], "author": r["author"], "author_id": r.get("author_id", ""), "turn": r["turn"], "votes": r["votes"], "reasons": r.get("reasons", {})}
                            for r in proposal_records
                        ],
                        "scoreboard": scored_proposals,
                    })
                except Exception:
                    pass

        await ws.send_json({
            "type": "complete",
            "proposals": proposals,
            "proposal_records": [
                {"text": r["text"], "author": r["author"], "author_id": r.get("author_id", ""), "turn": r["turn"], "votes": r["votes"], "reasons": r.get("reasons", {})}
                for r in proposal_records
            ],
            "total_turns": len(messages),
            "consensus": 100,
        })

    except WebSocketDisconnect:
        _session_stopped = True
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": _friendly_error(e)})
        except Exception:
            pass
    finally:
        # ── Clean up background tasks ──
        _session_stopped = True
        for task in list(_background_tasks):
            if not task.done():
                task.cancel()
        if _background_tasks:
            await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()
        # ── Close per-session HTTP client ──
        if _session_client and not _session_client.is_closed:
            await _session_client.aclose()

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
    c.print(f"  [cyan]◈[/cyan] Nexus (chairman):    [bold]{CHAIRMAN_MODEL.split('/')[-1].split(':')[0]}[/bold] ({CHAIRMAN_PROVIDER})")

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
    uvicorn.run(
        app, host=HOST, port=PORT, log_level="warning",
        # Fix 3: WebSocket keepalive — prevents proxies/browsers from dropping
        # idle connections during long deliberation sessions (10+ minutes).
        ws_ping_interval=30,   # send ping every 30s
        ws_ping_timeout=10,    # close if no pong within 10s
    )