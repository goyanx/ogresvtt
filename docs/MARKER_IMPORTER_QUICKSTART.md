# Marker Importer Quickstart (Grok Tool-Calling)

Use this when you already ran `marker_single` on a campaign PDF and want to load
the extracted content into OgresVTT AI DM data tables.

## 1) Prerequisites

- Python 3.11+
- A valid Grok API key in `.env.local`:

```env
XAI_API_KEY=xai-...
AI_DM_GROK_MODEL=grok-3-mini
AI_DM_DB_PATH=ai_dm/data/dm.sqlite
```

## 2) Run marker-pdf extraction

Example:

```powershell
marker_single "Vecna Nest of the Eldritch Eye.pdf" "./vecna_nest_of_eldritch_eye"
```

## 3) Run importer

From repo root:

```powershell
python scripts/marker_import_grok.py `
  --marker-dir "C:\Users\goyan\Documents\Code\ogresvtt-testcampaigns\vecna_nest_of_eldritch_eye" `
  --source-title "Vecna: Nest of the Eldritch Eye" `
  --edition "5.5e"
```

## 4) Validate result

- Optional admin UI:
  - `http://localhost:8765/dm-admin`
- Check imported rows:
  - `comp_sources`, `comp_documents`, `comp_sections`, `comp_chunks`
  - `camp_characters`, `npc_profiles`, `npc_personality`
  - `map_scenes`, `map_regions`
- Inspect artifact:
  - `<marker-dir>/ogres_import_extracted.json`

## 5) Useful flags

- `--dry-run` : no DB writes
- `--skip-grok` : RAG ingest only
- `--dotenv <path>` : alternate env file
- `--max-files N` : process first N text files
- `--legacy-json-mode` : fallback non-tool-call extraction

## 6) Start sidecar and use AI DM

```powershell
uvicorn ai_dm.main:app --port 8765 --reload
```

In app:
1. Open `✦ AI DM` panel.
2. Set backend to `LangGraph sidecar`.
3. Ensure sidecar URL is `http://localhost:8765`.
4. Run DM turn.

The DM can now retrieve imported lore/rules from RAG and use persisted NPC/map
records for continuity.
