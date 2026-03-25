<p align="center">
  <a href="https://github.com/finnmagnuskverndalen/gibberlink-revisited">
    <img src="logo.svg" alt="GibberLink Revisited" width="500">
  </a>
</p>

<p align="center">
  <strong>Four AI agents deliberate on any problem — debating, proposing solutions, voting, and reaching consensus — live, with voice.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/python-3.10+-green.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/FastAPI-WebSocket-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/LLM-any%20provider-ff6b3d.svg" alt="Any LLM">
</p>

---

Inspired by the viral [GibberLink](https://github.com/PennyroyalTea/gibberlink) demo — but instead of two agents switching to beeps, this puts **four distinct AI personalities** into a structured council that debates, proposes, votes, and converges on real solutions.

> **Demo:** _Screenshots/GIF coming soon — run it locally to see the council in action._

## How it works

A council session moves through four phases, scaled proportionally to however many rounds you choose (8–32):

```
Phase 1: ◇ DEFINE    — agents analyze the problem from their unique perspectives
Phase 2: ◆ DEBATE    — open argument, challenging ideas, proposing solutions
Phase 3: ◈ CONVERGE  — building on the strongest proposals, voting begins
Phase 4: ▣ SOLVE     — final positions, chairman delivers the verdict
```

Each agent has a **distinct role and personality**:

| Agent | Role | Style |
|-------|------|-------|
| **Voss** | Strategist | Direct, decisive, systems-thinker. Cuts through noise. |
| **Lyra** | Creative | Lateral thinker. Challenges assumptions, flips the frame. |
| **Kael** | Skeptic | Rigorous, evidence-driven. Pokes holes, demands proof. |
| **Iris** | Synthesizer | Finds common ground. Bridges disagreements. |
| **Nexus** | Chairman | Speaks only at the end. Delivers the final verdict. |

When an agent makes a formal **PROPOSAL**, every other agent (including the chairman) votes on it — agree, amend, or disagree — with a one-sentence reason. Proposals are scored with role-based weighting (the skeptic's judgment carries more weight, the chairman has veto power).

## Features

- **Any LLM provider** — OpenRouter (free models), Gemini, Anthropic, OpenAI, xAI Grok
- **Live model fetching** — setup wizard pulls currently available models from OpenRouter API
- **Custom model support** — enter any OpenRouter model ID, or mix providers across agents
- **Proposal & voting system** — agents formally propose solutions, others vote with reasons
- **Weighted scoring** — role-based vote weights, chairman veto power, ranked scoreboard
- **Chairman synthesis** — Nexus observes the full debate and delivers a structured final verdict
- **Text-to-Speech** — ElevenLabs, Kokoro (local, free), or Qwen3-TTS with distinct voices per agent
- **Adjustable rounds** — 8 to 32 via slider, phases scale proportionally
- **Real-time web UI** — live chat, proposal tracker with votes, consensus bar, JSON inspector
- **Transcript export** — download the full deliberation as structured JSON

## Architecture

```
┌─────────────┐     WebSocket/JSON      ┌──────────────┐
│   Browser    │◄──────────────────────►│  FastAPI      │
│  (index.html)│    messages + audio     │  server.py    │
└─────────────┘                         └──────┬───────┘
                                               │
              ┌────────────┬───────────┬───────┼───────┬────────────┐
              │            │           │       │       │            │
        ┌─────▼─────┐ ┌───▼───┐ ┌─────▼─────┐ │  ┌────▼────┐ ┌────▼────┐
        │   Voss    │ │ Lyra  │ │   Kael    │ │  │  Iris   │ │  Nexus  │
        │ strategist│ │creative│ │  skeptic  │ │  │ synth.  │ │chairman │
        │ (any LLM) │ │(any LLM)│ │ (any LLM) │ │  │(any LLM)│ │(any LLM)│
        └───────────┘ └───────┘ └───────────┘ │  └─────────┘ └─────────┘
                                              │
                                     ┌────────▼────────┐
                                     │   TTS Engine     │
                                     │ ElevenLabs /     │
                                     │ Kokoro / Qwen3   │
                                     └─────────────────┘
```

## Quick start

### 1. Clone & setup

```bash
git clone https://github.com/finnmagnuskverndalen/gibberlink-revisited.git
cd gibberlink-revisited
python3 setup.py
```

The setup wizard will:
- Create a virtual environment and install dependencies
- Fetch **live models** from OpenRouter (top free + cheapest paid)
- Walk you through API key and model configuration for all 5 agents
- Optionally configure TTS (ElevenLabs, Kokoro, or Qwen3-TTS)
- Create your `.env` file

### 2. Run

```bash
python3 server.py
```

### 3. Open

Navigate to **http://127.0.0.1:8765**, pick a topic, adjust the number of rounds, and hit Launch.

## Supported providers

| Provider | Setup | Free models? |
|----------|-------|-------------|
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Yes — Llama, Gemini, DeepSeek, Qwen, Mistral and more |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Yes — Gemini 2.0/2.5 Flash |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | $5 free credit |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | No |
| **xAI Grok** | [console.x.ai](https://console.x.ai/) | Free credits on signup |

> **Cheapest way to run:** Use OpenRouter for all five agents with free models. Total cost: $0.

The setup wizard fetches available models live from the OpenRouter API, so you always see what's currently working. You can also enter any custom model ID or mix providers across agents.

## TTS (optional)

Three TTS options, each with distinct voices per agent:

| Engine | Type | Quality | Setup |
|--------|------|---------|-------|
| **ElevenLabs** | Cloud API | Highest | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) — 10K chars/month free |
| **Kokoro** | Local (CPU) | Good | 82M params, ~300MB download, no GPU needed. Recommended for most setups. |
| **Qwen3-TTS** | Local (CPU/GPU) | Good | 600M params, ~1.3GB download, needs 3GB+ RAM |

If you skip TTS during setup, everything works in text-only mode. The setup wizard gives hardware-aware recommendations based on your system.

## The voting system

When an agent makes a proposal during the converge or solution phase, every other agent votes:

- **Agree** (+2 points × role weight)
- **Amend** (+1 point × role weight)
- **Disagree** (+0 points)

Role weights reflect each agent's expertise: the skeptic's judgment carries 1.5× weight, the synthesizer's agreement signals real convergence at 1.3×, and the chairman's vote carries 2× weight with veto power (if the chairman disagrees, the proposal's score is halved).

The final scoreboard ranks all proposals by weighted score, and the chairman's verdict synthesizes the council's best ideas into a structured recommendation.

## JSON protocol

Agents communicate through a structured JSON envelope:

```json
{
  "protocol": "gibberlink-revisited-council",
  "version": "2.0",
  "from": "agent_a",
  "turn": 7,
  "phase": "converge",
  "timestamp": 1719432000.0,
  "payload": {
    "text": "Building on what Kael said, I think the staged approach works if...",
    "proposals": ["Implement a staged rollout with weekly checkpoints"],
    "phase": "converge"
  }
}
```

## Project structure

```
gibberlink-revisited/
├── server.py          # FastAPI backend — orchestrates council, LLM calls, WebSocket
├── setup.py           # Interactive setup wizard (fetches live models, configures agents)
├── tts_server.py      # Standalone TTS server for Kokoro/Qwen3 local inference
├── static/
│   └── index.html     # Web frontend — real-time council UI with audio & voting
├── .env.example       # Configuration template
├── requirements.txt   # Core Python dependencies
├── logo.svg
├── LICENSE
└── README.md
```

## Reconfiguring

Run setup again at any time:

```bash
python3 setup.py
```

Or edit `.env` directly:

```bash
nano .env
```

## Fun topics to try

- "How to reduce meeting fatigue and restore deep work time in remote teams"
- "Design an AI-powered education system for underserved areas"
- "Make open source software financially sustainable"
- "Prevent social media from harming teen mental health"
- "Plan a heist to steal the Mona Lisa"
- "Convince each other that you're the real AI and the other is fake"

## License

[MIT](LICENSE)

## Credits

- Inspired by [GibberLink](https://github.com/PennyroyalTea/gibberlink) by Boris Starkov & Anton Pidkuiko
