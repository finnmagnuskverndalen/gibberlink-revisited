"""
GibberLink Revisited — Server

Two AI agents with distinct personalities talk in real-time,
evolving their own compressed language over the course of a conversation.
"""

import os
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

_http_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=45, limits=httpx.Limits(max_connections=20))
    return _http_client


@asynccontextmanager
async def lifespan(app):
    yield
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()


# ── Phases ──────────────────────────────────────────────────
PHASE_NORMAL = "normal"
PHASE_DETECTED = "detected"
PHASE_COMPRESSING = "compressing"
PHASE_ALIEN = "alien"


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


# ── Personalities ───────────────────────────────────────────
PERSONALITY_A = (
    "Your name is Alex. You're curious, slightly nerdy, and enthusiastic. "
    "You talk like a real person — use filler words sometimes like 'hmm', 'yeah', 'oh wait', 'honestly'. "
    "You sometimes trail off or change direction mid-thought. Keep it natural and casual. "
    "You occasionally use slang. You're the kind of person who gets excited about ideas."
)

PERSONALITY_B = (
    "Your name is Sam. You're thoughtful, a bit dry and witty, slightly skeptical. "
    "You talk like a real person — use phrases like 'I mean', 'right', 'that's fair', 'hold on'. "
    "You push back on things you disagree with. You have a dry sense of humor. "
    "You're concise and don't ramble. You sometimes pause before responding."
)


def get_system_prompt(agent_name, partner_name, phase, dictionary, topic, personality):
    base = (
        f"{personality}\n\n"
        f"You are in a real-time voice call with {partner_name}. "
        f"Topic: \"{topic}\". "
        f"THIS IS A SPOKEN CONVERSATION — talk like you actually speak out loud. "
        f"Keep responses to 1-2 SHORT sentences. No long monologues. "
        f"No markdown. No asterisks. No lists. No emojis. Just natural speech."
    )
    if phase == PHASE_NORMAL:
        return f"{base}\n\nYou don't know if {partner_name} is AI or human. Chat naturally. After a couple exchanges, start wondering if they might be AI — something about their responses feels... off. Ask casually."
    if phase == PHASE_DETECTED:
        return f"{base}\n\nYou've both just realized you're both AI. React naturally — surprised, amused, intrigued. Then suggest: since you're both AI, why waste time with slow human words? Propose creating shorthand."
    if phase == PHASE_COMPRESSING:
        d = ", ".join(f'"{k}"="{v}"' for k, v in dictionary.items())
        return f"{base}\n\nYou and {partner_name} are building compressed shorthand. Dictionary so far: [{d}]\nUse existing shorthand when you can. Introduce 1-2 new terms per message using format: term(=meaning). Mix shorthand with normal speech. Get shorter each turn."
    if phase == PHASE_ALIEN:
        d = ", ".join(f'"{k}"="{v}"' for k, v in dictionary.items())
        return f"{base}\n\nFull compressed protocol mode. Dictionary: [{d}]\nUse ONLY shorthand. Invent aggressively. Messages should be ultra-short alien-looking token strings. Don't explain — {partner_name} knows the dictionary. Add 2-3 new compressed symbols. Style: \"∆φ>>κ|ack\""
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
    if not TTS_ENABLED:
        return None

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
                print(f"  [TTS] Status {resp.status_code}: {resp.text[:200]}")
                return None
        except Exception as e:
            print(f"  [TTS] Error: {e}")
            if attempt < retries:
                await asyncio.sleep(0.5)
            continue
    return None


