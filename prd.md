# PRD: AI Dungeon Master for OgresVTT

## Overview

Add an AI Dungeon Master (AI DM) feature to OgresVTT that uses a locally-hosted LLM via **Ollama** or the **Grok API** (xAI) to autonomously narrate the adventure, manage NPCs/monsters, and control tokens on the board in real time.

The AI DM acts as a host-side agent: it reads game state from the DataScript database, decides what should happen next, and dispatches the same events a human DM would — placing tokens, moving them, rolling initiative, and updating health — while narrating the scene in a sidebar chat.

---

## Problem Statement

Running a TTRPG session requires a dedicated human DM who must juggle narrative, rules, and tactical map management simultaneously. This is a significant barrier for groups who want to play but lack an experienced DM, or who want to practice encounters solo. OgresVTT's lightweight architecture and clean event system make it a strong foundation for embedding an AI DM that is approachable and locally-runnable (no cloud dependency required).

---

## Goals

1. **AI-controlled tokens** — The AI DM can spawn, move, and remove tokens on the active scene grid without human intervention.
2. **Narrative output** — The AI DM produces natural-language narration displayed in a dedicated panel visible to all players.
3. **LLM flexibility** — Support two backends: **Ollama** (local, privacy-first) and **Grok** (xAI cloud API), switchable via settings.
4. **Host authority** — Only the session host can enable/configure the AI DM; players receive its actions like any other host action.
5. **Interruptible** — The human host can pause, override, or take over from the AI DM at any time.

---

## Non-Goals

- Automated rules adjudication (spell lookup, condition tracking) — out of scope for v1.
- AI-controlled player characters (movement on player request is in scope; autonomous AI control of player tokens is not).
- Fine-tuned or custom models — use off-the-shelf instruction-following models.

---

## User Stories

| ID | As a… | I want to… | So that… |
|----|-------|------------|----------|
| US-1 | Host | Enable an AI DM for my session | I can run an encounter without preparing everything manually |
| US-2 | Host | Choose between Ollama and Grok backends | I can pick local privacy vs. cloud quality |
| US-3 | Host | Provide a campaign brief / scenario prompt | The AI DM understands the tone and setting |
| US-4 | Host | See what the AI DM is about to do before it acts | I can approve or reject actions |
| US-5 | Host | Pause the AI DM mid-encounter | I can step in when needed |
| US-6 | Player | See narration from the AI DM in a chat panel | I stay immersed in the story |
| US-7 | Player | See tokens move on the board as the AI DM acts | The encounter feels alive |
| US-8 | Host | Set the AI DM to auto-approve mode | Fully automated sessions run without manual confirmation |
| US-9 | Player | Type "I move north" and see my token move | My character's movement is reflected on the board instantly |
| US-10 | Host | Enable voice narration | The DM reads narration aloud for immersive play |
| US-11 | Host | Enable terrain vision detection | The DM knows whether tokens are on a wall, road, water, etc. |
| US-12 | Player | Ask the DM a question in the narration box | I get an in-character response without breaking immersion |

---

## Feature Specification

### 1. AI DM Configuration Panel

A new "AI DM" section in the host toolbar (beside the existing scene/initiative panels).

**Fields:**
- **Enable AI DM** — toggle (default: off)
- **Backend** — select: `Ollama (local, direct)` | `Grok (xAI, direct)` | `LangGraph sidecar (multi-step)`
- **Ollama endpoint** — text field, default `http://localhost:11434` (shown for Ollama backend)
- **Sidecar URL** — text field, default `http://localhost:8765` (shown for LangGraph backend)
- **Grok API key** — password field (stored in `localStorage`, never sent to OgresVTT server; shown for Grok backend)
- **Model** — text field (e.g. `qwen3:14b`, `grok-3-mini`)
- **Scenario prompt** — textarea for campaign context / DM instructions
- **Auto-approve actions** — checkbox (default: on)
- **Voice narration** — checkbox; enables Kokoro TTS via the LangGraph sidecar `/dm/speak` endpoint
- **Voice** — select: George (British male) ★, Lewis, Adam, Echo, Sky, Nova, Emma
- **Speed** — range slider 0.7×–1.3×
- **Terrain vision** — checkbox; enables per-token terrain detection via a vision model
- **Vision model** — text field, default `qwen3-vl:8b` (shown when terrain vision enabled)
- **Turn interval** — slider: 5–60 seconds (default 15)

