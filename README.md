<p align="center">
  <h1 align="center">🪙 llm-apipool</h1>
  <p align="center"><strong>40+ Free LLM APIs → One OpenAI‑compatible endpoint</strong></p>
  <p align="center">
    Stop juggling API keys. One proxy, one format, zero cost.
  </p>
</p>

<p align="center">
  <a href="https://github.com/GFardad/llm-apipool/actions"><img src="https://img.shields.io/github/actions/workflow/status/GFardad/llm-apipool/test.yml?branch=main&label=tests&logo=github" alt="Tests"></a>
  <a href="https://pypi.org/project/llm-apipool/"><img src="https://img.shields.io/badge/pypi-1.0.0-blue?logo=pypi" alt="PyPI v1.0.0"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11%20|%203.12-blue?logo=python" alt="Python"></a>
  <a href="https://github.com/GFardad/llm-apipool/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License"></a>
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/badge/lint-ruff-orange?logo=ruff" alt="Ruff"></a>
  <br/>
  <a href="https://github.com/GFardad/llm-apipool/stargazers"><img src="https://img.shields.io/github/stars/GFardad/llm-apipool?style=social" alt="Stars"></a>
  <a href="https://github.com/GFardad/llm-apipool/issues"><img src="https://img.shields.io/github/issues/GFardad/llm-apipool?style=social" alt="Issues"></a>
</p>

---

## 🤯 The Problem

You want to build with LLMs without spending $200/month. The free tiers exist — Groq, Cerebras, Mistral, Google, OpenRouter, SambaNova, GitHub, Hugging Face, Replicate, Cohere…

But managing 40+ API keys, remembering which SDK to use, handling 429 rate‑limits, and switching providers when one goes down? That's the nightmare this project solves.

**llm-apipool** is a production‑grade CLI/TUI/proxy that aggregates every free‑tier LLM into a single OpenAI‑compatible endpoint. Drop it in, point any tool at `http://localhost:8000/v1`, and never think about individual API keys again.

## ✨ What It Does

```
┌──────────────┐     ┌───────────────┐     ┌─────────────┐
│  Your App /  │────▶│  llm-apipool  │────▶│  Groq       │
│  Agent /     │     │  Proxy        │     ├─────────────┤
│  LangChain   │     │  :8000/v1     │────▶│  Cerebras   │
│              │     │               │     ├─────────────┤
│  One format  │     │  40+ keys     │────▶│  Mistral    │
│  One key     │     │  auto-rotate  │     ├─────────────┤
│  One URL     │     │  rate-limit   │────▶│  OpenRouter │
└──────────────┘     │  fallback     │     ├─────────────┤
                     │  cooldown     │────▶│  Google     │
                     │  tracking     │     ├─────────────┤
                     │  audit log    │────▶│  … 30+ more │
                     └───────────────┘     └─────────────┘
```

**Zero API cost.** One `pip install`. Instant access to frontier models through free tiers.

---

## 🚀 Quick Start

```bash
# Install
pip install "llm-apipool[all]"

# Register your keys (one-time)
llm-apipool add --provider groq     --key gsk_...    --model llama-3.3-70b-versatile
llm-apipool add --provider mistral  --key sk_...      --model mistral-large-latest
llm-apipool add --provider cerebras --key csk_...     --model llama3.3-70b

# Start the proxy
llm-apipool proxy --port 8000

# Use it — any OpenAI-compatible tool
export OPENAI_API_BASE="http://localhost:8000/v1"
export OPENAI_API_KEY="keypool"
```

That's it. Your existing agents, scripts, and apps now have access to 40+ free LLM providers through a single endpoint.

---

