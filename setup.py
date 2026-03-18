#!/usr/bin/env python3
"""
GibberLink Revisited — Setup Script
Run this once to configure your environment.
Fetches live model data from OpenRouter API.
"""

import os
import sys
import subprocess
import json

BANNER = r"""
   _____ _ _     _               _     _       _    
  / ____(_) |   | |             | |   (_)     | |   
 | |  __ _| |__ | |__   ___ _ __| |    _ _ __ | | __
 | | |_ | | '_ \| '_ \ / _ \ '__| |   | | '_ \| |/ /
 | |__| | | |_) | |_) |  __/ |  | |___| | | | |   < 
  \_____|_|_.__/|_.__/ \___|_|  |_____|_|_| |_|_|\_\
           R  E  V  I  S  I  T  E  D
"""

VOICES = [
    ("21m00Tcm4TlvDq8ikWAM", "Rachel (female, calm)"),
    ("pNInz6obpgDQGcFmaJgB", "Adam (male, deep)"),
    ("EXAVITQu4vr4xnSDxMaL", "Bella (female, warm)"),
    ("ErXwobaYiN019PkySvjV", "Antoni (male, crisp)"),
    ("MF3mGyEYCl7XYWbV9V6O", "Elli (female, young)"),
    ("TxGEqnHWrfWFTfGW9XjX", "Josh (male, mature)"),
]

OTHER_PROVIDERS = [
    {
        "id": "gemini",
        "name": "Google Gemini (free tier)",
        "key_url": "https://aistudio.google.com/apikey",
        "key_prefix": "",
        "models": [
            ("gemini-2.0-flash", "Gemini 2.0 Flash (free)"),
            ("gemini-2.5-flash-preview-05-20", "Gemini 2.5 Flash (free)"),
            ("gemini-2.5-pro-preview-05-06", "Gemini 2.5 Pro"),
        ],
    },
    {
        "id": "anthropic",
        "name": "Anthropic (Claude direct)",
        "key_url": "https://console.anthropic.com/",
        "key_prefix": "sk-ant-",
        "models": [
            ("claude-sonnet-4-20250514", "Claude Sonnet 4"),
            ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
        ],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "key_url": "https://platform.openai.com/api-keys",
        "key_prefix": "sk-",
        "models": [
            ("gpt-4o-mini", "GPT-4o Mini"),
            ("gpt-4o", "GPT-4o"),
        ],
    },
    {
        "id": "grok",
        "name": "xAI Grok",
        "key_url": "https://console.x.ai/",
        "key_prefix": "xai-",
        "models": [
            ("grok-3-mini-fast", "Grok 3 Mini Fast"),
            ("grok-3-fast", "Grok 3 Fast"),
        ],
    },
]


# ── Helpers ─────────────────────────────────────────────────
def color(text, code): return f"\033[{code}m{text}\033[0m"
def green(t):  return color(t, "32")
def red(t):    return color(t, "31")
def cyan(t):   return color(t, "36")
def yellow(t): return color(t, "33")
def bold(t):   return color(t, "1")
def dim(t):    return color(t, "2")
def mag(t):    return color(t, "35")


def ask(prompt, default=""):
    suffix = f" [{dim(default)}]" if default else ""
    val = input(f"  {prompt}{suffix}: ").strip()
    return val if val else default


# ── Fetch OpenRouter models ─────────────────────────────────
def fetch_openrouter_models():
    """Fetch live model list from OpenRouter API and return top free + top cheap."""
    try:
        import httpx
    except ImportError:
        # httpx not installed yet, use urllib
        import urllib.request
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"User-Agent": "GibberLink-Revisited/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    else:
        resp = httpx.get("https://openrouter.ai/api/v1/models", timeout=15)
        data = resp.json()

    models = data.get("data", [])

    # Filter to text chat models only
    chat_models = []
    for m in models:
        model_id = m.get("id", "")
        name = m.get("name", model_id)
        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", "0") or "0")
        context = m.get("context_length", 0)

        # Skip non-chat, image-only, embedding models
        if not model_id or "/embed" in model_id:
            continue

        chat_models.append({
            "id": model_id,
            "name": name,
            "prompt_price": prompt_price,
            "context": context,
            "is_free": prompt_price == 0,
        })

    # Split into free and paid
    free_models = [m for m in chat_models if m["is_free"]]
    paid_models = [m for m in chat_models if not m["is_free"]]

    # Sort free by context length (bigger = better), paid by price (cheapest first)
    free_models.sort(key=lambda m: m["context"], reverse=True)
    paid_models.sort(key=lambda m: m["prompt_price"])

    # Top 10 free, top 10 cheapest paid
    top_free = free_models[:10]
    top_paid = paid_models[:10]

    return top_free, top_paid


def format_price(price_per_token):
    """Format price per token to $/M tokens."""
    per_million = price_per_token * 1_000_000
    if per_million < 0.01:
        return "~free"
    if per_million < 1:
        return f"${per_million:.2f}/M"
    return f"${per_million:.1f}/M"


