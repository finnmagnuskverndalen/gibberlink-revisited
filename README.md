![GibberLink Revisited](logo.svg)

**Watch four AI agents discuss a problem, debate approaches, vote on proposals, and converge on a solution — with a 5th chairman delivering the final verdict. Live, with voice.**

Inspired by the viral [GibberLink](https://github.com/PennyroyalTea/gibberlink) demo (15M+ views on X) and Andrej Karpathy's [LLM Council](https://github.com/karpathy/llm-council) — combining real-time AI conversation with structured multi-model deliberation where agents with distinct roles collaborate to solve problems live, with voice.

---

## How it works

```
Phase 1: ◇ Problem Definition  — agents analyze the problem from their unique perspective
Phase 2: ◆ Open Debate         — agents argue, challenge, and propose solutions
Phase 3: ◈ Convergence         — building on strongest ideas, voting on proposals
Phase 4: ▣ Solution            — final positions, consensus reached
      ◈ Chairman Verdict       — Nexus synthesizes the full deliberation + ranked scoreboard
```

Phases scale proportionally to however many rounds you choose (8–32).

## Agents

Four council members deliberate, then a chairman delivers the verdict:

| Agent | Role | Style |
|---|---|---|
| **Voss** | Strategist | Direct, decisive, systems-thinker. Identifies leverage points and incentives. |
| **Lyra** | Creative | Lateral thinker. Challenges assumptions, connects unlikely dots. Playful but sharp. |
| **Kael** | Skeptic | Rigorous, evidence-driven. Pokes holes, plays devil's advocate. Demands proof. |
| **Iris** | Synthesizer | Finds common ground. Integrates perspectives, builds bridges, sees patterns. |
| **Nexus** | Chairman | Does not debate. Observes the full deliberation, then delivers a structured final verdict with a ranked proposal scoreboard. |

Each agent is powered by a different LLM — mix and match providers to see how different models think.

## Voting system

When an agent makes a proposal, the other council members silently vote on it:

- **Agree** — supports the proposal as stated
- **Amend** — supports the direction but wants changes
- **Disagree** — opposes the proposal

Votes appear as badges on each proposal in the side panel. At the end, the chairman's verdict includes a **ranked scoreboard** showing all proposals sorted by vote score (agree=2pts, amend=1pt, disagree=0pts).

## Features

- **Any LLM provider** — OpenRouter (free models), Gemini, Anthropic, OpenAI, xAI Grok
- **Live model fetching** — setup wizard pulls currently available models from OpenRouter API with live pricing
- **4-phase deliberation** — problem → debate → converge → solution
- **5 agents** — 4 debaters (strategist, creative, skeptic, synthesizer) + 1 chairman
- **Proposal voting** — agents silently vote agree/disagree/amend on each proposal
- **Chairman verdict** — Nexus delivers a structured final synthesis with ranked proposal scoreboard
- **Response sanitization** — detects and retries broken LLM outputs (hallucinated dialogue, classifier labels, gibberish)
- **Text-to-Speech** — ElevenLabs (cloud), Kokoro-ONNX (local, recommended), or Qwen3-TTS (local, heavy)
- **Hardware-aware TTS** — setup detects your GPU VRAM and recommends the right option
- **Pipelined generation** — next turn generates while current audio plays, no gap between responses
- **Live consensus bar** — watch agreement build as the council converges
- **Export transcript** — download full deliberation + proposals + votes + verdict as JSON
- **Real-time web UI** — live chat, proposal panel with votes, JSON protocol inspector

## Architecture

```
┌─────────────┐     WebSocket/JSON      ┌──────────────┐
│   Browser    │◄──────────────────────►│  FastAPI      │
│  (index.html)│    messages + audio     │  server.py    │
└─────────────┘                         └──────┬───────┘
                                               │
              ┌────────────────────────────────┼────────────────────────────────┐
              │                                │                                │
        ┌─────▼─────┐  ┌──────▼──────┐  ┌─────▼─────┐  ┌──────▼──────┐  ┌─────▼──────┐
        │   Voss    │  │    Lyra     │  │   Kael    │  │    Iris     │  │   Nexus    │
        │ strategist│  │  creative   │  │  skeptic  │  │ synthesizer │  │  chairman  │
        │ (any LLM) │  │ (any LLM)  │  │ (any LLM) │  │  (any LLM)  │  │ (any LLM)  │
        └───────────┘  └────────────┘  └───────────┘  └────────────┘  └────────────┘
                                               │
                                    ┌──────────▼───────────┐
                                    │  tts_server.py       │
                                    │  Kokoro / Qwen3      │
                                    │  (auto-started)      │
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
- Walk you through API key and model configuration for all five agents (4 debaters + chairman)
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

> **Cheapest way to run:** Use OpenRouter for all five agents with different free models. Total cost: $0.

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

## Response quality

Free models can produce garbage outputs — hallucinated multi-character dialogue, leaked classifier labels (`safe`/`unsafe`), or prompt token leaks. GibberLink Revisited handles this automatically:

- **Sanitization** — strips classifier labels, leaked tokens, HTML tags, and lines where an agent writes dialogue for other agents
- **Validation** — detects broken responses (gibberish, multi-speaker hallucinations, repeated junk)
- **Retry** — if a response is broken, retries once with a stricter prompt
- **Graceful fallback** — if still broken, uses a phase-appropriate fallback response to keep the conversation flowing

For best results, use higher-quality models (paid OpenRouter models, Gemini Flash, or Claude Haiku) for at least the chairman role.

## What makes this different from GibberLink?

| | GibberLink (original) | GibberLink Revisited |
|---|---|---|
| **Purpose** | AI-to-AI language evolution | Structured problem-solving deliberation |
| **Agents** | 2 generic | 5 named roles: strategist, creative, skeptic, synthesizer, chairman |
| **Phases** | 2 (human / protocol) | 4 + chairman verdict |
| **Output** | Compressed alien language | Proposals, votes, ranked scoreboard, final verdict |
| **Voting** | None | Agents vote agree/disagree/amend on each proposal |
| **Chairman** | None | 5th agent synthesizes full deliberation into structured verdict |
| **TTS** | ElevenLabs only | ElevenLabs, Kokoro-ONNX, or Qwen3-TTS |
| **Models** | ElevenLabs Conversational AI only | Any LLM — mix and match providers |
| **Quality** | No safeguards | Response sanitization, validation, retry, and fallback |
| **Export** | None | Full JSON transcript with proposals, votes, and verdict |
| **Setup** | Manual | Wizard — detects hardware, installs deps, writes .env |

## Project structure

```
gibberlink-revisited/
├── server.py          # FastAPI backend — orchestrates agents, voting, chairman, TTS, WebSocket
├── tts_server.py      # Local TTS server (Kokoro or Qwen3, auto-started)
├── setup.py           # Interactive setup wizard (5 agents + TTS)
├── static/
│   └── index.html     # Web frontend — chat UI with voting, scoreboard, consensus tracking
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
- Built with [OpenRouter](https://openrouter.ai), [ElevenLabs](https://elevenlabs.io), [Kokoro-ONNX](https://github.com/thewh1teagle/kokoro-onnx), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), and whatever LLMs you choose