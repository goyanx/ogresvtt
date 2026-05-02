#!/usr/bin/env python3
"""
Standalone CLI importer for marker-pdf output -> OgresVTT SQLite + JSON artifacts.

What it does:
1) Ingests marker-generated .md/.txt files into compendium RAG tables.
2) Uses Grok (xAI chat completions API) to extract structured entities.
3) Upserts extracted scenes/NPCs into existing OgresVTT sidecar-compatible tables.

This script intentionally does not import or modify ai_dm code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


XAI_URL = "https://api.x.ai/v1/chat/completions"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        row = line.strip()
        if not row or row.startswith("#") or "=" not in row:
            continue
        k, v = row.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def load_env(dotenv_path: Path | None) -> dict[str, str]:
    merged = {}
    if dotenv_path is not None:
        merged.update(parse_env_file(dotenv_path))
    else:
        merged.update(parse_env_file(Path(".env.local")))
    merged.update(os.environ)
    return merged


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def split_sections(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    sections: list[tuple[str, str]] = []
    current_heading = "Document"
    buf: list[str] = []

    for line in lines:
        if re.match(r"^\s{0,3}#{1,6}\s+\S", line):
            if buf:
                sections.append((current_heading, "\n".join(buf).strip()))
                buf = []
            current_heading = re.sub(r"^\s{0,3}#{1,6}\s+", "", line).strip()
            continue
        buf.append(line)

    if buf:
        sections.append((current_heading, "\n".join(buf).strip()))
    return [(h, t) for h, t in sections if t]


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    if max_chars <= overlap:
        raise ValueError("max_chars must be greater than overlap")
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + max_chars)
        chunk = text[i:j].strip()
        if chunk:
            out.append(chunk)
        if j == n:
            break
        i = max(0, j - overlap)
    return out


def estimate_token_count(text: str) -> int:
    return max(1, len(text) // 4)


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _safe_json_loads(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _format_xai_error_payload(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "unknown xAI error"
    if isinstance(payload.get("error"), dict):
        err = payload["error"]
        msg = err.get("message") or err.get("type") or "xAI error"
        code = err.get("code")
        return f"{msg} (code={code})" if code else str(msg)
    if isinstance(payload.get("error"), str):
        return payload["error"]
    if "message" in payload:
        return str(payload["message"])
    return json.dumps(payload, ensure_ascii=False)[:400]


def _extract_message_json_dict(chat_response: dict[str, Any]) -> dict[str, Any]:
    choices = chat_response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("xAI response has no choices")
    msg = choices[0].get("message")
    if not isinstance(msg, dict):
        raise RuntimeError("xAI response has no message object")
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("xAI response message content is empty")
    content = re.sub(r"^```json\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE | re.MULTILINE)
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise RuntimeError("xAI response content is not a JSON object")
    return parsed


def build_visual_context(marker_dir: Path, toc_limit: int = 120, image_limit: int = 200) -> str:
    image_files = sorted(
        [
            p.name
            for p in marker_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]
    )[:image_limit]
    toc_titles: list[str] = []
    for meta_path in sorted(marker_dir.rglob("*_meta.json")):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
        except json.JSONDecodeError:
            continue
        toc = data.get("table_of_contents")
        if not isinstance(toc, list):
            continue
        for entry in toc:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").replace("\n", " ").strip()
            page = entry.get("page_id")
            if title:
                toc_titles.append(f"p{page}: {title}" if page is not None else title)
            if len(toc_titles) >= toc_limit:
                break
        if len(toc_titles) >= toc_limit:
            break

    lines = ["VISUAL ASSET CONTEXT"]
    lines.append("Images (filenames):")
    if image_files:
        lines.extend(f"- {name}" for name in image_files)
    else:
        lines.append("- (none)")
    lines.append("TOC headings from marker metadata:")
    if toc_titles:
        lines.extend(f"- {title}" for title in toc_titles)
    else:
        lines.append("- (none)")
    return "\n".join(lines)


def build_llm_input(doc_text: str, visual_context: str, text_limit: int = 36000) -> str:
    text = doc_text[:text_limit]
    return (
        "You are ingesting a DnD adventure into a structured campaign database.\n"
        "Place data by semantic meaning (NPCs, scenes, regions, hooks).\n"
        "Use visual/map clues from filenames and TOC headings when deciding scenes/regions.\n\n"
        f"{visual_context}\n\n"
        "ADVENTURE TEXT START\n"
        f"{text}\n"
        "ADVENTURE TEXT END\n"
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
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
        CREATE TABLE IF NOT EXISTS comp_entities (
          id INTEGER PRIMARY KEY,
          entity_type TEXT NOT NULL,
          name TEXT NOT NULL,
          slug TEXT,
          aliases_json TEXT,
          raw_json TEXT,
          section_id INTEGER REFERENCES comp_sections(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS map_scenes (
          id INTEGER PRIMARY KEY,
          external_scene_id TEXT UNIQUE,
          name TEXT,
          width INTEGER,
          height INTEGER,
          grid_size INTEGER,
          map_file_path TEXT,
          map_file_name TEXT,
          image_hash TEXT,
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
          region_key TEXT NOT NULL,
          region_name TEXT,
          geometry_json TEXT NOT NULL,
          tags_json TEXT,
          UNIQUE(scene_id, region_key)
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
        """
    )
    conn.commit()


