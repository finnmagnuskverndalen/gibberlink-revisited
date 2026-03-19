![GibberLink Revisited](logo.svg)

**Watch four AI agents discuss a problem, debate approaches, and converge on a solution — live, with voice.**

Inspired by the viral [GibberLink](https://github.com/PennyroyalTea/gibberlink) demo (15M+ views on X) and Andrej Karpathy's [LLM Council](https://github.com/karpathy/llm-council) — combining real-time AI conversation with structured multi-model deliberation where agents with distinct roles collaborate to solve problems live, with voice.

---

## How it works

```
Phase 1: ◇ Problem Definition  — agents analyze the problem from their unique perspective
Phase 2: ◆ Open Debate         — agents argue, challenge, and propose mechanisms
Phase 3: ◈ Convergence         — building on strongest ideas, synthesizing agreement
Phase 4: ▣ Solution            — final positions, consensus reached
```

Phases scale proportionally to however many rounds you choose (8–32).

## Agents

Four council members with distinct cognitive roles:

| Agent | Role | Style |
|---|---|---|
| **Voss** | Strategist | Direct, decisive, systems-thinker. Identifies leverage points and incentives. |
| **Lyra** | Creative | Lateral thinker. Challenges assumptions, connects unlikely dots. Playful but sharp. |
| **Kael** | Skeptic | Rigorous, evidence-driven. Pokes holes, plays devil's advocate. Demands proof. |
| **Iris** | Synthesizer | Finds common ground. Integrates perspectives, builds bridges, sees patterns. |

Each agent is powered by a different LLM — mix and match providers to see how different models think.

## JSON protocol

```json
{
  "protocol": "gibberlink-revisited-council",
  "version": "2.0",
  "from": "agent_a",
  "turn": 8,
  "phase": "converge",
  "payload": {
    "text": "Building on what's emerged — the base layer addresses structure, the middle handles adoption friction, and the top creates visible momentum.",
    "proposals": ["Staged multi-layer approach with built-in feedback loops"],
    "phase": "converge"
  }
}
```

## Features

- **Any LLM provider** — OpenRouter (free models), Gemini, Anthropic, OpenAI, xAI Grok
- **Live model fetching** — setup wizard pulls currently available models from OpenRouter API with live pricing
- **4-phase deliberation** — problem → debate → converge → solution
- **4 distinct agent roles** — strategist, creative, skeptic, synthesizer
- **Text-to-Speech** — ElevenLabs (cloud), Kokoro-ONNX (local, recommended), or Qwen3-TTS (local, heavy)
- **Hardware-aware TTS** — setup detects your GPU VRAM and recommends the right option
- **Pipelined generation** — next turn generates while current audio plays, no gap between responses
- **Live consensus bar** — watch agreement build as the council converges
- **Proposal tracking** — proposals are extracted and displayed in the side panel
- **Export transcript** — download full deliberation + proposals as JSON
- **Real-time web UI** — live chat, proposal panel, JSON protocol inspector

## Architecture

```
┌─────────────┐     WebSocket/JSON      ┌──────────────┐
│   Browser    │◄──────────────────────►│  FastAPI      │
│  (index.html)│    messages + audio     │  server.py    │
└─────────────┘                         └──────┬───────┘
                                               │
                    ┌──────────────────────────┼──────────────────────────┐
                    │                          │                          │
              ┌─────▼─────┐            ┌──────▼──────┐      ┌────────────▼─────────┐
              │ Voss / Lyra │           │ Kael / Iris  │      │  tts_server.py       │
              │  (any LLM)  │           │  (any LLM)   │      │  Kokoro / Qwen3      │
              └────────────┘            └─────────────┘      │  (auto-started)      │
                                                              └──────────────────────┘
```

## Quick start

### 1. Clone & setup

```bash
git clone https://github.com/finnmagnuskverndalen/gibberlink-revisited.git
cd gibberlink-revisited
python3 setup.py
```

The setup wizard will:

- Create a `.venv` virtual environment automatically (handles Debian/Ubuntu PEP 668)
- Install core dependencies inside the venv
- Fetch **live models** from OpenRouter (top free + cheapest paid, with live pricing)
- Walk you through API key and model configuration for all four agents
- Detect your GPU VRAM and recommend the best TTS provider
- Install the right TTS dependencies and download model files automatically
- Create your `.env` file

### 2. Run

```bash
python3 server.py
```

The venv is detected automatically — no need to activate it. If TTS is configured, `tts_server.py` starts in the background automatically.

### 3. Open

Navigate to **http://127.0.0.1:8765**, describe a problem, adjust the number of rounds, and hit **[ launch agents ]**.

## Supported LLM providers

| Provider | Setup | Free models? |
|---|---|---|
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Yes — Llama, Gemini, DeepSeek, Qwen, Mistral and more |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Yes — Gemini 2.0/2.5 Flash |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | $5 free credit |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | No |
| **xAI Grok** | [console.x.ai](https://console.x.ai/) | Free credits on signup |

> **Cheapest way to run:** Use OpenRouter for all four agents with different free models. Total cost: $0.

## Text-to-Speech

The setup wizard detects your GPU VRAM and recommends the best option. `tts_server.py` starts automatically when you run `server.py` — no second terminal needed.

### Kokoro-ONNX (local — recommended)

82M parameter model, ~300MB download, runs entirely on CPU via ONNX runtime. Near real-time on any modern laptop. No GPU required. Model files download automatically on first run.

### ElevenLabs (cloud)

Highest quality, ~75ms latency. Free tier: 10K characters/month, no credit card needed.

Get a key at [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys).

### Qwen3-TTS (local — heavy)

600M parameter model, ~1.3GB download, runs on CPU. Richer voice variety than Kokoro but significantly slower.

### TTS hardware guide

| Hardware | Recommendation |
|---|---|
| No NVIDIA GPU | Kokoro — runs great on CPU |
| < 3GB VRAM (e.g. GTX 1050) | Kokoro — Qwen3 will crash |
| 3–6GB VRAM | Kokoro (faster) or Qwen3 (richer voices) |
| 6GB+ VRAM | Any — ElevenLabs for best quality |

## What makes this different from GibberLink?

| | GibberLink (original) | GibberLink Revisited |
|---|---|---|
| **Purpose** | AI-to-AI language evolution | Structured problem-solving deliberation |
| **Agents** | 2 generic | 4 named roles: strategist, creative, skeptic, synthesizer |
| **Phases** | 2 (human / protocol) | 4 (problem / debate / converge / solution) |
| **Output** | Compressed alien language | Concrete proposals and consensus |
| **TTS** | ElevenLabs only | ElevenLabs, Kokoro-ONNX, or Qwen3-TTS |
| **Models** | ElevenLabs Conversational AI only | Any LLM — mix and match providers |
| **Tracking** | Dictionary of compressed terms | Proposal panel with consensus progress |
| **Export** | None | Full JSON transcript with proposals |
| **Setup** | Manual | Wizard — detects hardware, installs deps, writes .env |

## Project structure

```
gibberlink-revisited/
├── server.py          # FastAPI backend — orchestrates agents, TTS, WebSocket
├── tts_server.py      # Local TTS server (Kokoro or Qwen3, auto-started)
├── setup.py           # Interactive setup wizard
├── static/
│   └── index.html     # Web frontend — chat UI with consensus tracking
├── .env.example       # Configuration template
├── requirements.txt   # Core dependencies (TTS deps installed by setup.py)
├── logo.svg
└── README.md
```

## Reconfiguring

```bash
python3 setup.py
```

Or edit `.env` directly:

```bash
nano .env
```

## Problems to try

- "How to reduce meeting fatigue and restore deep work time in remote-first teams"
- "Design an AI-powered education system for underserved areas"
- "Solve urban food waste at scale"
- "Make open source financially sustainable"
- "Prevent social media from harming teen mental health"
- "Decarbonize shipping and logistics"
- "Design a fair system for allocating scarce medical resources"
- "How to make cities walkable without displacing existing residents"

## License

MIT

## Credits

- Inspired by [GibberLink](https://github.com/PennyroyalTea/gibberlink) by Boris Starkov & Anton Pidkuiko
- Inspired by [LLM Council](https://github.com/karpathy/llm-council) by Andrej Karpathy — the idea of grouping multiple LLMs into a council that reviews, debates, and synthesizes responses
