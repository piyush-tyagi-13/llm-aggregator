# Models Page Architecture — Free-First Design

> **Goal**: Architect the system and workflow for how users interact with models in llm-apipool, with "Free" as the core concept. This is a data-flow and component architecture, not a UI redesign.

---

## 1. Core Insight: Two Parallel Systems That Must Merge

Currently the project has **two free-model systems** that don't talk to each other:

| System | Source | What It Knows | Used For |
|--------|--------|---------------|----------|
| **A: Main DB** (`models` table, `is_free` column) | Provider `/v1/models` + `free_detection.py` | All models seen via any key, with a heuristic free flag | Model listing, routing, tier system |
| **B: FreeLLMAPI** (`free_models.db`) | Curated catalog from `freellmapi.co` + user custom entries | Verified free models, independent of user's keys | "FREE" badge, green dot, Free Models Manager |

**Problem**: They disagree (different detection strategies), they're not unified in the UI, and the user has to understand both to know what they can actually use.

**Solution**: System B (FreeLLMAPI) becomes the **primary** free model source. System A's `is_free` is the **fallback** for models not in the catalog.

---

## 2. User Mental Model — Three Questions

The Models page should answer exactly three questions, in priority order:

```
┌──────────────────────────────────────────────────┐
│  Q1: "What free models can I use RIGHT NOW?"      │
│  → Models that are free AND I have a key for      │
│  → The default view, scoped to user's keys        │
├──────────────────────────────────────────────────┤
│  Q2: "What free models could I unlock?"           │
│  → Free models I COULD use if I add a key         │
│  → Shows which key is needed                      │
├──────────────────────────────────────────────────┤
│  Q3: "How are my models doing?"                   │
│  → Cooldowns, rate limits, health                 │
│  → Per-model and per-provider status              │
└──────────────────────────────────────────────────┘
```

Everything else (tier editing, effort config, routing override) is **advanced/power-user** and should be visually separated.

---

## 3. Data Flow — Unifying the Two Systems

### Current Broken Flow
```
User adds key → sync_provider_models() → 
  normalize_model() uses free_detection.py → is_free in main DB ←→ FreeLLMAPI catalog (disconnected)
                                                       ↑
                                              User sees firehose of ALL models
```

### Proposed Flow
```
User adds key → sync_provider_models() →
  normalize_model() detects model → queries FreeLLMAPI catalog for verified-free status →
    Sets is_free = TRUE if in FreeLLMAPI catalog
    Falls back to free_detection.py heuristics if NOT in catalog
  → Links key to model via key_model_access table
  → User sees only models that match their keys
```

### Backend Changes Needed

**`GET /api/models`** — new filter logic:

```
GET /api/models?available_only=true&free_only=true
  → JOIN models with key_model_access WHERE key_id IN user's active keys
  → AND models.is_free = 1 OR models.platform IN FreeLLMAPI providers
  → Returns: [{model, key_id, key_preview, free_verified_by, ...}]
```

**`GET /api/models/available`** — NEW endpoint returning:

```json
{
  "ready": [
    {"model": "llama-3.3-70b", "provider": "groq", "key": "gsk_****abcd", 
     "free_verified": "freellmapi", "health": "healthy", "tier": 2}
  ],
  "locked": [
    {"model": "claude-3-haiku", "provider": "anthropic", 
     "key_needed": true, "key_hint": "Add an Anthropic key to unlock"}
  ]
}
```

---

## 4. Component Tree — Clean Separation

Instead of a monolithic 1466-line ModelsPage, we split into focused components:

```
ModelsPage (orchestrator — ~100 lines)
├── AvailableModelsPanel              ← Q1: the core view
│   ├── ProviderGroup[groq, cerebras,...]
│   │   ├── FreeModelRow[llama-3.3-70b, ...]
│   │   │   ├── StatusDot (healthy/warning/error)
│   │   │   ├── ModelName + FreeBadge
│   │   │   ├── QualityScore (intelligence/speed/reliability compact)
│   │   │   ├── KeyUsageBar (requests today / limit)
│   │   │   └── ActionButtons (enable/disable, config, pin)
│   │   └── ProviderHealthSummary (rate limits, cooldowns)
│   └── EmptyState ("Add a key to see available models")
│
├── UnlockableModelsPanel             ← Q2: what you're missing
│   └── LockedProviderCard[anthropic, openai, ...]
│       ├── ProviderIcon + Name
│       └── FreeModelPreview (top 5 models available if key added)
│
├── ModelHealthPanel                  ← Q3: status
│   ├── CooldownTable
│   ├── RateLimitWarnings
│   └── CircuitBreakerStatus
│
└── AdvancedSettings (collapsible)    ← power user
    ├── TierEditor (modal or inline)
    ├── EffortConfig (modal)
    └── RoutingOverride
```