def call_xai_chat(api_key: str, payload: dict[str, Any], retries: int = 2) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        XAI_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    last_err: Exception | None = None
    for _ in range(retries + 1):
        try:
            with urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if "choices" not in data:
                raise RuntimeError(f"xAI response missing choices: {_format_xai_error_payload(data)}")
            return data
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""
            payload_err = _safe_json_loads(body)
            detail = _format_xai_error_payload(payload_err) if payload_err else body[:400]
            last_err = RuntimeError(f"HTTP {exc.code} from xAI: {detail}")
            # 4xx are typically non-retriable request issues.
            if 400 <= int(exc.code) < 500:
                break
            time.sleep(1.5)
        except (URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError, RuntimeError) as exc:
            last_err = exc
            time.sleep(1.5)
    raise RuntimeError(f"Grok call failed: {last_err}")


def _tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "upsert_map_config",
                "description": "Create or update a map scene from adventure text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scene_external_id": {"type": "string"},
                        "name": {"type": "string"},
                        "grid_size": {"type": "integer"},
                        "map_file_name": {"type": "string"},
                        "description": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["scene_external_id", "name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "upsert_map_region",
                "description": "Create or update a scene region polygon metadata record.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scene_external_id": {"type": "string"},
                        "region_key": {"type": "string"},
                        "region_name": {"type": "string"},
                        "geometry_json": {"type": "object"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["scene_external_id", "region_key", "geometry_json"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "upsert_npc",
                "description": "Create or update an NPC profile and personality.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string"},
                        "class_archetype": {"type": "string"},
                        "motivation": {"type": "string"},
                        "secrets": {"type": "array", "items": {"type": "string"}},
                        "traits": {"type": "array", "items": {"type": "string"}},
                        "ideals": {"type": "array", "items": {"type": "string"}},
                        "bonds": {"type": "array", "items": {"type": "string"}},
                        "flaws": {"type": "array", "items": {"type": "string"}},
                        "mannerisms": {"type": "array", "items": {"type": "string"}},
                        "languages": {"type": "array", "items": {"type": "string"}},
                        "features": {"type": "array", "items": {"type": "string"}},
                        "notes": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
        },
    ]


@dataclass
class ImportCounters:
    files: int = 0
    sections: int = 0
    chunks: int = 0
    npcs: int = 0
    scenes: int = 0
    regions: int = 0
    hooks: int = 0


