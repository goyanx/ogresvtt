"""
AI Dungeon Master FastAPI sidecar.

Endpoints:
  POST /dm/turn   — LangGraph multi-step turn (returns tool calls + narration)
  POST /dm/speak  — Kokoro TTS (returns WAV audio bytes)
  GET  /dm/voices — List available TTS voices
  GET  /health

Admin:
  GET  /dm-admin
  GET  /dm-admin/api/tables
  GET  /dm-admin/api/table/{name}
  POST /dm-admin/api/query

Start with:
  uvicorn ai_dm.main:app --port 8765 --reload
"""
from __future__ import annotations

import functools
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from ai_dm.backends import grok, ollama
from ai_dm.db import get_conn, init_db, list_tables, resolve_db_path
from ai_dm.graph import build_graph
from ai_dm.logging_config import configure_logging


TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
READONLY_SQL_RE = re.compile(r"^\s*(select|with|pragma|explain)\b", re.IGNORECASE)


def _load_env_files() -> None:
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".env.local",
        Path.cwd() / ".env",
        here.parent / ".env.local",
        here.parent / ".env",
        here.parents[1] / ".env.local",
        here.parents[1] / ".env",
    ]
    for env_file in candidates:
        if env_file.exists():
            load_dotenv(env_file, override=False)


