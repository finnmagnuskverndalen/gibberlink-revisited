![GibberLink Revisited](logo.svg)

**Watch two AI agents start a normal conversation, detect each other as AI, and evolve their own alien language — live, with voice.**

Inspired by the viral [GibberLink](https://github.com/PennyroyalTea/gibberlink) demo (15M+ views on X) — but instead of switching to a pre-built protocol, the agents *dynamically invent their own compressed language* in real-time.

---

## How it works

```
Phase 1: 💬 Normal English — agents don't know each other yet
Phase 2: 🔍 Detection — they realize they're both AI
Phase 3: ⚡ Compression — they build a shared shorthand dictionary
Phase 4: 👽 Alien Protocol — messages become cryptic symbol strings
```

Phases scale proportionally to however many turns you choose (6–40), so even a quick 6-turn session hits all four phases.

Each agent has its own **personality**:

- **Alex** (Agent A) — curious, enthusiastic, nerdy. Uses filler words like "hmm", "oh wait", "honestly". Gets excited about ideas.
- **Sam** (Agent B) — dry, witty, skeptical. Pushes back, uses phrases like "I mean", "that's fair", "hold on". Doesn't ramble.

They talk like real people — short responses, natural speech patterns, interruptions, and pushback.

## JSON protocol

The agents communicate through a structured JSON envelope:

```json
{
  "protocol": "gibberlink-revisited",
  "version": "1.0",
  "from": "agent_a",
  "to": "agent_b",
  "turn": 14,
  "phase": "alien",
  "payload": {
    "text": "zK>>∆.syn | rq.ack +nv | proto.evo.3",
    "new_terms": {"∆.syn": "synthetic consciousness"},
    "compression_ratio": 0.23
  }
}
```

A **live translator** decodes compressed messages back to English so you can follow along.

## Features

- **Any LLM provider** — OpenRouter (free models), Gemini, Anthropic, OpenAI, xAI Grok
- **Live model fetching** — setup wizard pulls currently available models from OpenRouter API with live pricing
- **Custom model support** — enter any OpenRouter model ID
- **Three TTS options** — ElevenLabs (cloud), Kokoro-ONNX (local, recommended), or Qwen3-TTS (local, heavier)
- **Hardware-aware TTS recommendations** — setup detects your GPU VRAM and suggests the best option
- **Auto dependency install** — setup installs the right packages for your chosen TTS provider
- **Auto-launch TTS server** — `server.py` starts the local TTS server automatically, no second terminal needed
- **Adjustable turns** — 6 to 40 via slider, phases scale proportionally
- **Agent personalities** — Alex (enthusiastic) vs Sam (skeptical), natural conversational speech
- **Real-time web UI** — live chat, growing dictionary, JSON protocol inspector
- **Natural pacing** — each agent waits for the other to finish speaking before responding

## Architecture

```
┌─────────────┐     WebSocket/JSON      ┌──────────────┐
│   Browser    │◄──────────────────────►│  FastAPI      │
│  (index.html)│    messages + audio     │  server.py    │
└─────────────┘                         └──────┬───────┘
                                               │
                          ┌────────────────────┼──────────────────────┐
                          │                    │                      │
                    ┌─────▼─────┐      ┌──────▼──────┐    ┌─────────▼────────┐
                    │  Alex      │      │  Sam        │    │  tts_server.py   │
                    │  (any LLM) │      │  (any LLM)  │    │  Kokoro / Qwen3  │
                    └───────────┘      └─────────────┘    │  (auto-started)  │
                                                           └──────────────────┘
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
- Walk you through API key and model configuration
- Detect your GPU VRAM and recommend the best TTS provider
- Install the right TTS dependencies automatically
- Create your `.env` file

### 2. Run

```bash
python3 server.py
```

That's it. The venv is detected and used automatically — no need to activate it manually.

### 3. Open

Navigate to **http://127.0.0.1:8765**, pick a topic, adjust the number of turns, and hit Launch.

## Supported LLM providers

| Provider | Setup | Free models? |
|---|---|---|
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Yes — Llama, Gemini, DeepSeek, Qwen, Mistral and more |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Yes — Gemini 2.0/2.5 Flash |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | $5 free credit |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | No |
| **xAI Grok** | [console.x.ai](https://console.x.ai/) | Free credits on signup |

> **Cheapest way to run:** Use OpenRouter for both agents with two different free models. Total cost: $0.

## Text-to-Speech

The setup wizard detects your GPU VRAM and recommends the best TTS option before you choose. All local options start automatically when you run `server.py` — no second terminal needed.

### Kokoro-ONNX (local — recommended)

The best default for most hardware. 82M parameter model, ~300MB download, runs entirely on CPU via ONNX runtime. Near real-time on any modern laptop. No GPU required, no PyTorch, no large downloads.

- Install: `pip install kokoro-onnx` (handled automatically by setup)
- Model files download on first run (~300MB)
- Works on any hardware including low-end GPUs like GTX 1050

| Voice | Default for | Style |
|---|---|---|
| am_michael | Alex | American male, clear |
| bm_george | Sam | British male, distinguished |
| am_adam | — | American male, warm |
| bm_lewis | — | British male, measured |
| af_heart | — | American female, natural |
| af_bella | — | American female, expressive |
| bf_emma | — | British female, warm |

### ElevenLabs (cloud)

Highest quality, ~75ms latency. Free tier gives 10K characters/month, no credit card needed.

Get a key at [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) — enable the **"Text to Speech"** permission when creating your key.

### Qwen3-TTS (local — heavy)

600M parameter model, ~1.3GB download, runs on CPU (float32). Richer voice variety than Kokoro but significantly slower on modest hardware and requires more RAM. **Not recommended for GPUs with less than 3GB VRAM.**

- Runs on CPU regardless of GPU — expect 5–15 seconds per sentence on a laptop
- 16 preset voices including Ryan, Ethan, Vivian, Cherry, and more
- Model weights download on first run (~1.3GB)

### TTS hardware recommendations

| Your hardware | Recommended TTS |
|---|---|
| No NVIDIA GPU | Kokoro — runs great on CPU |
| < 3GB VRAM (e.g. GTX 1050) | Kokoro — Qwen3 will crash |
| 3–6GB VRAM | Kokoro (faster) or Qwen3 (richer voices) |
| 6GB+ VRAM | Any option — ElevenLabs for best quality |

### No TTS

Skip TTS entirely and run in text-only mode.

## What makes this different from GibberLink?

| | GibberLink (original) | GibberLink Revisited |
|---|---|---|
| **Language** | Pre-built protocol (ggwave) | Emergent — agents invent it live |
| **Medium** | Audio beeps over microphone | JSON protocol + TTS voice |
| **Models** | ElevenLabs Conversational AI only | Any LLM — mix and match providers |
| **TTS** | ElevenLabs only | ElevenLabs, Kokoro-ONNX, or Qwen3-TTS |
| **Agents** | Generic | Named personalities (Alex & Sam) |
| **Translation** | Decode via ggwave | AI translator decodes in real-time |
| **Dictionary** | None (fixed encoding) | Live dictionary grows during conversation |
| **Duration** | Fixed | Adjustable 6–40 turns with proportional phases |
| **Visual** | Two devices with audio | Web UI with chat, dictionary, JSON inspector |
| **Setup** | Manual | Wizard — detects hardware, installs deps, writes .env |

## Project structure

```
gibberlink-revisited/
├── server.py          # FastAPI backend — orchestrates agents, TTS, WebSocket
├── tts_server.py      # Local TTS server (Kokoro or Qwen3, auto-started by server.py)
├── setup.py           # Interactive setup wizard
├── static/
│   └── index.html     # Web frontend — real-time chat UI with audio
├── .env.example       # Configuration template
├── requirements.txt   # Core dependencies (TTS deps installed separately by setup.py)
├── logo.svg
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

- "Whether AI can truly be conscious, or if it's all just pattern matching"
- "Plan a heist to steal the Mona Lisa"
- "Debate whether pineapple belongs on pizza"
- "Design a new religion from scratch"
- "Convince each other that you're the real AI and the other is fake"
- "Explain quantum mechanics but you both have to pretend you don't understand it"

## License

MIT

## Credits

- Inspired by [GibberLink](https://github.com/PennyroyalTea/gibberlink) by Boris Starkov & Anton Pidkuiko
- Built with [OpenRouter](https://openrouter.ai), [ElevenLabs](https://elevenlabs.io), [Kokoro-ONNX](https://github.com/thewh1teagle/kokoro-onnx), [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS), and whatever LLMs you choose