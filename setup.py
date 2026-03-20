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

# Minimum requirements for a model to work well as a council agent
_MIN_CONTEXT_LENGTH = 4000       # multi-turn council needs decent context

def _is_suitable_model(m: dict) -> bool:
    """Check if a model is suitable for council deliberation."""
    # Must have sufficient context
    ctx = m.get("context_length", 0)
    if ctx < _MIN_CONTEXT_LENGTH:
        return False

    # Skip embedding-only, image-only, or audio-only models
    mid = m.get("id", "").lower()
    skip_keywords = ["embed", "tts", "whisper", "dall-e", "stable-diffusion",
                     "midjourney", "imagen", "music", "vision-preview",
                     "moderation", "guard", "safety", "classifier"]
    if any(kw in mid for kw in skip_keywords):
        return False

    # Skip if architecture says no text output (but allow if field is missing)
    arch = m.get("architecture", {})
    output_mods = arch.get("output_modalities", [])
    if output_mods and "text" not in output_mods:
        return False

    return True


def _model_cost(m: dict) -> float:
    """Total cost per million tokens (prompt + completion) for sorting."""
    pricing = m.get("pricing", {})
    try:
        prompt = float(pricing.get("prompt", "0") or 0)
        completion = float(pricing.get("completion", "0") or 0)
        return (prompt + completion) * 1e6  # cost per 1M tokens
    except (ValueError, TypeError):
        return 999.0