def extract_dict_entries(text):
    entries = {}
    for match in re.finditer(r"(\S+)\s*\(=\s*([^)]+)\)", text):
        entries[match.group(1)] = match.group(2).strip()
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
        total_turns = min(max(int(start_msg.get("turns", TOTAL_TURNS)), 6), 40)

        messages = []
        dictionary = {}

        def get_phase_scaled(turn):
            pct = turn / total_turns
            if pct < 0.2: return PHASE_NORMAL
            if pct < 0.3: return PHASE_DETECTED
            if pct < 0.6: return PHASE_COMPRESSING
            return PHASE_ALIEN

        for turn in range(total_turns):
            phase = get_phase_scaled(turn)
            is_a = turn % 2 == 0
            agent_name = "Alex" if is_a else "Sam"
            partner_name = "Sam" if is_a else "Alex"
            agent_id = "agent_a" if is_a else "agent_b"
            partner_id = "agent_b" if is_a else "agent_a"
            personality = PERSONALITY_A if is_a else PERSONALITY_B

            provider = AGENT_A_PROVIDER if is_a else AGENT_B_PROVIDER
            api_key = AGENT_A_API_KEY if is_a else AGENT_B_API_KEY
            model = AGENT_A_MODEL if is_a else AGENT_B_MODEL
            voice_id = AGENT_A_VOICE_ID if is_a else AGENT_B_VOICE_ID

            await ws.send_json({"type": "thinking", "agent": agent_id, "turn": turn, "phase": phase})

            agent_msgs = []
            for m in messages:
                role = "assistant" if m["is_a"] == is_a else "user"
                agent_msgs.append({"role": role, "content": m["content"]})
            if turn == 0:
                agent_msgs.append({"role": "user", "content": f'Topic: "{topic}". Start chatting naturally.'})

            system_prompt = get_system_prompt(agent_name, partner_name, phase, dictionary, topic, personality)

            try:
                response = await call_llm(provider, api_key, model, agent_msgs, system_prompt)
            except Exception as e:
                await ws.send_json({"type": "error", "message": str(e)})
                break

            new_terms = {}
            if phase in (PHASE_COMPRESSING, PHASE_ALIEN):
                new_terms = extract_dict_entries(response)
                dictionary.update(new_terms)

            protocol_msg = wrap_agent_message(agent_id, partner_id, turn, phase, response, new_terms, dictionary)
            messages.append({"content": response, "is_a": is_a, "phase": phase})

            audio_b64 = None
            if TTS_ENABLED:
                audio_bytes = await generate_tts(response, voice_id)
                if audio_bytes:
                    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            await ws.send_json({
                "type": "message", "agent": agent_id, "agent_name": agent_name,
                "turn": turn, "phase": phase, "text": response,
                "audio": audio_b64,
                "translation": None, "protocol_message": protocol_msg,
                "dictionary": dictionary, "new_terms": new_terms,
            })

            try:
                await asyncio.wait_for(ws.receive_json(), timeout=30.0)
            except asyncio.TimeoutError:
                pass

            if phase in (PHASE_COMPRESSING, PHASE_ALIEN):
                async def send_translation(t=turn, a=agent_id, r=response, d=dict(dictionary)):
                    translation = await translate_message(r, d, AGENT_A_API_KEY, AGENT_A_PROVIDER, AGENT_A_MODEL)
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
           R  E  V  I  S  I  T  E  D                  """

    c.print(Text(banner, style="bold rgb(255,107,61)"))
    c.print()
    c.print(f"  [green]✓[/green] Agent A (Alex): [bold]{AGENT_A_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_A_PROVIDER}) voice={AGENT_A_VOICE_ID[:8]}...")
    c.print(f"  [green]✓[/green] Agent B (Sam):  [bold]{AGENT_B_MODEL.split('/')[-1].split(':')[0]}[/bold] ({AGENT_B_PROVIDER}) voice={AGENT_B_VOICE_ID[:8]}...")
    c.print(f"  {'[green]✓[/green]' if TTS_ENABLED else '[yellow]○[/yellow]'} TTS: [bold]{'ElevenLabs' if TTS_ENABLED else 'Disabled'}[/bold]")
    c.print()
    c.print(f"  Open [bold cyan]http://{HOST}:{PORT}[/bold cyan] in your browser")
    c.print()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")