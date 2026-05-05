# AI DM Data Admin

This document describes the SQLite-backed data layer used by the LangGraph sidecar.

## Admin URL

When the sidecar is running, open:

- `http://localhost:8765/dm-admin`

The UI lets you:
- browse tables and rows
- run SQL queries
- inspect RAG content and campaign runtime state

By default, SQL console is read-only. Enable writes with:

- `AI_DM_ADMIN_ALLOW_WRITE=true`

## Database Location

Default file:

- `ai_dm/data/dm.sqlite`

Override path:

- `AI_DM_DB_PATH=C:\path\to\custom.sqlite`

## Schema Domains

### Compendium / RAG (`comp_*`)
- `comp_sources`
- `comp_documents`
- `comp_sections`
- `comp_chunks`
- `comp_chunks_fts` (FTS5)
- `comp_entities`
- `comp_monsters`

### Campaign Runtime (`camp_*`)
- `camp_characters`
- `camp_character_stats`
- `camp_resources`
- `camp_conditions`
- `camp_inventory_items`
- `camp_inventory_currency`

### Combat/Event History (`comb_*`)
- `comb_encounters`
- `comb_initiative`
- `comb_events`

### Map + Position + Trigger (`map_*`, `trg_*`)
- `map_scenes`
- `map_regions`
- `map_token_positions`
- `trg_definitions`
- `trg_bindings`
- `trg_firings`

### NPC Social/Behavior State (`npc_*`)
- `npc_profiles`
- `npc_personality`
- `npc_opinions`
- `npc_relationships`
- `npc_memory_events`

### DM Continuity
- `dm_rulings`

## RAG Ingestion Workflow

Use the ingest script to load handpicked DnD manuals in Markdown or text format:

```powershell
python -m ai_dm.ingest_compendium \
  --source-title "DnD 5.5e Manual" \
  --edition "5.5e" \
  --doc-title "PHB" \
  --file C:\path\to\phb_excerpt.md
```

You can pass `--file` multiple times.

## Marker-PDF Importer (Standalone CLI)

For adventure/module extraction pipelines (for example `marker_single`), use:

- `scripts/marker_import_grok.py`

This importer:
- ingests extracted `.md` / `.txt` into `comp_*` RAG tables
- uses Grok chat-completions function/tool-calling to provision:
  - `camp_characters`
  - `npc_profiles`
  - `npc_personality`
  - `map_scenes`
  - `map_regions`
- writes `<marker-dir>/ogres_import_extracted.json` as an audit artifact

It is intentionally decoupled from sidecar runtime modules (`ai_dm/*`).

### Required Env

- `XAI_API_KEY` (or `GROK_API_KEY` / `AI_DM_GROK_API_KEY`)
- Optional model: `AI_DM_GROK_MODEL` (or `GROK_MODEL` / `XAI_MODEL`)
- Optional DB path: `AI_DM_DB_PATH`

### Example Command

```powershell
python scripts/marker_import_grok.py `
  --marker-dir "C:\path\to\marker_output" `
  --source-title "Vecna: Nest of the Eldritch Eye" `
  --edition "5.5e"
```

### CLI Notes

- `--dry-run`: parse and call model, but rollback DB writes.
- `--skip-grok`: ingest text chunks only; no NPC/map provisioning.
- `--legacy-json-mode`: fallback to single JSON extraction mode (no function-call loop).
- `--dotenv <path>`: load env values from custom file instead of `.env.local`.

Quickstart:
- [MARKER_IMPORTER_QUICKSTART.md](MARKER_IMPORTER_QUICKSTART.md)

## Agentic Tools (Sidecar Query Tools)

The planning loop can call these internal tools:

- `retrieve_rules`
- `get_monster_stats`
- `upsert_character`
- `set_character_stats`
- `set_character_resources`
- `get_character_sheet`
- `add_inventory_item`
- `set_npc_personality`
- `set_npc_opinion`
- `set_npc_relationship`
- `record_combat_event`
- `upsert_token_position`
- `define_map_region`
- `define_trigger`
- `evaluate_triggers`
- `save_ruling`
- `get_rulings`

These execute inside sidecar and do not go to browser tool dispatch.

Action tools (dispatched to client):
- `show_map` — switch/create target scene and apply map render settings in-app.
- `move_token`, `spawn_token`, `remove_token`
- `update_hp`, `apply_damage`
- `roll_initiative`, `advance_turn`
- `leave_initiative` — end combat/initiative mode and clear tracker state.

## Runtime Diagnostics

LangGraph sidecar logs (`logs/ai_dm.log`) include turn-level context and chosen actions:
- `turn_id`, `turn_label`, `turn_is_player` on `dm_turn start`
- `dm_turn tool_calls detail=[...]` on success
- full `validation_errors` details when validation fails

Client-side dispatch failures are surfaced in Narration as:
- `[AI DM Tool Dispatch] ...`

## Notes

- Keep source citations in `comp_chunks.citation` for traceability.
- Use `dm_rulings` to preserve campaign adjudication consistency.
- Keep table writes through tool calls when possible; use raw SQL admin writes for maintenance/migrations.


## Map Scene Config Fields

`map_scenes` includes DM-switchable map metadata/config:
- `external_scene_id`
- `name`
- `map_file_path`
- `map_file_name`
- `image_hash`
- `width`, `height`, `grid_size`
- `offset_x`, `offset_y`
- `show_grid`, `dark_mode`, `grid_align`, `show_object_outlines`
- `lighting`
- `config_json`
- `updated_at`

These fields are editable from `/dm-admin` via the **Map Config Admin** section.
