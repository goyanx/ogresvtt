# OgresVTT — Developer Context

## Developer Environment

- **OS**: Windows
- **Install Clojure** (PowerShell as Administrator):
  ```powershell
  iwr -useb download.clojure.org/install/win-install-1.11.1.1165.ps1 | iex
  ```
  Or via Scoop: `scoop install clj-deps`
- **Install Java**: Eclipse Temurin JDK 21
- **Install Node.js**: https://nodejs.org/
- **Install frontend deps**: `npm install`
- **Run multiplayer server**: `clojure -M -m ogres.server.core 5000`
- **Run frontend**: `npx shadow-cljs watch app`
- **Run AI DM sidecar**:
  ```powershell
  cd ai_dm
  pip install -r requirements.txt
  uvicorn ai_dm.main:app --port 8765 --reload
  ```

## Project Overview

**OgresVTT** is a browser-first VTT.

**Stack**
- Frontend: ClojureScript + UIX + DataScript + shadow-cljs
- Multiplayer backend: Clojure + Pedestal + Jetty + WebSockets
- AI sidecar: Python + FastAPI + LangGraph
- Persistence:
  - Browser: IndexedDB + DataScript state
  - Sidecar: SQLite (`ai_dm/data/dm.sqlite` by default)

## AI DM Status

AI DM supports:
- Direct backend mode (Ollama/Grok)
- LangGraph sidecar mode (multi-step)
- English-only narration constraints
- Tool-driven board actions
- Optional Kokoro TTS

LangGraph flow currently:
- `assess_situation -> plan_actions -> validate -> reflect_retry`

## Sidecar Data Layer

SQLite schema domains:
- `comp_*` (RAG compendium + FTS)
- `camp_*` (characters/stats/resources/inventory)
- `comb_*` (combat events)
- `map_*` (map configs, positions)
- `trg_*` (location/event triggers)
- `npc_*` (traits, opinions, relationships, memory)
- `dm_rulings` (continuity rulings)

Admin UI and API:
- `GET /dm-admin`
- `GET /dm-admin/api/tables`
- `GET /dm-admin/api/table/{name}`
- `POST /dm-admin/api/query`
- `GET /dm-admin/api/maps`
- `POST /dm-admin/api/maps/upsert`

## Key Files

| File | Purpose |
|------|---------|
| `src/main/ogres/server/core.clj` | WebSocket server and room lifecycle |
| `src/main/ogres/app/events.cljs` | Client-side event mutations |
| `src/main/ogres/app/provider/state.cljs` | DataScript schema |
| `src/main/ogres/app/ai/tool_dispatch.cljs` | AI tool-call to client event dispatch |
| `ai_dm/main.py` | FastAPI sidecar endpoints and admin routes |
| `ai_dm/graph.py` | LangGraph graph wiring |
| `ai_dm/nodes/*.py` | Assess/plan/validate/reflect nodes |
| `ai_dm/tools.py` | Sidecar tool definitions |
| `ai_dm/query_executor.py` | Sidecar query tool execution router |
| `ai_dm/db.py` | SQLite schema/init/migrations |
| `ai_dm/ingest_compendium.py` | RAG ingestion utility |
| `docs/AI_DM_DATA_ADMIN.md` | Data admin/runbook |
| `prd.md` | Product requirements and backlog |

## Logging

- App server logs: `logs/ogres.log`
- Sidecar logs: `logs/ai_dm.log`

The `logs/` directory is git-ignored.
