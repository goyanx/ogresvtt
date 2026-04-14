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
- AI-controlled player characters.
- Fine-tuned or custom models — use off-the-shelf instruction-following models.
- Voice synthesis or TTS narration.

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

---

## Feature Specification

### 1. AI DM Configuration Panel

A new "AI DM" section in the host toolbar (beside the existing scene/initiative panels).

**Fields:**
- **Enable AI DM** — toggle (default: off)
- **Backend** — radio: `Ollama` | `Grok`
- **Ollama endpoint** — text field, default `http://localhost:11434`
- **Ollama model** — text field, default `llama3`
- **Grok API key** — password field (stored in `localStorage`, never sent to OgresVTT server)
- **Grok model** — dropdown: `grok-3`, `grok-3-mini`
- **Scenario prompt** — textarea for campaign context / DM instructions (e.g., "Dark dungeon crawl, 4 level-3 adventurers, gothic horror tone")
- **Action mode** — radio: `Auto-approve` | `Confirm each action`
- **Frequency** — slider: how often the AI DM acts (in seconds, range 5–60, default 15)

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

### 3. LLM Action Protocol

The AI DM communicates via a structured JSON response format. The model is instructed (via system prompt) to respond with:

```json
{
  "narration": "The orc shaman raises its staff and lightning crackles across the room.",
  "actions": [
    { "type": "move-token",   "token-id": "abc123", "x": 320, "y": 256 },
    { "type": "spawn-token",  "label": "Fire Elemental", "x": 160, "y": 192, "color": "#e05c00" },
    { "type": "update-hp",    "token-id": "abc123", "hp": 14 },
    { "type": "remove-token", "token-id": "def456" },
    { "type": "roll-initiative", "token-ids": ["abc123", "ghi789"] },
    { "type": "advance-turn" }
  ]
}
```

The system prompt enforces this schema strictly. If the model returns malformed JSON, the client retries once with an error-correction nudge before skipping the turn.

**Supported action types (v1):**

| Action | Description |
|--------|-------------|
| `move-token` | Move an existing token to grid position (x, y) |
| `spawn-token` | Create a new token with label, position, optional color/image |
| `remove-token` | Delete a token from the scene |
| `update-hp` | Set a token's current HP |
| `roll-initiative` | Roll initiative for listed tokens and insert into tracker |
| `advance-turn` | Move to the next turn in the initiative order |

### 4. Action Execution Pipeline

```
AI DM Timer fires
      │
      ▼
Serialize game state → build prompt
      │
      ▼
Call LLM backend (Ollama / Grok HTTP)
      │
      ▼
Parse JSON response
      │
      ├─ confirm mode? ──► Show "AI DM Action Preview" modal to host
      │                         Host: [Approve] [Edit] [Reject]
      │
      └─ auto mode? ──────► Directly dispatch events
              │
              ▼
      Dispatch OgresVTT events (same as human DM actions)
              │
              ▼
      DataScript transact → WebSocket broadcast → all clients update
              │
              ▼
      Narration appended to AI DM chat panel (broadcast to all)
```

### 5. AI DM Chat / Narration Panel

- A new collapsible panel on the right side of the screen labeled **"DM Narration"**.
- Visible to all connected clients (host and players).
- Each narration entry shows: AI DM avatar icon, narration text, timestamp.
- Host-typed messages also appear here (host can contribute narrative manually).
- Panel is scrollable; last 50 entries retained in session memory.
- Narration is broadcast over the existing WebSocket room so all players see it.

### 6. LLM Backend Integration

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
│   ├── core.cljs          # AI DM state machine, timer loop, orchestration
│   ├── prompt.cljs        # Game state → prompt serialization
│   ├── parser.cljs        # LLM JSON response parsing & validation
│   ├── backends/
│   │   ├── ollama.cljs    # Ollama HTTP client
│   │   └── grok.cljs      # Grok/xAI HTTP client
│   └── actions.cljs       # AI action → OgresVTT event dispatch
├── component/
│   ├── panel_ai_dm.cljs   # AI DM configuration panel
│   └── panel_narration.cljs # Narration chat panel
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

| Milestone | Deliverables |
|-----------|-------------|
| **M1 — Foundation** | DataScript schema, AI DM config panel UI, settings persistence |
| **M2 — Backends** | Ollama + Grok HTTP clients, shared prompt builder, JSON parser |
| **M3 — Action Execution** | AI action → OgresVTT event dispatch, token ID validation |
| **M4 — Narration Panel** | Narration UI component, WebSocket broadcast of narration entries |
| **M5 — Confirm Flow** | Action preview modal, approve/edit/skip logic |
| **M6 — Polish & Docs** | Error states, loading indicators, Ollama setup docs, demo scenario |

---

## Open Questions

1. Should the AI DM maintain a turn-by-turn memory (conversation history) across turns, or use a stateless single-prompt approach per turn? Conversation history improves coherence but increases token cost with Grok.
2. Should spawned tokens use a default placeholder image, or should the AI DM suggest image search keywords to present to the host?
3. Should initiative rolling be handled by the AI DM or always left to the host to maintain player agency at encounter start?
4. Can players "speak to" the AI DM via the narration panel, influencing its decisions?

---

## Acceptance Criteria

- [ ] Host can enable AI DM and select Ollama or Grok backend from the configuration panel.
- [ ] AI DM produces narration text visible to all session participants.
- [ ] AI DM can spawn, move, and remove tokens on the active scene via dispatched events.
- [ ] All AI-dispatched token actions are broadcast via WebSocket and reflected on all clients.
- [ ] In confirm mode, no action executes without host approval.
- [ ] Grok API key is never transmitted to the OgresVTT server.
- [ ] Invalid/hallucinated token references in AI responses are silently dropped (no crash).
- [ ] AI DM can be paused and resumed by the host without losing session state.
- [ ] Narration panel is read-only for players; host can type additional narration.