def insert_rag_for_file(
    conn: sqlite3.Connection,
    source_id: int,
    path: Path,
    doc_title: str,
    chunk_chars: int,
    chunk_overlap: int,
) -> list[tuple[int, str, str]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cur = conn.execute(
        "INSERT INTO comp_documents (source_id, title, slug, hash) VALUES (?, ?, ?, ?)",
        (source_id, doc_title, slugify(doc_title), file_hash),
    )
    doc_id = cur.lastrowid
    section_refs: list[tuple[int, str, str]] = []
    for idx, (heading, body) in enumerate(split_sections(text), start=1):
        sec = conn.execute(
            "INSERT INTO comp_sections (document_id, section_path, heading) VALUES (?, ?, ?)",
            (doc_id, f"{idx}", heading),
        )
        section_id = sec.lastrowid
        section_refs.append((section_id, heading, body))
        for i, chunk in enumerate(chunk_text(body, chunk_chars, chunk_overlap), start=1):
            citation = f"{path.name} :: {heading} :: chunk {i}"
            conn.execute(
                "INSERT INTO comp_chunks (section_id, chunk_index, text, citation, token_count) VALUES (?, ?, ?, ?, ?)",
                (section_id, i, chunk, citation, estimate_token_count(chunk)),
            )
    return section_refs


def upsert_scene(conn: sqlite3.Connection, scene: dict[str, Any]) -> int:
    ext = scene.get("external_scene_id") or f"scene:{slugify(scene.get('name', 'unnamed'))}"
    name = scene.get("name")
    grid_size = scene.get("grid_size")
    map_file_name = scene.get("map_file_name")
    config_json = json_dumps(
        {
            "description": scene.get("description"),
            "tags": scene.get("tags", []),
        }
    )
    conn.execute(
        """
        INSERT INTO map_scenes (external_scene_id, name, grid_size, map_file_name, config_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(external_scene_id) DO UPDATE SET
          name=excluded.name,
          grid_size=coalesce(excluded.grid_size, map_scenes.grid_size),
          map_file_name=coalesce(excluded.map_file_name, map_scenes.map_file_name),
          config_json=excluded.config_json,
          updated_at=CURRENT_TIMESTAMP
        """,
        (ext, name, grid_size, map_file_name, config_json),
    )
    row = conn.execute("SELECT id FROM map_scenes WHERE external_scene_id=?", (ext,)).fetchone()
    return int(row[0])


def upsert_region(conn: sqlite3.Connection, region: dict[str, Any], scene_id: int) -> None:
    region_key = region.get("region_key") or slugify(region.get("region_name", "region"))
    region_name = region.get("region_name")
    geometry = region.get("geometry_json") or {}
    tags = region.get("tags") or []
    conn.execute(
        """
        INSERT INTO map_regions (scene_id, region_key, region_name, geometry_json, tags_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(scene_id, region_key) DO UPDATE SET
          region_name=excluded.region_name,
          geometry_json=excluded.geometry_json,
          tags_json=excluded.tags_json
        """,
        (scene_id, region_key, region_name, json_dumps(geometry), json_dumps(tags)),
    )


def upsert_npc(conn: sqlite3.Connection, npc: dict[str, Any]) -> None:
    name = (npc.get("name") or "").strip()
    if not name:
        return
    external_id = f"npc:{slugify(name)}"
    notes = npc.get("notes")
    conn.execute(
        """
        INSERT INTO camp_characters (external_id, name, is_player, notes)
        VALUES (?, ?, 0, ?)
        ON CONFLICT(external_id) DO UPDATE SET
          name=excluded.name,
          notes=coalesce(excluded.notes, camp_characters.notes)
        """,
        (external_id, name, notes),
    )
    row = conn.execute("SELECT id FROM camp_characters WHERE external_id=?", (external_id,)).fetchone()
    cid = int(row[0])
    conn.execute(
        """
        INSERT INTO npc_profiles (npc_character_id, class_archetype, role, motivation_text, secrets_text, languages_json, features_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(npc_character_id) DO UPDATE SET
          class_archetype=excluded.class_archetype,
          role=excluded.role,
          motivation_text=excluded.motivation_text,
          secrets_text=excluded.secrets_text,
          languages_json=excluded.languages_json,
          features_json=excluded.features_json
        """,
        (
            cid,
            npc.get("class_archetype"),
            npc.get("role"),
            npc.get("motivation"),
            json_dumps(npc.get("secrets", [])),
            json_dumps(npc.get("languages", [])),
            json_dumps(npc.get("features", [])),
        ),
    )
    conn.execute(
        """
        INSERT INTO npc_personality (npc_character_id, personality_traits_json, ideals_json, bonds_json, flaws_json, mannerisms_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(npc_character_id) DO UPDATE SET
          personality_traits_json=excluded.personality_traits_json,
          ideals_json=excluded.ideals_json,
          bonds_json=excluded.bonds_json,
          flaws_json=excluded.flaws_json,
          mannerisms_json=excluded.mannerisms_json
        """,
        (
            cid,
            json_dumps(npc.get("traits", [])),
            json_dumps(npc.get("ideals", [])),
            json_dumps(npc.get("bonds", [])),
            json_dumps(npc.get("flaws", [])),
            json_dumps(npc.get("mannerisms", [])),
        ),
    )


def run_tool_call_provisioning(
    conn: sqlite3.Connection,
    api_key: str,
    model: str,
    text: str,
    dry_run: bool,
    max_rounds: int = 10,
) -> dict[str, Any]:
    system_prompt = (
        "You are a data provisioning agent for D&D campaign ingestion. "
        "Use tool calls to insert/update entities from the provided adventure text. "
        "Reason about where each piece belongs in the DB schema before calling a tool. "
        "Prefer high-confidence entities only. "
        "After tool calls, return a compact JSON object with keys: summary, hooks. "
        "hooks should be an array of {title, summary, trigger}."
    )
    tools = _tool_defs()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]
    counters = {"npcs": 0, "scenes": 0, "regions": 0}
    hooks: list[dict[str, Any]] = []

    for _ in range(max_rounds):
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
        }
        data = call_xai_chat(api_key, payload)
        msg = data["choices"][0]["message"]
        messages.append(msg)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            content = (msg.get("content") or "").strip()
            if content:
                try:
                    parsed = json.loads(re.sub(r"^```json\s*|\s*```$", "", content, flags=re.IGNORECASE | re.MULTILINE))
                    if isinstance(parsed, dict) and isinstance(parsed.get("hooks"), list):
                        hooks = parsed["hooks"]
                except json.JSONDecodeError:
                    pass
            break

        for call in tool_calls:
            fn = call["function"]["name"]
            call_id = call["id"]
            args_raw = call["function"].get("arguments") or "{}"
            try:
                args = json.loads(args_raw)
            except json.JSONDecodeError:
                args = {}
            result: dict[str, Any]
            try:
                if fn == "upsert_npc":
                    if not dry_run:
                        upsert_npc(conn, args)
                    counters["npcs"] += 1
                    result = {"status": "ok", "tool": fn, "name": args.get("name")}
                elif fn == "upsert_map_config":
                    scene = {
                        "external_scene_id": args.get("scene_external_id"),
                        "name": args.get("name"),
                        "grid_size": args.get("grid_size"),
                        "map_file_name": args.get("map_file_name"),
                        "description": args.get("description"),
                        "tags": args.get("tags", []),
                    }
                    sid = None
                    if not dry_run:
                        sid = upsert_scene(conn, scene)
                    counters["scenes"] += 1
                    result = {"status": "ok", "tool": fn, "scene_external_id": scene["external_scene_id"], "scene_id": sid}
                elif fn == "upsert_map_region":
                    ext = args.get("scene_external_id")
                    row = conn.execute("SELECT id FROM map_scenes WHERE external_scene_id=?", (ext,)).fetchone()
                    if row is None:
                        result = {"status": "error", "tool": fn, "error": f"scene not found: {ext}"}
                    else:
                        if not dry_run:
                            upsert_region(conn, args, int(row[0]))
                        counters["regions"] += 1
                        result = {"status": "ok", "tool": fn, "region_key": args.get("region_key")}
                else:
                    result = {"status": "error", "tool": fn, "error": "unknown tool"}
            except Exception as exc:  # defensive: keep loop going
                result = {"status": "error", "tool": fn, "error": str(exc)}

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return {"counts": counters, "hooks": hooks}


