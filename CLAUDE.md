# OgresVTT — Claude Code Context

## Developer Environment

- **OS**: Windows
- **Install Clojure**: Use the MSI installer from https://github.com/clojure/brew-install/releases/latest
- **Install Java**: Eclipse Temurin JDK 21 from https://adoptium.net/
- **Install Node.js**: https://nodejs.org/ (required for shadow-cljs)
- **Install dependencies**: `npm install`
- **Run server**: `clojure -M -m ogres.server.core 5000`
- **Run frontend**: `npx shadow-cljs watch app`

## Project Overview

**OgresVTT** is a free, open-source virtual tabletop (VTT) for running tabletop RPG sessions online. It runs entirely in the browser — no sign-ups, no ads.

**Stack:**
- Frontend: ClojureScript + UIX (React) + DataScript + shadow-cljs
- Backend: Clojure + Pedestal + Jetty + WebSockets
- Persistence: IndexedDB (client) + in-memory atom (server)
- Realtime sync: WebSocket rooms with Transit/MessagePack encoding

## Active Branch

`claude/ai-dungeon-master-prd-xJuMc`

All current work lives on this branch. Never push to `main` without explicit instruction.

## Current Work: AI Dungeon Master

We are building an AI Dungeon Master feature. The full spec is in `prd.md`.

### What the AI DM does
- Reads live game state (tokens, initiative, HP) from DataScript
- Calls an LLM backend (Ollama or Grok) using the OpenAI-compatible **tool calling** API
- The LLM invokes typed tools (`spawn_token`, `move_token`, `update_hp`, etc.) to control the board
- Narration text is broadcast to all players via the existing WebSocket room
- Host can run in **confirm mode** (approve each action) or **auto mode** (fully autonomous)

### LLM Backends
| Backend | How | Notes |
|---------|-----|-------|
| Ollama | `POST http://localhost:11434/api/chat` | Local, private, free. Use tool-capable models: `llama3.1`, `mistral-nemo`, `qwen2.5`. Requires `OLLAMA_ORIGINS=*` |
| Grok (xAI) | `POST https://api.x.ai/v1/chat/completions` | Cloud, higher quality. Models: `grok-3`, `grok-3-mini`. API key stored in `localStorage` only — never sent to OgresVTT server |

### LangGraph Sidecar (optional)
An optional Python/FastAPI sidecar (`ai_dm/`) that runs a `langgraph.StateGraph` for multi-step agentic reasoning before emitting tool calls. Graph nodes: `assess_situation → plan_actions → execute_tools → validate → reflect_retry`. The ClojureScript client calls `POST /dm/turn` and receives a validated tool call list.

Toggle between **Direct** (single LLM call, low latency) and **LangGraph** (multi-step planning, higher quality) in the AI DM config panel.

### New files planned
```
src/main/ogres/app/
├── ai/
│   ├── core.cljs            # AI DM state machine + timer loop
│   ├── prompt.cljs          # Game state → prompt serialization
│   ├── tools.cljs           # OpenAI tool definitions
│   ├── tool_dispatch.cljs   # tool_call name → OgresVTT event
│   ├── backends/
│   │   ├── ollama.cljs
│   │   ├── grok.cljs
│   │   └── langgraph.cljs
│   └── actions.cljs
├── component/
│   ├── panel_ai_dm.cljs     # Config panel
│   └── panel_narration.cljs # Narration chat panel

ai_dm/                       # LangGraph sidecar (Python)
├── main.py
├── graph.py
├── nodes/
├── tools.py
├── backends/
├── state.py
├── Dockerfile
└── requirements.txt
```

### DataScript schema additions
```clojure
:ai-dm/enabled      :ai-dm/backend    :ai-dm/endpoint
:ai-dm/model        :ai-dm/scenario   :ai-dm/auto-approve
:ai-dm/interval-ms
:narration/text     :narration/timestamp  :narration/source
```

## Logging

Server logs to `logs/ogres.log` (relative to process working directory).
Configured via `src/main/simplelogger.properties` (SLF4J Simple).
The `logs/` directory is git-ignored.

Key log events:
- `:server/start` — on `-main`
- `:room/created` — host opens or auto-creates a room
- `:session/joined` — player joins a room
- `:session/left` — player disconnects
- `:room/destroyed` — host disconnects, room torn down
- `:ws/error` — WebSocket error with connection UUID

## Key Files

| File | Purpose |
|------|---------|
| `src/main/ogres/server/core.clj` | WebSocket server, room management, all log calls |
| `src/main/ogres/app/events.cljs` | All client-side game state mutations |
| `src/main/ogres/app/provider/state.cljs` | DataScript schema |
| `src/main/ogres/app/provider/session.cljs` | WebSocket multiplayer sync |
| `src/main/simplelogger.properties` | SLF4J file logging config |
| `prd.md` | Full AI DM product requirements document |
| `deps.edn` | Clojure dependencies |
| `shadow-cljs.edn` | ClojureScript build config |
