#!/usr/bin/env python3
"""
GibberLink Revisited — Setup Wizard
Installs dependencies, fetches live models from OpenRouter, and writes .env
"""

import os
import sys
import json
import subprocess

try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx", "-q"])
    import httpx

# ── Helpers ──────────────────────────────────────────────────

def bold(s):   return f"\033[1m{s}\033[0m"
def green(s):  return f"\033[32m{s}\033[0m"
def yellow(s): return f"\033[33m{s}\033[0m"
def cyan(s):   return f"\033[36m{s}\033[0m"
def red(s):    return f"\033[31m{s}\033[0m"
def dim(s):    return f"\033[2m{s}\033[0m"

def ask(prompt, default=""):
    val = input(f"{prompt} [{default}]: ").strip()
    return val if val else default

def ask_yn(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    val = input(f"{prompt} [{hint}]: ").strip().lower()
    if not val:
        return default
    return val.startswith("y")

VENV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv")

def get_venv_python():
    """Return the path to the venv Python binary."""
    if sys.platform == "win32":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")

def ensure_venv():
    """Create .venv if it doesn't exist, return venv Python path."""
    venv_python = get_venv_python()
    if not os.path.exists(venv_python):
        print(dim("  Creating virtual environment in .venv ..."))
        subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
        print(green("  ✓ Virtual environment created"))
    return venv_python

def _get_pip() -> list:
    """Return the pip command to use, creating a venv if needed.
    Re-execs setup.py inside the venv on first run so all imports work."""
    in_venv = (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )
    if in_venv:
        return [sys.executable, "-m", "pip"]

    # System Python on Debian/Ubuntu (PEP 668) — create/use .venv
    venv_python = ensure_venv()
    if sys.executable != venv_python:
        print(dim("  Re-launching setup inside .venv..."))
        os.execv(venv_python, [venv_python] + sys.argv)
    return [venv_python, "-m", "pip"]


def install_base_deps():
    """Install core server dependencies (always required)."""
    print(bold("\n📦 Installing core dependencies..."))
    pip = _get_pip()
    subprocess.check_call(pip + ["install", "-r", "requirements.txt", "-q"])
    print(green("  ✓ Core dependencies installed"))


KOKORO_BASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_MODEL_FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]

