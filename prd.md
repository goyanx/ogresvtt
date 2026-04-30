# PRD: AI Dungeon Master + LangGraph + RAG for OgresVTT

## Overview

OgresVTT now includes an AI Dungeon Master system with three runtime modes:
- Direct Ollama (single-call, local)
- Direct Grok/xAI (single-call, cloud)
- LangGraph sidecar (multi-step planning with SQLite-backed memory and RAG)

The host can run AI-assisted encounters where narration, tactical actions, map changes, and campaign continuity are coordinated through tool calls and validated against game/runtime state.

## Current Product Goals

1. Give hosts a reliable AI DM that can narrate and control encounter flow.
2. Keep board actions deterministic by validating tool arguments before client dispatch.
3. Persist campaign memory in SQLite so narrative and rulings remain consistent.
4. Support DnD manual ingestion for rules/lore retrieval during planning.
5. Provide a browser admin surface for campaign/RAG data operations.

## In Scope (Implemented)

- AI DM host panel and narration panel integration in client.
- LangGraph sidecar endpoint `POST /dm/turn`.
- Sidecar graph loop:
  - `assess_situation -> plan_actions -> validate -> reflect_retry`
- Internal query-tool execution router in sidecar (`execute_query_tool`).
- English-only DM response constraint in planning/system prompt path.
- SQLite schema bootstrap and migrations at sidecar startup.
- RAG ingestion utility for manual text/markdown compendium sources.
- Sidecar admin UI/API at `/dm-admin` for inspection and SQL operations.
- Map scene configuration persistence and `show_map` action tool wiring to client.

## Out of Scope (Current)

- Full multi-agent decomposition (coordinator + specialist sub-agents) is not yet implemented.
- Automatic OCR/PDF pipeline for manual ingestion (manual pre-processing is expected).
- Fine-tuned DM model training.

## Runtime Architecture

### Client (ClojureScript)

- Builds game-state context and conversation history.
- Calls either direct backend or sidecar.
- Dispatches validated action tools to existing app events.
- Handles `show_map` to switch/render configured map scenes.

Key files:
- `src/main/ogres/app/ai/tools.cljs`
- `src/main/ogres/app/ai/tool_dispatch.cljs`
- `src/main/ogres/app/events.cljs`
- `src/main/ogres/app/provider/state.cljs`

### Sidecar (Python/FastAPI + LangGraph)

- Receives `dm_turn` requests.
- Runs graph nodes for assess/plan/validate/reflect.
- Executes internal query tools against SQLite for RAG and campaign memory.
- Returns browser-dispatchable action tools plus narration.
- Exposes admin pages/APIs.

Key files:
- `ai_dm/main.py`
- `ai_dm/graph.py`
- `ai_dm/nodes/plan.py`
- `ai_dm/query_executor.py`
- `ai_dm/tools.py`
- `ai_dm/db.py`
- `ai_dm/static/dm_admin.html`
- `ai_dm/ingest_compendium.py`

## Data Model (SQLite)

Database path defaults to:
- `ai_dm/data/dm.sqlite`

Domains:
- Compendium/RAG: `comp_*` + `comp_chunks_fts`
- Campaign state: `camp_*`
- Combat history: `comb_*`
- Map config and positioning: `map_*`
- Triggers and firings: `trg_*`
- NPC social state/memory: `npc_*`
- DM continuity rulings: `dm_rulings`

This schema is designed to hold:
- Character sheets/resources/conditions/inventory
- Combat events and initiative
- NPC traits/opinions/relationships/memory
- Region- and map-based trigger definitions
- Map file path/file name and render configuration for DM-driven map switching
- Rules/lore/monster references for retrieval

## RAG Workflow

1. Prepare handpicked DnD manual excerpts as `.md` or `.txt`.
2. Ingest with `python -m ai_dm.ingest_compendium ...`.
3. Sidecar query tools (`retrieve_rules`, `get_monster_stats`) fetch context during planning.
4. Retrieved context informs narration and action planning, then validated before dispatch.

## Admin UX

Admin endpoint:
- `http://localhost:8765/dm-admin`

Capabilities:
- table browser
- map config management
- SQL query console (read-only unless explicitly enabled)

Docs:
- `docs/AI_DM_DATA_ADMIN.md`

## Acceptance Criteria (Current Build)

- AI DM can run in direct and sidecar modes.
- Sidecar reaches Ollama/Grok and returns tool-based turn outputs.
- DM narration and board actions are visible in client.
- DM can request map display through `show_map`.
- SQLite initializes automatically and stores campaign + RAG data.
- Admin UI is reachable and can inspect/update map config rows.

## Risks and Constraints

- Sidecar and model endpoint mismatch can still cause 404s if endpoint/model settings drift.
- RAG quality depends on ingestion chunk quality and source curation.
- Single query-executor routing is flexible but can become crowded as tool count grows.

## TODO Backlog

- [ ] Multi-agent orchestration:
  - Add a coordinator and specialist agents/subgraphs:
    - Rules/RAG agent
    - Combat simulation agent
    - World-state/trigger agent
    - Narrative director agent
  - Keep existing `execute_query_tool` as fallback compatibility layer during transition.
- [ ] Add structured evaluation harness for narrative consistency and rule citation quality.
- [ ] Add migration/version dashboard in `/dm-admin`.
