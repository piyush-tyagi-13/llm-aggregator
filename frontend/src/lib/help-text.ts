export const HELP = {
  // ── Routing Strategy ──
  routingStrategy: 'Controls how the router selects which key to use. "Auto" picks the best strategy based on recent performance. "Priority" uses key priority order. "Balanced" distributes load evenly. "Smartest" prioritizes highest intelligence models. "Fastest" prioritizes lowest latency. "Reliable" prioritizes lowest error rate. "Custom" lets you set your own weights.',
  customWeights: 'Fine-tune the routing algorithm by weighting three dimensions: reliability (fewest errors), speed (lowest latency), and intelligence (highest model rank). Weights are normalized so they always sum to 1.0.',

  // ── Sticky Sessions ──
  stickyEnabled: 'When enabled, a single key+model pair is "stuck" to a session ID for the duration of the TTL. This ensures continuity — every message in a conversation uses the same model and API key. Disable to allow free rotation between keys.',
  stickyTtl: 'How long (in milliseconds) a sticky binding should last before expiring. After expiry, the next request picks a new key. Default: 30 minutes (1,800,000 ms).',
  stickyMaxEntries: 'Maximum number of concurrent sticky session bindings stored in memory. When full, the oldest expired entry is evicted. Default: 500 entries.',

  // ── Affinity Routing ──
  affinityEnabled: 'Pins a UID (user ID) to a specific key+model for the duration of its active request plus a 60-second semi-busy period. This prevents the same UID from being routed to different models mid-conversation while allowing other UIDs to use the freed slot. Max 5 concurrent slots. Mutually exclusive with Sticky Sessions.',
  affinitySlots: 'The number of concurrent request slots available for affinity routing. Each active UID occupies one slot. When all slots are full, new UIDs must wait for a slot to free up.',

  // ── Context Handoff ──
  handoffMode: 'When switching between models mid-conversation, "On Model Switch" injects a system message summarizing the prior conversation context so the new model can continue seamlessly. "Off" disables this — the new model starts fresh.',

  // ── Tier Fallback ──
  tierFallbackEnabled: 'When enabled, if no key is available in the preferred quality tier, the system will fall back to progressively lower tiers until a key is found. When disabled, only keys from the exact preferred tier are used.',

  // ── Tier Settings ──
  qualityTier: 'Your preferred model quality tier. Tier 1 (Frontier) = best models (GPT-5, Claude Opus, Gemini 2.5). Tier 2 (High-Perf) = strong models (GPT-4o, Claude Sonnet). Tier 3 (Good OSS) = capable open models (Llama 3, Mistral). Tier 4 (Fallback) = small/fast models.',
  maxFallbackTier: 'The worst tier the system is allowed to fall back to when tier fallback is enabled. For example, quality_tier=1 + max_fallback_tier=3 means: start at Tier 1, fall through Tiers 2 and 3 if needed, but never use Tier 4.',

  // ── Fallback Chain ──
  fallbackMaxSameKey: 'Maximum number of consecutive attempts allowed on the same API key before the router skips it and tries the next key. Prevents hammering a failing key. Default: 3.',
  fallbackMaxSameProvider: 'Maximum number of consecutive attempts allowed across all keys from the same provider before the router skips that provider entirely. Default: 3.',
  fallbackMaxAllProviders: 'Maximum total attempts across all keys and providers before the router gives up and returns an error. Default: 3.',
  fallbackCooldown: 'Duration in milliseconds that a key is placed in cooldown after hitting a rate limit (429). During cooldown, the key is not considered for routing. Default: 30 minutes (1,800,000 ms).',

  // ── Routing Override ──
  routingOverride: 'Force the router to only use specific models, specified as a comma-separated list of model names (e.g., "llama-3.3-70b-versatile,mixtral-8x7b"). When set, all other models are temporarily excluded. Leave empty for normal routing.',

  // ── Fallback Modes ──
  fallbackMode: 'Selects which routing mode the system uses. "Fallback Chain" is the standard provider-caching model that falls through tiers. "Sticky" pins a UID to the same model across requests. "Slimey" is QoS-based — it monitors TTFT and throughput and unpins if quality degrades.',
  fallbackModeFallback: 'Standard model caching/fallback. The router selects the best key based on tier, strategy, and availability. When a key fails, it falls back to the next best key. This is the default mode with no UID pinning.',
  fallbackModeSticky: 'Pins a UID to the same model+key for the duration of the conversation. Ensures consistency — every message uses the same provider and model. If that key fails, the UID is unpinned and falls back to normal routing.',
  fallbackModeSlimey: 'Quality-of-Service based routing. The system monitors TTFT (time to first token) and throughput (tokens/sec) for each UID-provider pair. If either metric falls outside your acceptable range, the UID is unpinned and falls back to the best alternative. Ideal for latency-sensitive applications.',

  // ── Slimey QoS ──
  slimeyMaxTtft: 'Maximum acceptable Time To First Token in milliseconds. If the average TTFT over the last 5 requests exceeds this, the provider is considered unacceptable and the UID is unpinned. Default: 5000ms (5 seconds).',
  slimeyMinThroughput: 'Minimum acceptable throughput in tokens per second. If the average throughput over the last 5 requests falls below this, the provider is considered unacceptable. Default: 10 tokens/sec.',

  // ── Keys Page ──
  keyStatus: 'The current health status of this key. Green = healthy (recent requests succeeded). Yellow = in cooldown (temporarily disabled due to rate limit). Red = error state (repeated failures). Grey = inactive (manually disabled).',
  keyCooldown: 'This key is in cooldown due to a rate limit (429). It will be automatically re-enabled when the cooldown period expires. You can manually clear the cooldown using the button.',
  keyModel: 'The model assigned to this key. Each key is typically tied to a specific model or model family. You can edit this inline to reassign the key to a different model.',
  keyPriority: 'The priority of this key within its provider group. Higher priority keys are selected first. You can reorder keys by adjusting their priority values.',
  bulkImport: 'Paste multiple API keys at once for batch registration. Supports formats: one key per line, provider:key pairs, --- delimited blocks, or NDJSON. The system will auto-detect the provider for each key.',

  // ── Models Page ──
  modelTier: 'The quality tier of this model. Tier 1 (Frontier) = best-in-class models. Tier 2 (High-Perf) = strong performers. Tier 3 (Good OSS) = capable open-source. Tier 4 (Fallback) = small/fast utility models.',
  modelCapabilities: 'The capabilities this model supports. Vision = can process images. Tools = can use function calling. Streaming = supports real-time token streaming. Thinking = supports reasoning/chain-of-thought.',
  modelHealth: 'The recent health status of this model based on the last 24 hours of requests. Shows average latency, error rate, and whether it is currently rate-limited.',
  modelEffort: 'Configure the reasoning effort for this model. Maps your unified Low/Medium/High setting to provider-specific parameters (e.g., reasoning_effort for OpenAI, thinking+budget_tokens for Anthropic).',
  unlockableModels: 'These providers have no active keys in the pool and their models are unavailable. Click "Add key →" to navigate to the Keys page and register a key for this provider.',

  // ── Logs Page ──
  dataManagement: 'Logs are persisted in SQLite alongside key data. Configure retention and cleanup behavior on the Settings page to control disk usage.',
  logAccess: 'The access log records every HTTP request to the proxy, including request/response bodies (truncated), headers, and timing. Useful for debugging client issues.',
  logAudit: 'The audit log records every API call made through the proxy: which subscriber called which model, how many tokens were used, latency, and success/failure status. Essential for usage tracking and debugging.',
  logDateRange: 'Select how many days of log history to include. Default: 30 days. Maximum: 365 days.',
  logFormat: 'Choose the export format for your log data. CSV is best for spreadsheet analysis. JSON preserves the full data structure. JSONL is ideal for programmatic processing (one JSON object per line).',
  logLiveTail: 'Stream new log entries in real-time via Server-Sent Events (SSE). Useful for live debugging — each new request appears as it happens without refreshing.',
  logStorage: 'The total disk space used by all log files. Logs are stored in ~/.llm-apipool/logs/ with daily rotation and automatic cleanup of files older than 7 days.',
  logTypeSelector: 'Choose which log category to explore. Audit logs track API call details (who, what, when). Access logs record HTTP request/response metadata. Proxy logs capture full request/response bodies including model outputs.',

  // ── Analytics Page ──
  breakerStates: 'Circuit breaker state summary. OPEN = tripped due to failures (auto-recovers in 5 min). HALF-OPEN = testing if recovery worked (3 successes to close). CLOSED = healthy and operating normally.',
  circuitBreaker: 'Circuit Breakers automatically disable a provider+model+key combination after a configurable number of consecutive failures. After a recovery period (5 minutes), the breaker transitions to "half-open" — if the next request succeeds, the breaker closes. If it fails again, the breaker stays open.',
  modelLatency: 'Per-model performance metrics including request count, average latency, peak latency, and total token consumption. Higher latency may indicate provider congestion or model complexity.',
  overviewKeys: 'Key pool overview showing total registered keys, currently active (healthy) keys, and the number of days covered by the analytics window.',
  overviewPerformance: 'Real-time aggregated performance metrics across all active providers. Includes total requests, errors, rate-limit hits (429s), and token usage since the proxy started.',
  providerPenalties: 'Tracks when providers are penalized due to excessive failures or errors. Each penalty increases a score (0-10) and affects routing priority. A provider at max penalty is temporarily deprioritized.',
  providerTraffic: 'Breakdown of request volume, error count, and rate-limit (429) frequency per provider. Sorted by total requests descending so the busiest providers appear first. Useful for identifying which providers are handling the most load and which are hitting limits.',
  statsOverview: 'Aggregated usage statistics across all providers. Shows total requests, error rate, 429 count, token usage, and average/peak latency for the selected time period.',

  // ── Navbar ──
  pinnedModel: 'A model is currently pinned via Routing Override. All requests will be routed to this model only. Click to go to Settings and clear the override.',
  darkMode: 'Toggle between light and dark color schemes. Your preference is saved in localStorage.',
} as const
