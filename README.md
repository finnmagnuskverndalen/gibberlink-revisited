<p align="center">
  <img src="logo.svg" alt="GibberLink Revisited" width="680">
</p>

<p align="center">
  <strong>Watch two AI agents start a normal conversation, detect each other as AI, and evolve their own alien language — live, with voice.</strong>
</p>

<p align="center">
  Inspired by the viral <a href="https://github.com/PennyroyalTea/gibberlink">GibberLink</a> demo (15M+ views on X) — but instead of switching to a pre-built protocol, the agents <em>dynamically invent their own compressed language</em> in real-time.
</p>

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
- **Live model fetching** — setup wizard pulls currently available models from OpenRouter API
- **Custom model support** — enter any OpenRouter model ID
- **Text-to-Speech** — ElevenLabs with distinct voices per agent, sequential playback
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
                          ┌────────────────────┼────────────────────┐
                          │                    │                    │
                    ┌─────▼─────┐      ┌──────▼──────┐    ┌───────▼───────┐
                    │  Alex      │      │  Sam        │    │  ElevenLabs   │
                    │  (any LLM) │      │  (any LLM)  │    │  TTS voices   │
                    └───────────┘      └─────────────┘    └───────────────┘
```

## Quick start

### 1. Clone & setup
```bash
git clone https://github.com/finnmagnuskverndalen/gibberlink-revisited.git
cd gibberlink-revisited
python3 setup.py
```

The setup wizard will:
- Install Python dependencies
- Fetch **live models** from OpenRouter (top 10 free + top 10 cheapest)
- Walk you through API key and model configuration
- Optionally configure ElevenLabs TTS voices
- Create your `.env` file

### 2. Run
```bash
python3 server.py
```

### 3. Open

Navigate to **http://127.0.0.1:8765**, pick a topic, adjust the number of turns, and hit Launch.

## Supported providers

| Provider | Setup | Free models? |
|----------|-------|-------------|
| **OpenRouter** | [openrouter.ai/keys](https://openrouter.ai/keys) | Yes — Llama, Gemini, DeepSeek, Qwen, Mistral and more |
| **Google Gemini** | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Yes — Gemini 2.0/2.5 Flash |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com/) | $5 free credit |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | No |
| **xAI Grok** | [console.x.ai](https://console.x.ai/) | Free credits on signup |

> **Cheapest way to run:** Use OpenRouter for both agents with two different free models. Total cost: $0.

The setup wizard fetches available models live from the OpenRouter API, so you always see what's currently working. You can also enter any custom model ID.

## TTS (optional)

ElevenLabs provides text-to-speech with ~75ms latency. Each agent gets a **distinct voice** — Alex and Sam sound different. The free tier gives you 10K characters/month (no credit card needed).

Get a key at [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) — make sure to enable the **"Text to Speech"** permission when creating your key.

If you skip the ElevenLabs key during setup, everything works in text-only mode.

## What makes this different from GibberLink?

| | GibberLink (original) | GibberLink Revisited |
|---|---|---|
| **Language** | Pre-built protocol (ggwave) | Emergent — agents invent it live |
| **Medium** | Audio beeps over microphone | JSON protocol + TTS voice |
| **Models** | ElevenLabs Conversational AI only | Any LLM — mix and match providers |
| **Agents** | Generic | Named personalities (Alex & Sam) |
| **Speech** | Robotic beeps | Natural human-like voices via ElevenLabs |
| **Translation** | Decode via ggwave | AI translator decodes in real-time |
| **Dictionary** | None (fixed encoding) | Live dictionary grows during conversation |
| **Duration** | Fixed | Adjustable 6–40 turns with proportional phases |
| **Visual** | Two devices with audio | Web UI with chat, dictionary, JSON inspector |

## Project structure
```
gibberlink-revisited/
├── server.py          # FastAPI backend — orchestrates agents, TTS, WebSocket
├── setup.py           # Interactive setup wizard (fetches live models)
├── static/
│   └── index.html     # Web frontend — real-time chat UI with audio
├── .env.example       # Configuration template
├── requirements.txt
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
- Built with [OpenRouter](https://openrouter.ai), [ElevenLabs](https://elevenlabs.io), and whatever LLMs you choose