def download_kokoro_models():
    """Download Kokoro model files into the project directory if missing."""
    import urllib.request
    here = os.path.dirname(os.path.abspath(__file__))
    all_present = all(os.path.exists(os.path.join(here, f)) for f in KOKORO_MODEL_FILES)
    if all_present:
        print(dim("  ✓ Kokoro model files already present"))
        return

    print(bold("\n📥 Downloading Kokoro model files (~300MB total)..."))
    for filename in KOKORO_MODEL_FILES:
        dest = os.path.join(here, filename)
        if os.path.exists(dest):
            print(dim(f"  ✓ {filename} already exists"))
            continue
        url = f"{KOKORO_BASE_URL}/{filename}"
        print(f"  Downloading {filename}...", end=" ", flush=True)
        try:
            def _progress(block, block_size, total):
                if total > 0:
                    pct = min(100, block * block_size * 100 // total)
                    print(f"\r  Downloading {filename}... {pct}%", end="", flush=True)
            urllib.request.urlretrieve(url, dest, reporthook=_progress)
            size_mb = os.path.getsize(dest) / 1024 / 1024
            print(green(f"\r  ✓ {filename} ({size_mb:.0f} MB)"))
        except Exception as e:
            print(red(f"\n  ✗ Failed: {e}"))
            print(dim(f"    Run manually: wget {url}"))
            sys.exit(1)
    print(green("  ✓ Kokoro model files ready"))


def install_kokoro_deps():
    """Install Kokoro-ONNX dependencies (only when TTS_PROVIDER=kokoro)."""
    print(bold("\n📦 Installing Kokoro-TTS dependencies..."))
    print(dim("  (kokoro-onnx + soundfile + espeak-ng — lightweight, no GPU needed)"))
    pip = _get_pip()

    print(dim("  Installing kokoro-onnx and soundfile..."))
    ret = subprocess.call(pip + ["install", "kokoro-onnx", "soundfile", "-q"])
    if ret != 0:
        print(yellow("  ⚠ pip install had errors — attempting to continue"))

    # espeak-ng is needed for G2P phoneme fallback on Linux
    import shutil
    if not shutil.which("espeak-ng") and sys.platform.startswith("linux"):
        print(dim("  Installing espeak-ng (system package)..."))
        subprocess.call(
            ["sudo", "apt-get", "install", "-y", "-q", "espeak-ng"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    print(green("  ✓ Kokoro pip packages installed"))
    download_kokoro_models()


def install_qwen3_deps():
    """Install Qwen3-TTS dependencies (only when TTS_PROVIDER=qwen3)."""
    print(bold("\n📦 Installing Qwen3-TTS dependencies..."))
    print(dim("  (torch + qwen-tts + soundfile + scipy — may take a few minutes)"))
    pip = _get_pip()

    print(dim("  Installing PyTorch (CPU build)..."))
    subprocess.check_call(pip + [
        "install", "torch", "torchaudio",
        "--index-url", "https://download.pytorch.org/whl/cpu",
        "-q",
    ])

    print(dim("  Installing qwen-tts, soundfile, scipy..."))
    subprocess.check_call(pip + ["install", "qwen-tts", "soundfile", "scipy", "-q"])
    print(green("  ✓ Qwen3-TTS dependencies installed"))
    print(dim("  Note: the model weights (~1.3 GB) download on first server start.\n"))

# ── OpenRouter live model fetch ──────────────────────────────

def fetch_openrouter_models(api_key: str):
    """Fetch available models from OpenRouter, return top free + cheapest paid."""
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            models = resp.json().get("data", [])
    except Exception as e:
        print(yellow(f"  ⚠ Could not fetch live models: {e}"))
        return [], []

    free_models = []
    paid_models = []

    # Build a live pricing lookup keyed by model id
    live_pricing = {m.get("id", ""): m.get("pricing", {}) for m in models}

    for m in models:
        mid = m.get("id", "")
        pricing = m.get("pricing", {})
        try:
            prompt_cost = float(pricing.get("prompt", "0") or 0)
        except (ValueError, TypeError):
            prompt_cost = 0.0

        if mid.endswith(":free") or prompt_cost == 0.0:
            free_models.append(m)
        else:
            paid_models.append((prompt_cost, m))

    paid_models.sort(key=lambda x: x[0])
    top_free = free_models[:10]
    top_paid = [m for _, m in paid_models[:10]]
    return top_free, top_paid


def display_models(models, label, start_idx=1):
    print(bold(f"\n  {label}:"))
    for i, m in enumerate(models, start=start_idx):
        name = m.get("name") or m.get("id", "")
        mid = m.get("id", "")
        ctx = m.get("context_length", "?")
        pricing = m.get("pricing", {})
        try:
            cost = float(pricing.get("prompt", 0) or 0)
            cost_str = "free" if cost == 0 else f"${cost * 1e6:.2f}/M tok"
        except (ValueError, TypeError):
            cost_str = "?"
        print(f"    {cyan(str(i).rjust(2))}. {name[:45]:<45} {dim(cost_str)}  {dim(mid)}")
    return start_idx + len(models)


def pick_model(label, free_models, paid_models, default_id):
    """Interactive model picker."""
    all_std = free_models + paid_models
    next_idx = display_models(free_models, "Top free models")
    next_idx = display_models(paid_models, "Cheapest paid models", start_idx=next_idx)

    print(f"\n    {cyan('0')}. Enter a custom model ID")
    print()

    while True:
        raw = input(f"  Pick {label} model number (or 0 for custom) [default: {default_id}]: ").strip()
        if not raw:
            return default_id

        try:
            choice = int(raw)
        except ValueError:
            print(red("  Please enter a number."))
            continue

        if choice == 0:
            custom = input("  Enter custom model ID: ").strip()
            return custom if custom else default_id

        if 1 <= choice <= len(all_std):
            return all_std[choice - 1]["id"]

        print(red(f"  Invalid choice. Pick 1–{len(all_std)} or 0 for custom."))


# ── Provider config ──────────────────────────────────────────

PROVIDER_DEFAULTS = {
    "openrouter": {
        "key_hint": "sk-or-...",
        "key_env": "OPENROUTER_API_KEY",
        "url": "https://openrouter.ai/keys",
    },
    "anthropic": {
        "key_hint": "sk-ant-...",
        "key_env": "ANTHROPIC_API_KEY",
        "url": "https://console.anthropic.com",
    },
    "openai": {
        "key_hint": "sk-...",
        "key_env": "OPENAI_API_KEY",
        "url": "https://platform.openai.com/api-keys",
    },
    "gemini": {
        "key_hint": "AIza...",
        "key_env": "GEMINI_API_KEY",
        "url": "https://aistudio.google.com/apikey",
    },
    "grok": {
        "key_hint": "xai-...",
        "key_env": "GROK_API_KEY",
        "url": "https://console.x.ai",
    },
}

PROVIDERS = list(PROVIDER_DEFAULTS.keys())

def pick_provider(label, default="openrouter"):
    print(bold(f"\n  {label} provider:"))
    for i, p in enumerate(PROVIDERS, 1):
        marker = green("✓") if p == default else " "
        print(f"    {marker} {cyan(str(i))}. {p}")
    raw = input(f"  Pick provider [default: {default}]: ").strip()
    if not raw:
        return default
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(PROVIDERS):
            return PROVIDERS[idx]
    except ValueError:
        if raw in PROVIDERS:
            return raw
    return default


def configure_agent(label, default_provider="openrouter", default_model=None,
                    free_models=None, paid_models=None):
    print(bold(f"\n{'─'*50}"))
    print(bold(f"  {label}"))
    print(f"{'─'*50}")

    provider = pick_provider(f"{label} — provider", default=default_provider)
    info = PROVIDER_DEFAULTS[provider]

    existing_key = os.environ.get(info["key_env"], "")
    if existing_key:
        print(f"  {green('✓')} Found existing {info['key_env']} in environment")
        api_key = existing_key
    else:
        print(f"  Get your key at: {cyan(info['url'])}")
        api_key = ask(f"  {label} API key ({info['key_hint']})", default="")

    if provider == "openrouter" and free_models is not None:
        model = pick_model(label, free_models, paid_models,
                           default_id=default_model or "deepseek/deepseek-chat-v3-0324:free")
    else:
        fallbacks = {
            "anthropic": "claude-3-5-haiku-20241022",
            "openai": "gpt-4o-mini",
            "gemini": "gemini-2.0-flash",
            "grok": "grok-3-mini-beta",
        }
        model = ask(f"  Model ID", default=default_model or fallbacks.get(provider, ""))

    return provider, api_key, model


# ── TTS configuration ────────────────────────────────────────

# ── TTS voice lists ──────────────────────────────────────────

QWEN3_SPEAKERS = [
    ("Ryan",   "Male   — youthful, clear, natural"),
    ("Ethan",  "Male   — seasoned, low and mellow"),
    ("Miles",  "Male   — calm, measured"),
    ("Leo",    "Male   — warm, conversational"),
    ("Vivian", "Female — bright, slightly edgy"),
    ("Cherry", "Female — warm, gentle"),
    ("Serena", "Female — smooth, professional"),
    ("Nova",   "Female — energetic, expressive"),
]

KOKORO_VOICES = [
    ("am_adam",   "Male   — American, warm"),
    ("am_michael","Male   — American, clear"),
    ("bm_george", "Male   — British, distinguished"),
    ("bm_lewis",  "Male   — British, measured"),
    ("af_heart",  "Female — American, natural"),
    ("af_bella",  "Female — American, expressive"),
    ("bf_emma",   "Female — British, warm"),
    ("bf_isabella","Female — British, smooth"),
]

def _detect_vram_gb() -> float:
    """Try to detect NVIDIA VRAM in GB. Returns 0.0 if no GPU found."""
    try:
        import subprocess, re
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, text=True
        ).strip().splitlines()[0]
        return round(int(out) / 1024, 1)
    except Exception:
        return 0.0

def _tts_recommendation() -> str:
    """Return a hardware-aware TTS recommendation string."""
    vram = _detect_vram_gb()
    if vram == 0:
        return (f"  💡 {bold('Recommendation:')} No NVIDIA GPU detected.\n"
                f"     → {green('Kokoro')} is ideal: 82M params, ~300MB, near real-time on CPU, zero GPU needed.")
    elif vram < 3:
        return (f"  💡 {bold('Recommendation:')} {yellow(f'{vram}GB VRAM detected')} — too small for Qwen3-TTS.\n"
                f"     → {green('Kokoro')} is ideal: 82M params, ~300MB, runs entirely on CPU.\n"
                f"     → Qwen3-TTS needs 2-4GB VRAM minimum and will crash on your GPU.")
    elif vram < 6:
        return (f"  💡 {bold('Recommendation:')} {yellow(f'{vram}GB VRAM')} — Kokoro or Qwen3-TTS (CPU) both work.\n"
                f"     → {green('Kokoro')} for speed, Qwen3-TTS for slightly richer voice variety.")
    else:
        return (f"  💡 {bold('Recommendation:')} {green(f'{vram}GB VRAM')} — any local option works well.\n"
                f"     → ElevenLabs for best quality, Kokoro for fast free local TTS.")

def configure_tts():
    print(bold(f"\n{'─'*50}"))
    print(bold("  🔊 Text-to-Speech"))
    print(f"{'─'*50}")
    print()
    print(_tts_recommendation())
    print()
    print(f"    {cyan('1')}. ElevenLabs  {dim('— cloud API, highest quality, 10K chars/month free')}")
    print(f"    {cyan('2')}. Kokoro       {dim('— local, free, 82M params, ~300MB, fast CPU inference')}")
    print(f"    {cyan('3')}. Qwen3-TTS   {dim('— local, free, 600M params, ~1.3GB, needs 3GB+ RAM')}")
    print(f"    {cyan('4')}. None        {dim('— text-only mode, no audio')}")
    print()

    choice = input("  Pick TTS provider [1/2/3/4, default: 2]: ").strip()

    if choice == "1":
        return _configure_elevenlabs()
    elif choice == "3":
        return _configure_qwen3()
    elif choice == "4":
        print(dim("  Skipping TTS — running in text-only mode"))
        return {"provider": "none"}
    else:
        return _configure_kokoro()


def _configure_elevenlabs():
    print(f"\n  {bold('ElevenLabs')}")
    print(f"  Free tier: 10K chars/month — {cyan('https://elevenlabs.io/app/settings/api-keys')}")
    api_key = ask("  API key (sk-...)", default="")
    if not api_key:
        print(yellow("  ⚠ No key entered — falling back to text-only"))
        return {"provider": "none"}
    print(f"\n  Default voices: Alex={dim('Rachel (21m00Tcm4TlvDq8ikWAM)')}  Sam={dim('Adam (pNInz6obpgDQGcFmaJgB)')}")
    print(dim("  Press Enter to keep defaults, or paste a voice ID from elevenlabs.io/voice-library"))
    voice_a = ask("  Alex  (Agent A) voice ID", default="21m00Tcm4TlvDq8ikWAM")
    voice_b = ask("  Sam   (Agent B) voice ID", default="pNInz6obpgDQGcFmaJgB")
    voice_c = ask("  Jordan(Agent C) voice ID", default="21m00Tcm4TlvDq8ikWAM")
    voice_d = ask("  Riley (Agent D) voice ID", default="pNInz6obpgDQGcFmaJgB")
    return {
        "provider":    "elevenlabs",
        "api_key":     api_key,
        "voice_a":     voice_a,
        "voice_b":     voice_b,
        "voice_c":     voice_c,
        "voice_d":     voice_d,
        "model":       "eleven_flash_v2_5",
    }


def _configure_qwen3():
    print(f"\n  {bold('Qwen3-TTS — local inference')}")
    print(f"  Model: {cyan('Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice')} (~1.3 GB download)")
    print(dim("  Runs on CPU — expect 5-15s per sentence on modest hardware."))
    print(dim("  A separate tts_server.py will handle inference so server.py stays fast.\n"))

    print(bold("  Speaker voices:"))
    for i, (name, desc) in enumerate(QWEN3_SPEAKERS, 1):
        print(f"    {cyan(str(i))}. {name:<8} {dim(desc)}")

    def pick_speaker(label, default_name):
        raw = input(f"\n  Pick {label} voice [default: {default_name}]: ").strip()
        if not raw:
            return default_name
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(QWEN3_SPEAKERS):
                return QWEN3_SPEAKERS[idx][0]
        except ValueError:
            if raw in [s[0] for s in QWEN3_SPEAKERS]:
                return raw
        print(yellow(f"  Invalid — using {default_name}"))
        return default_name

    voice_a = pick_speaker("Alex  (Agent A)", "Ryan")
    voice_b = pick_speaker("Sam   (Agent B)", "Ethan")
    voice_c = pick_speaker("Jordan(Agent C)", "Miles")
    voice_d = pick_speaker("Riley (Agent D)", "Leo")

    port = ask("  TTS server port", default="7861")
    return {
        "provider": "qwen3",
        "voice_a":  voice_a,
        "voice_b":  voice_b,
        "voice_c":  voice_c,
        "voice_d":  voice_d,
        "port":     port,
    }


def _configure_kokoro():
    print(f"\n  {bold('Kokoro — local inference (recommended for modest hardware)')}")
    print(f"  Model: {cyan('kokoro-onnx')} — 82M params, ~300MB download, no GPU needed")
    print(dim("  Runs entirely on CPU via ONNX runtime. Near real-time on most laptops.\n"))

    print(bold("  Voices:"))
    for i, (vid, desc) in enumerate(KOKORO_VOICES, 1):
        print(f"    {cyan(str(i))}. {vid:<14} {dim(desc)}")

    def pick_voice(label, default_id):
        raw = input(f"\n  Pick {label} voice [default: {default_id}]: ").strip()
        if not raw:
            return default_id
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(KOKORO_VOICES):
                return KOKORO_VOICES[idx][0]
        except ValueError:
            if raw in [v[0] for v in KOKORO_VOICES]:
                return raw
        print(yellow(f"  Invalid — using {default_id}"))
        return default_id

    voice_a = pick_voice("Alex  (Agent A)", "am_michael")
    voice_b = pick_voice("Sam   (Agent B)", "bm_george")
    voice_c = pick_voice("Jordan(Agent C)", "am_adam")
    voice_d = pick_voice("Riley (Agent D)", "bm_lewis")
    port = ask("  TTS server port", default="7862")
    return {
        "provider": "kokoro",
        "voice_a":  voice_a,
        "voice_b":  voice_b,
        "voice_c":  voice_c,
        "voice_d":  voice_d,
        "port":     port,
    }


# ── Write .env ───────────────────────────────────────────────

def write_env(agent_a, agent_b, agent_c, agent_d, tts):
    a_provider, a_key, a_model = agent_a
    b_provider, b_key, b_model = agent_b
    c_provider, c_key, c_model = agent_c
    d_provider, d_key, d_model = agent_d
    p = tts.get("provider", "none")

    # Build TTS block depending on provider
    if p == "elevenlabs":
        tts_block = f"""# ── TTS: ElevenLabs ─────────────────────────────────────────
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY={tts["api_key"]}
ELEVENLABS_MODEL={tts["model"]}
AGENT_A_VOICE_ID={tts["voice_a"]}
AGENT_B_VOICE_ID={tts["voice_b"]}
AGENT_C_VOICE_ID={tts.get("voice_c", tts["voice_a"])}
AGENT_D_VOICE_ID={tts.get("voice_d", tts["voice_b"])}"""
    elif p == "kokoro":
        tts_block = f"""# ── TTS: Kokoro local ───────────────────────────────────────
TTS_PROVIDER=kokoro
KOKORO_TTS_URL=http://localhost:{tts["port"]}
AGENT_A_KOKORO_VOICE={tts["voice_a"]}
AGENT_B_KOKORO_VOICE={tts["voice_b"]}
AGENT_C_KOKORO_VOICE={tts.get("voice_c", "am_adam")}
AGENT_D_KOKORO_VOICE={tts.get("voice_d", "bm_lewis")}"""
    elif p == "qwen3":
        tts_block = f"""# ── TTS: Qwen3-TTS local ────────────────────────────────────
TTS_PROVIDER=qwen3
QWEN3_TTS_URL=http://localhost:{tts["port"]}
AGENT_A_QWEN3_VOICE={tts["voice_a"]}
AGENT_B_QWEN3_VOICE={tts["voice_b"]}
AGENT_C_QWEN3_VOICE={tts.get("voice_c", "Miles")}
AGENT_D_QWEN3_VOICE={tts.get("voice_d", "Leo")}"""
    else:
        tts_block = "# ── TTS: disabled ──────────────────────────────────────────\nTTS_PROVIDER=none"

    env_content = f"""# GibberLink Revisited — generated by setup.py
# Re-run `python3 setup.py` at any time to reconfigure.

# ── Agent A (Alex) ───────────────────────────────────────────
AGENT_A_PROVIDER={a_provider}
AGENT_A_API_KEY={a_key}
AGENT_A_MODEL={a_model}

# ── Agent B (Sam) ────────────────────────────────────────────
AGENT_B_PROVIDER={b_provider}
AGENT_B_API_KEY={b_key}
AGENT_B_MODEL={b_model}

# ── Agent C (Jordan) ─────────────────────────────────────────
AGENT_C_PROVIDER={c_provider}
AGENT_C_API_KEY={c_key}
AGENT_C_MODEL={c_model}

# ── Agent D (Riley) ──────────────────────────────────────────
AGENT_D_PROVIDER={d_provider}
AGENT_D_API_KEY={d_key}
AGENT_D_MODEL={d_model}
{tts_block}

# ── Server ───────────────────────────────────────────────────
HOST=127.0.0.1
PORT=8765
"""
    with open(".env", "w") as f:
        f.write(env_content)
    print(green("\n  ✓ .env written"))

    # Post-config tips
    if p in ("kokoro", "qwen3"):
        print()
        print(bold("  ▶  Just run GibberLink — the TTS server starts automatically:"))
        print(f"       {cyan('python server.py')}")
        if p == "kokoro":
            print(dim("       (First start downloads ~300MB model, then loads in seconds)"))
        else:
            print(dim("       (First start downloads ~1.3GB model, may take a minute to load)"))


# ── Main ─────────────────────────────────────────────────────

def main():
    print(bold("\n🔗 GibberLink Revisited — Setup Wizard\n"))

    install_base_deps()

    # Try to get OpenRouter key early so we can fetch live models
    print(bold("\n🌐 Fetching live models from OpenRouter..."))
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not or_key:
        print(dim("  (Enter your OpenRouter key now to fetch live models, or press Enter to skip)"))
        or_key = input("  OpenRouter API key: ").strip()

    free_models, paid_models = [], []
    if or_key:
        free_models, paid_models = fetch_openrouter_models(or_key)
        print(green(f"  ✓ Fetched {len(free_models)} free + {len(paid_models)} cheapest paid models"))

    else:
        print(yellow("  ⚠ Skipping live fetch — you can still enter any model ID manually"))

    print(bold("\n🤖 Configure Agents"))

    agent_a = configure_agent(
        "Agent A — Alex",
        default_provider="openrouter",
        default_model="deepseek/deepseek-chat-v3-0324:free",
        free_models=free_models,
        paid_models=paid_models,
    )

    # If Agent A uses OpenRouter, pre-fill its key for Agent B
    if agent_a[0] == "openrouter" and or_key and not agent_a[1]:
        agent_a = (agent_a[0], or_key, agent_a[2])

    agent_b = configure_agent(
        "Agent B — Sam",
        default_provider="openrouter",
        default_model="meta-llama/llama-4-maverick:free",
        free_models=free_models,
        paid_models=paid_models,
    )

    agent_c = configure_agent(
        "Agent C — Jordan",
        default_provider="openrouter",
        default_model="google/gemini-2.0-flash-exp:free",
        free_models=free_models,
        paid_models=paid_models,
    )

    agent_d = configure_agent(
        "Agent D — Riley",
        default_provider="openrouter",
        default_model="mistralai/mistral-small-3.1-24b-instruct:free",
        free_models=free_models,
        paid_models=paid_models,
    )

    tts = configure_tts()

    # Install TTS deps right after selection so errors surface before .env is written
    if tts.get("provider") == "kokoro":
        install_kokoro_deps()
    elif tts.get("provider") == "qwen3":
        install_qwen3_deps()

    write_env(agent_a, agent_b, agent_c, agent_d, tts)

    print(bold("\n✅ Setup complete!\n"))
    print(f"  Run the server:  {cyan('python3 server.py')}")
    print(f"  Then open:       {cyan('http://127.0.0.1:8765')}")
    print()


if __name__ == "__main__":
    main()