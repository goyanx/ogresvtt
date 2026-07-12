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
- Character sheets from the campaign database (stats, HP, spell slots, gear) are auto-injected into every DM turn — party always, NPCs when their token is on the board
- One-call D&D Beyond character import into the campaign database
- Story beat harness (Sanderson's Promise / Progress / Payoff): the DM keeps a persistent ledger of narrative promises and gets per-turn pacing directives to establish, advance, and pay them off
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

### 14) Character sheets: the DM's per-turn memory

The LangGraph DM no longer depends on choosing to call `get_character_sheet` —
every turn, the sidecar builds a compact **CHARACTER SHEETS** block from the
campaign database and injects it into the assess, plan, and combat prompts:

- **Party members** (`camp_characters.is_player = 1`) are always included.
- **NPCs/monsters** are included when a board token label matches their name
  (initiative suffixes like "Goblin 2" are handled).
- Each entry carries ability scores with modifiers, proficiency bonus,
  passive Perception, speed, HP / temp HP / spell slots, active conditions,
  and equipped gear — so checks, saves, attacks, and damage use real numbers.

Populate the database via the D&D Beyond import below, the `marker-pdf`
campaign importer (section 16), the `/dm-admin` console, or let the DM itself
persist characters with `upsert_character` / `set_character_stats` during play.

### 15) Import your D&D Beyond character

Set your character's privacy to **Public** on dndbeyond.com, then (with the
sidecar running):

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8765/dm/import/ddb-character `
  -ContentType "application/json" `
  -Body '{"character": "https://www.dndbeyond.com/characters/12345678"}'
```

You can pass the full URL or just the numeric id. Use `"is_player": false`
to import a DM-controlled NPC. The import fills `camp_characters`,
`camp_character_stats` (abilities with racial bonuses, proficiency bonus,
passive Perception, speed), `camp_resources` (current/max/temp HP, spell
slots), inventory, and currency. Appearance and personality traits land in
the character's notes, which also feed narration and Comfy image-generation
context. Re-importing the same character updates it in place.

This uses D&D Beyond's public character JSON endpoint — no login or scraping;
it only works for characters you've set to Public.

### 16) Import `marker-pdf` campaign output with Grok tool-calling

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

### 17) Import a D&D Beyond adventure you own

`scripts/ddb_fetch_sources.py` converts DDB source/adventure chapters into
the markdown folder format that the section-16 importer consumes, and
downloads the map/handout images referenced by each chapter into
`<out-dir>/images/` (that was the tedious part — no more hunting maps).

**Option A — browser-saved pages (no scripted site access at all):**
while logged in, open each chapter and save it (`Ctrl+S`, "HTML only")
into one folder, then:

```powershell
python scripts/ddb_fetch_sources.py --html-dir C:\campaigns\lmop_saved --out-dir C:\campaigns\lmop
```

**Option B — direct fetch with your session cookie.** Copy the
`CobaltSession` cookie value from your browser (DevTools → Application →
Cookies → dndbeyond.com) into `.env.local` as `DDB_COBALT_SESSION=...`
(this file is git-ignored), then:

```powershell
python scripts/ddb_fetch_sources.py `
  --url https://www.dndbeyond.com/sources/dnd/lmop `
  --whole-book --out-dir C:\campaigns\lmop
```

`--whole-book` discovers every chapter from the table of contents;
`--delay` (default 1.5s) spaces out requests; `--no-images` skips image
downloads. If DDB returns 403 for scripted access, fall back to Option A.

> **Note:** automated access is against D&D Beyond's Terms of Service.
> Option B exists for personal import of adventures you have purchased,
> with your own account, at your own risk — Option A avoids the issue
> entirely. Never commit your cookie.

**Then finish the pipeline:**

```powershell
python scripts/marker_import_grok.py --marker-dir C:\campaigns\lmop `
  --source-title "Lost Mine of Phandelver" --edition 5e
```

That populates the rules RAG plus NPC/map tables, which the DM auto-reads
every turn (section 14). Upload the downloaded map images from
`C:\campaigns\lmop\images\` as scene backgrounds in the app, name the
scenes after their chapters, and play.

### 18) Story beats: Promise / Progress / Payoff (LangGraph sidecar)

Following Brandon Sanderson's plotting framework, the DM loop keeps a
persistent **beat ledger** (`beat_*` tables) so the campaign has actual
narrative structure instead of turn-by-turn improvisation:

- **Promise** — the DM records concrete narrative commitments with
  `promise_beat` (a villain to confront, a mystery, a debt, an arc), with a
  tension tier: `minor` (scene), `standard` (arc), `major` (campaign).
- **Progress** — when a turn's events visibly advance a promise, the DM
  records it with `progress_beat`. Progress the player can feel:
  escalation, revelation, consequence — not filler.
- **Payoff** — once a beat has enough progress steps (2 / 3 / 5 by tier),
  it's flagged ripe; the DM resolves it with `payoff_beat` so the landing
  is "surprising yet inevitable", then seeds the next promise.

Every `/dm/turn` increments a turn counter and injects a **STORY BEATS**
block into the assess, plan, and combat prompts: open promises with their
progress, recently paid-off beats (as callback material), and deterministic
**pacing directives** computed by the harness:

| Ledger state | Directive |
|---|---|
| No open promises | Establish one this turn (and foreshadow it) |
| Beat idle ≥ 4 turns | Advance it visibly or retire it |
| Beat at its progress threshold | Ripe — pay it off, then seed the next promise |
| 5 open promises | Stop promising; progress or pay off instead |
| Otherwise | Advance at least one promise with visible movement |

The ledger is DM-internal (never mentioned to players), inspectable at
`/dm-admin` (tables `beat_promises`, `beat_progress`), and persists across
sessions — so a promise made tonight pays off next week. Requires the
LangGraph sidecar backend.
