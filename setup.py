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

# ── Hardcoded uncensored model list ─────────────────────────
# These are known uncensored/unfiltered models on OpenRouter.
# Marked (free) where a :free variant exists.
UNCENSORED_MODELS = [
    {
        "id": "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
        "name": "Venice Uncensored — Dolphin Mistral 24B (free)",
        "note": "Uncensored fine-tune of Mistral 24B by dphn.ai x Venice.ai",
    },
    {
        "id": "cognitivecomputations/dolphin3.0-mistral-24b:free",
        "name": "Dolphin 3.0 Mistral 24B (free)",
        "note": "Uncensored instruct model, stripped of alignment layers",
    },
    {
        "id": "cognitivecomputations/dolphin-llama-3.3-70b",
        "name": "Dolphin Llama 3.3 70B",
        "note": "Uncensored Llama 3.3 70B fine-tune — requires credits",
    },
    {
        "id": "cognitivecomputations/dolphin3.0-r1-mistral-24b:free",
        "name": "Dolphin 3.0 R1 Mistral 24B (free)",
        "note": "Reasoning-capable uncensored Dolphin with R1-style CoT",
    },
    {
        "id": "nousresearch/hermes-3-llama-3.1-70b",
        "name": "Hermes 3 Llama 3.1 70B",
        "note": "Lightly aligned, highly steerable — requires credits",
    },
    {
        "id": "nousresearch/hermes-3-llama-3.1-405b",
        "name": "Hermes 3 Llama 3.1 405B",
        "note": "Largest Hermes — very capable, requires credits",
    },
    {
        "id": "sao10k/l3.3-euryale-70b",
        "name": "Euryale 70B v2.3",
        "note": "Creative/roleplay focused, minimal restrictions",
    },
    {
        "id": "venice/uncensored:free",
        "name": "Venice: Uncensored (free)",
        "note": "Venice.ai hosted uncensored model — free tier",
    },
]

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

def install_deps():
    print(bold("\n📦 Installing Python dependencies..."))

    # Detect if we're already inside the .venv
    in_venv = (
        hasattr(sys, "real_prefix")
        or (hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix)
    )

    if in_venv:
        # Already in a venv — install directly
        pip = [sys.executable, "-m", "pip"]
    else:
        # System Python on Debian/Ubuntu (PEP 668) — use/create .venv
        venv_python = ensure_venv()
        pip = [venv_python, "-m", "pip"]

        # Re-exec setup.py inside the venv so the rest of the wizard
        # can import freshly installed packages (httpx etc.)
        if sys.executable != venv_python:
            print(dim(f"  Re-launching setup inside .venv..."))
            os.execv(venv_python, [venv_python] + sys.argv)

    subprocess.check_call(pip + ["install", "-r", "requirements.txt", "-q"])
    print(green("  ✓ Dependencies installed"))

    print(dim(f"\n  Tip: to run the server use the venv Python:"))
    print(dim(f"       .venv/bin/python server.py"))
    print(dim(f"  Or activate the venv first:"))
    print(dim(f"       source .venv/bin/activate && python server.py\n"))

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

    # Enrich hardcoded uncensored list with live pricing data
    for u in UNCENSORED_MODELS:
        u["pricing"] = live_pricing.get(u["id"], {})

    for m in models:
        mid = m.get("id", "")
        pricing = m.get("pricing", {})
        try:
            prompt_cost = float(pricing.get("prompt", "0") or 0)
        except (ValueError, TypeError):
            prompt_cost = 0.0

        # Skip uncensored — we handle those separately
        if any(tag in mid.lower() for tag in ["dolphin", "hermes", "euryale", "venice/uncensored"]):
            continue

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


def display_uncensored_models(start_idx):
    print(bold(f"\n  🔓 Uncensored / Unfiltered models:"))
    for i, m in enumerate(UNCENSORED_MODELS, start=start_idx):
        pricing = m.get("pricing", {})
        try:
            prompt_cost = float(pricing.get("prompt", "0") or 0)
            compl_cost  = float(pricing.get("completion", "0") or 0)
            if prompt_cost == 0 and compl_cost == 0:
                cost_str = green("free")
            else:
                cost_str = yellow(f"${prompt_cost * 1e6:.2f}/${compl_cost * 1e6:.2f} per M tok (in/out)")
        except (ValueError, TypeError):
            cost_str = dim("price unknown")

        name = m["name"].split(" (")[0]  # strip old hardcoded (free)/(paid) suffix
        print(f"    {cyan(str(i).rjust(2))}. {name:<48} {cost_str}")
        print(f"        {dim(m['note'])}")
        print(f"        {dim(m['id'])}")
    return start_idx + len(UNCENSORED_MODELS)


