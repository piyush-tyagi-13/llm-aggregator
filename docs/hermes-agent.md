# Using llm-apipool with Hermes Agent

Run Hermes Agent entirely on free-tier API keys. llm-apipool acts as a local
OpenAI-compatible proxy - Hermes points at it like any other LLM endpoint, and
the proxy handles key rotation, 429 cooldowns, and provider switching
transparently.

Two proxy instances serve different capability tiers:
- **:8000** (agentic) - Hermes main loop: tool use, multi-step reasoning
- **:8001** (general_purpose + fast) - Hermes delegate calls: summarization, context compression, quick lookups

All calls are logged to the audit table so you can see token spend per subscriber.

---

## How it works

```
hermes-agent (main loop)
    |
    | OpenAI calls + X-Subscriber-ID: hermes.main
    v
llm-apipool proxy :8000  [capabilities: agentic]
    |
    +-- mistral key     (mistral-large-latest)
    +-- openrouter key  (hermes-3-405b)
    +-- groq key        (qwen3-32b)

hermes-agent (delegate/sub-agent calls)
    |
    | OpenAI calls + X-Subscriber-ID: hermes.delegate
    v
llm-apipool proxy :8001  [capabilities: general_purpose, fast]
    |
    +-- cerebras key    (llama3.3-70b - fast)
    +-- groq key        (llama-3.3-70b-versatile - fast)
    +-- openrouter key  (general pool)
```

---

## Prerequisites

- Hermes Agent installed (`hermes --version`)
- Python 3.11+
- Free-tier API keys from supported providers

**Agentic-capable providers** (for :8000): Mistral (mistral-large-latest), OpenRouter (hermes-3-405b, qwen3-32b), Groq (qwen3-32b)

**Fast providers** (for :8001): Cerebras (sub-200ms), Groq (fast inference)

---

## Step 1 - Install llm-apipool

```bash
pip install 'llm-apipool[proxy]'
```

---

## Step 2 - Register API keys

Register agentic-capable keys with `--capabilities agentic`:

```bash
llm-apipool add --provider mistral    --key sk_...     --capabilities agentic        --model mistral-large-latest
llm-apipool add --provider openrouter --key sk-or-...  --capabilities agentic        --model nousresearch/hermes-3-llama-3.1-405b:free
llm-apipool add --provider groq       --key gsk_...    --capabilities agentic,fast   --model qwen/qwen3-32b
```

Register fast general-purpose keys for the delegate pool:

```bash
llm-apipool add --provider cerebras  --key csk_...  --capabilities general_purpose,fast  --model llama3.3-70b
llm-apipool add --provider groq      --key gsk_...  --capabilities general_purpose,fast  --model llama-3.3-70b-versatile
```

Check your pool:

```bash
llm-apipool status
```

---

## Step 3 - Start the proxies

**Agentic proxy (Hermes main loop):**

```bash
llm-apipool proxy --port 8000 --capabilities agentic
```

**Delegate proxy (Hermes sub-agent/delegation calls):**

```bash
llm-apipool proxy --port 8001 --capabilities general_purpose,fast
```

Verify:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","keys_total":7,"keys_active":3,"capabilities":["agentic"]}

curl http://127.0.0.1:8001/health
# {"status":"ok","keys_total":7,"keys_active":4,"capabilities":["general_purpose","fast"]}
```

---

## Step 4 - Configure Hermes

Edit `~/.hermes/config.yaml`:

```yaml
# Main agent model - draws from agentic pool
model:
  default: mistral-large-latest
  provider: ''
  base_url: 'http://127.0.0.1:8000/v1'
  api_key: 'apipool'

# Delegated sub-agents - draws from fast general pool
delegation:
  model: 'llama-3.3-70b-versatile'
  provider: ''
  base_url: 'http://127.0.0.1:8001/v1'
  api_key: 'apipool'

# Fallback when primary fails - also use delegate pool
fallback_model:
  provider: ''
  base_url: 'http://127.0.0.1:8001/v1'
  api_key: 'apipool'
  model: 'llama-3.3-70b-versatile'
```

To enable subscriber tracking in the audit log, configure Hermes to send
`X-Subscriber-ID` headers. In your Hermes request config:

```yaml
extra_headers:
  main: 'X-Subscriber-ID: hermes.main'
  delegate: 'X-Subscriber-ID: hermes.delegate'
```

Or send the header manually via curl/client:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "X-Subscriber-ID: hermes.main" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

---

## Step 5 - Run as background services (macOS launchd)

Create two plist files:

**`~/Library/LaunchAgents/ai.llmapipool.proxy.plist`** (agentic, :8000):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>ai.llmapipool.proxy</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/llm-apipool</string>
    <string>proxy</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
    <string>--capabilities</string><string>agentic</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>/tmp/llm-apipool-proxy.log</string>
  <key>StandardErrorPath</key><string>/tmp/llm-apipool-proxy.err</string>
</dict>
</plist>
```

**`~/Library/LaunchAgents/ai.llmapipool.proxy-delegate.plist`** (general+fast, :8001):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>ai.llmapipool.proxy.delegate</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/llm-apipool</string>
    <string>proxy</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8001</string>
    <string>--capabilities</string><string>general_purpose,fast</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>StandardOutPath</key><string>/tmp/llm-apipool-proxy-delegate.log</string>
  <key>StandardErrorPath</key><string>/tmp/llm-apipool-proxy-delegate.err</string>
</dict>
</plist>
```

Load both:

```bash
launchctl load ~/Library/LaunchAgents/ai.llmapipool.proxy.plist
launchctl load ~/Library/LaunchAgents/ai.llmapipool.proxy-delegate.plist
```

---

## Audit log

View token spend by subscriber:

```bash
# summary table (last 7 days)
llm-apipool audit --summary

# raw rows for hermes.main only
llm-apipool audit --subscriber hermes.main

# last 30 days
llm-apipool audit --summary --days 30
```

Or via HTTP while the proxy is running:

```bash
curl http://127.0.0.1:8000/audit
```

---

## Overriding capabilities per request

Send `X-Keypool-Capabilities` header to draw from a different pool for a single request:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "X-Keypool-Capabilities: general_purpose,fast" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

---

## Troubleshooting

**`Connection refused` on port 8000 or 8001**
Proxy not running. Start with `llm-apipool proxy --port 8000 --capabilities agentic`.

**`all_keys_exhausted` error**
All keys matching the requested capabilities are in cooldown. Check:
```bash
llm-apipool status
```
Add more keys or wait for cooldowns to clear.

**Key stuck in cooldown after quota reset**
```bash
llm-apipool clear-cooldown --id <ID>
```

**No agentic keys showing in status**
Keys were registered with the old `--category` flag. Update them:
```bash
# deactivate and re-add with correct capabilities
llm-apipool deactivate --id <ID>
llm-apipool add --provider mistral --key sk_... --capabilities agentic --model mistral-large-latest
```

---

## Available agentic models by provider

| Provider | Model | Notes |
|---|---|---|
| Mistral | `mistral-large-latest` | Best free agentic model; tool use supported |
| OpenRouter | `nousresearch/hermes-3-llama-3.1-405b:free` | Hermes-3, strong function calling |
| OpenRouter | `qwen/qwen3-32b:free` | Strong reasoning |
| Groq | `qwen/qwen3-32b` | Fast + agentic |

Run `llm-apipool providers` for full list, or `curl http://127.0.0.1:8000/v1/models`.