### 2. Game State Serialization

Before each AI DM turn, the current game state is serialized into a structured prompt context:

```
SCENE: <scene name>
GRID: <width>x<height>, size <grid-size>px
TOKENS:
  - id: <id>, label: <name>, pos: (<x>,<y>), hp: <current>/<max>, flags: <flags>
INITIATIVE ORDER: <ordered list with current-turn marker>
ROUND: <round number>
```

This context is prepended to the system prompt so the model always has a grounded view of the board.

### 3. LLM Tool Calling Interface

Rather than prompting the model to return a freeform JSON blob, the AI DM uses the **OpenAI-compatible `tools` API** supported by both Ollama (tool-capable models: `llama3.1`, `mistral-nemo`, `qwen2.5`) and Grok. Each action in the action protocol is registered as a callable tool with a strict JSON Schema definition. The model selects and invokes tools natively — no brittle prompt-based JSON parsing required.

#### Tool Definitions (sent with every request)

Complete tool set — **bold** entries were added after initial design:

```json
[
  {
    "type": "function",
    "function": {
      "name": "narrate",
      "description": "Emit narration text visible to all players. Always call this once per turn.",
      "parameters": {
        "type": "object",
        "properties": {
          "text": { "type": "string", "maxLength": 300 }
        },
        "required": ["text"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "move_token",
      "description": "Move an existing NPC/monster token to a new grid position.",
      "parameters": {
        "type": "object",
        "properties": {
          "token_id": { "type": "string" },
          "x":        { "type": "integer", "description": "Pixel x, snapped to grid" },
          "y":        { "type": "integer", "description": "Pixel y, snapped to grid" }
        },
        "required": ["token_id", "x", "y"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "spawn_token",
      "description": "Place a new NPC or monster token on the scene.",
      "parameters": {
        "type": "object",
        "properties": {
          "label":  { "type": "string" },
          "x":      { "type": "integer" },
          "y":      { "type": "integer" },
          "hp":     { "type": "integer", "description": "Starting hit points" },
          "color":  { "type": "string",  "description": "Hex color string, e.g. #e05c00" }
        },
        "required": ["label", "x", "y"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "remove_token",
      "description": "Remove a token from the scene (e.g. defeated creature).",
      "parameters": {
        "type": "object",
        "properties": {
          "token_id": { "type": "string" }
        },
        "required": ["token_id"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "update_hp",
      "description": "Set a token's current hit points.",
      "parameters": {
        "type": "object",
        "properties": {
          "token_id": { "type": "string" },
          "hp":       { "type": "integer", "minimum": 0 }
        },
        "required": ["token_id", "hp"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "roll_initiative",
      "description": "Roll initiative for a list of tokens and insert them into the tracker.",
      "parameters": {
        "type": "object",
        "properties": {
          "token_ids": { "type": "array", "items": { "type": "string" } }
        },
        "required": ["token_ids"]
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "advance_turn",
      "description": "Advance the initiative tracker to the next combatant's turn.",
      "parameters": { "type": "object", "properties": {} }
    }
  }
]
```

#### Tool Call Execution Flow

When the LLM responds, its message contains a `tool_calls` array. Each call is dispatched sequentially:

1. **Validate** — confirm every `token_id` argument exists in the current DataScript state.
2. **Dispatch** — map the tool name to the corresponding OgresVTT event and transact.
3. **Result** — append a synthetic `tool` role message back to the conversation (enables multi-turn reasoning in LangGraph mode, see §LangGraph Module).

If the model returns no `tool_calls`, the client sends a follow-up nudge message (`"Please call the narrate tool now."`) and retries once.

**Supported tools:**

| Tool | Triggers OgresVTT Event | Notes |
|------|------------------------|-------|
| `narrate` | `:narration/append` | Always called once per turn |
| `move_token` | `:objects/translate` | NPC/monster tokens only |
| `spawn_token` | `:tokens/create` | |
| `remove_token` | `:tokens/remove` | |
| `update_hp` | `:initiative/update-hp` | |
| `roll_initiative` | `:initiative/roll` | |
| `advance_turn` | `:initiative/advance` | |
| **`move_player_token`** | `:objects/translate` | Player-flagged tokens; use when player explicitly says they move |
| **`list_tokens`** | *(query — no event)* | Returns token list; resolved inside sidecar or in query-feedback loop |

