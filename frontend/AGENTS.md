# FRONTEND KNOWLEDGE BASE

**Stack:** React 18 + Vite + TypeScript + Tailwind CSS + Radix UI + Vitest
**Purpose:** Dashboard UI for llm-apipool — key management, model table, analytics, settings, and effort configuration.

## OVERVIEW

Single-page React app with 5 pages (Keys, Playground, Models, Analytics, Settings) routed via `react-router-dom`.
Talks exclusively to the Python FastAPI backend at `http://localhost:8000` via Axios.
All LLM interaction goes through the proxy; this UI never calls external APIs directly.

## STRUCTURE

```
frontend/
├── src/
│   ├── main.tsx              # React root (QueryClientProvider + App)
│   ├── App.tsx               # BrowserRouter, Navbar, 5 Routes
│   ├── index.css             # Tailwind imports
│   ├── vite-env.d.ts         # Vite env types
│   ├── lib/
│   │   └── api.ts            # Axios instance, apiFetch helper
│   ├── components/
│   │   └── navbar.tsx        # Top navigation bar
│   ├── pages/
│   │   ├── KeysPage.tsx      # Key CRUD: list, import, deactivate, per-key model editor
│   │   ├── PlaygroundPage.tsx# Live chat test console
│   │   ├── ModelsPage.tsx    # Model table with per-model effort sliders + ⚡ Effort all… dropdown
│   │   ├── AnalyticsPage.tsx # Usage analytics, provider breakdown
│   │   └── SettingsPage.tsx  # Routing strategy, sticky, handoff, fallback, affinity, tier settings
│   └── test/
│       ├── setup.ts          # @testing-library/jest-dom import
│       └── App.test.tsx      # 6 smoke tests (routing, component render)
├── index.html                # Vite entry point
├── vite.config.ts            # Proxy: /api/* and /v1/* → localhost:8000
├── vitest.config.ts          # Vitest config (jsdom, @/ alias, setup)
├── tailwind.config.js        # Theme tokens (extend here, not inline)
└── tsconfig.json             # Strict mode; excludes src/test/ from production tsc
```

## WHERE TO LOOK

| Task | File | Notes |
|------|------|-------|
| App shell + routing | `App.tsx` | BrowserRouter, Navbar, 5 Routes; redirect / → /keys |
| Key list / import / deactivate | `KeysPage.tsx` | Axios calls to `/api/keys`; per-key model editor column |
| Model table + effort | `ModelsPage.tsx` | Table from TanStack Table; per-model effort slider; ⚡ Effort all… dropdown |
| Live model testing | `PlaygroundPage.tsx` | Test prompts via `/v1/chat/completions` |
| Analytics dashboard | `AnalyticsPage.tsx` | Charts/data for key usage, provider breakdown |
| Settings | `SettingsPage.tsx` | Fields for strategy, sticky, handoff, fallback, affinity, tiers; transient save feedback |
| API client | `lib/api.ts` | Axios with `import.meta.env.VITE_API_BASE`, JSON body serialization |
| Navbar | `components/navbar.tsx` | Navigation links with active route highlighting |
| Vitest tests | `src/test/App.test.tsx` | 6 tests: renders navbar, verifies route→component mapping |
| Backend proxy config | `vite.config.ts` | Dev-only; production must set `VITE_API_BASE` env var |
| Vitest config | `vitest.config.ts` | jsdom environment, @ alias, setup file |
| Shared UI primitives | Radix UI imports | Dialog, Select, Switch, DropdownMenu — import from `@radix-ui/react-*` |
| Styling tokens | `tailwind.config.js` | Extend theme here; avoid arbitrary `[]` values in JSX |

## CONVENTIONS

- **API calls:** Axios via `lib/api.ts` `apiFetch()` wrapper — all REST endpoints (`/api/*` and `/v1/*`).
- **State:** `@tanstack/react-query` for server state (useQuery, useMutation); component-local `useState` for UI state.
- **Types:** Define request/response shapes inline in the component file that owns the call; no separate `types/` directory yet.
- **Tailwind:** Utility classes in JSX; extract to a helper when a class list exceeds ~6 tokens. Never use `style={{}}` for values that have a Tailwind equivalent.
- **Radix UI:** Use unstyled Radix primitives and apply Tailwind classes directly — do not import Radix themes.
- **Error handling:** Surface API errors in-component via local error state rendered near the triggering control. No `alert()` or `console.error()` as sole feedback.
- **Tests:** Vitest + React Testing Library. Mock page components in route tests to avoid API calls.
- **Backend contract:** Key objects carry `provider`, `key_preview`, `capabilities[]`, `model`, and `is_active`. Proxy model alias is `LLM-Apipool`.

## ANTI-PATTERNS

- Do not hardcode `http://localhost:8000` — use `import.meta.env.VITE_API_BASE` in production, Vite proxy in dev.
- Do not import from `tailwind.config.ts` at runtime — tokens are compile-time only.
- Do not use `useRef<T>(null)` without null in the type union — React 18 strict types require `useRef<T | null>(null)` for mutable refs.
- No global store — keep state in react-query cache or component-local state.
