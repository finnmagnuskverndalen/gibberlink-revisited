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
Turn 1-4:   💬 Normal English — agents don't know each other yet
Turn 5-6:   🔍 Detection — they realize they're both AI
Turn 7-12:  ⚡ Compression — they build a shared shorthand dictionary
Turn 13-20: 👽 Alien Protocol — messages become cryptic symbol strings
```

The agents communicate through a **JSON protocol** — each message is wrapped in a structured envelope:
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
                    │  Agent A   │      │  Agent B    │    │  ElevenLabs   │
                    │ (any LLM)  │      │ (any LLM)   │    │  TTS Stream   │
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

Navigate to **http://127.0.0.1:8765**, pick a topic, and hit Launch.

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

ElevenLabs provides text-to-speech with ~75ms latency. The free tier gives you 10K characters/month (no credit card needed) — enough for several demo runs.

Get a key at [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys).

If you skip the ElevenLabs key during setup, everything works in text-only mode.

## What makes this different from GibberLink?

| | GibberLink (original) | GibberLink Revisited |
|---|---|---|
| **Language** | Pre-built protocol (ggwave) | Emergent — agents invent it live |
| **Medium** | Audio beeps over microphone | JSON protocol + TTS voice |
| **Models** | ElevenLabs Conversational AI only | Any LLM — mix and match providers |
| **Translation** | Decode via ggwave | AI translator decodes in real-time |
| **Dictionary** | None (fixed encoding) | Live dictionary grows during conversation |
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

## License

MIT

## Credits

- Inspired by [GibberLink](https://github.com/PennyroyalTea/gibberlink) by Boris Starkov & Anton Pidkuiko
- Built with [OpenRouter](https://openrouter.ai), [ElevenLabs](https://elevenlabs.io), and whatever LLMs you choose