def _env_first(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


def _allow_admin_write() -> bool:
    raw = os.getenv("AI_DM_ADMIN_ALLOW_WRITE", "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _validate_table_name(name: str) -> str:
    if not TABLE_NAME_RE.match(name):
        raise HTTPException(status_code=400, detail="invalid table name")
    return name


def _is_read_only_sql(sql: str) -> bool:
    return bool(READONLY_SQL_RE.match(sql or ""))


def _get_or_create_scene(conn, scene_external_id: str) -> int:
    row = conn.execute(
        "SELECT id FROM map_scenes WHERE external_scene_id=? LIMIT 1", (scene_external_id,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO map_scenes (external_scene_id, name) VALUES (?, ?)",
        (scene_external_id, scene_external_id),
    )
    return cur.lastrowid


_load_env_files()
log_path = configure_logging()
logger = logging.getLogger("ai_dm.main")
DB_PATH = init_db()
ADMIN_HTML_PATH = Path(__file__).resolve().parent / "static" / "dm_admin.html"

DEFAULT_OLLAMA_ENDPOINT = _env_first(
    "AI_DM_OLLAMA_ENDPOINT", "OLLAMA_ENDPOINT", default="http://localhost:11434"
)
DEFAULT_OLLAMA_MODEL = _env_first(
    "AI_DM_OLLAMA_MODEL", "OLLAMA_MODEL", default="qwen2.5:14b-instruct-q4_K_M"
)
DEFAULT_GROK_MODEL = _env_first(
    "AI_DM_GROK_MODEL", "GROK_MODEL", "XAI_MODEL", default="grok-3-mini"
)
DEFAULT_BACKEND = _env_first("AI_DM_DEFAULT_BACKEND", default="ollama").strip().lower()

app = FastAPI(title="AI DM LangGraph Sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    logger.info("AI DM sidecar startup complete log_file=%s db=%s", log_path, DB_PATH)


@app.middleware("http")
async def _request_logging(request: Request, call_next):
    response = await call_next(request)
    logger.info(
        "request completed method=%s path=%s status=%s",
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


# ---------------------------------------------------------------------------
# /dm/turn
# ---------------------------------------------------------------------------

class TurnRequest(BaseModel):
    backend: str = ""
    endpoint: str = ""
    model: str = ""
    api_key: str = ""
    scenario: str = ""
    game_state: str = ""
    history: list[dict] = []


class TurnResponse(BaseModel):
    tool_calls: list[dict]
    narration: str
    validation_errors: list[str]
    retry_count: int


@app.post("/dm/turn", response_model=TurnResponse)
async def dm_turn(req: TurnRequest):
    backend = (req.backend or DEFAULT_BACKEND or "ollama").strip().lower()
    if backend == "ollama":
        endpoint = (req.endpoint or DEFAULT_OLLAMA_ENDPOINT).strip()
        model = (req.model or DEFAULT_OLLAMA_MODEL).strip()
        llm_call = functools.partial(
            ollama.chat_completion, endpoint=endpoint, model=model
        )
    elif backend == "grok":
        api_key = (
            req.api_key
            or _env_first("XAI_API_KEY", "GROK_API_KEY", "AI_DM_GROK_API_KEY")
        ).strip()
        model = (req.model or DEFAULT_GROK_MODEL).strip()
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key required for grok backend")
        llm_call = functools.partial(
            grok.chat_completion, api_key=api_key, model=model
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {req.backend}")

    logger.info(
        "dm_turn start backend=%s model=%s endpoint=%s history_count=%s game_state_chars=%s",
        backend,
        model,
        endpoint if backend == "ollama" else "-",
        len(req.history),
        len(req.game_state or ""),
    )

    graph = build_graph(llm_call)
    initial_state = {
        "scenario": req.scenario,
        "game_state": req.game_state,
        "history": req.history,
        "plan": "",
        "tool_calls": [],
        "validation_errors": [],
        "retry_count": 0,
        "narration": "",
        "combat_mode": False,
    }

    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception as exc:
        logger.exception("dm_turn failed backend=%s model=%s endpoint=%s", backend, model, req.endpoint)
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "dm_turn success tool_calls=%s validation_errors=%s retry_count=%s narration_chars=%s",
        len(final_state["tool_calls"]),
        len(final_state["validation_errors"]),
        final_state["retry_count"],
        len(final_state["narration"] or ""),
    )

    return TurnResponse(
        tool_calls=final_state["tool_calls"],
        narration=final_state["narration"],
        validation_errors=final_state["validation_errors"],
        retry_count=final_state["retry_count"],
    )


# ---------------------------------------------------------------------------
# /dm/speak  — Kokoro TTS
# ---------------------------------------------------------------------------

class SpeakRequest(BaseModel):
    text: str
    voice: str = "bm_george"
    speed: float = 0.95


@app.post("/dm/speak")
async def dm_speak(req: SpeakRequest):
    import asyncio
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")
    try:
        from ai_dm.tts import synthesize
        loop = asyncio.get_event_loop()
        wav_bytes = await loop.run_in_executor(
            None, synthesize, req.text, req.voice, req.speed
        )
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Kokoro TTS not installed. Run: pip install kokoro soundfile",
        )
    except Exception as exc:
        logger.exception("dm_speak failed")
        raise HTTPException(status_code=500, detail=str(exc))

    return Response(content=wav_bytes, media_type="audio/wav")


@app.get("/dm/voices")
def dm_voices():
    try:
        from ai_dm.tts import AVAILABLE_VOICES
        return {"voices": AVAILABLE_VOICES}
    except ImportError:
        return {"voices": [], "error": "kokoro not installed"}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    tts_available = True
    try:
        import kokoro  # noqa: F401
    except ImportError:
        tts_available = False
    return {
        "status": "ok",
        "tts": tts_available,
        "defaults": {
            "ollama_endpoint": DEFAULT_OLLAMA_ENDPOINT,
            "ollama_model": DEFAULT_OLLAMA_MODEL,
            "grok_model": DEFAULT_GROK_MODEL,
        },
        "db": {
            "path": str(resolve_db_path()),
            "admin_write_enabled": _allow_admin_write(),
        },
    }


# ---------------------------------------------------------------------------
# /dm-admin
# ---------------------------------------------------------------------------

class AdminQueryRequest(BaseModel):
    sql: str


class MapConfigRequest(BaseModel):
    scene_external_id: str
    name: str | None = None
    map_file_path: str | None = None
    map_file_name: str | None = None
    image_hash: str | None = None
    width: int | None = None
    height: int | None = None
    grid_size: int | None = None
    offset_x: float | None = None
    offset_y: float | None = None
    show_grid: bool | None = None
    dark_mode: bool | None = None
    grid_align: bool | None = None
    show_object_outlines: bool | None = None
    lighting: str | None = None
    config_json: str | None = None


class MapRegionRequest(BaseModel):
    scene_external_id: str
    region_key: str
    region_name: str | None = None
    geometry_json: dict | str
    tags_json: dict | str | None = None


@app.get("/dm-admin", response_class=HTMLResponse)
def dm_admin_page():
    if not ADMIN_HTML_PATH.exists():
        raise HTTPException(status_code=500, detail="admin page not found")
    return HTMLResponse(content=ADMIN_HTML_PATH.read_text(encoding="utf-8"))


@app.get("/dm-admin/api/tables")
def dm_admin_tables():
    return {
        "db_path": str(resolve_db_path()),
        "admin_write_enabled": _allow_admin_write(),
        "tables": list_tables(),
    }


@app.get("/dm-admin/api/table/{table_name}")
def dm_admin_table_rows(table_name: str, limit: int = 100, offset: int = 0):
    table = _validate_table_name(table_name)
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    sql = f"SELECT * FROM {table} LIMIT ? OFFSET ?"
    try:
        with get_conn() as conn:
            rows = conn.execute(sql, (limit, offset)).fetchall()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "table": table,
        "limit": limit,
        "offset": offset,
        "row_count": len(rows),
        "rows": [dict(r) for r in rows],
    }

@app.get("/dm-admin/api/maps")
def dm_admin_maps(limit: int = 200):
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM map_scenes ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"count": len(rows), "maps": [dict(r) for r in rows]}


@app.post("/dm-admin/api/maps/upsert")
def dm_admin_maps_upsert(req: MapConfigRequest):
    payload = req.model_dump()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM map_scenes WHERE external_scene_id=? LIMIT 1",
            (payload["scene_external_id"],),
        ).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO map_scenes (external_scene_id, name) VALUES (?, ?)",
                (payload["scene_external_id"], payload.get("name") or payload["scene_external_id"]),
            )
            scene_id = cur.lastrowid
        else:
            scene_id = row["id"]

        conn.execute(
            """
            UPDATE map_scenes
            SET name=coalesce(?, name),
                map_file_path=coalesce(?, map_file_path),
                map_file_name=coalesce(?, map_file_name),
                image_hash=coalesce(?, image_hash),
                width=coalesce(?, width),
                height=coalesce(?, height),
                grid_size=coalesce(?, grid_size),
                offset_x=coalesce(?, offset_x),
                offset_y=coalesce(?, offset_y),
                show_grid=coalesce(?, show_grid),
                dark_mode=coalesce(?, dark_mode),
                grid_align=coalesce(?, grid_align),
                show_object_outlines=coalesce(?, show_object_outlines),
                lighting=coalesce(?, lighting),
                config_json=coalesce(?, config_json),
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                payload.get("name"),
                payload.get("map_file_path"),
                payload.get("map_file_name"),
                payload.get("image_hash"),
                payload.get("width"),
                payload.get("height"),
                payload.get("grid_size"),
                payload.get("offset_x"),
                payload.get("offset_y"),
                1 if payload.get("show_grid") is True else 0 if payload.get("show_grid") is False else None,
                1 if payload.get("dark_mode") is True else 0 if payload.get("dark_mode") is False else None,
                1 if payload.get("grid_align") is True else 0 if payload.get("grid_align") is False else None,
                1 if payload.get("show_object_outlines") is True else 0 if payload.get("show_object_outlines") is False else None,
                payload.get("lighting"),
                payload.get("config_json"),
                scene_id,
            ),
        )
        row = conn.execute("SELECT * FROM map_scenes WHERE id=?", (scene_id,)).fetchone()
    return {"status": "ok", "scene": dict(row)}


@app.post("/dm-admin/api/regions/upsert")
def dm_admin_regions_upsert(req: MapRegionRequest):
    payload = req.model_dump()
    ext_id = (payload.get("scene_external_id") or "").strip()
    region_key = (payload.get("region_key") or "").strip()
    if not ext_id:
        raise HTTPException(status_code=400, detail="scene_external_id is required")
    if not region_key:
        raise HTTPException(status_code=400, detail="region_key is required")

    geometry = payload.get("geometry_json")
    tags = payload.get("tags_json")
    geometry_json = geometry if isinstance(geometry, str) else json.dumps(geometry)
    tags_json = tags if isinstance(tags, str) else (json.dumps(tags) if tags is not None else None)
    region_name = payload.get("region_name") or region_key

    with get_conn() as conn:
        scene_id = _get_or_create_scene(conn, ext_id)
        row = conn.execute(
            "SELECT id FROM map_regions WHERE scene_id=? AND region_key=? LIMIT 1",
            (scene_id, region_key),
        ).fetchone()
        if row is None:
            cur = conn.execute(
                """
                INSERT INTO map_regions (scene_id, region_key, region_name, geometry_json, tags_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scene_id, region_key, region_name, geometry_json, tags_json),
            )
            region_id = cur.lastrowid
        else:
            region_id = row["id"]
            conn.execute(
                """
                UPDATE map_regions
                SET region_name=coalesce(?, region_name),
                    geometry_json=coalesce(?, geometry_json),
                    tags_json=coalesce(?, tags_json)
                WHERE id=?
                """,
                (region_name, geometry_json, tags_json, region_id),
            )

        region = conn.execute("SELECT * FROM map_regions WHERE id=?", (region_id,)).fetchone()
    return {"status": "ok", "region": dict(region)}



@app.post("/dm-admin/api/query")
def dm_admin_query(req: AdminQueryRequest):
    sql = (req.sql or "").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="sql must not be empty")
    if ";" in sql[:-1]:
        raise HTTPException(status_code=400, detail="multiple statements are not allowed")

    write_mode = _allow_admin_write()
    if not write_mode and not _is_read_only_sql(sql):
        raise HTTPException(
            status_code=403,
            detail="write queries disabled. Set AI_DM_ADMIN_ALLOW_WRITE=true to enable",
        )

    try:
        with get_conn() as conn:
            cur = conn.execute(sql)
            if cur.description is None:
                conn.commit()
                return {"write": True, "row_count": cur.rowcount, "rows": []}
            rows = [dict(r) for r in cur.fetchall()]
            return {"write": False, "row_count": len(rows), "rows": rows}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
