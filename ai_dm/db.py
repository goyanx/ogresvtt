"""SQLite helpers and baseline schema for AI DM runtime + compendium."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

DB_ENV_KEY = "AI_DM_DB_PATH"
DEFAULT_DB_PATH = Path("ai_dm") / "data" / "dm.sqlite"

_lock = threading.Lock()


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS comp_sources (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  edition TEXT,
  version TEXT,
  imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
  license_note TEXT
);

CREATE TABLE IF NOT EXISTS comp_documents (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES comp_sources(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  slug TEXT,
  hash TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comp_sections (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES comp_documents(id) ON DELETE CASCADE,
  section_path TEXT,
  heading TEXT,
  page_start INTEGER,
  page_end INTEGER
);

CREATE TABLE IF NOT EXISTS comp_chunks (
  id INTEGER PRIMARY KEY,
  section_id INTEGER NOT NULL REFERENCES comp_sections(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  citation TEXT,
  token_count INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS comp_chunks_fts USING fts5(
  text,
  citation,
  content='comp_chunks',
  content_rowid='id'
);

CREATE TABLE IF NOT EXISTS comp_entities (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,
  name TEXT NOT NULL,
  slug TEXT,
  aliases_json TEXT,
  raw_json TEXT,
  section_id INTEGER REFERENCES comp_sections(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS comp_monsters (
  id INTEGER PRIMARY KEY,
  entity_id INTEGER NOT NULL REFERENCES comp_entities(id) ON DELETE CASCADE,
  size TEXT,
  creature_type TEXT,
  alignment TEXT,
  armor_class INTEGER,
  hit_points_avg INTEGER,
  hit_dice TEXT,
  speed_json TEXT,
  str_score INTEGER,
  dex_score INTEGER,
  con_score INTEGER,
  int_score INTEGER,
  wis_score INTEGER,
  cha_score INTEGER,
  challenge_rating TEXT,
  proficiency_bonus INTEGER,
  saves_json TEXT,
  skills_json TEXT,
  senses_json TEXT,
  languages_json TEXT,
  traits_json TEXT,
  actions_json TEXT,
  reactions_json TEXT,
  legendary_actions_json TEXT
);

CREATE TABLE IF NOT EXISTS camp_characters (
  id INTEGER PRIMARY KEY,
  external_id TEXT UNIQUE,
  name TEXT NOT NULL,
  is_player INTEGER NOT NULL DEFAULT 0,
  race TEXT,
  class_name TEXT,
  subclass TEXT,
  background TEXT,
  level INTEGER,
  alignment TEXT,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS camp_character_stats (
  character_id INTEGER PRIMARY KEY REFERENCES camp_characters(id) ON DELETE CASCADE,
  proficiency_bonus INTEGER,
  str_score INTEGER,
  dex_score INTEGER,
  con_score INTEGER,
  int_score INTEGER,
  wis_score INTEGER,
  cha_score INTEGER,
  passive_perception INTEGER,
  passive_investigation INTEGER,
  passive_insight INTEGER,
  speeds_json TEXT,
  saves_json TEXT,
  skills_json TEXT
);

CREATE TABLE IF NOT EXISTS camp_resources (
  character_id INTEGER PRIMARY KEY REFERENCES camp_characters(id) ON DELETE CASCADE,
  hp_current INTEGER,
  hp_max INTEGER,
  hp_temp INTEGER,
  hit_dice_json TEXT,
  spell_slots_json TEXT,
  exhaustion_level INTEGER DEFAULT 0,
  death_successes INTEGER DEFAULT 0,
  death_failures INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS camp_conditions (
  id INTEGER PRIMARY KEY,
  character_id INTEGER NOT NULL REFERENCES camp_characters(id) ON DELETE CASCADE,
  condition_name TEXT NOT NULL,
  source TEXT,
  rounds_remaining INTEGER,
  is_concentration INTEGER DEFAULT 0,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS camp_inventory_items (
  id INTEGER PRIMARY KEY,
  character_id INTEGER NOT NULL REFERENCES camp_characters(id) ON DELETE CASCADE,
  item_name TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  equipped_slot TEXT,
  is_attuned INTEGER DEFAULT 0,
  properties_json TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS camp_inventory_currency (
  character_id INTEGER PRIMARY KEY REFERENCES camp_characters(id) ON DELETE CASCADE,
  cp INTEGER DEFAULT 0,
  sp INTEGER DEFAULT 0,
  ep INTEGER DEFAULT 0,
  gp INTEGER DEFAULT 0,
  pp INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comb_encounters (
  id INTEGER PRIMARY KEY,
  scene_id TEXT,
  name TEXT,
  status TEXT DEFAULT 'active',
  started_at TEXT DEFAULT CURRENT_TIMESTAMP,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS comb_initiative (
  id INTEGER PRIMARY KEY,
  encounter_id INTEGER NOT NULL REFERENCES comb_encounters(id) ON DELETE CASCADE,
  character_id INTEGER REFERENCES camp_characters(id) ON DELETE SET NULL,
  token_id TEXT,
  initiative_value INTEGER,
  initiative_order INTEGER,
  is_active_turn INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comb_events (
  id INTEGER PRIMARY KEY,
  encounter_id INTEGER REFERENCES comb_encounters(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL,
  actor_character_id INTEGER REFERENCES camp_characters(id) ON DELETE SET NULL,
  target_character_id INTEGER REFERENCES camp_characters(id) ON DELETE SET NULL,
  payload_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS map_scenes (
  id INTEGER PRIMARY KEY,
  external_scene_id TEXT UNIQUE,
  name TEXT,
  map_file_path TEXT,
  map_file_name TEXT,
  image_hash TEXT,
  width INTEGER,
  height INTEGER,
  grid_size INTEGER,
  offset_x REAL,
  offset_y REAL,
  show_grid INTEGER,
  dark_mode INTEGER,
  grid_align INTEGER,
  show_object_outlines INTEGER,
  lighting TEXT,
  config_json TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS map_regions (
  id INTEGER PRIMARY KEY,
  scene_id INTEGER NOT NULL REFERENCES map_scenes(id) ON DELETE CASCADE,
  region_key TEXT,
  region_name TEXT,
  geometry_json TEXT NOT NULL,
  tags_json TEXT
);

CREATE TABLE IF NOT EXISTS map_token_positions (
  id INTEGER PRIMARY KEY,
  scene_id INTEGER NOT NULL REFERENCES map_scenes(id) ON DELETE CASCADE,
  token_id TEXT NOT NULL,
  character_id INTEGER REFERENCES camp_characters(id) ON DELETE SET NULL,
  x REAL NOT NULL,
  y REAL NOT NULL,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(scene_id, token_id)
);

CREATE TABLE IF NOT EXISTS trg_definitions (
  id INTEGER PRIMARY KEY,
  trigger_key TEXT UNIQUE,
  name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  condition_json TEXT NOT NULL,
  action_json TEXT NOT NULL,
  is_enabled INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS trg_bindings (
  id INTEGER PRIMARY KEY,
  trigger_id INTEGER NOT NULL REFERENCES trg_definitions(id) ON DELETE CASCADE,
  scene_id INTEGER REFERENCES map_scenes(id) ON DELETE CASCADE,
  region_id INTEGER REFERENCES map_regions(id) ON DELETE CASCADE,
  character_id INTEGER REFERENCES camp_characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trg_firings (
  id INTEGER PRIMARY KEY,
  trigger_id INTEGER NOT NULL REFERENCES trg_definitions(id) ON DELETE CASCADE,
  binding_id INTEGER REFERENCES trg_bindings(id) ON DELETE CASCADE,
  event_id INTEGER REFERENCES comb_events(id) ON DELETE SET NULL,
  fired_at TEXT DEFAULT CURRENT_TIMESTAMP,
  result_json TEXT
);

CREATE TABLE IF NOT EXISTS npc_profiles (
  npc_character_id INTEGER PRIMARY KEY REFERENCES camp_characters(id) ON DELETE CASCADE,
  class_archetype TEXT,
  role TEXT,
  motivation_text TEXT,
  secrets_text TEXT,
  languages_json TEXT,
  features_json TEXT
);

CREATE TABLE IF NOT EXISTS npc_personality (
  npc_character_id INTEGER PRIMARY KEY REFERENCES camp_characters(id) ON DELETE CASCADE,
  personality_traits_json TEXT,
  ideals_json TEXT,
  bonds_json TEXT,
  flaws_json TEXT,
  mannerisms_json TEXT
);

CREATE TABLE IF NOT EXISTS npc_opinions (
  id INTEGER PRIMARY KEY,
  npc_character_id INTEGER NOT NULL REFERENCES camp_characters(id) ON DELETE CASCADE,
  target_type TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  attitude TEXT,
  trust_score INTEGER,
  fear_score INTEGER,
  respect_score INTEGER,
  affection_score INTEGER,
  reason_text TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS npc_relationships (
  id INTEGER PRIMARY KEY,
  npc_character_id INTEGER NOT NULL REFERENCES camp_characters(id) ON DELETE CASCADE,
  other_character_id INTEGER REFERENCES camp_characters(id) ON DELETE CASCADE,
  relationship_type TEXT NOT NULL,
  strength_score INTEGER,
  visibility TEXT,
  notes TEXT,
  since_event_id INTEGER REFERENCES comb_events(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS npc_memory_events (
  id INTEGER PRIMARY KEY,
  npc_character_id INTEGER NOT NULL REFERENCES camp_characters(id) ON DELETE CASCADE,
  event_id INTEGER REFERENCES comb_events(id) ON DELETE SET NULL,
  valence INTEGER,
  importance INTEGER,
  summary TEXT,
  expires_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dm_rulings (
  id INTEGER PRIMARY KEY,
  session_ref TEXT,
  topic TEXT NOT NULL,
  decision TEXT NOT NULL,
  citation TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS beat_meta (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS beat_promises (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  promise TEXT NOT NULL,
  payoff_condition TEXT,
  subject TEXT,
  tension TEXT NOT NULL DEFAULT 'standard',
  status TEXT NOT NULL DEFAULT 'open',
  progress_count INTEGER NOT NULL DEFAULT 0,
  created_turn INTEGER,
  last_progress_turn INTEGER,
  resolution TEXT,
  resolved_turn INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS beat_progress (
  id INTEGER PRIMARY KEY,
  beat_id INTEGER NOT NULL REFERENCES beat_promises(id) ON DELETE CASCADE,
  note TEXT NOT NULL,
  turn INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_beat_progress_beat ON beat_progress(beat_id);

CREATE INDEX IF NOT EXISTS idx_beat_promises_status ON beat_promises(status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_map_regions_scene_key
  ON map_regions(scene_id, region_key);

CREATE INDEX IF NOT EXISTS idx_comp_entities_type_name
  ON comp_entities(entity_type, name);

CREATE INDEX IF NOT EXISTS idx_dm_rulings_topic_session
  ON dm_rulings(topic, session_ref);

CREATE TRIGGER IF NOT EXISTS comp_chunks_ai AFTER INSERT ON comp_chunks BEGIN
  INSERT INTO comp_chunks_fts(rowid, text, citation)
  VALUES (new.id, new.text, coalesce(new.citation, ''));
END;

CREATE TRIGGER IF NOT EXISTS comp_chunks_ad AFTER DELETE ON comp_chunks BEGIN
  INSERT INTO comp_chunks_fts(comp_chunks_fts, rowid, text, citation)
  VALUES('delete', old.id, old.text, coalesce(old.citation, ''));
END;

CREATE TRIGGER IF NOT EXISTS comp_chunks_au AFTER UPDATE ON comp_chunks BEGIN
  INSERT INTO comp_chunks_fts(comp_chunks_fts, rowid, text, citation)
  VALUES('delete', old.id, old.text, coalesce(old.citation, ''));
  INSERT INTO comp_chunks_fts(rowid, text, citation)
  VALUES (new.id, new.text, coalesce(new.citation, ''));
END;
"""