def pick_openrouter_model(label, top_free, top_paid):
    """Interactive model picker with live OpenRouter data."""
    print(f"\n  {bold(f'Pick model for {label}')}")

    # Build numbered list
    options = []
    idx = 0

    print(f"\n    {dim('── FREE (no credits needed) ──')}")
    print(f"    {cyan('0')}. {mag('openrouter/free')} — Auto-router (picks best available)")
    options.append(("openrouter/free", "Auto-router (free)"))

    for m in top_free:
        idx += 1
        ctx = f"{m['context']//1000}K" if m['context'] else "?"
        print(f"    {cyan(str(idx))}. {m['name']} {dim(f'[{ctx} ctx]')}")
        options.append((m["id"], m["name"]))

    print(f"\n    {dim('── CHEAPEST PAID ──')}")
    for m in top_paid:
        idx += 1
        price = format_price(m["prompt_price"])
        ctx = f"{m['context']//1000}K" if m['context'] else "?"
        print(f"    {cyan(str(idx))}. {m['name']} {dim(f'[{price} in, {ctx} ctx]')}")
        options.append((m["id"], m["name"]))

    print(f"\n    {dim('── CUSTOM ──')}")
    idx += 1
    print(f"    {cyan(str(idx))}. Enter a custom model ID")
    options.append(("__custom__", "Custom"))

    while True:
        choice = input(f"  Choice [0]: ").strip()
        if not choice:
            return options[0]
        try:
            i = int(choice)
            if 0 <= i < len(options):
                selected = options[i]
                if selected[0] == "__custom__":
                    print(f"    {dim('Browse models at: https://openrouter.ai/models')}")
                    custom_id = ask("Model ID (e.g. anthropic/claude-sonnet-4)")
                    if not custom_id:
                        print(f"    {red('Required.')}"); continue
                    return (custom_id, custom_id.split("/")[-1])
                return selected
        except ValueError:
            pass
        print(f"    {red('Invalid, try again.')}")


def pick_other_provider_model(agent_label):
    """Pick from non-OpenRouter providers."""
    print(f"\n  {bold(f'Provider for {agent_label}')}")
    for i, p in enumerate(OTHER_PROVIDERS, 1):
        print(f"    {cyan(str(i))}. {p['name']}")

    while True:
        choice = input(f"  Choice [1]: ").strip()
        if not choice:
            provider = OTHER_PROVIDERS[0]; break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(OTHER_PROVIDERS):
                provider = OTHER_PROVIDERS[idx]; break
        except ValueError:
            pass
        print(f"    {red('Invalid.')}")

    print(f"\n  Get your key at: {cyan(provider['key_url'])}")
    api_key = ask("API key")
    if not api_key:
        print(f"  {red('Required.')}"); sys.exit(1)

    print(f"\n  {bold('Model:')}")
    for i, (mid, mname) in enumerate(provider["models"], 1):
        print(f"    {cyan(str(i))}. {mname}")
    while True:
        choice = input(f"  Choice [1]: ").strip()
        if not choice:
            model_id, model_name = provider["models"][0]; break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(provider["models"]):
                model_id, model_name = provider["models"][idx]; break
        except ValueError:
            pass
        print(f"    {red('Invalid.')}")

    return {
        "provider": provider["id"],
        "api_key": api_key,
        "model": model_id,
        "display_name": model_name,
    }