### 4. Action Execution Pipeline

```
AI DM Timer fires  (or LangGraph node signals ready)
      │
      ▼
Serialize game state → build messages array + tool definitions
      │
      ▼
Call LLM backend (Ollama / Grok) with tool_choice: "auto"
      │
      ▼
Receive tool_calls from model response
      │
      ├─ confirm mode? ──► Show "AI DM Action Preview" modal to host
      │                         Host: [Approve] [Edit] [Reject]
      │
      └─ auto mode? ──────► Validate tool args against game state
              │
              ▼
      Dispatch OgresVTT events (same as human DM actions)
              │
              ▼
      DataScript transact → WebSocket broadcast → all clients update
              │
              ▼
      Tool results appended to conversation history (for LangGraph)
              │
              ▼
      Narration broadcast to all via narrate tool result
```

### 5. AI DM Chat / Narration Panel

- A new collapsible panel on the right side of the screen labeled **"DM Narration"**.
- Visible to all connected clients (host and players).
- Each narration entry shows: AI DM avatar icon, narration text, timestamp.
- Host-typed messages also appear here (host can contribute narrative manually).
- Panel is scrollable; last 50 entries retained in session memory.
- Narration is broadcast over the existing WebSocket room so all players see it.

### 6. Terrain Vision Detection

Before each AI DM turn, if **Terrain vision** is enabled and the scene has a background image, the system:

1. Pulls each token's pixel position from DataScript (`:object/point`).
2. Crops a square region of the scene background image (3 × grid-size px by default) centred on each token using an offscreen Canvas.
3. Encodes the crop as a JPEG base64 string and sends it to the Ollama `/api/chat` vision endpoint.
4. Receives a 2–5 word terrain description (e.g. `"stone cave floor"`, `"wooden bridge"`, `"shallow water"`).
5. Detections run concurrently via `Promise.all` and are assembled into a `token-id → terrain-string` map.
6. The map is passed to `prompt/serialize-game-state` which appends `terrain: "..."` to each token's line in the game state prompt.

**Vision prompt:**
```
You are analysing a small crop from a fantasy tabletop RPG map.
Describe ONLY the terrain/surface type in 2-5 words.
Examples: 'stone cave floor', 'dungeon wall', 'underground river', ...
Do NOT mention any tokens, figures, or game pieces.
```

**Recommended vision model:** `qwen3-vl:8b` (runs in ~7 GB VRAM, spatial reasoning, OCR in 32 languages).

Detection is silently skipped if:
- Vision is disabled in config
- No scene background image is loaded
- The scene image is not in the local IndexedDB cache (e.g. remote player)

### 7. Voice Narration

When **Voice narration** is enabled, the DM speaks each narration text aloud via the LangGraph sidecar's `/dm/speak` endpoint, which uses [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) TTS (82M params, CPU-capable).

- Audio clips are queued and played sequentially via the Web Audio API (no overlap).
- Playback uses blob URLs released after the clip ends.
- `voice/stop!` clears the queue (e.g. when host disables AI DM mid-session).

**Available voices:** `bm_george` (British male ★), `bm_lewis`, `am_adam`, `am_echo`, `af_sky`, `af_nova`, `bf_emma`.

### 8. Two-Way Chat & Player Movement

The narration panel input box has two modes depending on whether the AI DM is active:

| AI DM state | Input behaviour |
|-------------|----------------|
| Disabled | Broadcasts plain host narration to all players |
| Enabled | Sends message to the DM as a user turn; DM responds immediately |

When a player message contains a movement intent (`I move north`, `I go east 2 squares`, `run to the door`), the AI DM calls `move_player_token` to shift the player's token on the board and narrates the result.

**Supported directions:** north, south, east, west, northeast, northwest, southeast, southwest.

### 9. LLM Backend Integration

#### Recommended Models