## 📸 Dashboard & TUI

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/home.jpg" alt="Dashboard Home"/></td>
    <td width="50%"><img src="docs/screenshots/add_key.jpg" alt="Add Key Dialog"/></td>
  </tr>
  <tr>
    <td align="center"><em>React Dashboard — key management, analytics, settings</em></td>
    <td align="center"><em>Add keys with auto-provider detection</em></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/tui-keys.png" alt="TUI Keys View"/></td>
    <td width="50%"><img src="docs/screenshots/tui-add-key.png" alt="TUI Add Key"/></td>
  </tr>
  <tr>
    <td align="center"><em>Textual TUI — full key pool at a glance</em></td>
    <td align="center"><em>Interactive key import wizard</em></td>
  </tr>
</table>

---

## 🧩 What Makes It Special

| Capability | llm-apipool | DIY scripts |
|---|---|---|
| **Provider count** | 40+ built-in | You write each one |
| **Rate-limit handling** | Auto-cooldown + fallback tiers | Custom try/catch per provider |
| **Key rotation** | Round-robin across multiple keys per provider | Manual switch |
| **Streaming** | True SSE for OpenAI‑compat providers | Need per-provider implementation |
| **Unified effort config** | One command sets reasoning_effort across OpenAI/Anthropic/DeepSeek/Google | N/A |
| **Audit log** | Who called what, when, with which key | Build it yourself |
| **TUI** | Full interactive terminal UI | Nothing |
| **Dashboard** | React SPA with analytics | Nothing |
| **Docker** | Multi-stage with healthcheck | Nothing |
| **LangChain** | `AggregatorChat` drop‑in | Wrap in custom code |
| **Alembic migrations** | Proper schema versioning | ad-hoc SQL |
| **Tests** | 522 passing | Usually 0 |
| **Hermes Agent integration** | Documented, tested pattern | Guess and pray |

---

## 💡 Use Cases

**Run Hermes Agent entirely on free APIs** — Two proxy instances (agentic + fast), one `hermes-agent` instance, zero API bills. [Full guide →](docs/hermes-agent.md)

**Build a multi-provider chatbot** — `AggregatorChat` drops into any LangChain chain. Set `capabilities=["agentic"]` or `["general_purpose", "fast"]` and let the rotator handle the rest.

**Load‑test free tiers** — Register 5 Groq keys, set cooldown fallback, and blast requests. The proxy handles rotation transparently.

**Self‑hosted AI gateway** — Docker‑compose with healthcheck, environment‑configurable, ready for 24/7 operation.

---

## 📋 Features at a Glance

- **40+ providers** — Groq, Cerebras, Mistral, OpenRouter, Google, SambaNova, GitHub, Hugging Face, Replicate, Cohere, Anthropic, OpenAI, DeepSeek, xAI, Together, Fireworks, and more
- **Smart tier routing** — 4 quality tiers with automatic fallback when keys hit rate limits
- **Auto‑import from file** — key‑per‑line, `provider:key`, `---` blocks, NDJSON
- **Real streaming** — True SSE for OpenAI‑compatible providers, simulated for others
- **Think‑token stripping** — Removes `\u001b{...}\u001b}` from reasoning model outputs
- **Effort / thinking per model** — Unified Low/Medium/High maps to provider‑specific params
- **Subscriber tracking** — Attribute every call to `hermes.main`, `mdcore.ingest`, or any subscriber ID
- **Connection pooling** — Reuses HTTP connections across requests (TTFT optimized)
- **Alembic migrations** — Proper DB schema versioning
- **Interactive TUI** — Textual app with 5 tabs: keys, models, audit log, import, status
- **React Dashboard** — Keys page, Models table with tier/context/effort, Analytics, Settings
- **Docker** — Multi‑stage build, healthcheck, `docker-compose.yml`
- **522 passing tests** — Coverage of key detection, effort config, bulk import, settings, routing

---

## ⚙️ Effort & Thinking Configuration

Set reasoning effort across all providers with a single command:

```bash
curl -X POST http://localhost:8000/api/models/effort/set-all \
  -H "Content-Type: application/json" \
  -d '{"level": "medium"}'
```

Maps automatically:

