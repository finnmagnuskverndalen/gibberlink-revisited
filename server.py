"""
GibberLink Revisited — LLM Council Server

Four AI council members deliberate on a problem in real-time,
debating approaches and converging on a solution — with voice.
"""

import os
import sys
import subprocess

# ── Venv bootstrap ───────────────────────────────────────────
from bootstrap import reexec_in_venv
reexec_in_venv()

import json
import asyncio
import base64
import re
import time
import threading
from contextlib import asynccontextmanager

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from bootstrap import free_port
from llm import call_llm, LLMFatalError, LLMRetryableError, friendly_error
from tts import (
    clean_for_tts, generate_tts, start_tts_server, stop_tts_server,
    is_tts_ready, set_tts_ready,
)
from sanitize import sanitize_response, is_response_broken
from council import (
    PHASE_PROBLEM, PHASE_DEBATE, PHASE_CONVERGE, PHASE_SOLUTION,
    DEFAULT_AGENTS,
    build_personality, get_system_prompt, wrap_council_message,
    extract_proposals, proposals_are_similar,
    collect_votes, build_scoreboard,
)


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

# ── TTS config ──────────────────────────────────────────────
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
    if p in ("kokoro", "qwen3"):
        return p
    return "none"

EFFECTIVE_TTS = _resolve_tts_provider()
TTS_ENABLED   = EFFECTIVE_TTS != "none"


# ── Voice maps ──────────────────────────────────────────────

KOKORO_VOICE_MAP = {
    "agent_a": AGENT_A_KOKORO_VOICE, "agent_b": AGENT_B_KOKORO_VOICE,
    "agent_c": AGENT_C_KOKORO_VOICE, "agent_d": AGENT_D_KOKORO_VOICE,
    "chairman": CHAIRMAN_KOKORO_VOICE,
}
EL_VOICE_MAP = {
    "agent_a": AGENT_A_VOICE_ID, "agent_b": AGENT_B_VOICE_ID,
    "agent_c": AGENT_C_VOICE_ID, "agent_d": AGENT_D_VOICE_ID,
    "chairman": CHAIRMAN_VOICE_ID,
}
QWEN3_VOICE_MAP = {
    "agent_a": AGENT_A_QWEN3_VOICE, "agent_b": AGENT_B_QWEN3_VOICE,
    "agent_c": AGENT_C_QWEN3_VOICE, "agent_d": AGENT_D_QWEN3_VOICE,
    "chairman": CHAIRMAN_QWEN3_VOICE,
}


# ── HTTP client helpers ─────────────────────────────────────

_health_client: httpx.AsyncClient | None = None

async def _get_health_client() -> httpx.AsyncClient:
    global _health_client
    if _health_client is None or _health_client.is_closed:
        _health_client = httpx.AsyncClient(timeout=5, limits=httpx.Limits(max_connections=4))
    return _health_client

def _make_session_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=20))


# ── Lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    if EFFECTIVE_TTS in ("kokoro", "qwen3"):
        def _bg_start():
            ok = start_tts_server(EFFECTIVE_TTS, KOKORO_TTS_URL, QWEN3_TTS_URL)
            if ok:
                set_tts_ready()
            else:
                print("  [TTS] Running in text-only mode (TTS unavailable)")
        threading.Thread(target=_bg_start, daemon=True).start()
        print("  [TTS] Model loading in background — browser ready now, audio starts once model is loaded")
    elif TTS_ENABLED:
        set_tts_ready()
    yield
    stop_tts_server()
    global _health_client
    if _health_client and not _health_client.is_closed:
        await _health_client.aclose()


# ── Session helpers ─────────────────────────────────────────

def _get_voice_id(agent_cfg: dict) -> str:
    if EFFECTIVE_TTS == "kokoro":    return agent_cfg["voice_kokoro"]
    elif EFFECTIVE_TTS == "qwen3":   return agent_cfg["voice_qwen3"]
    else:                            return agent_cfg["voice_el"]