MAP_SCENES_COLUMNS = [
    ("map_file_path", "TEXT"),
    ("map_file_name", "TEXT"),
    ("image_hash", "TEXT"),
    ("offset_x", "REAL"),
    ("offset_y", "REAL"),
    ("show_grid", "INTEGER"),
    ("dark_mode", "INTEGER"),
    ("grid_align", "INTEGER"),
    ("show_object_outlines", "INTEGER"),
    ("lighting", "TEXT"),
    ("config_json", "TEXT"),
    ("updated_at", "TEXT DEFAULT CURRENT_TIMESTAMP"),
]


def resolve_db_path() -> Path:
    raw = os.getenv(DB_ENV_KEY)
    return Path(raw) if raw else DEFAULT_DB_PATH


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, name: str, type_sql: str) -> None:
    cols = _table_columns(conn, table)
    if name not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {type_sql}")


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for col_name, col_type in MAP_SCENES_COLUMNS:
        _ensure_column(conn, "map_scenes", col_name, col_type)


def init_db() -> Path:
    db_path = resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(SCHEMA_SQL)
            _apply_migrations(conn)
            conn.commit()
        finally:
            conn.close()
    return db_path


def get_conn() -> sqlite3.Connection:
    db_path = resolve_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def list_tables() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    return [r[0] for r in rows]