| Role | Model | Notes |
|------|-------|-------|
| AI DM (tool calling) | `qwen3:14b` | Outperforms Qwen2.5-14B; ~11 GB at Q4_K_M |
| Terrain vision | `qwen3-vl:8b` | Spatial reasoning, 32-language OCR; ~7 GB |

Both fit concurrently on 2× 12 GB VRAM (24 GB total).

#### Ollama

- HTTP POST to `{endpoint}/api/chat`
- Request body: OpenAI-compatible chat completions format
- Model: configurable (e.g., `llama3`, `mistral`, `gemma3`)
- Streaming: disabled for v1 (parse complete response)
- Auth: none required (local network)

#### Grok (xAI)

- HTTP POST to `https://api.x.ai/v1/chat/completions`
- Auth: `Authorization: Bearer {api-key}` header
- Model: `grok-3` or `grok-3-mini`
- Request format: OpenAI-compatible
- API key stored client-side only; never relayed through OgresVTT server

#### Shared System Prompt Template

```
You are an AI Dungeon Master running a tabletop RPG encounter in a virtual tabletop application.
Your job is to narrate events and control NPC/monster tokens on the board.

SCENARIO:
{scenario-prompt}

RULES:
- Respond ONLY with valid JSON matching the schema provided.
- Do not move player tokens (they are controlled by players).
- Keep narration under 100 words per turn.
- Position coordinates are in pixels; the grid cell size is {grid-size}px.
- Snap token positions to the nearest grid cell center.
- Do not repeat the same action twice in a row.
- If there is nothing to do, return an empty actions array with brief flavor narration.

CURRENT GAME STATE:
{game-state}

RESPONSE SCHEMA:
{"narration": "string", "actions": [...]}
```

---

## Technical Architecture

### New Files

```
src/main/ogres/app/
├── ai/
│   ├── core.cljs           # AI DM state machine, timer loop, orchestration
│   ├── prompt.cljs         # Game state → prompt serialization (terrain-aware)
│   ├── tools.cljs          # OpenAI tool definitions (mirrors ai_dm/tools.py)
│   ├── tool_dispatch.cljs  # tool_call name → OgresVTT event dispatch
│   ├── vision.cljs         # Terrain detection via Ollama vision model
│   ├── voice.cljs          # Kokoro TTS audio queue + playback
│   └── backends/
│       ├── ollama.cljs     # Ollama HTTP client (direct mode)
│       ├── grok.cljs       # Grok/xAI HTTP client (direct mode)
│       └── langgraph.cljs  # LangGraph sidecar HTTP client
├── component/
│   ├── panel_ai_dm.cljs    # AI DM configuration panel
│   └── panel_narration.cljs # Narration chat + two-way DM chat

ai_dm/                      # LangGraph sidecar (Python, optional)
├── main.py                 # FastAPI app, /dm/turn, /dm/speak, /dm/voices
├── graph.py                # LangGraph StateGraph definition
├── nodes/
│   ├── assess.py           # assess_situation node
│   ├── plan.py             # plan_actions node (with query-feedback loop)
│   ├── execute.py          # execute_tools node
│   ├── validate.py         # validate node
│   └── reflect.py          # reflect_retry node
├── tools.py                # Tool schema definitions (source of truth)
├── tts.py                  # Kokoro TTS synthesis → WAV bytes
├── query_executor.py       # Executes list_tokens queries against game_state text
├── backends/
│   ├── ollama.py           # Ollama async HTTP client
│   └── grok.py             # Grok/xAI async HTTP client
├── state.py                # DMGraphState TypedDict
├── Dockerfile              # Sidecar container image
└── requirements.txt        # langgraph, langchain-core, fastapi, httpx, kokoro, soundfile
```

### DataScript Schema Additions

```clojure
;; AI DM configuration (singleton entity)
:ai-dm/enabled        {:db/cardinality :db.cardinality/one}
:ai-dm/backend        {:db/cardinality :db.cardinality/one}  ;; :ollama | :grok
:ai-dm/endpoint       {:db/cardinality :db.cardinality/one}
:ai-dm/model          {:db/cardinality :db.cardinality/one}
:ai-dm/scenario       {:db/cardinality :db.cardinality/one}
:ai-dm/auto-approve   {:db/cardinality :db.cardinality/one}
:ai-dm/interval-ms    {:db/cardinality :db.cardinality/one}

;; Narration log (many entities)
:narration/text       {:db/cardinality :db.cardinality/one}
:narration/timestamp  {:db/cardinality :db.cardinality/one}
:narration/source     {:db/cardinality :db.cardinality/one}  ;; :ai | :host
```