# Fallback models if the live API fetch fails or returns nothing
_FALLBACK_FREE_MODELS = [
    {"id": "deepseek/deepseek-chat-v3-0324:free", "name": "DeepSeek V3 (free)", "context_length": 64000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "meta-llama/llama-4-maverick:free", "name": "Llama 4 Maverick (free)", "context_length": 128000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini 2.0 Flash (free)", "context_length": 1048576, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "mistralai/mistral-small-3.1-24b-instruct:free", "name": "Mistral Small 3.1 (free)", "context_length": 96000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "qwen/qwen-2.5-72b-instruct:free", "name": "Qwen 2.5 72B (free)", "context_length": 32768, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "microsoft/phi-4:free", "name": "Phi-4 (free)", "context_length": 16384, "pricing": {"prompt": "0", "completion": "0"}},
]

_FALLBACK_PAID_MODELS = [
    {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3", "context_length": 64000, "pricing": {"prompt": "0.00000014", "completion": "0.00000028"}},
    {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash", "context_length": 1048576, "pricing": {"prompt": "0.0000001", "completion": "0.0000004"}},
    {"id": "google/gemini-2.5-flash-preview", "name": "Gemini 2.5 Flash", "context_length": 1048576, "pricing": {"prompt": "0.00000015", "completion": "0.0000006"}},
    {"id": "mistralai/mistral-small-latest", "name": "Mistral Small", "context_length": 32000, "pricing": {"prompt": "0.0000001", "completion": "0.0000003"}},
    {"id": "anthropic/claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "context_length": 200000, "pricing": {"prompt": "0.0000008", "completion": "0.000004"}},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "context_length": 128000, "pricing": {"prompt": "0.00000015", "completion": "0.0000006"}},
    {"id": "meta-llama/llama-4-maverick", "name": "Llama 4 Maverick", "context_length": 128000, "pricing": {"prompt": "0.0000002", "completion": "0.0000006"}},
    {"id": "qwen/qwen-2.5-72b-instruct", "name": "Qwen 2.5 72B", "context_length": 32768, "pricing": {"prompt": "0.00000016", "completion": "0.00000016"}},
    {"id": "mistralai/mistral-nemo", "name": "Mistral Nemo", "context_length": 128000, "pricing": {"prompt": "0.00000003", "completion": "0.00000003"}},
    {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1", "context_length": 64000, "pricing": {"prompt": "0.00000055", "completion": "0.00000219"}},
    {"id": "google/gemma-3-27b-it", "name": "Gemma 3 27B", "context_length": 96000, "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}},
    {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Nemotron 70B", "context_length": 131072, "pricing": {"prompt": "0.00000012", "completion": "0.0000003"}},
]


def fetch_openrouter_models(api_key: str):
    """Fetch available models from OpenRouter, return top free + cheapest paid.
    
    Filters for chat-capable models with sufficient context length.
    Sorts free models by context length, paid by total cost.
    Falls back to a hardcoded list if the API fetch fails.
    """
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            models = resp.json().get("data", [])
    except Exception as e:
        print(yellow(f"  ⚠ Could not fetch live models: {e}"))
        print(dim("  Using fallback model list"))
        return _FALLBACK_FREE_MODELS, _FALLBACK_PAID_MODELS

    if not models:
        print(yellow("  ⚠ API returned no models — using fallback list"))
        return _FALLBACK_FREE_MODELS, _FALLBACK_PAID_MODELS

    free_models = []
    paid_models = []

    for m in models:
        if not _is_suitable_model(m):
            continue

        mid = m.get("id", "")
        pricing = m.get("pricing", {})
        try:
            prompt_cost = float(pricing.get("prompt", "0") or 0)
        except (ValueError, TypeError):
            prompt_cost = 0.0

        if mid.endswith(":free") or prompt_cost == 0.0:
            free_models.append(m)
        else:
            paid_models.append(m)

    # Free: sort by context length descending (bigger context = better for debate)
    free_models.sort(key=lambda m: m.get("context_length", 0), reverse=True)
    # Paid: sort by total cost ascending (cheapest first)
    paid_models.sort(key=lambda m: _model_cost(m))

    top_free = free_models[:12]
    top_paid = paid_models[:20]

    # If live fetch returned too few, supplement with fallbacks
    if len(top_free) < 3:
        print(dim("  (few free models found — supplementing with known models)"))
        top_free = _FALLBACK_FREE_MODELS
    if len(top_paid) < 5:
        print(dim("  (few paid models found — supplementing with known models)"))
        top_paid = _FALLBACK_PAID_MODELS

    total_skipped = len(models) - len(free_models) - len(paid_models)
    if total_skipped > 0:
        print(dim(f"  ({total_skipped} models filtered out — embedding, image, low-context, etc.)"))

    return top_free, top_paid


def display_models(models, label, start_idx=1):
    print(bold(f"\n  {label}:"))
    for i, m in enumerate(models, start=start_idx):
        name = m.get("name") or m.get("id", "")
        mid = m.get("id", "")
        ctx = m.get("context_length", 0)
        ctx_str = f"{ctx//1000}k" if ctx >= 1000 else str(ctx)
        pricing = m.get("pricing", {})
        try:
            cost = float(pricing.get("prompt", 0) or 0)
            cost_str = "free" if cost == 0 else f"${cost * 1e6:.2f}/M"
        except (ValueError, TypeError):
            cost_str = "?"
        print(f"    {cyan(str(i).rjust(2))}. {name[:40]:<40} {dim(ctx_str):>6}  {dim(cost_str):<10} {dim(mid)}")
    return start_idx + len(models)


def pick_model(label, free_models, paid_models, default_id):
    """Interactive model picker."""
    all_std = free_models + paid_models
    print(dim(f"\n  {'':>4}  {'Model':<40} {'Ctx':>6}  {'Cost':<10} {'ID'}"))
    print(dim(f"  {'':>4}  {'─'*40} {'─'*6}  {'─'*10} {'─'*30}"))
    next_idx = display_models(free_models, "Free models (sorted by context length)")
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
    "opencode_zen": {
        "key_hint": "oc-...",
        "key_env": "OPENCODE_API_KEY",
        "url": "https://opencode.ai/auth",
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
                    free_models=None, paid_models=None, key_cache=None):
    """Configure a single agent. key_cache is a dict of {key_env: key_value}
    shared across all agents so users only enter each API key once."""
    if key_cache is None:
        key_cache = {}

    print(bold(f"\n{'─'*50}"))
    print(bold(f"  {label}"))
    print(f"{'─'*50}")

    provider = pick_provider(f"{label} — provider", default=default_provider)
    info = PROVIDER_DEFAULTS[provider]

    # Check cache first, then env, then ask
    api_key = key_cache.get(info["key_env"], "")
    if not api_key:
        api_key = os.environ.get(info["key_env"], "")
    if api_key:
        print(f"  {green('✓')} Reusing {info['key_env']} from {'previous agent' if info['key_env'] in key_cache else 'environment'}")
    else:
        print(f"  Get your key at: {cyan(info['url'])}")
        api_key = ask(f"  {label} API key ({info['key_hint']})", default="")

    # Cache the key for subsequent agents
    if api_key:
        key_cache[info["key_env"]] = api_key

    if provider == "openrouter" and free_models is not None:
        model = pick_model(label, free_models, paid_models,
                           default_id=default_model or "deepseek/deepseek-chat-v3-0324:free")
    elif provider == "opencode_zen":
        # OpenCode Zen uses opencode/ prefix for model IDs
        fallback = default_model or "opencode/big-pickle"
        print(f"\n  {dim('OpenCode Zen models: opencode/gpt-5.3-codex, opencode/claude-sonnet-4-6,')}")
        print(f"  {dim('opencode/gemini-3-flash, opencode/big-pickle, opencode/qwen-max, etc.')}")
        print(f"  {dim('Full list: https://opencode.ai/docs/zen/')}")
        model = ask(f"  Model ID", default=fallback)
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
    voice_ch = ask("  Nexus (Chairman) voice ID", default="21m00Tcm4TlvDq8ikWAM")
    return {
        "provider":    "elevenlabs",
        "api_key":     api_key,
        "voice_a":     voice_a,
        "voice_b":     voice_b,
        "voice_c":     voice_c,
        "voice_d":     voice_d,
        "voice_ch":    voice_ch,
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
    voice_ch = pick_speaker("Nexus (Chairman)", "Axel")

    port = ask("  TTS server port", default="7861")
    return {
        "provider": "qwen3",
        "voice_a":  voice_a,
        "voice_b":  voice_b,
        "voice_c":  voice_c,
        "voice_d":  voice_d,
        "voice_ch": voice_ch,
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
    voice_ch = pick_voice("Nexus (Chairman)", "am_echo")
    port = ask("  TTS server port", default="7862")
    return {
        "provider": "kokoro",
        "voice_a":  voice_a,
        "voice_b":  voice_b,
        "voice_c":  voice_c,
        "voice_d":  voice_d,
        "voice_ch": voice_ch,
        "port":     port,
    }


# ── Write .env ───────────────────────────────────────────────

def write_env(agent_a, agent_b, agent_c, agent_d, chairman, tts):
    a_provider, a_key, a_model = agent_a
    b_provider, b_key, b_model = agent_b
    c_provider, c_key, c_model = agent_c
    d_provider, d_key, d_model = agent_d
    ch_provider, ch_key, ch_model = chairman
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
AGENT_D_VOICE_ID={tts.get("voice_d", tts["voice_b"])}
CHAIRMAN_VOICE_ID={tts.get("voice_ch", tts["voice_a"])}"""
    elif p == "kokoro":
        tts_block = f"""# ── TTS: Kokoro local ───────────────────────────────────────
TTS_PROVIDER=kokoro
KOKORO_TTS_URL=http://localhost:{tts["port"]}
AGENT_A_KOKORO_VOICE={tts["voice_a"]}
AGENT_B_KOKORO_VOICE={tts["voice_b"]}
AGENT_C_KOKORO_VOICE={tts.get("voice_c", "am_adam")}
AGENT_D_KOKORO_VOICE={tts.get("voice_d", "bm_lewis")}
CHAIRMAN_KOKORO_VOICE={tts.get("voice_ch", "am_echo")}"""
    elif p == "qwen3":
        tts_block = f"""# ── TTS: Qwen3-TTS local ────────────────────────────────────
TTS_PROVIDER=qwen3
QWEN3_TTS_URL=http://localhost:{tts["port"]}
AGENT_A_QWEN3_VOICE={tts["voice_a"]}
AGENT_B_QWEN3_VOICE={tts["voice_b"]}
AGENT_C_QWEN3_VOICE={tts.get("voice_c", "Miles")}
AGENT_D_QWEN3_VOICE={tts.get("voice_d", "Leo")}
CHAIRMAN_QWEN3_VOICE={tts.get("voice_ch", "Axel")}"""
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

# ── Chairman (Nexus) ─────────────────────────────────────────
CHAIRMAN_PROVIDER={ch_provider}
CHAIRMAN_API_KEY={ch_key}
CHAIRMAN_MODEL={ch_model}
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

    # Shared key cache — enter each API key once, reuse across agents
    key_cache = {}

    # Try to get OpenRouter key early so we can fetch live models
    print(bold("\n🌐 Fetching live models from OpenRouter..."))
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not or_key:
        print(dim("  (Enter your OpenRouter key now to fetch live models, or press Enter to skip)"))
        or_key = input("  OpenRouter API key: ").strip()

    free_models, paid_models = [], []
    if or_key:
        key_cache["OPENROUTER_API_KEY"] = or_key
        free_models, paid_models = fetch_openrouter_models(or_key)
        print(green(f"  ✓ Fetched {len(free_models)} free + {len(paid_models)} cheapest paid models"))
    else:
        print(yellow("  ⚠ Skipping live fetch — you can still enter any model ID manually"))

    print(bold("\n🤖 Configure Agents"))
    print(dim("  Tip: API keys are shared automatically — enter each key only once.\n"))

    agent_a = configure_agent(
        "Voss — Strategist",
        default_provider="openrouter",
        default_model="deepseek/deepseek-chat-v3-0324:free",
        free_models=free_models,
        paid_models=paid_models,
        key_cache=key_cache,
    )

    agent_b = configure_agent(
        "Lyra — Creative",
        default_provider="openrouter",
        default_model="meta-llama/llama-4-maverick:free",
        free_models=free_models,
        paid_models=paid_models,
        key_cache=key_cache,
    )

    agent_c = configure_agent(
        "Kael — Skeptic",
        default_provider="openrouter",
        default_model="google/gemini-2.0-flash-exp:free",
        free_models=free_models,
        paid_models=paid_models,
        key_cache=key_cache,
    )

    agent_d = configure_agent(
        "Iris — Synthesizer",
        default_provider="openrouter",
        default_model="mistralai/mistral-small-3.1-24b-instruct:free",
        free_models=free_models,
        paid_models=paid_models,
        key_cache=key_cache,
    )

    print(bold(f"\n{'─'*50}"))
    print(bold("  ◈ Chairman — Nexus (synthesizes the final verdict)"))
    print(f"{'─'*50}")

    chairman = configure_agent(
        "Nexus — Chairman",
        default_provider="openrouter",
        default_model="deepseek/deepseek-chat-v3-0324:free",
        free_models=free_models,
        paid_models=paid_models,
        key_cache=key_cache,
    )

    tts = configure_tts()

    # Install TTS deps right after selection so errors surface before .env is written
    if tts.get("provider") == "kokoro":
        install_kokoro_deps()
    elif tts.get("provider") == "qwen3":
        install_qwen3_deps()

    write_env(agent_a, agent_b, agent_c, agent_d, chairman, tts)

    print(bold("\n✅ Setup complete!\n"))
    print(f"  Run the server:  {cyan('python3 server.py')}")
    print(f"  Then open:       {cyan('http://127.0.0.1:8765')}")
    print()


if __name__ == "__main__":
    main()