| Level | OpenAI / xAI | Anthropic | Google | DeepSeek |
|-------|-------------|-----------|--------|----------|
| low | reasoning_effort: low | thinking: off | thinking: off | thinking: off |
| medium | reasoning_effort: medium | thinking: on (16K budget) | thinking: on | thinking: off |
| high | reasoning_effort: high | thinking: on (64K budget) | thinking: on | thinking: on |

---

## 🛠️ Works With

llm-apipool integrates with **any tool that supports OpenAI-compatible APIs**:

| Tool | How to Connect |
|---|---|
| **Hermes Agent** | Point `base_url` at `http://localhost:8000/v1` — [full guide](docs/hermes-agent.md) |
| **OpenCode** | Set `OPENAI_API_BASE=http://localhost:8000/v1` |
| **Claude Code** | `claude --proxy http://localhost:8000/v1` |
| **Cursor** | Settings → API → OpenAI-compatible → `http://localhost:8000/v1` |
| **Continue.dev** | Add `"apiBase": "http://localhost:8000/v1"` to config.json |
| **LangChain** | `AggregatorChat` drop‑in wrapper |
| **OpenAI SDK** | `openai.base_url = "http://localhost:8000/v1"` |
| **curl / httpx** | Swap `api.openai.com` → `localhost:8000` |

**No code changes required** in any of these tools. Just change the base URL.

---

## 🤔 FAQ

**Q: Do I need paid API keys?**
A: No. All 40+ providers offer free tiers. You just need to sign up and grab a free key.

**Q: How is this different from LiteLLM?**
A: LiteLLM is a paid enterprise AI gateway ($250+/mo pro plan). llm-apipool is **100% free, open-source, and focused on free-tier API aggregation**. LiteLLM is better for enterprise billing/rate-limiting at scale; llm-apipool is better for individual devs and small teams who want zero API bills.

**Q: How is this different from a simple round-robin script?**
A: llm-apipool handles 429 cooldowns, tier-based fallback, streaming, think-token stripping, cross-provider effort configuration, subscriber audit logging, and has a TUI + dashboard. A script does none of this out of the box.

**Q: Do I need to install anything besides Python?**
A: No. `pip install "llm-apipool[all]"` gives you CLI + TUI + proxy. Node.js is only needed if you build the frontend from source.

**Q: Can I run this in production?**
A: Yes. Docker compose with healthcheck, persistent SQLite, and environment config. Designed for 24/7 operation as a local gateway.

**Q: What happens when a key hits its rate limit?**
A: The proxy automatically applies a cooldown and falls back to the next available key or tier. The rotator tracks cooldown expiry per key.

**Q: Is streaming supported?**
A: Yes. True SSE streaming for OpenAI-compatible providers (Groq, Cerebras, Mistral, etc.). Simulated streaming (token-by-token yield) for others.

---

## 🐳 Docker

```bash
docker compose up -d
# Proxy at http://localhost:8000
```

Works with any OpenAI‑compatible tool — set `OPENAI_API_BASE=http://localhost:8000/v1`.

---

## 🧪 Supported Providers

