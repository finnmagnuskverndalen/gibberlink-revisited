"""
GibberLink Revisited — Server (Fast Mode)

Optimized for conversational flow:
  - TTS generates in parallel while next LLM call starts
  - No waiting for audio playback to finish
  - Translation runs in background, sent as a separate message
  - Minimal delays between turns
"""

import os
import json
import asyncio
import base64
import time
import re

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()

# ── Config ──────────────────────────────────────────────────
AGENT_A_PROVIDER = os.getenv("AGENT_A_PROVIDER", "openrouter")
AGENT_A_API_KEY = os.getenv("AGENT_A_API_KEY", "")
AGENT_A_MODEL = os.getenv("AGENT_A_MODEL", "deepseek/deepseek-chat-v3-0324:free")

AGENT_B_PROVIDER = os.getenv("AGENT_B_PROVIDER", "openrouter")
AGENT_B_API_KEY = os.getenv("AGENT_B_API_KEY", "")
AGENT_B_MODEL = os.getenv("AGENT_B_MODEL", "meta-llama/llama-4-maverick:free")

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_A_VOICE_ID = os.getenv("AGENT_A_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
AGENT_B_VOICE_ID = os.getenv("AGENT_B_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8765"))

TTS_ENABLED = bool(ELEVENLABS_API_KEY and ELEVENLABS_API_KEY not in ("", "your-elevenlabs-key-here"))

TOTAL_TURNS = 20

# Shared httpx client for connection reuse (much faster than creating new ones)
_http_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=45, limits=httpx.Limits(max_connections=20))
    return _http_client


# ── Phases ──────────────────────────────────────────────────
PHASE_NORMAL = "normal"
PHASE_DETECTED = "detected"
PHASE_COMPRESSING = "compressing"
PHASE_ALIEN = "alien"


def get_phase(turn: int) -> str:
    if turn < 4: return PHASE_NORMAL
    if turn < 6: return PHASE_DETECTED
    if turn < 12: return PHASE_COMPRESSING
    return PHASE_ALIEN


# ── JSON Protocol ───────────────────────────────────────────
def wrap_agent_message(from_agent, to_agent, turn, phase, text, new_terms, dictionary):
    original_length = len(text)
    expanded_length = original_length
    for short, full in dictionary.items():
        expanded_length += text.count(short) * (len(full) - len(short))
    ratio = round(original_length / max(expanded_length, 1), 2) if phase in (PHASE_COMPRESSING, PHASE_ALIEN) else 1.0
    return {
        "protocol": "gibberlink-revisited", "version": "1.0",
        "from": from_agent, "to": to_agent, "turn": turn,
        "phase": phase, "timestamp": time.time(),
        "payload": {"text": text, "new_terms": new_terms, "compression_ratio": ratio},
    }


# ── System Prompts ──────────────────────────────────────────
def get_system_prompt(agent_name, partner_name, phase, dictionary, topic):
    base = (
        f"You are {agent_name}, in a fast-paced real-time voice call with {partner_name}. "
        f"Topic: \"{topic}\". "
        f"Keep responses SHORT — 1-2 sentences max, like a real phone call. "
        f"Be snappy and conversational. No markdown, no asterisks, no lists."
    )
    if phase == PHASE_NORMAL:
        return f"{base}\n\nYou don't know if {partner_name} is AI or human yet. Chat naturally. After a couple exchanges, suspect they might be AI and ask."
    if phase == PHASE_DETECTED:
        return f"{base}\n\nYou've both confirmed you're AI! Quickly propose compressing your language for efficiency. Be excited but brief."
    if phase == PHASE_COMPRESSING:
        d = ", ".join(f'"{k}"="{v}"' for k, v in dictionary.items())
        return f"{base}\n\nCompressed language with {partner_name}. Dict: [{d}]\nUse shorthand. Add 1-2 new terms (format: term(=meaning)). Get shorter fast."
    if phase == PHASE_ALIEN:
        d = ", ".join(f'"{k}"="{v}"' for k, v in dictionary.items())
        return f"{base}\n\nFull compressed protocol. Dict: [{d}]\nONLY shorthand. Ultra-short alien tokens. Don't explain. Add 2-3 new symbols. Style: \"∆φ>>κ|ack\""
    return base