def main() -> int:
    ap = argparse.ArgumentParser(description="Import marker-pdf output into OgresVTT using Grok extraction.")
    ap.add_argument("--marker-dir", required=True, help="Directory produced by marker_single.")
    ap.add_argument("--db-path", default=None, help="SQLite DB path (default from AI_DM_DB_PATH or ai_dm/data/dm.sqlite).")
    ap.add_argument("--source-title", default=None, help="Compendium source title.")
    ap.add_argument("--edition", default="5.5e", help="Edition label for compendium source.")
    ap.add_argument("--version", default="marker-pdf", help="Source version metadata.")
    ap.add_argument("--chunk-chars", type=int, default=1200, help="Chunk size for RAG inserts.")
    ap.add_argument("--chunk-overlap", type=int, default=150, help="Chunk overlap for RAG inserts.")
    ap.add_argument("--max-files", type=int, default=0, help="Limit input file count (0 = all).")
    ap.add_argument("--model", default=None, help="Grok model override.")
    ap.add_argument("--fallback-model", default=None, help="Fallback model if primary model request fails.")
    ap.add_argument("--dotenv", default=None, help="Path to env file (default .env.local).")
    ap.add_argument("--skip-grok", action="store_true", help="Ingest text only; skip Grok extraction.")
    ap.add_argument("--dry-run", action="store_true", help="No DB writes.")
    ap.add_argument("--legacy-json-mode", action="store_true", help="Use old JSON extraction path instead of tool calls.")
    args = ap.parse_args()

    marker_dir = Path(args.marker_dir)
    if not marker_dir.exists() or not marker_dir.is_dir():
        print(f"error: marker dir not found: {marker_dir}", file=sys.stderr)
        return 2

    env = load_env(Path(args.dotenv) if args.dotenv else None)
    api_key = env.get("XAI_API_KEY") or env.get("GROK_API_KEY") or env.get("AI_DM_GROK_API_KEY")
    # Prefer a cost-efficient reasoning model for importer cognition, then fallback.
    model = (
        args.model
        or env.get("AI_DM_GROK_IMPORT_MODEL")
        or env.get("AI_DM_GROK_MODEL")
        or env.get("GROK_MODEL")
        or env.get("XAI_MODEL")
        or "grok-4-fast-reasoning"
    )
    fallback_model = args.fallback_model or env.get("AI_DM_GROK_IMPORT_FALLBACK_MODEL") or "grok-3-mini"
    db_path = args.db_path or env.get("AI_DM_DB_PATH") or str(Path("ai_dm") / "data" / "dm.sqlite")
    source_title = args.source_title or marker_dir.name
    visual_context = build_visual_context(marker_dir)

    files = sorted(
        [p for p in marker_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"}]
    )
    if args.max_files > 0:
        files = files[: args.max_files]
    if not files:
        print("error: no .md/.txt files found in marker dir", file=sys.stderr)
        return 2
    if not args.skip_grok and not api_key:
        print("error: missing Grok API key (XAI_API_KEY / GROK_API_KEY / AI_DM_GROK_API_KEY)", file=sys.stderr)
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)

    counters = ImportCounters()
    extracted_bundle: list[dict[str, Any]] = []
    source_id = None

    if not args.dry_run:
        cur = conn.execute(
            "INSERT INTO comp_sources (title, edition, version) VALUES (?, ?, ?)",
            (source_title, args.edition, args.version),
        )
        source_id = int(cur.lastrowid)

    for path in files:
        counters.files += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        sections = split_sections(text)
        counters.sections += len(sections)

        if not args.dry_run:
            section_refs = insert_rag_for_file(
                conn=conn,
                source_id=source_id,
                path=path,
                doc_title=path.stem,
                chunk_chars=args.chunk_chars,
                chunk_overlap=args.chunk_overlap,
            )
            for _sid, _heading, body in section_refs:
                counters.chunks += len(chunk_text(body, args.chunk_chars, args.chunk_overlap))

        if args.skip_grok:
            continue

        # Use a bounded payload to control cost and context size.
        grok_input = build_llm_input(text, visual_context)
        if args.legacy_json_mode:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract D&D campaign entities from adventure text. "
                            "Return strict JSON only with keys: npcs, scenes, map_regions, hooks."
                        ),
                    },
                    {"role": "user", "content": grok_input},
                ],
                "temperature": 0.1,
            }
            try:
                data = call_xai_chat(api_key, payload)
            except RuntimeError:
                payload["model"] = fallback_model
                data = call_xai_chat(api_key, payload)
            parsed = _extract_message_json_dict(data)
            npcs = parsed.get("npcs", []) if isinstance(parsed.get("npcs", []), list) else []
            scenes = parsed.get("scenes", []) if isinstance(parsed.get("scenes", []), list) else []
            regions = parsed.get("map_regions", []) if isinstance(parsed.get("map_regions", []), list) else []
            hooks = parsed.get("hooks", []) if isinstance(parsed.get("hooks", []), list) else []
            counters.npcs += len(npcs)
            counters.scenes += len(scenes)
            counters.regions += len(regions)
            counters.hooks += len(hooks)
            if not args.dry_run:
                for scene in scenes:
                    upsert_scene(conn, scene)
                for npc in npcs:
                    upsert_npc(conn, npc)
                for region in regions:
                    ext = region.get("scene_external_id")
                    if not ext:
                        continue
                    row = conn.execute("SELECT id FROM map_scenes WHERE external_scene_id=?", (ext,)).fetchone()
                    if row is not None:
                        upsert_region(conn, region, int(row[0]))
        else:
            try:
                result = run_tool_call_provisioning(
                    conn=conn,
                    api_key=api_key,
                    model=model,
                    text=grok_input,
                    dry_run=args.dry_run,
                )
            except RuntimeError as exc:
                print(
                    f"warning: tool-call provisioning failed on model={model} ({exc}); trying fallback model={fallback_model}",
                    file=sys.stderr,
                )
                try:
                    result = run_tool_call_provisioning(
                        conn=conn,
                        api_key=api_key,
                        model=fallback_model,
                        text=grok_input,
                        dry_run=args.dry_run,
                    )
                except RuntimeError as exc2:
                    print(
                        f"warning: fallback tool-calling also failed ({exc2}); falling back to legacy JSON mode",
                        file=sys.stderr,
                    )
                    payload = {
                        "model": fallback_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Extract D&D campaign entities from adventure text. "
                                    "Return strict JSON only with keys: npcs, scenes, map_regions, hooks."
                                ),
                            },
                            {"role": "user", "content": grok_input},
                        ],
                        "temperature": 0.1,
                    }
                    data = call_xai_chat(api_key, payload)
                    parsed = _extract_message_json_dict(data)
                    npcs = parsed.get("npcs", []) if isinstance(parsed.get("npcs", []), list) else []
                    scenes = parsed.get("scenes", []) if isinstance(parsed.get("scenes", []), list) else []
                    regions = parsed.get("map_regions", []) if isinstance(parsed.get("map_regions", []), list) else []
                    hooks = parsed.get("hooks", []) if isinstance(parsed.get("hooks", []), list) else []
                    counters.npcs += len(npcs)
                    counters.scenes += len(scenes)
                    counters.regions += len(regions)
                    counters.hooks += len(hooks)
                    if not args.dry_run:
                        for scene in scenes:
                            upsert_scene(conn, scene)
                        for npc in npcs:
                            upsert_npc(conn, npc)
                        for region in regions:
                            ext = region.get("scene_external_id")
                            if not ext:
                                continue
                            row = conn.execute("SELECT id FROM map_scenes WHERE external_scene_id=?", (ext,)).fetchone()
                            if row is not None:
                                upsert_region(conn, region, int(row[0]))
                    extracted_bundle.append(
                        {
                            "source_file": str(path),
                            "npcs": npcs,
                            "scenes": scenes,
                            "map_regions": regions,
                            "hooks": hooks,
                        }
                    )
                    print(
                        f"[file] {path.name}: sections={len(sections)} npcs={len(npcs)} scenes={len(scenes)} regions={len(regions)} hooks={len(hooks)}"
                    )
                    continue
            hooks = result.get("hooks", [])
            counts = result.get("counts", {})
            counters.npcs += int(counts.get("npcs", 0))
            counters.scenes += int(counts.get("scenes", 0))
            counters.regions += int(counts.get("regions", 0))
            counters.hooks += len(hooks)
            npcs = []
            scenes = []
            regions = []

        extracted_bundle.append(
            {
                "source_file": str(path),
                "npcs": npcs if args.legacy_json_mode else None,
                "scenes": scenes if args.legacy_json_mode else None,
                "map_regions": regions if args.legacy_json_mode else None,
                "hooks": hooks,
            }
        )
        print(
            f"[file] {path.name}: sections={len(sections)} npcs={len(npcs)} scenes={len(scenes)} regions={len(regions)} hooks={len(hooks)}"
        )

    out_path = marker_dir / "ogres_import_extracted.json"
    out_path.write_text(json.dumps(extracted_bundle, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.dry_run:
        conn.rollback()
    else:
        conn.commit()
    conn.close()

    print("")
    print("Import complete")
    print(f"  files: {counters.files}")
    print(f"  sections: {counters.sections}")
    print(f"  chunks: {counters.chunks}")
    print(f"  npcs: {counters.npcs}")
    print(f"  scenes: {counters.scenes}")
    print(f"  regions: {counters.regions}")
    print(f"  hooks: {counters.hooks}")
    print(f"  db: {db_path}")
    print(f"  extracted-json: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
