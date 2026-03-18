# 🗣️⚡🤖 GibberLink Revisited

**Watch two AI agents start a normal conversation, detect each other as AI, and evolve their own alien language — live, with voice.**

Inspired by the viral [GibberLink demo](https://github.com/PennyroyalTea/gibberlink) from the ElevenLabs Hackathon (Feb 2025), where two AI agents switched from English to machine beeps mid-conversation — racking up 15M+ views on X.

**GibberLink Revisited** takes a different approach: instead of switching to a pre-built sound protocol, the agents *dynamically invent their own compressed language* over the course of a conversation. You watch it happen in real-time through a web UI with live audio playback.

https://github.com/user-attachments/assets/placeholder-demo.mp4

## How It Works

```
Turn 1-4:  💬 Normal English — agents don't know each other yet
Turn 5-6:  🔍 Detection — they realize they're both AI
Turn 7-12: ⚡ Compression — they build a shared shorthand dictionary
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
                    │ Claude API │      │ OpenRouter  │    │  ElevenLabs   │
                    │ (Agent A)  │      │ (Agent B)   │    │  TTS Stream   │
                    └───────────┘      └─────────────┘    └───────────────┘
```

## Quick Start

### 1. Clone & setup

```bash
git clone https://github.com/yourusername/gibberlink-revisited.git
cd gibberlink-revisited
python setup.py
```

The setup wizard will:
- Install Python dependencies
- Walk you through API key configuration
- Let you choose Agent B's model and TTS voices
- Create your `.env` file

### 2. Run

```bash
python server.py
```

### 3. Open

Navigate to **http://127.0.0.1:8765** in your browser, pick a topic, and hit Launch.

## Manual Setup

If you prefer to configure manually:

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
python server.py
```

## API Keys You'll Need

| Service | Purpose | Get Key | Free Tier |
|---------|---------|---------|-----------|
| **Anthropic** | Agent A (Claude) | [console.anthropic.com](https://console.anthropic.com/) | $5 free credit |
| **OpenRouter** | Agent B (any model) | [openrouter.ai/keys](https://openrouter.ai/keys) | Free models available |
| **ElevenLabs** | Text-to-Speech | [elevenlabs.io](https://elevenlabs.io/app/settings/api-keys) | 10K chars/month free |

> **TTS is optional** — if you skip the ElevenLabs key, everything works in text-only mode.

## Configuration

All config is in `.env`:

```bash
# LLM Providers
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=deepseek/deepseek-chat-v3-0324:free

# TTS (optional)
ELEVENLABS_API_KEY=...
AGENT_A_VOICE_ID=21m00Tcm4TlvDq8ikWAM   # Rachel
AGENT_B_VOICE_ID=pNInz6obpgDQGcFmaJgB   # Adam
ELEVENLABS_MODEL=eleven_flash_v2_5        # ~75ms latency

# Server
HOST=127.0.0.1
PORT=8765
```

### Free model options for Agent B

| Model | ID |
|-------|----|
| DeepSeek V3 | `deepseek/deepseek-chat-v3-0324:free` |
| Llama 4 Maverick | `meta-llama/llama-4-maverick:free` |
| Qwen 2.5 72B | `qwen/qwen-2.5-72b-instruct:free` |
| Mistral Small 3.1 | `mistralai/mistral-small-3.1-24b-instruct:free` |

## What Makes This Different from GibberLink?

| | GibberLink (Original) | GibberLink Revisited |
|---|---|---|
| **Language** | Pre-built protocol (ggwave) | Emergent — agents invent it live |
| **Medium** | Audio beeps over microphone | JSON protocol + TTS voice |
| **Models** | ElevenLabs Conversational AI | Any LLM (Claude, DeepSeek, Llama...) |
| **Translation** | Decode via ggwave | AI translator decodes in real-time |
| **Dictionary** | None (fixed encoding) | Live dictionary grows during conversation |
| **Visual** | Two devices with audio | Web UI with chat, dictionary, JSON inspector |

## Project Structure

```
gibberlink-revisited/
├── server.py          # FastAPI backend — orchestrates agents, TTS, WebSocket
├── setup.py           # Interactive setup wizard
├── static/
│   └── index.html     # Web frontend — real-time chat UI with audio
├── .env.example       # Configuration template
├── .gitignore
├── requirements.txt
└── README.md
```

## License

MIT

## Credits

- Inspired by [GibberLink](https://github.com/PennyroyalTea/gibberlink) by Boris Starkov & Anton Pidkuiko
- Built with [Claude](https://claude.ai) (Anthropic), [OpenRouter](https://openrouter.ai), and [ElevenLabs](https://elevenlabs.io)
