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
- Narrates events to all players in real time via the DM Narration panel
- Two-way chat — ask the DM questions and get in-character responses
- Voice narration via Kokoro TTS (British male narrator by default)
- **Terrain vision** — vision model detects what surface each token stands on (stone floor, dungeon wall, forest path, etc.) and includes it in the DM's context
- Player movement — typing "I move north" shifts the player's token on the board
- Query tools — DM can call `list_tokens` mid-turn to inspect who is on the board
- Backends: Ollama (local/private), Grok xAI (cloud), LangGraph sidecar (multi-step agentic)
- LangGraph mode adds assess → plan → validate → reflect-retry reasoning loop with agentic query-feedback

---

## Development Setup (Windows)

### Prerequisites

| Tool | Install |
|------|---------|
| **Node.js** | [nodejs.org](https://nodejs.org/) |
| **Java JDK 21** | [Eclipse Temurin](https://adoptium.net/) |
| **Clojure** | PowerShell (run as Administrator): `iwr -useb download.clojure.org/install/win-install-1.11.1.1165.ps1 \| iex` |
| **Python 3.11+** | [python.org](https://www.python.org/) — only needed for AI DM sidecar |

### Frontend (ClojureScript)

```powershell
# Clone the repository
git clone https://github.com/goyanx/ogresvtt.git
cd ogresvtt

# Switch to the AI DM feature branch
git checkout claude/ai-dungeon-master-prd-xJuMc

# Install JS dependencies
npm install

# Start the frontend dev server (hot reload at http://localhost:8080)
npx shadow-cljs watch app
```

### Backend (Clojure game server)

The backend is only needed for **multiplayer** online sessions. Solo/local play works without it.

```powershell
# In a separate terminal
clojure -M -m ogres.server.core 5000
```

Logs are written to `logs/ogres.log`. Create the directory first:

```powershell
mkdir logs
```

---

## AI Dungeon Master Setup

The AI DM runs entirely in the host's browser. The LLM backend is your choice.

### Option A — Ollama (local, recommended for privacy)

1. Install [Ollama](https://ollama.com) and pull a tool-capable model:
   ```powershell
   ollama pull qwen3:14b
   ```

2. Start Ollama with CORS enabled (required for browser fetch):
   ```powershell
   $env:OLLAMA_ORIGINS="*"
   ollama serve
   ```

3. In OgresVTT open the **wand icon** panel → set:
   - Backend: `Ollama (local, direct)`
   - Endpoint: `http://localhost:11434`
   - Model: `qwen3:14b`

> **Recommended models (2× 12 GB VRAM / 24 GB total):**
> | Role | Model | Pull command |
> |------|-------|--------------|
> | AI DM (tool calling) | `qwen3:14b` | `ollama pull qwen3:14b` |
> | Terrain vision | `qwen3-vl:8b` | `ollama pull qwen3-vl:8b` |
>
> Qwen3-14B outperforms Qwen2.5-14B across all benchmarks and fits in ~11 GB at Q4_K_M.  
> Both models run concurrently with ~19 GB total — well within 24 GB.
>
> **Disable thinking mode** for faster turns — add `/no_think` to the model name or set the model to `qwen3:14b` with the system prompt already containing `\nThink briefly.` Qwen3 defaults to extended chain-of-thought which can add latency.

### Option B — Grok xAI (cloud)

1. Get an API key at [console.x.ai](https://console.x.ai)
2. In OgresVTT open the **wand icon** panel → set:
   - Backend: `Grok (xAI, direct)`
   - API Key: your `xai-...` key *(stored in browser only, never sent to the OgresVTT server)*
   - Model: `grok-3-mini`

### Option C — LangGraph Sidecar (multi-step agentic reasoning)

The sidecar adds a reasoning loop: **assess → plan → validate → reflect/retry** before executing tool calls. Requires Python.

```powershell
cd ai_dm
pip install -r requirements.txt
uvicorn ai_dm.main:app --port 8765 --reload
```

In OgresVTT open the **wand icon** panel → set Backend to `LangGraph sidecar (multi-step)`.

### Voice Narration (optional)

Powered by [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — runs on CPU, no GPU needed.

```powershell
pip install kokoro soundfile numpy
```

On Windows, espeak-ng is needed for phonemization. Install it from the
[espeak-ng releases page](https://github.com/espeak-ng/espeak-ng/releases/latest)
(download the `.msi` installer). It may work without it for English — try without first.

Once the sidecar is running, enable **Voice narration** in the AI DM panel and select a voice.
**George (British male)** is the recommended dungeon master voice.

### Terrain Vision (optional)

The AI DM can detect what terrain each token is standing on by sending a cropped region of the map to a vision model. This enriches its narration and tactics — a goblin on a "stone bridge" behaves differently from one on "open grassland".

1. Pull the vision model:
   ```powershell
   ollama pull qwen3-vl:8b
   ```

2. In the AI DM panel, enable **Terrain vision** and set the Vision model to `qwen3-vl:8b`

3. Make sure your scene has a background map image — terrain detection is skipped if no image is loaded

The detection runs concurrently for all tokens before each DM turn. Results appear in the game state prompt as `terrain: "stone cave floor"` per token.

---

## Using the AI Dungeon Master

### Quick Start

1. Load a map scene and place some NPC tokens on the board
2. Open the **wand icon (✦)** tab → configure backend, model, and scenario
3. Write a scenario describing your campaign context, e.g.:
   ```
   Dark dungeon crawl inside Cragmaw Cave. 4 level-3 adventurers.
   Goblins and a bugbear patrol the tunnels. Gothic horror tone.
   Monsters retreat when below half HP. Narrate in second person.
   ```
4. Click **Run turn** to test a single manual turn
5. Enable **Auto-approve** and set a turn interval to run autonomously
6. Open the **T (narration)** tab to see and hear the DM's narration

### Talking to the DM

With the AI DM enabled, the narration panel input becomes a two-way chat:
- Type a message and click **Ask** — your message is added to the conversation and the DM responds immediately
- When disabled the input broadcasts plain host narration to all players

### Player Movement

When the AI DM is active and you type a movement command in the narration box (e.g. `I move north`, `I go east 2 squares`), the DM will shift your player token on the board in that direction and narrate the result. Compass directions supported: north, south, east, west, northeast, northwest, southeast, southwest.

### Panel Reference

| Icon | Panel | Purpose |
|------|-------|---------|
| 👤 | Tokens | Manage token images |
| 🖼 | Scene | Scene options, grid, fog of war |
| 🖼🖼 | Props | Environmental prop images |
| ⏳ | Initiative | Combat turn tracker |
| ✦ | **AI DM** | Configure and control the AI Dungeon Master |
| **T** | **Narration** | DM narration feed and chat |
| 👥 | Lobby | Online session, room code, player list |
| 🔧 | Data | Export/import/reset local data |

### AI DM Config Reference

| Setting | Description |
|---------|-------------|
| **Enable AI DM** | Activates the AI DM |
| **Backend** | Ollama / Grok / LangGraph sidecar |
| **Endpoint / Sidecar URL** | URL of your local Ollama or LangGraph server |
| **Model** | LLM model name (`qwen3:14b` recommended) |
| **Scenario** | Free-text campaign context injected into every system prompt |
| **Auto-approve** | Run turns automatically on a timer |
| **Turn interval** | How often the DM acts (5 – 60 seconds) |
| **Voice narration** | Speak narration aloud via Kokoro TTS (requires sidecar) |
| **Voice** | TTS voice character (George British male recommended) |
| **Speed** | Narration speaking rate (0.95× = slightly slower, more dramatic) |
| **Terrain vision** | Detect surface type under each token via a vision model |
| **Vision model** | Vision model name (`qwen3-vl:8b` recommended) |

---

## Docker (self-hosted)

```sh
docker compose up -d
```

For full configuration options see the [wiki docs](https://github.com/samcf/ogres/wiki/Docker-Usage).

## Contributing

Interested in helping fix bugs or extending features? Look for issues labeled **beginner friendly** and comment that you'd like to work on it.