### New Events (events.cljs additions)

| Event | Payload | Description |
|-------|---------|-------------|
| `:ai-dm/configure` | config map | Update AI DM settings |
| `:ai-dm/toggle` | boolean | Enable/disable AI DM |
| `:ai-dm/run-turn` | — | Trigger an immediate AI DM turn |
| `:ai-dm/apply-actions` | action vector | Execute parsed AI actions |
| `:narration/append` | text, source | Add entry to narration log |

### LangGraph Orchestration Module

LangGraph is an optional orchestration layer that sits between the OgresVTT client and the LLM backend. It models the AI DM's reasoning as a **directed graph of nodes**, enabling multi-step agentic behaviour — planning a full encounter, branching on combat vs. exploration phase, looping for self-correction — that cannot be expressed in a single LLM call.

When enabled, the ClojureScript AI DM core calls the LangGraph sidecar's HTTP API instead of calling Ollama/Grok directly. The sidecar runs the graph, handles all LLM calls internally, and returns a resolved list of validated tool calls to the client.

#### Architecture

```
┌────────────────────────────────────────────────────────┐
│  OgresVTT Browser (ClojureScript)                      │
│                                                        │
│  ai/core.cljs                                          │
│    │  POST /dm/turn  { game_state, scenario, history } │
│    │◄──────────────────────────────────────────────────┤
│    │  { tool_calls: [...], narration: "..." }          │
│    ▼                                                   │
│  ai/actions.cljs → dispatch OgresVTT events            │
└────────────────────────────────────────────────────────┘
             │ HTTP (localhost or configured URL)
             ▼
┌────────────────────────────────────────────────────────┐
│  LangGraph Sidecar  (Python, FastAPI)                  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │  DM Graph  (langgraph.StateGraph)                │  │
│  │                                                  │  │
│  │  ┌──────────┐    ┌──────────┐    ┌───────────┐  │  │
│  │  │ assess_  │───►│ plan_    │───►│ execute_  │  │  │
│  │  │ situation│    │ actions  │    │ tools     │  │  │
│  │  └──────────┘    └──────────┘    └─────┬─────┘  │  │
│  │       ▲                                │        │  │
│  │       │          ┌──────────┐          │        │  │
│  │       └──────────│ reflect  │◄─────────┘        │  │
│  │    (if needed)   │ / retry  │  (on tool error)  │  │
│  │                  └──────────┘                   │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  Backends: Ollama client  |  Grok client               │
└────────────────────────────────────────────────────────┘
```

#### Graph Nodes

| Node | Responsibility |
|------|---------------|
| `assess_situation` | Read serialized game state; classify current phase (`combat`, `exploration`, `narrative`); decide if any action is warranted this turn |
| `plan_actions` | For combat: choose tactically sound moves for each NPC (focus fire, flanking, retreat when low HP). For exploration: decide room reveals, ambient spawns, story beats |
| `execute_tools` | Invoke the tool-calling LLM with the plan as context; collect `tool_calls` from model response |
| `validate` | Check all tool call arguments against game state; remove invalid references; flag corrections needed |
| `reflect_retry` | If validation found errors, send a correction message to the LLM and re-run `execute_tools` (max 2 retries) |

#### Graph Edges & Conditional Routing

```python
graph.add_edge("assess_situation", "plan_actions")
graph.add_edge("plan_actions", "execute_tools")
graph.add_edge("execute_tools", "validate")
graph.add_conditional_edges(
    "validate",
    lambda state: "reflect_retry" if state["errors"] else END,
    {"reflect_retry": "execute_tools", END: END}
)
```

#### State Schema

```python
class DMGraphState(TypedDict):
    game_state:    str          # serialized board state
    scenario:      str          # host-provided scenario prompt
    phase:         str          # "combat" | "exploration" | "narrative"
    plan:          str          # plan_actions output (natural language)
    messages:      list[dict]   # full conversation history (for tool results)
    tool_calls:    list[dict]   # validated, ready-to-dispatch tool calls
    errors:        list[str]    # validation errors from last execute pass
    retry_count:   int
```

