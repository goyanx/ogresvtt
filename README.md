![Screenshot of the Ogres app](site/web/media/ogres-media-collection.webp)

## Features

[ogres.app](https://ogres.app) is a free and open-source virtual tabletop that you can run in your browser and use to play with your friends. It aims to be a very lightweight alternative to some of the more comprehensive tools available today. Its limited core feature-set is intended to help dungeon masters quickly setup encounters and adventures with only the most important necessities.

**Scene Management**
- Create, switch between, and delete multiple scenes
- Upload background map images (up to 10 MB)
- Configurable grid with snapping, size, and origin controls
- Toggle grid display, object outlines, and dark mode per scene

**Tokens**
- Place, move, resize, rotate, and delete tokens
- Set token size categories (Tiny → Gargantuan), label, and image
- Mark tokens as player characters or NPCs
- Hide/reveal tokens (host-only), lock tokens against accidental movement
- Apply light sources and aura radii to tokens
- Track hit points and mark tokens as dead/defeated
- Apply D&D 5e status conditions (Blinded, Charmed, Frightened, Prone, etc.)

**Combat & Initiative**
- Initiative tracker with turn order, round counter, and HP tracking
- Roll and input initiative values; advance turns automatically

**Drawing & Measurement Tools**
- Draw circles, rectangles, polygons, cones, and lines on the scene
- Ruler for measuring distances between any two points
- Customizable shape colors and fill patterns
- Optional grid-alignment for drawn shapes

**Fog of War**
- Draw custom mask areas to hide parts of the map
- Toggle, delete, or batch-reveal/hide masks
- Three lighting states: Revealed, Dimmed, Hidden

**Notes & Props**
- Place GM notes with icons (bookmark, dice, door, location, fire, skull, question)
- Control per-note visibility (host-only or public)
- Place and manage environmental props/objects from an image library

**Multiplayer Sessions**
- One-click host/join with shareable room URLs — no sign-up required
- Real-time sync of scene state, token movement, and fog of war
- See connected players and share cursor positions

**Player Profiles & Assets**
- Customize name, color, description, and avatar image per player
- Shared image library for tokens, maps, and props with thumbnail previews

**Data Management**
- All data saved locally in the browser (IndexedDB) — nothing sent to a server
- Export full backup to file and restore from backup
- Reset application data at any time

**Accessibility & UX**
- Keyboard shortcuts for common actions
- Right-click context menus, drag-and-drop from galleries
- Copy/cut/paste objects; multi-select via shift-click or drag selection
- Responsive design suitable for phones and tablets
- Easy to adapt for any tabletop game system

**AI Dungeon Master** *(experimental)*
- LLM-powered DM that reads the live board and controls NPC/monster tokens
- Spawns, moves, and removes tokens; rolls initiative; updates HP
- Can end combat cleanly by leaving initiative when surrender/truce/retreat resolves an encounter
- Narrates events to all players in real time via the DM Narration panel
- Two-way chat — ask the DM questions and get in-character responses
- Table chat panel (💬) — player messages feed the AI DM as declared actions
- Persistent token notes/attributes the DM reads every turn and can update itself
- Generated ambient soundscapes and one-shot sound effects the DM switches to match the scene (no audio files needed — everything is synthesized in the browser)
- Voice narration via Kokoro TTS (British male narrator by default)
- Backends: Ollama (local/private), Grok xAI (cloud), LangGraph sidecar (multi-step agentic)
- LangGraph mode adds assess → plan → validate → reflect-retry reasoning loop

---

## Configure and Run (Windows)

### 1) Prerequisites

| Tool | Required For | Install |
|------|--------------|---------|
| **Node.js** | Frontend | [nodejs.org](https://nodejs.org/) |
| **Java JDK 21** | Frontend build (`shadow-cljs`) | [Eclipse Temurin](https://adoptium.net/) |
| **Clojure** | Multiplayer backend server | PowerShell (Admin): `iwr -useb download.clojure.org/install/win-install-1.11.1.1165.ps1 \| iex` |
| **Python 3.11+** | LangGraph sidecar / voice | [python.org](https://www.python.org/) |

### 2) Clone and install dependencies

```powershell
git clone https://github.com/goyanx/ogresvtt.git
cd ogresvtt
npm install
mkdir logs
```

### 3) Run the project

Start frontend (required):

```powershell
npx shadow-cljs watch app
```

Start backend (optional, only for multiplayer sessions):

```powershell
clojure -M -m ogres.server.core 5000
```

Open `http://localhost:8080`.

### 4) Choose your runtime mode

| Mode | Extra Process Needed | In-app AI DM Backend | Notes |
|------|----------------------|----------------------|-------|
| Solo/local tabletop (no AI) | none | disabled | Fastest setup |
| AI Direct + Ollama | `ollama serve` | `Ollama (local, direct)` | Local/private |
| AI Direct + Grok | none | `Grok (xAI, direct)` | API key stored in browser localStorage |
| AI LangGraph + Ollama | `uvicorn ai_dm.main:app --port 8765 --reload` (+ Ollama) | `LangGraph sidecar` + `Sidecar LLM backend = Ollama` | Multi-step reasoning |
| AI LangGraph + Grok | `uvicorn ai_dm.main:app --port 8765 --reload` | `LangGraph sidecar` + `Sidecar LLM backend = Grok` | Can use `.env.local` defaults |

### 5) Ollama setup (if using Ollama)

```powershell
ollama pull qwen2.5:14b-instruct-q4_K_M
$env:OLLAMA_ORIGINS="*"
ollama serve
```

In OgresVTT AI DM panel:
- Backend: `Ollama (local, direct)` (or `LangGraph sidecar` + `Sidecar LLM backend = Ollama`)
- Ollama endpoint: `http://localhost:11434`
- Model: `qwen2.5:14b-instruct-q4_K_M` (or another tool-capable model)

### 6) LangGraph sidecar setup (optional)

```powershell
copy .env.local.example .env.local
cd ai_dm
pip install -r requirements.txt
uvicorn ai_dm.main:app --port 8765 --reload
```

Then in OgresVTT AI DM panel:
- Backend: `LangGraph sidecar (multi-step)`
- Sidecar URL: `http://localhost:8765`
- Sidecar LLM backend: `Ollama` or `Grok`

If you use `Sidecar LLM backend = Grok`, you can configure `.env.local` for defaults
(file can be in repo root or `ai_dm/`, or your current working directory when launching `uvicorn`):

```env
XAI_API_KEY=xai-...
GROK_MODEL=grok-3-mini
```

Supported env keys:
- Default sidecar backend: `AI_DM_DEFAULT_BACKEND` (`ollama` or `grok`)
- Grok API key: `XAI_API_KEY` or `GROK_API_KEY` or `AI_DM_GROK_API_KEY`
- Grok model: `GROK_MODEL` or `XAI_MODEL` or `AI_DM_GROK_MODEL`
- Ollama endpoint: `AI_DM_OLLAMA_ENDPOINT` or `OLLAMA_ENDPOINT`
- Ollama model: `AI_DM_OLLAMA_MODEL` or `OLLAMA_MODEL`
- Query loop rounds: `AI_DM_MAX_QUERY_ROUNDS` (default `4`)
- Validation retries: `AI_DM_MAX_RETRIES` (default `2`)

### 7) AI DM quick usage

1. Open the **✦ AI DM** panel.
2. Enable AI DM.
3. Configure backend/model/scenario.
4. Click **Run turn** to test.
5. Enable **Auto-approve** + set interval for autonomous turns.
6. Use **T (Narration)** panel to view output or chat with the DM.

AI DM combat behavior notes:
- Auto-approve timer skips automatic turns while the current initiative token is a player token.
- In LangGraph mode, sidecar logs include current turn context and selected action tools:
  - `turn_id`, `turn_label`, `turn_is_player`
  - `dm_turn tool_calls detail=[...]`
- When combat is over, the DM may emit `leave_initiative` to clear initiative state.

### 8) Soundscapes & sound effects (no setup required)

The AI DM can play looping ambient soundscapes and one-shot sound effects.
Everything is synthesized live with the Web Audio API — there are no audio
files to download and no extra process to run.

Enable it in the **✦ AI DM** panel:

1. Turn on **Soundscape & effects**.
2. Pick an **Ambience** mood manually, or let the DM switch it with the
   `set_ambience` tool as the story moves (it uses `battle` when combat starts
   and restores the scene mood afterwards).
3. Adjust **Audio volume**, and use **Preview effect** to audition any sound.

Available ambience moods: `dungeon`, `cave`, `forest`, `tavern`, `battle`,
`storm`, `mystic`, `calm` (and `none` for silence).

Available effects (used by the DM via the `play_sound` tool): `sword_clash`,
`arrow_whoosh`, `magic_cast`, `fireball`, `door_creak`, `thunder`,
`monster_roar`, `coins`, `dice_roll`, `heal`, `victory_fanfare`,
`damage_hit`, `death_knell`.

Notes:
- Browsers block audio until you interact with the page once; if you hear
  nothing, click anywhere in the app and it will resume.
- Settings (enabled, volume, last mood) persist in the browser.

### 9) Token notes / attributes (AI DM memory per token)

Right-click a token → **Attributes** (journal icon) to attach free-text notes:
personality, motives, oaths, fears, conditions not covered by HP/flags.

- The AI DM reads a summary of every token's notes each turn.
- The DM persists lasting facts itself with the `update_token_attribute`
  tool — `append` mode adds a new line without erasing what you wrote.
- Copy/paste buttons move notes between tokens; Clear empties them.

### 10) Table chat (💬)

The **Table chat** panel is available to both host and players. Player
messages are read by the AI DM as declared actions ("I attack the goblin",
"I move north"), which is how a solo player drives their character between
DM turns.

### 11) Voice narration (optional)

Powered by [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M).

```powershell
pip install kokoro soundfile numpy
```

Windows phonemization may require espeak-ng:
[espeak-ng latest releases](https://github.com/espeak-ng/espeak-ng/releases/latest)

### 12) Troubleshooting

- `AI DM Error: Grok API key not set`
  - Direct mode: set key in AI DM panel.
  - LangGraph mode: set key in panel or `.env.local`.
- LangGraph cannot connect
  - Ensure sidecar is running on `http://localhost:8765`.
- No multiplayer sync
  - Ensure Clojure backend is running on port `5000`.
- DM says combat ended but initiative still visible
  - Ensure frontend is rebuilt/reloaded after pulling latest changes.
  - Confirm sidecar log has `dm_turn tool_calls detail=['narrate', 'leave_initiative']`.
  - If action dispatch fails, Narration panel shows `[AI DM Tool Dispatch] ...` with reason.

## Panel Reference

| Icon | Panel | Purpose |
|------|-------|---------|
| 👤 | Tokens | Manage token images |
| 🖼 | Scene | Scene options, grid, fog of war |
| 🖼🖼 | Props | Environmental prop images |
| ⏳ | Initiative | Combat turn tracker |
| ✦ | **AI DM** | Configure and control the AI Dungeon Master |
| **T** | **Narration** | DM narration feed and host↔DM chat |
| 💬 | **Table chat** | Player chat — messages feed the AI DM as declared actions |
| 👥 | Lobby | Online session, room code, player list |
| 🔧 | Data | Export/import/reset local data |

### AI DM Config Reference

| Setting | Description |
|---------|-------------|
| **Enable AI DM** | Activates the AI DM |
| **Backend** | Ollama / Grok / LangGraph sidecar |
| **Sidecar LLM backend** | In LangGraph mode, selects Ollama or Grok for the sidecar |
| **Endpoint / Sidecar URL** | URL of your local Ollama or LangGraph server |
| **Model** | LLM model name (`qwen2.5:14b-instruct-q4_K_M` recommended) |
| **Scenario** | Free-text campaign context injected into every system prompt |
| **Auto-approve** | Run turns automatically on a timer |
| **Turn interval** | How often the DM acts (5 – 60 seconds) |
| **Voice narration** | Speak narration aloud via Kokoro TTS |
| **Voice** | TTS voice character (George British male recommended) |
| **Speed** | Narration speaking rate (0.95× = slightly slower, more dramatic) |
| **Soundscape & effects** | Enable generated ambient audio and sound effects |
| **Ambience** | Current soundscape mood (also switched by the DM via `set_ambience`) |
| **Audio volume** | Master volume for ambience and effects |
| **Preview effect** | Audition any of the built-in synthesized effects |

---

## Docker (self-hosted)

```sh
docker compose up -d
```

For full configuration options see the [wiki docs](https://github.com/samcf/ogres/wiki/Docker-Usage).

## Running the tests

```powershell
npx shadow-cljs compile test
```

Runs the ClojureScript test suite (collision, pathfinding, dd2vtt import,
events, and AI tool dispatch) under Node.

## Contributing

Interested in helping fix bugs or extending features? Look for issues labeled **beginner friendly** and comment that you'd like to work on it.

### 13) SQLite RAG + Data Admin (LangGraph sidecar)

The sidecar now initializes a local SQLite database for compendium RAG and
campaign runtime memory (characters, stats, combat events, NPC relationships,
map triggers, rulings).

Default database path:
- `ai_dm/data/dm.sqlite`

Optional env vars:
- `AI_DM_DB_PATH` — override sqlite file path
- `AI_DM_ADMIN_ALLOW_WRITE=true` — allow write SQL in admin console

Open admin UI:
- `http://localhost:8765/dm-admin`

Admin APIs:
- `GET /dm-admin/api/tables`
- `GET /dm-admin/api/table/{table_name}?limit=100&offset=0`
- `POST /dm-admin/api/query`
- `GET /dm-admin/api/maps?limit=200`
- `POST /dm-admin/api/maps/upsert`

Ingest handpicked DnD manuals (Markdown/Text) into RAG tables:

```powershell
python -m ai_dm.ingest_compendium \
  --source-title "DnD 5.5e Manual" \
  --edition "5.5e" \
  --doc-title "PHB" \
  --file C:\path\to\manual.md
```

After ingestion, the agent can call `retrieve_rules` and `get_monster_stats` during planning.

See [docs/AI_DM_DATA_ADMIN.md](docs/AI_DM_DATA_ADMIN.md) for schema/admin details.



LangGraph DM can now emit `show_map` action tool calls to request scene/map switching in the client, backed by `map_scenes` config in SQLite.

### 14) Import `marker-pdf` campaign output with Grok tool-calling

Use the standalone CLI importer to ingest `marker_single` output into SQLite RAG
and campaign tables. This script is independent from sidecar runtime code
(it does not import or modify `ai_dm` modules).

Script path:
- `scripts/marker_import_grok.py`

Input:
- folder produced by `marker_single` (reads `.md` / `.txt`)

Output:
- RAG rows in `comp_*` tables
- NPC + map provisioning in `camp_*`, `npc_*`, `map_*` tables via Grok function/tool calls
- extraction artifact file: `<marker-dir>/ogres_import_extracted.json`

Required env for Grok:
- `XAI_API_KEY` (or `GROK_API_KEY` / `AI_DM_GROK_API_KEY`)
- Optional model override: `AI_DM_GROK_MODEL` (or `GROK_MODEL` / `XAI_MODEL`)
- Optional DB override: `AI_DM_DB_PATH`

Example:

```powershell
python scripts/marker_import_grok.py `
  --marker-dir "C:\Users\goyan\Documents\Code\ogresvtt-testcampaigns\vecna_nest_of_eldritch_eye" `
  --source-title "Vecna: Nest of the Eldritch Eye" `
  --edition "5.5e"
```

Useful flags:
- `--dry-run` (no DB writes)
- `--skip-grok` (RAG ingest only)
- `--dotenv <path>` (use non-default env file)
- `--max-files N` (cap number of processed files)
- `--legacy-json-mode` (fallback: non-tool-call extraction path)

See [docs/AI_DM_DATA_ADMIN.md](docs/AI_DM_DATA_ADMIN.md) for DB domains and tooling context.
Quickstart: [docs/MARKER_IMPORTER_QUICKSTART.md](docs/MARKER_IMPORTER_QUICKSTART.md)