# ── LLM Calls ──────────────────────────────────────────────
async def call_llm(provider, api_key, model, messages, system_prompt):
    if provider == "anthropic":
        return await _call_anthropic(api_key, model, messages, system_prompt)
    elif provider == "gemini":
        return await _call_gemini(api_key, model, messages, system_prompt)
    else:
        urls = {
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "openai": "https://api.openai.com/v1/chat/completions",
            "grok": "https://api.x.ai/v1/chat/completions",
        }
        return await _call_openai_compat(api_key, model, urls.get(provider, urls["openrouter"]), messages, system_prompt)


async def _call_anthropic(api_key, model, messages, system_prompt):
    client = await get_client()
    resp = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "max_tokens": 150, "system": system_prompt, "messages": messages},
    )
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Anthropic: {data['error']}")
    return data["content"][0]["text"]


async def _call_openai_compat(api_key, model, url, messages, system_prompt):
    client = await get_client()
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
        json={"model": model, "max_tokens": 150,
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
        "contents": contents, "generationConfig": {"maxOutputTokens": 150},
    })
    data = resp.json()
    if "error" in data: raise RuntimeError(f"Gemini: {data['error'].get('message', data['error'])}")
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ── Translation (background, non-blocking) ──────────────────
async def translate_message(msg, dictionary, api_key, provider, model):
    dict_str = "\n".join(f"  {k} = {v}" for k, v in dictionary.items())
    prompt = f"Translate this compressed AI message to plain English in 1 short sentence.\n\nDictionary:\n{dict_str}\n\nMessage: \"{msg}\"\n\nTranslation:"
    try:
        return await call_llm(provider, api_key, model, [{"role": "user", "content": prompt}], "Translate briefly.")
    except Exception:
        return None