#### Sidecar API

```
POST /dm/turn
Body:  { "game_state": "...", "scenario": "...", "history": [...] }
Response: {
  "tool_calls": [
    { "name": "narrate",    "arguments": { "text": "..." } },
    { "name": "move_token", "arguments": { "token_id": "...", "x": 320, "y": 256 } }
  ],
  "phase": "combat",
  "plan_summary": "Orc focuses on weakest player; shaman casts fear."
}

GET  /dm/health    →  { "status": "ok", "backend": "ollama|grok" }
POST /dm/reset     →  clears conversation history
```

#### File Structure (Sidecar)

```
ai_dm/
├── main.py            # FastAPI app, /dm/turn endpoint
├── graph.py           # LangGraph StateGraph definition
├── nodes/
│   ├── assess.py      # assess_situation node
│   ├── plan.py        # plan_actions node
│   ├── execute.py     # execute_tools node (calls Ollama/Grok)
│   ├── validate.py    # validate node
│   └── reflect.py     # reflect_retry node
├── tools.py           # Tool definitions (mirrors JS tool schema)
├── backends/
│   ├── ollama.py      # Ollama async HTTP client
│   └── grok.py        # Grok/xAI async HTTP client
├── state.py           # DMGraphState TypedDict
└── requirements.txt   # langgraph, langchain-core, fastapi, httpx
```

#### Configuration Toggle

The sidecar is opt-in. The AI DM config panel adds a new **"Orchestration"** field:

- `Direct` — ClojureScript calls Ollama/Grok directly (single-shot, low latency)
- `LangGraph` — calls the sidecar for multi-step agentic turns (higher quality, ~2–5 s latency)

The sidecar URL is configurable (default: `http://localhost:8000`), allowing the sidecar to run on a separate machine or in Docker alongside OgresVTT.

#### When to Use LangGraph

| Scenario | Recommended mode |
|----------|-----------------|
| Quick encounters, low-end hardware | Direct |
| Complex multi-NPC tactics | LangGraph |
| Solo play with full narrative AI | LangGraph |
| Grok cloud backend (paid per token) | Direct (fewer calls) |
| Ollama local, unlimited tokens | LangGraph |

### Token Identity Contract

The AI DM must only reference tokens by their DataScript `:db/id` (exposed in the serialized state). The prompt serialization layer maps human-readable labels to IDs. The parser validates that all referenced IDs exist in the current state before dispatching any actions, preventing hallucinated token manipulation.

---

## Security Considerations

- **API key isolation**: Grok API key is stored in `localStorage` under the host's browser only. It is never included in WebSocket messages or sent to the OgresVTT server.
- **Ollama CORS**: Ollama must be started with `OLLAMA_ORIGINS=*` or the VTT origin when running locally. Document this requirement clearly.
- **Input sanitization**: Narration text from the LLM is rendered as plain text (not HTML) to prevent XSS.
- **Action validation**: Every AI-generated action is validated against the current game state before dispatch. Unknown token IDs, out-of-bounds positions, and negative HP values are rejected.
- **Rate limiting**: The AI DM enforces a minimum interval between turns (configurable, min 5 s) to prevent runaway API spend.

---

## UX / Design Notes

- AI DM panel uses the same design system as existing panels (UIX components, existing CSS variables).
- A pulsing indicator in the toolbar shows when the AI DM is active.
- When in "confirm" mode, a non-blocking toast-style modal overlays the bottom of the screen with the proposed actions and narration text, with Approve / Edit / Skip buttons.
- Token movements triggered by the AI DM are animated the same way as drag-and-drop movements (smooth transition via existing CSS).
- Players see a subtle "(AI DM)" badge next to narration entries to distinguish AI from host text.

---

## Milestones