async def _generate_tts_for_text(text: str, voice_id: str, client: httpx.AsyncClient) -> bytes | None:
    if not TTS_ENABLED:
        return None
    tts_text = clean_for_tts(text)
    if not tts_text:
        return None
    return await generate_tts(
        tts_text, voice_id, client, effective_tts=EFFECTIVE_TTS,
        elevenlabs_api_key=ELEVENLABS_API_KEY, elevenlabs_model=ELEVENLABS_MODEL,
        kokoro_url=KOKORO_TTS_URL, qwen3_url=QWEN3_TTS_URL,
    )

def _audio_format() -> str:
    return "wav" if EFFECTIVE_TTS in ("qwen3", "kokoro") else "mp3"

def _get_phase(turn: int, total_turns: int) -> str:
    pct = turn / total_turns
    if pct < 0.15:  return PHASE_PROBLEM
    if pct < 0.55:  return PHASE_DEBATE
    if pct < 0.80:  return PHASE_CONVERGE
    return PHASE_SOLUTION

def _estimate_consensus(turn: int, total_turns: int, phase: str) -> int:
    pct = turn / total_turns
    if phase == PHASE_PROBLEM:   return int(pct * 100 * 0.15)
    elif phase == PHASE_DEBATE:  return 10 + int((pct - 0.15) * 100 * 0.8)
    elif phase == PHASE_CONVERGE: return 45 + int((pct - 0.55) * 100 * 1.5)
    else:                         return min(95 + int((pct - 0.80) * 100 * 0.25), 100)

_FALLBACK_PHRASES = {
    PHASE_PROBLEM:  "I think the core issue here is understanding the real constraints before we jump to solutions.",
    PHASE_DEBATE:   "I hear what the others are saying, but I think we need to consider the practical implications more carefully.",
    PHASE_CONVERGE: "We seem to be making progress. I can see elements of a workable solution forming from what's been said.",
    PHASE_SOLUTION: "I think we've landed on a reasonable approach. Let's move forward with what we've agreed on.",
}

def _build_roster_payload(agents, all_agents):
    return [{"id": a["id"], "name": a["name"], "color": a["color"], "role": a["role"],
             "mood": a.get("mood", ""), "model": a.get("model", "").split("/")[-1].split(":")[0]} for a in all_agents]

def _serialize_records(records):
    return [{"text": r["text"], "author": r["author"], "author_id": r.get("author_id", ""),
             "turn": r["turn"], "votes": r["votes"], "reasons": r.get("reasons", {})} for r in records]


# ── FastAPI app ─────────────────────────────────────────────