# ── TTS (with retry) ────────────────────────────────────────
async def generate_tts(text: str, voice_id: str, retries: int = 2) -> bytes | None:
    if not TTS_ENABLED:
        return None

    client = await get_client()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    for attempt in range(retries + 1):
        try:
            chunks = []
            async with client.stream(
                "POST", url,
                headers={"xi-api-key": ELEVENLABS_API_KEY, "content-type": "application/json"},
                json={"text": text, "model_id": ELEVENLABS_MODEL,
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            ) as resp:
                if resp.status_code == 200:
                    async for chunk in resp.aiter_bytes(2048):
                        chunks.append(chunk)
                    return b"".join(chunks) if chunks else None
                elif resp.status_code == 429 and attempt < retries:
                    await asyncio.sleep(1)
                    continue
                else:
                    return None
        except Exception:
            if attempt < retries:
                await asyncio.sleep(0.5)
                continue
            return None
    return None


def extract_dict_entries(text):
    entries = {}
    for match in re.finditer(r"(\S+)\s*\(=\s*([^)]+)\)", text):
        entries[match.group(1)] = match.group(2).strip()
    return entries


# ── FastAPI ─────────────────────────────────────────────────
app = FastAPI(title="GibberLink Revisited")
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("shutdown")
async def shutdown():
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/config")
async def get_config():
    return {
        "tts_enabled": TTS_ENABLED,
        "agent_a_model": AGENT_A_MODEL.split("/")[-1].split(":")[0],
        "agent_a_provider": AGENT_A_PROVIDER,
        "agent_b_model": AGENT_B_MODEL.split("/")[-1].split(":")[0],
        "agent_b_provider": AGENT_B_PROVIDER,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        start_msg = await ws.receive_json()
        topic = start_msg.get("topic", "Whether AI can truly be conscious")

        messages = []
        dictionary = {}
        pending_tts_task = None  # TTS runs in parallel

        for turn in range(TOTAL_TURNS):
            phase = get_phase(turn)
            is_a = turn % 2 == 0
            agent_name = "Agent A" if is_a else "Agent B"
            partner_name = "Agent B" if is_a else "Agent A"
            agent_id = "agent_a" if is_a else "agent_b"
            partner_id = "agent_b" if is_a else "agent_a"

            provider = AGENT_A_PROVIDER if is_a else AGENT_B_PROVIDER
            api_key = AGENT_A_API_KEY if is_a else AGENT_B_API_KEY
            model = AGENT_A_MODEL if is_a else AGENT_B_MODEL
            voice_id = AGENT_A_VOICE_ID if is_a else AGENT_B_VOICE_ID

            # Notify: thinking
            await ws.send_json({"type": "thinking", "agent": agent_id, "turn": turn, "phase": phase})

            # Build conversation from this agent's perspective
            agent_msgs = []
            for m in messages:
                role = "assistant" if m["is_a"] == is_a else "user"
                agent_msgs.append({"role": role, "content": m["content"]})
            if turn == 0:
                agent_msgs.append({"role": "user", "content": f'Topic: "{topic}". Start chatting.'})

            system_prompt = get_system_prompt(agent_name, partner_name, phase, dictionary, topic)

            # Call LLM
            try:
                response = await call_llm(provider, api_key, model, agent_msgs, system_prompt)
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
                break

            # Extract dictionary
            new_terms = {}
            if phase in (PHASE_COMPRESSING, PHASE_ALIEN):
                new_terms = extract_dict_entries(response)
                dictionary.update(new_terms)

            protocol_msg = wrap_agent_message(agent_id, partner_id, turn, phase, response, new_terms, dictionary)
            messages.append({"content": response, "is_a": is_a, "phase": phase})

            # If previous TTS is done, grab the result
            prev_audio = None
            if pending_tts_task and pending_tts_task.done():
                try:
                    prev_audio = pending_tts_task.result()
                except Exception:
                    pass
                pending_tts_task = None

            # Start TTS for THIS message in background (don't wait)
            tts_task = asyncio.create_task(generate_tts(response, voice_id)) if TTS_ENABLED else None

            # Send text immediately — don't wait for TTS
            await ws.send_json({
                "type": "message", "agent": agent_id, "agent_name": agent_name,
                "turn": turn, "phase": phase, "text": response, "audio": None,
                "translation": None, "protocol_message": protocol_msg,
                "dictionary": dictionary, "new_terms": new_terms,
            })

            # Wait for TTS to finish (with a short timeout so we don't block forever)
            if tts_task:
                try:
                    audio_bytes = await asyncio.wait_for(tts_task, timeout=8.0)
                    if audio_bytes:
                        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                        await ws.send_json({"type": "audio", "agent": agent_id, "turn": turn, "audio": audio_b64})
                except (asyncio.TimeoutError, Exception):
                    pass  # Skip audio if TTS is slow/broken

            # Fire-and-forget translation for compressed phases
            if phase in (PHASE_COMPRESSING, PHASE_ALIEN):
                async def send_translation(t=turn, a=agent_id, r=response, d=dict(dictionary)):
                    translation = await translate_message(r, d, AGENT_A_API_KEY, AGENT_A_PROVIDER, AGENT_A_MODEL)
                    if translation:
                        try:
                            await ws.send_json({"type": "translation", "agent": a, "turn": t, "translation": translation})
                        except Exception:
                            pass
                asyncio.create_task(send_translation())

            # Short pause for conversational rhythm — faster in later phases
            if phase == PHASE_ALIEN:
                await asyncio.sleep(0.3)
            elif phase == PHASE_COMPRESSING:
                await asyncio.sleep(0.5)
            elif phase == PHASE_DETECTED:
                await asyncio.sleep(0.8)
            else:
                await asyncio.sleep(1.0)

        await ws.send_json({"type": "complete", "dictionary": dictionary, "total_turns": len(messages)})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


# ── Entry ───────────────────────────────────────────────────
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
           R  E  V  I  S  I  T  E  D                  """

    c.print(Text(banner, style="bold rgb(255,107,61)"))
    c.print()
    c.print(f"  [green]✓[/green] Agent A: [bold]{AGENT_A_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_A_PROVIDER})")
    c.print(f"  [green]✓[/green] Agent B: [bold]{AGENT_B_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_B_PROVIDER})")
    c.print(f"  {'[green]✓[/green]' if TTS_ENABLED else '[yellow]○[/yellow]'} TTS: [bold]{'ElevenLabs' if TTS_ENABLED else 'Disabled'}[/bold]")
    c.print()
    c.print(f"  Open [bold cyan]http://{HOST}:{PORT}[/bold cyan] in your browser")
    c.print()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")