| Provider | Free Key | LLMs Available |
|---|---|---|
| **Groq** | [gsk_...](https://console.groq.com/keys) | Llama 3.3 70B, Qwen 3 32B, Mixtral 8x7B, DeepSeek R1 |
| **Cerebras** | [csk_...](https://cloud.cerebras.ai) | Llama 3.3 70B, Llama 3.1 8B |
| **Mistral** | [sk_...](https://console.mistral.ai/api-keys) | Mistral Large, Mistral Small, Codestral, Pixtral |
| **OpenRouter** | [sk-or-...](https://openrouter.ai/settings/keys) | 300+ models (free tier), Hermes 3 405B, Qwen 3 32B |
| **Google** | [AIza...](https://aistudio.google.com/apikey) | Gemini 2.0 Flash, Gemini 2.5 Pro, Gemma 3 |
| **SambaNova** | [key](https://cloud.sambanova.ai/apis) | Llama 3.3 70B, Qwen 3, DeepSeek R1 |
| **Hugging Face** | [hf_...](https://huggingface.co/settings/tokens) | Gemma 2 27B, Zephyr, StarCoder |
| **GitHub** | [ghp_...](https://github.com/settings/tokens) | GPT-4o mini, GPT-4o, o1, o3-mini |
| **xAI** | [xai-...](https://console.x.ai) | Grok 2, Grok 3 |
| **Together** | [key](https://api.together.ai/settings/api-keys) | DeepSeek R1, Llama 3.3, Qwen 3 |
| **DeepSeek** | [sk-...](https://platform.deepseek.ai) | DeepSeek V3, DeepSeek R1 |
| **Fireworks** | [key](https://fireworks.ai) | DeepSeek R1, Qwen 3, Llama 3.3 |
| **Anthropic** | [sk-ant-...](https://console.anthropic.com/) | Claude 3 Haiku, Claude 3.5 Sonnet |
| **Cohere** | [key](https://dashboard.cohere.com/api-keys) | Command R+, Command R |
| **Replicate** | [r8_...](https://replicate.com/account/api-tokens) | Llama 3.3 70B, DeepSeek R1 |
| **Lepton** | [key](https://lepton.ai) | DeepSeek R1, Qwen 3 |
| **Infermatic** | [key](https://infermatic.ai) | DeepSeek R1, Llama 3.3 |
| … and **25+ more** | | |

[Full provider guide →](PROVIDER_GUIDE.md)

---

## 📚 LangChain Integration

```python
from llm_apipool import AggregatorChat

llm = AggregatorChat(
    capabilities=["general_purpose", "fast"],
    quality_tier=1,
    max_fallback_tier=4,
)
response = llm.invoke("Explain quantum computing in simple terms")
```

Drops into any LangChain chain — `LLMChain`, `ConversationChain`, agents, etc.

---

## 🌐 API (OpenAI‑compatible)

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.3-70b-versatile",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

curl http://localhost:8000/v1/models          # list models
curl http://localhost:8000/health             # health check
curl http://localhost:8000/audit              # audit log
```

---

## 📈 Roadmap

- [x] **v1.0** — Core proxy, CLI, TUI, dashboard, 40+ providers, LangChain wrapper
- [ ] **v1.1** — Plugin system for custom providers, WebSocket streaming
- [ ] **v1.2** — Multi‑user auth, API key scoping, usage quotas per subscriber
- [ ] **v2.0** — Distributed proxy cluster, shared pool across machines

---

## 🤝 Contributing

llm-apipool thrives on community contributions. [See CONTRIBUTING.md](CONTRIBUTING.md) for:
- Adding new providers
- Reporting bugs
- Feature requests
- Code contributions

---

## ⭐ Why Star?

- **You use free LLM APIs** — This makes them 10× easier to manage
- **You build AI tools** — One integration gives you 40+ backends
- **You want zero API bills** — Free tiers are the way, and this makes them production‑grade
- **You contribute to OSS** — Provider contributions are quick and welcome

---

---

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=GFardad/llm-apipool&type=Date)](https://star-history.com/#GFardad/llm-apipool&Date)

---

<p align="center">
  <a href="https://github.com/GFardad/llm-apipool/stargazers">
    <img src="https://img.shields.io/github/stars/GFardad/llm-apipool?style=for-the-badge&logo=github" alt="Stars">
  </a>
  <br/>
  <a href="https://github.com/GFardad/llm-apipool/discussions">💬 Discussions</a>
  ·
  <a href="https://github.com/GFardad/llm-apipool/issues">🐛 Issues</a>
  ·
  <a href="https://github.com/GFardad/llm-apipool/blob/main/CONTRIBUTING.md">🤝 Contributing</a>
</p>

<p align="center">
  <sub>Built for the open-source AI community. Free tiers forever.</sub>
</p>