---

## 5. Workflows

### Workflow A: Adding a Key → Seeing Free Models
```
1. User pastes key "gsk_xxx..." on Keys page
2. System auto-detects provider → Groq
3. System syncs Groq models → discovers llama-3.3-70b, deepseek-r1, etc.
4. System cross-references FreeLLMAPI catalog → marks verified free
5. User navigates to Models page
6. AvailableModelsPanel shows: "Groq — 15 free models available"
7. User sees green dots next to FreeLLMAPI-verified models
8. User clicks "enable all" → bulk enables Groq free models
```

### Workflow B: Browsing Free Models by Quality
```
1. User opens Models page → default view shows "Available Free Models"
2. Sorted by intelligence_score descending
3. User sees: "Llama 3.3 70B (Groq) — Score: 92/100"
4. User toggles "show cooldowns" → sees llama is cold (0s)
5. User expands provider group → sees 15 Groq models ranked
6. User clicks "pin" on best model → routing locked to that model
```

### Workflow C: Discovering What's Missing
```
1. User scrolls to "Unlockable Models" section
2. Sees: "Anthropic — 8 free models (add key to unlock)"
3. Sees: "OpenAI — 6 free models (add key to unlock)"
4. User clicks "Add Anthropic key" → redirected to Keys page with Anthropic pre-selected
```

### Workflow D: Diagnosing Problems
```
1. User's request failed with "all_keys_exhausted"
2. User goes to Models page → ModelHealthPanel
3. Sees: "llama-3.3-70b (Groq) — cooldown 45s remaining"
4. Sees: "deepseek-r1 (Groq) — rate limited, retry in 120s"
5. User knows to wait or add another key
```

---

## 6. Unified Free Model Detection

Currently there are **4 sources of truth** for "is this model free?":

| Source | Location | Purpose |
|--------|----------|---------|
| `providers.json:free_tier` | Config file | NOT used by detection code — stale |
| `free_detection.py:PROVIDER_RULES` | Core engine | Heuristic fallback (strategy 3) |
| `free_models_catalog.json` | Config file | Static catalog fallback (strategy 4) |
| FreeLLMAPI catalog DB | freellmapi_catalog.py | Authoritative verified list |

**Proposed unified resolution order:**
```
1. FreeLLMAPI catalog (most authoritative)
2. free_detection.py PROVIDER_RULES + patterns
3. free_models_catalog.json (static fallback)
4. providers.json free_tier (legacy, deprecate)
```

When the FreeLLMAPI sync adds a model, it should ALSO upsert it into the main `models` table with `is_free=TRUE`. This makes the FreeLLMAPI catalog the **source of truth** for both systems.

---

## 7. API Surface — New & Changed

### New Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /api/models/available` | Models user can use (keyed + free) |
| `GET /api/models/unlockable` | Models user could use with more keys |
| `GET /api/models/health` | Cooldowns, rate limits, circuit breaker per model |

### Changed Endpoints
| Endpoint | Change |
|----------|--------|
| `GET /api/models` | Add `available_only=true` filter, return `key_id` and `key_preview` per model |
| `GET /api/models?free_only=true` | Now uses unified FreeLLMAPI catalog first, falls back to detection |
| `POST /api/freemodels/sync` | Also upserts into main `models` table with `is_free=TRUE` |

---

## 8. Implementation Phases

### Phase 1: Data Unification
- [ ] `POST /api/freemodels/sync` writes to both FreeLLMAPI DB AND main `models` table
- [ ] `GET /api/models/available` — new endpoint, joins key_model_access + models + FreeLLMAPI
- [ ] `GET /api/models/unlockable` — new endpoint, cross-references FreeLLMAPI with user's keys

### Phase 2: Component Restructure
- [ ] Extract `AvailableModelsPanel` from current ModelsPage
- [ ] Extract `UnlockableModelsPanel`
- [ ] Extract `ModelHealthPanel`
- [ ] Extract `AdvancedSettings` (collapsible)
- [ ] ModelsPage becomes thin orchestrator (~100 lines)

### Phase 3: Workflow Polish
- [ ] "Add key" flow from locked model card → redirects to Keys page with provider hint
- [ ] Bulk enable/disable for provider groups
- [ ] Per-model health indicator (green/yellow/red)
- [ ] Quality-sorted default view

---

## 9. Key Metrics to Track

| Metric | What It Tells Us |
|--------|------------------|
| "Free models available" count | How useful is the pool to the user |
| "Locked models" count | How much value is locked behind missing keys |
| Cooldown rate per model | Which models hit rate limits most |
| Free vs paid usage ratio | Is the system serving its purpose |