# ── Main ────────────────────────────────────────────────────
def main():
    print(color(BANNER, "38;5;208"))
    print(f"  {bold('Setup Wizard')}")
    print(f"  {dim('Installs deps, fetches live models, creates .env')}")

    # Step 1: deps
    print(f"\n  {bold('Step 1:')} Installing dependencies...")
    for flags in [["--break-system-packages"], []]:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "-q"] + flags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            print(f"  {green('✓')} Done"); break
        except subprocess.CalledProcessError:
            continue
    else:
        print(f"  {red('✗')} Failed. Run: pip install -r requirements.txt")

    # Step 2: provider choice
    print(f"\n  {bold('Step 2:')} Choose provider")
    print(f"    {cyan('1')}. {bold('OpenRouter')} {dim('(recommended — free models, one API key)')}")
    print(f"    {cyan('2')}. Other (Gemini, Anthropic, OpenAI, Grok)")

    provider_choice = ask("Choice", "1")
    use_openrouter = provider_choice != "2"

    if use_openrouter:
        # Fetch live models
        print(f"\n  {bold('Step 3:')} Fetching live models from OpenRouter...")
        try:
            top_free, top_paid = fetch_openrouter_models()
            print(f"  {green('✓')} Found {len(top_free)} free + {len(top_paid)} cheap models")
        except Exception as e:
            print(f"  {red('✗')} Could not fetch models: {e}")
            print(f"  {dim('Falling back to manual entry...')}")
            top_free, top_paid = [], []

        # API key
        print(f"\n  Get your key at: {cyan('https://openrouter.ai/keys')}")
        api_key = ask("OpenRouter API key")
        if not api_key:
            print(f"  {red('Required.')}"); sys.exit(1)
        if not api_key.startswith("sk-or-"):
            print(f"  {yellow('⚠')} Doesn't start with 'sk-or-' — might not work")
        else:
            print(f"  {green('✓')} Key accepted")

        if top_free or top_paid:
            model_a_id, model_a_name = pick_openrouter_model("Agent A", top_free, top_paid)
            print(f"  {green('✓')} Agent A → {bold(model_a_name)}")

            print(f"\n  {dim('Pick a DIFFERENT model for Agent B for more interesting conversations!')}")
            model_b_id, model_b_name = pick_openrouter_model("Agent B", top_free, top_paid)
            print(f"  {green('✓')} Agent B → {bold(model_b_name)}")
        else:
            # Manual fallback
            model_a_id = ask("Agent A model ID", "openrouter/free")
            model_a_name = model_a_id.split("/")[-1]
            model_b_id = ask("Agent B model ID", "openrouter/free")
            model_b_name = model_b_id.split("/")[-1]

        agent_a = {"provider": "openrouter", "api_key": api_key, "model": model_a_id, "display_name": model_a_name}
        agent_b = {"provider": "openrouter", "api_key": api_key, "model": model_b_id, "display_name": model_b_name}

    else:
        print(f"\n  {bold('Step 3:')} Configure agents")
        agent_a = pick_other_provider_model("Agent A")
        agent_b = pick_other_provider_model("Agent B")

    # TTS
    print(f"\n  {bold('Step 4:')} Text-to-Speech {dim('(optional)')}")
    print(f"  {dim('ElevenLabs: 10K chars/month free, no credit card.')}")
    print(f"  {dim('Key: https://elevenlabs.io/app/settings/api-keys')}")
    elevenlabs_key = ask("ElevenLabs key (enter to skip)")

    voice_a, voice_b = VOICES[0][0], VOICES[1][0]
    if elevenlabs_key:
        print(f"  {green('✓')} TTS enabled")
        print(f"\n  {bold('Voice for Agent A:')}")
        for i, (v, n) in enumerate(VOICES, 1):
            print(f"    {cyan(str(i))}. {n}")
        va = input(f"  Choice [1]: ").strip()
        va_idx = (int(va) - 1) if va.isdigit() and 0 < int(va) <= len(VOICES) else 0
        voice_a = VOICES[va_idx][0]

        remaining = [(v, n) for v, n in VOICES if v != voice_a]
        print(f"\n  {bold('Voice for Agent B:')}")
        for i, (v, n) in enumerate(remaining, 1):
            print(f"    {cyan(str(i))}. {n}")
        vb = input(f"  Choice [1]: ").strip()
        vb_idx = (int(vb) - 1) if vb.isdigit() and 0 < int(vb) <= len(remaining) else 0
        voice_b = remaining[vb_idx][0]
    else:
        print(f"  {yellow('○')} Skipped — text-only mode")

    # Write .env
    print(f"\n  {bold('Step 5:')} Writing .env...")
    if os.path.exists(".env"):
        if ask(".env exists. Overwrite? (y/n)", "y").lower() != "y":
            print(f"  {dim('Skipped.')}"); return

    with open(".env", "w") as f:
        f.write(f"""# GibberLink Revisited — Auto-generated
AGENT_A_PROVIDER={agent_a['provider']}
AGENT_A_API_KEY={agent_a['api_key']}
AGENT_A_MODEL={agent_a['model']}
AGENT_B_PROVIDER={agent_b['provider']}
AGENT_B_API_KEY={agent_b['api_key']}
AGENT_B_MODEL={agent_b['model']}
ELEVENLABS_API_KEY={elevenlabs_key or ''}
AGENT_A_VOICE_ID={voice_a}
AGENT_B_VOICE_ID={voice_b}
ELEVENLABS_MODEL=eleven_flash_v2_5
HOST=127.0.0.1
PORT=8765
""")
    print(f"  {green('✓')} .env created")

    print(f"\n  {green('═' * 46)}")
    print(f"  {green(bold('  Setup complete!'))}")
    print(f"  {green('═' * 46)}")
    print(f"\n  Agent A: {bold(agent_a['display_name'])} ({agent_a['provider']})")
    print(f"  Agent B: {bold(agent_b['display_name'])} ({agent_b['provider']})")
    print(f"  TTS:     {bold('ElevenLabs') if elevenlabs_key else dim('Disabled')}")
    print(f"\n  Run:  {cyan('python3 server.py')}")
    print(f"  Open: {cyan('http://127.0.0.1:8765')}\n")


if __name__ == "__main__":
    main()