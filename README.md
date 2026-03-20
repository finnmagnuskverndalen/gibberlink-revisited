![GibberLink Revisited](logo.svg)

**Five AI agents. One problem. A structured deliberation with role-weighted voting, chairman veto power, and a final verdict — live, with voice.**

Inspired by [GibberLink](https://github.com/PennyroyalTea/gibberlink) (15M+ views on X) and Andrej Karpathy's [LLM Council](https://github.com/karpathy/llm-council). Each agent runs on a different LLM. They debate, propose solutions, vote with reasons, and a chairman delivers the final verdict with a ranked scoreboard.

---

## How it works

```
Phase 1  ◇  DEFINE     — four agents analyze the problem from distinct perspectives
Phase 2  ◆  DEBATE     — argue approaches, challenge ideas, propose concrete solutions
Phase 3  ◈  CONVERGE   — build on strongest ideas, refine proposals, cast votes
Phase 4  ▣  SOLVE      — final positions, consensus reached
      ◈  VERDICT       — chairman synthesizes the deliberation + ranked scoreboard
```

Phases scale proportionally to the number of rounds you choose (8–32). Each proposal triggers a parallel vote round across all agents — including the chairman.

## The council

| Agent | Role | Cognitive style | Vote weight |
|---|---|---|---|
| **Voss** | Strategist | Systems-thinker. Identifies leverage points, incentives, and second-order effects. | 1.2× |
| **Lyra** | Creative | Lateral thinker. Challenges assumptions, connects unlikely dots. Playful but sharp. | 1.0× |
| **Kael** | Skeptic | Evidence-driven. Pokes holes, demands proof, plays devil's advocate. | 1.5× |
| **Iris** | Synthesizer | Finds common ground. Integrates perspectives, builds bridges, sees patterns. | 1.3× |
| **Nexus** | Chairman | Observes the full deliberation. Votes on proposals with 2.0× weight and **veto power**. Delivers the final verdict. | 2.0× |

Each agent is powered by a different LLM — mix and match providers to see how different models reason about the same problem.

## Voting system

When any agent makes a proposal, a parallel vote round is triggered:

| Vote | Meaning | Points |
|---|---|---|
| **Agree** | Supports the proposal as stated | 2 × role weight |
| **Amend** | Supports the direction but wants changes | 1 × role weight |
| **Disagree** | Opposes the proposal | 0 |

Every voter provides a **one-sentence reason** explaining their vote, shown in the sidebar and scoreboard.

The system includes several mechanisms for quality:

- **Proposer excluded** — the author doesn't vote on their own proposal (shown as "author" badge)
- **Chairman votes on everything** — Nexus participates in every vote with 2.0× weight
- **Chairman veto** — if Nexus disagrees, the proposal's score is halved and marked with a veto indicator
- **Role-weighted scoring** — Kael's skeptical disagree carries 1.5× weight; Iris's synthesizer agree carries 1.3×
- **Parallel execution** — all votes run simultaneously via `asyncio.gather`, not sequentially
- **Conversation context** — voters see the last 4 messages for informed decisions
- **Deduplication** — proposals with >70% word overlap are automatically skipped

## Features

- **6 LLM providers** — OpenRouter, OpenCode Zen, Gemini, Anthropic, OpenAI, xAI Grok
- **Smart model selection** — setup wizard fetches live models, filters by chat capability and context length, with hardcoded fallbacks
- **Shared API keys** — enter each key once, automatically reused across all agents on the same provider
- **4-phase deliberation** — problem → debate → converge → solution, then chairman verdict
- **5 distinct agents** — 4 debaters with cognitive specializations + 1 chairman with veto power
- **Role-weighted voting** — parallel vote collection with reasons, deduplication, and chairman veto
- **Ranked scoreboard** — proposals sorted by weighted score, shown in the chairman's verdict card
- **Model attribution** — each message shows which LLM powered it (e.g. "deepseek-chat-v3-0324")
- **Response sanitization** — detects and retries broken outputs (hallucinated dialogue, classifier leaks, gibberish)
- **Text-to-Speech** — ElevenLabs (cloud), Kokoro-ONNX (local, recommended), or Qwen3-TTS (local)
- **Hardware-aware TTS** — setup detects GPU VRAM and recommends the right option
- **Pipelined generation** — next turn's LLM call runs while current audio plays
- **Live consensus bar** — watch agreement build as the council converges
- **Export** — download full transcript with proposals, votes, reasons, and verdict as JSON

## Architecture

```
┌─────────────┐     WebSocket/JSON      ┌──────────────┐
│   Browser    │◄──────────────────────►│  FastAPI      │
│  (index.html)│   messages + audio      │  server.py    │
└─────────────┘                         └──────┬───────┘
                                               │
         ┌─────────────────────────────────────┼─────────────────────────────────────┐
         │                                     │                                     │
   ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐
   │   Voss    │  │   Lyra    │  │   Kael    │  │   Iris    │  │   Nexus   │
   │ strategist│  │ creative  │  │  skeptic  │  │synthesizer│  │ chairman  │
   │  1.2× wt  │  │  1.0× wt  │  │  1.5× wt  │  │  1.3× wt  │  │ 2.0× veto │
   │ (any LLM) │  │ (any LLM) │  │ (any LLM) │  │ (any LLM) │  │ (any LLM) │
   └───────────┘  └───────────┘  └───────────┘  └───────────┘  └───────────┘
                                       │
                            ┌──────────▼───────────┐
                            │    tts_server.py      │
                            │   Kokoro / Qwen3      │
                            │   (auto-started)      │
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

- Create a `.venv` virtual environment (handles Debian/Ubuntu PEP 668 automatically)
- Install core dependencies
- Fetch live models from OpenRouter (free + cheapest paid, filtered for chat capability)
- Walk you through provider and model selection for all 5 agents
- Share API keys automatically — enter each key once
- Detect GPU VRAM and recommend the best TTS option
- Install TTS dependencies and download model files
- Write your `.env`

### 2. Run

```bash
python3 server.py
```

The venv activates automatically. TTS server starts in the background if configured.

### 3. Open

**http://127.0.0.1:8765** — describe a problem, set the rounds, hit **[ launch agents ]**.

## Supported providers

| Provider | Setup | Free models? |
|---|---|---|
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Yes — Llama, Gemini, DeepSeek, Qwen, Mistral |
| **OpenCode Zen** | [opencode.ai/auth](https://opencode.ai/auth) | Some (Big Pickle, MiniMax, Nemotron) |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Yes — Gemini 2.0/2.5 Flash |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | $5 free credit |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | No |
| **xAI Grok** | [console.x.ai](https://console.x.ai/) | Free credits on signup |

> **$0 setup:** Use OpenRouter with free models for all 5 agents. Mix providers for better results — e.g. free models for debaters, a paid model for the chairman.

## Text-to-Speech

| Option | Latency | Size | Hardware |
|---|---|---|---|
| **Kokoro-ONNX** (recommended) | Near real-time | ~300MB | Any CPU |
| **ElevenLabs** (cloud) | ~75ms | — | Internet |
| **Qwen3-TTS** (local) | 5-15s/sentence | ~1.3GB | 3GB+ RAM |

The setup wizard detects your GPU and recommends the best option. `tts_server.py` auto-starts with `server.py`.

## Response quality

Free models sometimes produce garbage — hallucinated multi-character dialogue, leaked safety labels, or prompt token leaks. The server handles this automatically:

- **Sanitization** — strips classifier labels, leaked tokens, HTML tags, and cross-agent dialogue
- **Validation** — detects gibberish, multi-speaker hallucinations, and repetitive junk
- **Retry** — broken responses get one retry with a stricter prompt
- **Fallback** — if still broken, a phase-appropriate generic response keeps the conversation flowing

For best results, use a higher-quality model for at least the chairman (Nexus). His verdict is the most visible output.

## Project structure

```
gibberlink-revisited/
├── server.py          # FastAPI — agents, voting, chairman, TTS, WebSocket
├── tts_server.py      # Local TTS server (Kokoro / Qwen3, auto-started)
├── setup.py           # Interactive setup wizard (5 agents, shared keys, TTS)
├── static/
│   └── index.html     # Frontend — chat, voting badges, scoreboard, consensus bar
├── .env.example
├── requirements.txt
├── logo.svg
└── README.md
```

## Reconfiguring

```bash
python3 setup.py       # re-run the wizard
nano .env              # or edit directly
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
- Inspired by [LLM Council](https://github.com/karpathy/llm-council) by Andrej Karpathy
- Built with [OpenRouter](https://openrouter.ai), [OpenCode Zen](https://opencode.ai/zen), [ElevenLabs](https://elevenlabs.io), [Kokoro-ONNX](https://github.com/thewh1teagle/kokoro-onnx), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)