def pick_model(label, free_models, paid_models, default_id):
    """Interactive model picker including uncensored section."""
    all_std = free_models + paid_models
    next_idx = display_models(free_models, "Top free models")
    next_idx = display_models(paid_models, "Cheapest paid models", start_idx=next_idx)
    uncensored_start = next_idx
    next_idx = display_uncensored_models(start_idx=uncensored_start)

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

        std_count = len(all_std)
        if 1 <= choice <= std_count:
            return all_std[choice - 1]["id"]

        uncensored_idx = choice - uncensored_start
        if 0 <= uncensored_idx < len(UNCENSORED_MODELS):
            selected = UNCENSORED_MODELS[uncensored_idx]
            print(yellow(f"\n  ⚠  You selected an uncensored model: {selected['name']}"))
            print(yellow(     "     These models have reduced safety filters."))
            print(yellow(     "     Use responsibly and in accordance with OpenRouter's ToS.\n"))
            confirm = ask_yn("  Confirm selection?", default=True)
            if confirm:
                return selected["id"]
            else:
                print("  Selection cancelled, please pick again.")
                continue

        print(red(f"  Invalid choice. Pick 1–{next_idx - 1} or 0 for custom."))


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


# ── ElevenLabs TTS ───────────────────────────────────────────

def configure_tts():
    print(bold(f"\n{'─'*50}"))
    print(bold("  🔊 Text-to-Speech (ElevenLabs — optional)"))
    print(f"{'─'*50}")
    print("  Free tier: 10K characters/month, no credit card needed.")
    print(f"  Get a key at: {cyan('https://elevenlabs.io/app/settings/api-keys')}")
    print(dim("  (Press Enter to skip TTS and run in text-only mode)"))

    api_key = ask("  ElevenLabs API key", default="")
    if not api_key:
        print(dim("  Skipping TTS — running in text-only mode"))
        return "", "21m00Tcm4TlvDq8ikWAM", "pNInz6obpgDQGcFmaJgB"

    print(f"\n  Default voices: Alex={dim('Rachel')}  Sam={dim('Adam')}")
    print(dim("  (Press Enter to keep defaults, or paste a voice ID from elevenlabs.io/voice-library)"))
    voice_a = ask("  Alex voice ID", default="21m00Tcm4TlvDq8ikWAM")
    voice_b = ask("  Sam voice ID",  default="pNInz6obpgDQGcFmaJgB")
    return api_key, voice_a, voice_b


# ── Write .env ───────────────────────────────────────────────

def write_env(agent_a, agent_b, tts):
    a_provider, a_key, a_model = agent_a
    b_provider, b_key, b_model = agent_b
    tts_key, voice_a, voice_b = tts

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

# ── ElevenLabs TTS (optional) ────────────────────────────────
ELEVENLABS_API_KEY={tts_key}
AGENT_A_VOICE_ID={voice_a}
AGENT_B_VOICE_ID={voice_b}
ELEVENLABS_MODEL=eleven_flash_v2_5

# ── Server ───────────────────────────────────────────────────
HOST=127.0.0.1
PORT=8765
"""
    with open(".env", "w") as f:
        f.write(env_content)
    print(green("\n  ✓ .env written"))


# ── Main ─────────────────────────────────────────────────────

def main():
    print(bold("\n🔗 GibberLink Revisited — Setup Wizard\n"))

    install_deps()

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
        print(green(f"  ✓ Plus {len(UNCENSORED_MODELS)} curated uncensored models available"))
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

    tts = configure_tts()

    write_env(agent_a, agent_b, tts)

    print(bold("\n✅ Setup complete!\n"))
    print(f"  Run the server:  {cyan('python3 server.py')}")
    print(f"  Then open:       {cyan('http://127.0.0.1:8765')}")
    print()


if __name__ == "__main__":
    main()