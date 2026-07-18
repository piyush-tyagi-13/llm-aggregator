#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── Colors ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; CYAN='\033[0;36m'; AMBER='\033[0;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[start]${NC} $*"; }
ok()    { echo -e "${GREEN}[  ok]${NC} $*"; }
warn()  { echo -e "${AMBER}[warn]${NC} $*"; }

cleanup() {
  echo
  warn "Shutting down..."
  # Stop llm-apipool
  if [ -n "${API_PID:-}" ]; then
    kill "$API_PID" 2>/dev/null && wait "$API_PID" 2>/dev/null
    ok "llm-apipool stopped"
  fi
  # Stop FreeLLMAPI
  (cd /home/gfardad/freellmapi && docker compose --project-name freellmapi down 2>/dev/null)
  ok "FreeLLMAPI stopped"
  # Stop frontend dev server
  if [ -n "${FE_PID:-}" ]; then
    kill "$FE_PID" 2>/dev/null && wait "$FE_PID" 2>/dev/null
    ok "Frontend dev server stopped"
  fi
  ok "Cleanup complete"
  exit 0
}
trap cleanup SIGINT SIGTERM

# ── 0. Kill any leftover processes ──────────────────────────────────
info "Cleaning up old processes..."
lsof -ti:8000 2>/dev/null | xargs kill 2>/dev/null || true
# Note: port 7000 is Odysseus (separate project) — leave it alone

# ── 1. FreeLLMAPI (Docker) ─────────────────────────────────────────
info "Starting FreeLLMAPI (Docker)..."
cd /home/gfardad/freellmapi
docker compose --project-name freellmapi up -d 2>&1 | sed 's/^/  /'
cd "$ROOT"
ok "FreeLLMAPI running at http://localhost:3001"

# ── 2. llm-apipool proxy ────────────────────────────────────────────
info "Starting llm-apipool proxy..."
llm-apipool proxy --port 8000 --host 127.0.0.1 &
API_PID=$!
sleep 2
if kill -0 "$API_PID" 2>/dev/null; then
  ok "llm-apipool running at http://localhost:8000"
else
  warn "llm-apipool failed to start — check the logs above"
fi

# ── 3. Frontend dev server (optional, hot-reload) ──────────────────
if [ "${1:-}" = "--dev" ] || [ "${1:-}" = "-d" ]; then
  info "Starting frontend dev server (Vite)..."
  cd frontend
  npm run dev &
  FE_PID=$!
  cd "$ROOT"
  sleep 2
  if kill -0 "$FE_PID" 2>/dev/null; then
    ok "Frontend dev server at http://localhost:5173"
  else
    warn "Frontend dev server failed to start"
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────
echo
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  All services running!${NC}"
echo -e "${GREEN}  API proxy:   http://localhost:8000  (llm-apipool)${NC}"
echo -e "${GREEN}  Dashboard:   http://localhost:8000  (built frontend)${NC}"
if [ -n "${FE_PID:-}" ]; then
  echo -e "${GREEN}  Dev server:  http://localhost:5173  (Vite, hot-reload)${NC}"
fi
echo -e "${GREEN}  FreeLLMAPI:  http://localhost:3001${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
echo -e "${AMBER}  Press Ctrl+C to stop all services${NC}"
echo

# Wait for any child to exit
wait