| Milestone | Deliverables | Status |
|-----------|-------------|--------|
| **M1 — Foundation** | DataScript schema, AI DM config panel UI, settings persistence | ✅ Done |
| **M2 — Backends** | Ollama + Grok HTTP clients (direct mode), shared prompt builder | ✅ Done |
| **M3 — Tool Calling** | Tool definitions, tool_call dispatch → OgresVTT events, token ID validation | ✅ Done |
| **M4 — Narration Panel** | Narration UI, auto-scroll, two-way chat, "Thinking…" indicator | ✅ Done |
| **M5 — LangGraph Sidecar** | FastAPI app, `assess → plan → execute → validate` graph, query-feedback loop | ✅ Done |
| **M6 — LangGraph Integration** | `langgraph.cljs` client, orchestration toggle in config panel | ✅ Done |
| **M7 — Voice Narration** | Kokoro TTS sidecar endpoint, audio queue, voice/speed config | ✅ Done |
| **M8 — Player Tokens** | `list_tokens` query tool, `move_player_token` for player movement commands | ✅ Done |
| **M9 — Terrain Vision** | Vision model terrain detection, canvas crop, prompt integration, UI config | ✅ Done |
| **M10 — Polish & Docs** | README rewrite, error states, loading indicators, demo scenario | ✅ Done |
| **M11 — Confirm Flow** | Action preview modal, approve/edit/skip logic | 🔲 Planned |

---

## Open Questions

1. ~~Should the AI DM maintain turn-by-turn conversation history?~~ **Resolved:** Rolling 20-message history is kept in React state (trimmed with `take-last`).
2. Should spawned tokens use a default placeholder image, or should the AI DM suggest image search keywords to present to the host?
3. Should initiative rolling be handled by the AI DM or always left to the host to maintain player agency at encounter start?
4. ~~Can players "speak to" the AI DM via the narration panel?~~ **Resolved:** Two-way chat implemented — narration input routes to the DM when AI DM is active.
5. Should terrain vision results be cached per token position to avoid re-querying the vision model each turn when tokens haven't moved?

---

## Acceptance Criteria

**Core**
- [x] Host can enable AI DM and select Ollama, Grok, or LangGraph backend from the configuration panel.
- [x] AI DM produces narration text visible to all session participants.
- [x] AI DM can spawn, move, and remove tokens on the active scene via dispatched events.
- [x] All AI-dispatched token actions are broadcast via WebSocket and reflected on all clients.
- [ ] In confirm mode, no action executes without host approval. *(M11 — planned)*
- [x] Grok API key is never transmitted to the OgresVTT server.
- [x] AI DM can be paused and resumed by the host without losing session state.
- [x] Narration panel supports two-way chat when AI DM is active; plain narration when disabled.

**Tool Calling**
- [x] All board actions are triggered via LLM `tool_calls`, not freeform JSON parsing.
- [x] Tool arguments are validated against live DataScript state before dispatch; invalid `token_id` references are silently dropped (no crash).
- [x] `move_player_token` moves player-flagged tokens when the player explicitly requests movement.
- [x] `list_tokens` query tool returns token data to the LLM mid-turn via the query-feedback loop.
- [x] Tool results are appended to conversation history so subsequent turns have context.

**LangGraph Sidecar**
- [x] The sidecar exposes `POST /dm/turn` and returns a validated tool call list.
- [x] The `assess → plan → execute → validate` graph runs end-to-end for a sample encounter.
- [x] Validation errors trigger `reflect_retry` up to 2 times before the turn is abandoned.
- [x] `plan_actions` node runs a query-feedback loop (max 3 rounds) so the LLM can call `list_tokens` and receive real data before committing to actions.
- [x] Host can switch between Direct and LangGraph orchestration modes without reloading.
- [ ] Sidecar runs in Docker via `docker-compose` alongside the main OgresVTT services. *(Dockerfile present, compose wiring pending)*

**Voice Narration**
- [x] Sidecar exposes `POST /dm/speak` returning WAV audio from Kokoro TTS.
- [x] Audio clips are queued and played sequentially with no overlap.
- [x] Voice and speed are configurable in the AI DM panel.
- [x] Voice narration is silently skipped if the sidecar is unreachable.

**Terrain Vision**
- [x] When enabled, the scene background image is cropped around each token and sent to the vision model.
- [x] Terrain descriptions (e.g. `"stone cave floor"`) are appended to each token's game state entry.
- [x] Detection runs concurrently for all tokens via `Promise.all`.
- [x] Detection is silently skipped when vision is disabled, no image is loaded, or the sidecar is unreachable.