app = FastAPI(title="GibberLink Revisited — Council", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    return FileResponse("static/index.html")

@app.get("/api/config")
async def get_config():
    return {
        "tts_enabled": TTS_ENABLED, "tts_provider": EFFECTIVE_TTS,
        "agent_a_model": AGENT_A_MODEL.split("/")[-1].split(":")[0],
        "agent_a_provider": AGENT_A_PROVIDER,
        "agent_b_model": AGENT_B_MODEL.split("/")[-1].split(":")[0],
        "agent_b_provider": AGENT_B_PROVIDER,
        "default_agents": [{"id": a["id"], "name": a["name"], "color": a["color"],
                            "role": a["role"], "mood": a["mood"]} for a in DEFAULT_AGENTS],
    }

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


# ── WebSocket session ───────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _session_stopped = False
    _background_tasks: set[asyncio.Task] = set()
    _state_lock = asyncio.Lock()
    _session_client = _make_session_client()

    try:
        start_msg = await ws.receive_json()

        # Input validation
        raw_topic = start_msg.get("topic", "How to reduce meeting fatigue in remote teams")
        if not isinstance(raw_topic, str) or not raw_topic.strip():
            raw_topic = "How to reduce meeting fatigue in remote teams"
        problem = raw_topic.strip()[:500]
        try:
            total_turns = min(max(int(start_msg.get("turns", TOTAL_TURNS)), 6), 40)
        except (ValueError, TypeError):
            total_turns = TOTAL_TURNS

        # Build agent roster
        requested = start_msg.get("agents", None)
        all_providers = [AGENT_A_PROVIDER, AGENT_B_PROVIDER, AGENT_C_PROVIDER, AGENT_D_PROVIDER, CHAIRMAN_PROVIDER]
        all_keys      = [AGENT_A_API_KEY,  AGENT_B_API_KEY,  AGENT_C_API_KEY,  AGENT_D_API_KEY,  CHAIRMAN_API_KEY]
        all_models    = [AGENT_A_MODEL,    AGENT_B_MODEL,    AGENT_C_MODEL,    AGENT_D_MODEL,    CHAIRMAN_MODEL]

        agents = []
        for i in range(4):
            base = dict(DEFAULT_AGENTS[i])
            if requested and i < len(requested):
                req = requested[i]
                for field in ("name", "mood", "role", "personality"):
                    if req.get(field): base[field] = req[field]
            base["provider"] = all_providers[i]
            base["api_key"]  = all_keys[i]
            base["model"]    = all_models[i]
            aid = base["id"]
            base["voice_kokoro"] = KOKORO_VOICE_MAP.get(aid, "am_michael")
            base["voice_el"]     = EL_VOICE_MAP.get(aid, AGENT_A_VOICE_ID)
            base["voice_qwen3"]  = QWEN3_VOICE_MAP.get(aid, "Ryan")
            agents.append(base)

        chairman = dict(DEFAULT_AGENTS[4])
        chairman["provider"]     = CHAIRMAN_PROVIDER
        chairman["api_key"]      = CHAIRMAN_API_KEY
        chairman["model"]        = CHAIRMAN_MODEL
        chairman["voice_kokoro"] = KOKORO_VOICE_MAP.get("chairman", "am_echo")
        chairman["voice_el"]     = EL_VOICE_MAP.get("chairman", AGENT_A_VOICE_ID)
        chairman["voice_qwen3"]  = QWEN3_VOICE_MAP.get("chairman", "Axel")
        all_agents = agents + [chairman]

        # Session state
        messages = []
        proposals = []
        proposal_records = []

        # ── Build a single turn (runs as background task) ──
        async def build_turn(turn):
            phase     = _get_phase(turn, total_turns)
            agent_idx = turn % len(agents)
            agent     = agents[agent_idx]
            agent_id  = agent["id"]
            agent_name = agent["name"]
            others    = [a["name"] for a in agents if a["id"] != agent_id]
            personality = build_personality(agent)
            voice_id  = _get_voice_id(agent)

            # Sliding window for context
            MAX_HISTORY = 16
            src = messages if len(messages) <= MAX_HISTORY + 2 else messages[:2] + messages[-MAX_HISTORY:]
            agent_msgs = []
            for m in src:
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
            response = await call_llm(agent["provider"], agent["api_key"], agent["model"],
                                      agent_msgs, system_prompt, client=_session_client)

            # Sanitize
            response = sanitize_response(response, agent_name, others)
            if is_response_broken(response, agent_name):
                print(f"  [SANITIZE] Broken response from {agent_name} (turn {turn}), retrying...")
                strict = (f"You are {agent_name}. Respond to the council discussion with 1-2 sentences about: \"{problem}\". "
                          f"Speak ONLY as {agent_name}. Just give your opinion in plain English. Nothing else.")
                try:
                    response = await call_llm(agent["provider"], agent["api_key"], agent["model"],
                                              agent_msgs, strict, client=_session_client)
                    response = sanitize_response(response, agent_name, others)
                except Exception:
                    pass
                if is_response_broken(response, agent_name):
                    response = _FALLBACK_PHRASES.get(phase, "I need a moment to gather my thoughts on this.")

            # Proposals + voting
            new_proposals = extract_proposals(response)
            new_records = []
            for prop_text in new_proposals:
                async with _state_lock:
                    is_dup = any(proposals_are_similar(prop_text, r["text"]) for r in proposal_records)
                if is_dup:
                    continue
                votes, reasons = await collect_votes(agents, chairman, prop_text, agent_id, messages,
                                                     problem, call_llm, client=_session_client)
                new_records.append({"text": prop_text, "author": agent_name, "author_id": agent_id,
                                    "turn": turn, "votes": votes, "reasons": reasons})

            # Update state under lock
            async with _state_lock:
                proposals.extend(new_proposals)
                proposal_records.extend(new_records)
                spoken_text = re.sub(r'^\s*PROPOSAL:\s*', '', response, flags=re.MULTILINE).strip()
                protocol_msg = wrap_council_message(agent_id, turn, phase, spoken_text, new_proposals)
                messages.append({"agent_id": agent_id, "agent_idx": agent_idx, "content": spoken_text, "phase": phase})
                snap_proposals = proposals.copy()
                snap_records = _serialize_records(proposal_records)

            # TTS
            audio_b64 = None
            if TTS_ENABLED:
                audio_bytes = await _generate_tts_for_text(spoken_text, voice_id, _session_client)
                if audio_bytes:
                    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            return {
                "payload": {
                    "type": "message", "agent": agent_id, "agent_name": agent_name,
                    "agent_color": agent.get("color", "orange"), "agent_role": agent.get("role", ""),
                    "agent_model": agent.get("model", "").split("/")[-1].split(":")[0],
                    "turn": turn, "total_turns": total_turns, "phase": phase, "text": spoken_text,
                    "audio": audio_b64, "audio_format": _audio_format(),
                    "protocol_message": protocol_msg,
                    "proposals": snap_proposals, "proposal_records": snap_records,
                    "new_proposals": new_proposals, "new_proposal_records": new_records,
                    "consensus": _estimate_consensus(turn, total_turns, phase),
                    "num_agents": len(agents),
                    "agent_roster": _build_roster_payload(agents, all_agents),
                },
                "turn": turn,
            }

        # ── Pipelined turn loop ──
        pending_task = None
        for turn in range(total_turns):
            if _session_stopped:
                break
            if pending_task is None:
                phase = _get_phase(turn, total_turns)
                await ws.send_json({"type": "thinking", "agent": agents[turn % len(agents)]["id"], "turn": turn, "phase": phase})
                pending_task = asyncio.create_task(build_turn(turn))
                _background_tasks.add(pending_task)
                pending_task.add_done_callback(_background_tasks.discard)
            try:
                result = await pending_task
                pending_task = None
            except Exception as e:
                pending_task = None
                await ws.send_json({"type": "error", "message": friendly_error(e)})
                break
            if _session_stopped:
                break
            await ws.send_json(result["payload"])

            # Pre-start next turn
            if turn + 1 < total_turns and not _session_stopped:
                nxt = turn + 1
                await ws.send_json({"type": "thinking", "agent": agents[nxt % len(agents)]["id"], "turn": nxt, "phase": _get_phase(nxt, total_turns)})
                pending_task = asyncio.create_task(build_turn(nxt))
                _background_tasks.add(pending_task)
                pending_task.add_done_callback(_background_tasks.discard)

            try:
                ack = await asyncio.wait_for(ws.receive_json(), timeout=120.0)
                if isinstance(ack, dict) and ack.get("type") == "stop":
                    _session_stopped = True
                    break
            except asyncio.TimeoutError:
                pass

        # ── Chairman synthesis ──
        if not _session_stopped and messages:
            await ws.send_json({"type": "thinking", "agent": "chairman", "turn": total_turns, "phase": "synthesis"})
            transcript = "\n".join(
                f"{next((a['name'] for a in agents if a['id'] == m['agent_id']), m['agent_id'])} [{m['phase']}]: {m['content']}"
                for m in messages
            )
            prop_summary = ""
            if proposal_records:
                lines = []
                for i, rec in enumerate(proposal_records):
                    vc = {"agree": 0, "disagree": 0, "amend": 0}
                    for v in rec["votes"].values():
                        vc[v] = vc.get(v, 0) + 1
                    lines.append(f"  Proposal {i+1} by {rec['author']}: \"{rec['text']}\" — {vc['agree']} agree, {vc['disagree']} disagree, {vc['amend']} amend")
                prop_summary = "\nProposals and votes:\n" + "\n".join(lines)

            chairman_prompt = (
                f"You are Nexus, the Chairman of this council. You have observed the entire deliberation.\n\n"
                f"Problem: \"{problem}\"\n\nFull transcript:\n{transcript}\n{prop_summary}\n\n"
                f"Produce a clear, structured FINAL VERDICT. Include:\n"
                f"1. The problem as the council understood it (1 sentence)\n"
                f"2. Key points of agreement\n3. Key points of disagreement\n"
                f"4. The recommended solution (synthesize the best ideas)\n"
                f"5. Remaining caveats or open questions\n\n"
                f"Speak naturally as if delivering a verdict to the council. "
                f"Credit specific council members by name where appropriate. "
                f"Keep it to 6-10 sentences total. No markdown, no lists, no asterisks."
            )

            scored = build_scoreboard(proposal_records, all_agents)
            try:
                ch_resp = await call_llm(chairman["provider"], chairman["api_key"], chairman["model"],
                                         [{"role": "user", "content": chairman_prompt}],
                                         build_personality(chairman), max_tokens=500, client=_session_client)
                ch_audio = None
                if TTS_ENABLED:
                    ab = await _generate_tts_for_text(ch_resp, _get_voice_id(chairman), _session_client)
                    if ab: ch_audio = base64.b64encode(ab).decode("utf-8")
                await ws.send_json({
                    "type": "chairman", "agent": "chairman",
                    "agent_name": chairman["name"], "agent_color": chairman["color"],
                    "agent_role": chairman["role"],
                    "agent_model": chairman.get("model", "").split("/")[-1].split(":")[0],
                    "text": ch_resp, "audio": ch_audio, "audio_format": _audio_format(),
                    "proposal_records": _serialize_records(proposal_records), "scoreboard": scored,
                })
                try: await asyncio.wait_for(ws.receive_json(), timeout=120.0)
                except asyncio.TimeoutError: pass
            except Exception as e:
                print(f"  [Chairman] Synthesis failed: {e}")
                fallback = (f"The council deliberated over {len(messages)} rounds. "
                            f"{len(proposal_records)} proposal(s) were considered. "
                            f"The chairman was unable to produce a full synthesis due to a technical issue.")
                try:
                    await ws.send_json({
                        "type": "chairman", "agent": "chairman",
                        "agent_name": chairman["name"], "agent_color": chairman["color"],
                        "agent_role": chairman["role"],
                        "agent_model": chairman.get("model", "").split("/")[-1].split(":")[0],
                        "text": fallback, "audio": None, "audio_format": "mp3",
                        "proposal_records": _serialize_records(proposal_records), "scoreboard": scored,
                    })
                except Exception: pass

        await ws.send_json({
            "type": "complete", "proposals": proposals,
            "proposal_records": _serialize_records(proposal_records),
            "total_turns": len(messages), "consensus": 100,
        })

    except WebSocketDisconnect:
        _session_stopped = True
    except Exception as e:
        try: await ws.send_json({"type": "error", "message": friendly_error(e)})
        except Exception: pass
    finally:
        _session_stopped = True
        for task in list(_background_tasks):
            if not task.done(): task.cancel()
        if _background_tasks:
            await asyncio.gather(*_background_tasks, return_exceptions=True)
        _background_tasks.clear()
        if _session_client and not _session_client.is_closed:
            await _session_client.aclose()


# ── Main ────────────────────────────────────────────────────

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
    if EFFECTIVE_TTS == "elevenlabs":    tts_label = f"ElevenLabs  voices={AGENT_A_VOICE_ID[:8]}... / {AGENT_B_VOICE_ID[:8]}..."
    elif EFFECTIVE_TTS == "kokoro":      tts_label = f"Kokoro-ONNX (local)  voices={AGENT_A_KOKORO_VOICE} / {AGENT_B_KOKORO_VOICE}"
    elif EFFECTIVE_TTS == "qwen3":       tts_label = f"Qwen3-TTS (local)  voices={AGENT_A_QWEN3_VOICE} / {AGENT_B_QWEN3_VOICE}"
    else:                                tts_label = "Disabled (text-only)"
    c.print(f"  {'[green]✓[/green]' if TTS_ENABLED else '[yellow]○[/yellow]'} TTS: [bold]{tts_label}[/bold]")
    c.print()
    c.print(f"  Open [bold cyan]http://{HOST}:{PORT}[/bold cyan] in your browser")
    c.print()
    free_port(PORT)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", ws_ping_interval=30, ws_ping_timeout=10)
