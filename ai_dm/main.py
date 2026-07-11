"""
AI Dungeon Master FastAPI sidecar.

Endpoints:
  POST /dm/turn   — LangGraph multi-step turn (returns tool calls + narration)
  POST /dm/speak  — Kokoro TTS (returns WAV audio bytes)
  POST /dm/comfy/generate — Queue/poll ComfyUI workflow and return output image URLs
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

import asyncio
import functools
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import urlencode

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
import httpx
from pydantic import BaseModel

from ai_dm.backends import grok, ollama
from ai_dm.db import get_conn, init_db, list_tables, resolve_db_path
from ai_dm.graph import build_graph, build_image_prompt_graph
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


def _extract_current_turn_context(game_state: str) -> tuple[int | None, str | None, bool | None]:
    text = game_state or ""
    turn_id_match = re.search(r"CURRENT TURN ID:\s*(\d+)", text)
    turn_id = int(turn_id_match.group(1)) if turn_id_match else None
    if turn_id is None:
        return (None, None, None)

    # Initiative lines are serialized as:
    # - id: 17, label: "Algoreth", roll: 16, flags: [player], current_turn: true
    line_match = re.search(
        rf"^\s*-\s*id:\s*{turn_id}\s*,\s*label:\s*\"([^\"]*)\"(?P<rest>.*)$",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if not line_match:
        return (turn_id, None, None)
    label = line_match.group(1) or None
    rest = line_match.group("rest") or ""
    is_player = bool(re.search(r"flags:\s*\[[^\]]*\bplayer\b[^\]]*\]", rest, flags=re.IGNORECASE))
    return (turn_id, label, is_player)


def _normalize_base_url(url: str | None, fallback: str) -> str:
    value = (url or fallback or "").strip()
    return value.rstrip("/")


def _load_workflow_payload(workflow: dict | str | None) -> dict:
    if workflow is None:
        raise HTTPException(status_code=400, detail="workflow is required")
    if isinstance(workflow, dict):
        return workflow
    if not isinstance(workflow, str):
        raise HTTPException(status_code=400, detail="workflow must be an object or JSON/path string")

    raw = workflow.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="workflow must not be empty")

    if raw.startswith("{") or raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"workflow JSON parse failed: {exc}") from exc
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="workflow JSON root must be an object")
        return parsed

    path = Path(raw)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"workflow file not found: {raw}")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to read workflow file: {exc}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="workflow file root must be an object")
    return parsed


def _resolve_llm_call(
    *,
    backend: str,
    endpoint: str,
    model: str,
    api_key: str,
):
    resolved_backend = (backend or DEFAULT_BACKEND or "ollama").strip().lower()
    if resolved_backend == "ollama":
        resolved_endpoint = (endpoint or DEFAULT_OLLAMA_ENDPOINT).strip()
        resolved_model = (model or DEFAULT_OLLAMA_MODEL).strip()
        llm_call = functools.partial(
            ollama.chat_completion, endpoint=resolved_endpoint, model=resolved_model
        )
        return llm_call, resolved_backend, resolved_endpoint, resolved_model
    if resolved_backend == "grok":
        resolved_api_key = (
            api_key
            or _env_first("XAI_API_KEY", "GROK_API_KEY", "AI_DM_GROK_API_KEY")
        ).strip()
        resolved_model = (model or DEFAULT_GROK_MODEL).strip()
        if not resolved_api_key:
            raise HTTPException(status_code=400, detail="api_key required for grok backend")
        llm_call = functools.partial(
            grok.chat_completion, api_key=resolved_api_key, model=resolved_model
        )
        return llm_call, resolved_backend, "-", resolved_model
    raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}")


def _replace_prompt_placeholders(value, positive: str, negative: str, source: str):
    if isinstance(value, str):
        replaced = (
            value.replace("{{prompt}}", positive)
            .replace("{{positive_prompt}}", positive)
            .replace("{{negative_prompt}}", negative)
            .replace("{{source_prompt}}", source)
        )
        return replaced, replaced != value
    if isinstance(value, list):
        changed = False
        out = []
        for item in value:
            next_item, item_changed = _replace_prompt_placeholders(item, positive, negative, source)
            out.append(next_item)
            changed = changed or item_changed
        return out, changed
    if isinstance(value, dict):
        changed = False
        out = {}
        for k, v in value.items():
            next_v, node_changed = _replace_prompt_placeholders(v, positive, negative, source)
            out[k] = next_v
            changed = changed or node_changed
        return out, changed
    return value, False


def _inject_prompts_heuristic(workflow: dict, positive: str, negative: str):
    if not isinstance(workflow, dict):
        return workflow, False

    text_slots: list[tuple[dict, str, str]] = []
    for node_key, node in workflow.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for field in ("text", "prompt", "positive_prompt", "negative_prompt"):
            if isinstance(inputs.get(field), str):
                text_slots.append((inputs, field, str(node_key).lower()))

    if not text_slots:
        return workflow, False

    # Prefer negative-ish slots for negative prompt when possible.
    negative_idx = None
    for idx, (_inputs, field, node_key) in enumerate(text_slots):
        if "neg" in field or "neg" in node_key:
            negative_idx = idx
            break

    # Always assign one positive slot.
    text_slots[0][0][text_slots[0][1]] = positive
    changed = True

    if negative:
        if negative_idx is not None:
            inputs, field, _ = text_slots[negative_idx]
            inputs[field] = negative
        elif len(text_slots) > 1:
            text_slots[1][0][text_slots[1][1]] = negative
    return workflow, changed


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def _apply_comfy_perf_overrides(
    workflow: dict,
    *,
    steps: int,
    width: int,
    height: int,
    batch_size: int,
    cfg: float,
    sampler_name: str,
    scheduler: str,
) -> dict:
    if not isinstance(workflow, dict):
        return workflow

    steps = _clamp_int(steps, 4, 80)
    width = _clamp_int(width, 256, 2048)
    height = _clamp_int(height, 256, 2048)
    # Most latent/image models prefer dimensions divisible by 64.
    width -= (width % 64)
    height -= (height % 64)
    batch_size = _clamp_int(batch_size, 1, 4)
    cfg = _clamp_float(cfg, 1.0, 20.0)

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        class_type = str(node.get("class_type", "")).lower()

        # Generic overrides when fields exist.
        if "steps" in inputs:
            inputs["steps"] = steps
        if "cfg" in inputs:
            inputs["cfg"] = cfg
        if "sampler_name" in inputs and sampler_name:
            inputs["sampler_name"] = sampler_name
        if "scheduler" in inputs and scheduler:
            inputs["scheduler"] = scheduler
        if "width" in inputs:
            inputs["width"] = width
        if "height" in inputs:
            inputs["height"] = height
        if "batch_size" in inputs:
            inputs["batch_size"] = batch_size

        # Node-specific sensible defaults.
        if "ksampler" in class_type:
            inputs.setdefault("steps", steps)
            inputs.setdefault("cfg", cfg)
            if sampler_name:
                inputs.setdefault("sampler_name", sampler_name)
            if scheduler:
                inputs.setdefault("scheduler", scheduler)
        if "latent" in class_type and "empty" in class_type:
            inputs.setdefault("width", width)
            inputs.setdefault("height", height)
            inputs.setdefault("batch_size", batch_size)

    return workflow


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
DEFAULT_COMFY_BASE_URL = _env_first(
    "AI_DM_COMFY_BASE_URL", "COMFY_BASE_URL", default="http://127.0.0.1:8188"
)
DEFAULT_COMFY_POLL_INTERVAL = float(_env_first("COMFY_POLL_INTERVAL", default="0.5"))
DEFAULT_COMFY_TIMEOUT_SECS = int(_env_first("COMFY_TIMEOUT_SECS", default="240"))
DEFAULT_COMFY_MODEL_FAMILY = _env_first(
    "AI_DM_COMFY_MODEL_FAMILY", default="flux"
).strip().lower()
DEFAULT_COMFY_STEPS = int(_env_first("AI_DM_COMFY_STEPS", default="16"))
DEFAULT_COMFY_WIDTH = int(_env_first("AI_DM_COMFY_WIDTH", default="832"))
DEFAULT_COMFY_HEIGHT = int(_env_first("AI_DM_COMFY_HEIGHT", default="512"))
DEFAULT_COMFY_BATCH_SIZE = int(_env_first("AI_DM_COMFY_BATCH_SIZE", default="1"))
DEFAULT_COMFY_CFG = float(_env_first("AI_DM_COMFY_CFG", default="3.2"))
DEFAULT_COMFY_SAMPLER = _env_first("AI_DM_COMFY_SAMPLER", default="euler")
DEFAULT_COMFY_SCHEDULER = _env_first("AI_DM_COMFY_SCHEDULER", default="normal")

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
    system_prompt: str = ""
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
    llm_call, backend, endpoint, model = _resolve_llm_call(
        backend=req.backend,
        endpoint=req.endpoint,
        model=req.model,
        api_key=req.api_key,
    )

    turn_id, turn_label, turn_is_player = _extract_current_turn_context(req.game_state or "")
    logger.info(
        "dm_turn start backend=%s model=%s endpoint=%s history_count=%s game_state_chars=%s turn_id=%s turn_label=%s turn_is_player=%s",
        backend,
        model,
        endpoint if backend == "ollama" else "-",
        len(req.history),
        len(req.game_state or ""),
        turn_id,
        turn_label or "-",
        turn_is_player,
    )

    graph = build_graph(llm_call)
    initial_state = {
        "system_prompt": req.system_prompt,
        "scenario": req.scenario,
        "game_state": req.game_state,
        "history": req.history,
        "plan": "",
        "tool_calls": [],
        "validation_errors": [],
        "retry_count": 0,
        "narration": "",
        "combat_mode": False,
        "response_mode": "npc",
        "response_mode_reason": "",
        "latest_player_message": "",
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
    if final_state["tool_calls"]:
        tool_names = [
            tc.get("function", {}).get("name", "")
            for tc in final_state["tool_calls"]
        ]
        logger.info("dm_turn tool_calls detail=%s", tool_names)
    if final_state["validation_errors"]:
        logger.warning(
            "dm_turn validation_errors detail=%s",
            final_state["validation_errors"],
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
# /dm/comfy/generate  — ComfyUI image generation via sidecar
# ---------------------------------------------------------------------------

class ComfyGenerateRequest(BaseModel):
    workflow: dict | str | None = None
    comfy_base_url: str = ""
    client_id: str = ""
    poll_interval: float | None = None
    timeout_secs: int | None = None
    prompt_text: str = ""
    prompt_style: str = ""
    prompt_model_family: str = ""
    game_state: str = ""
    llm_backend: str = ""
    llm_endpoint: str = ""
    llm_model: str = ""
    api_key: str = ""
    comfy_steps: int | None = None
    comfy_width: int | None = None
    comfy_height: int | None = None
    comfy_batch_size: int | None = None
    comfy_cfg: float | None = None
    comfy_sampler_name: str = ""
    comfy_scheduler: str = ""


class ComfyImage(BaseModel):
    filename: str
    subfolder: str
    type: str
    view_url: str


class ComfyGenerateResponse(BaseModel):
    prompt_id: str
    image_count: int
    source_prompt: str
    positive_prompt: str
    negative_prompt: str
    images: list[ComfyImage]


@app.post("/dm/comfy/generate", response_model=ComfyGenerateResponse)
async def dm_comfy_generate(req: ComfyGenerateRequest):
    workflow_prompt = _load_workflow_payload(req.workflow)
    comfy_base_url = _normalize_base_url(req.comfy_base_url, DEFAULT_COMFY_BASE_URL)
    client_id = (req.client_id or os.getenv("COMFY_CLIENT_ID", "ogresvtt-dm-sidecar")).strip()
    poll_interval = (
        float(req.poll_interval) if req.poll_interval is not None else DEFAULT_COMFY_POLL_INTERVAL
    )
    timeout_secs = int(req.timeout_secs) if req.timeout_secs is not None else DEFAULT_COMFY_TIMEOUT_SECS
    source_prompt = (req.prompt_text or "").strip()
    style_hint = (req.prompt_style or "").strip()
    game_state = req.game_state or ""
    model_family = (req.prompt_model_family or DEFAULT_COMFY_MODEL_FAMILY or "flux").strip().lower()
    comfy_steps = req.comfy_steps if req.comfy_steps is not None else DEFAULT_COMFY_STEPS
    comfy_width = req.comfy_width if req.comfy_width is not None else DEFAULT_COMFY_WIDTH
    comfy_height = req.comfy_height if req.comfy_height is not None else DEFAULT_COMFY_HEIGHT
    comfy_batch_size = (
        req.comfy_batch_size if req.comfy_batch_size is not None else DEFAULT_COMFY_BATCH_SIZE
    )
    comfy_cfg = req.comfy_cfg if req.comfy_cfg is not None else DEFAULT_COMFY_CFG
    comfy_sampler_name = (req.comfy_sampler_name or DEFAULT_COMFY_SAMPLER).strip()
    comfy_scheduler = (req.comfy_scheduler or DEFAULT_COMFY_SCHEDULER).strip()
    positive_prompt = source_prompt
    negative_prompt = ""

    if source_prompt:
        llm_call, llm_backend, llm_endpoint, llm_model = _resolve_llm_call(
            backend=req.llm_backend,
            endpoint=req.llm_endpoint,
            model=req.llm_model,
            api_key=req.api_key,
        )
        logger.info(
            "dm_comfy_generate prompt_transform start backend=%s model=%s endpoint=%s model_family=%s",
            llm_backend,
            llm_model,
            llm_endpoint,
            model_family,
        )
        prompt_graph = build_image_prompt_graph(llm_call)
        transformed = await prompt_graph.ainvoke(
            {
                "source_prompt": source_prompt,
                "style_hint": style_hint,
                "model_family": model_family,
                "game_state": game_state,
            }
        )
        positive_prompt = (transformed.get("positive_prompt") or source_prompt).strip()
        negative_prompt = (transformed.get("negative_prompt") or "").strip()
    if not positive_prompt:
        positive_prompt = (
            "safe-for-work fantasy adventure scene, heroic party, cinematic lighting, detailed environment"
        )
    if not negative_prompt:
        negative_prompt = (
            "nsfw, nudity, explicit sexual content, fetish, gore, graphic violence, text, watermark, logo"
        )

    # Apply transformed prompts to workflow:
    # 1) token placeholders if present, else 2) heuristic assignment.
    workflow_prompt, replaced = _replace_prompt_placeholders(
        workflow_prompt, positive_prompt, negative_prompt, source_prompt
    )
    if not replaced:
        workflow_prompt, _ = _inject_prompts_heuristic(
            workflow_prompt, positive_prompt, negative_prompt
        )
    workflow_prompt = _apply_comfy_perf_overrides(
        workflow_prompt,
        steps=comfy_steps,
        width=comfy_width,
        height=comfy_height,
        batch_size=comfy_batch_size,
        cfg=comfy_cfg,
        sampler_name=comfy_sampler_name,
        scheduler=comfy_scheduler,
    )

    logger.info(
        "dm_comfy_generate start comfy_base_url=%s client_id=%s timeout_secs=%s poll_interval=%s source_prompt_chars=%s steps=%s size=%sx%s batch=%s cfg=%s sampler=%s scheduler=%s",
        comfy_base_url,
        client_id,
        timeout_secs,
        poll_interval,
        len(source_prompt),
        comfy_steps,
        comfy_width,
        comfy_height,
        comfy_batch_size,
        comfy_cfg,
        comfy_sampler_name,
        comfy_scheduler,
    )

    timeout = httpx.Timeout(timeout_secs)
    queue_payload = {"prompt": workflow_prompt, "client_id": client_id}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            queue_resp = await client.post(f"{comfy_base_url}/prompt", json=queue_payload)
            queue_resp.raise_for_status()
            queued = queue_resp.json()
            prompt_id = queued.get("prompt_id")
            if not prompt_id:
                raise HTTPException(status_code=502, detail=f"ComfyUI queue failed: {queued}")

            history_url = f"{comfy_base_url}/history/{prompt_id}"
            deadline = asyncio.get_running_loop().time() + timeout_secs
            outputs = {}
            while asyncio.get_running_loop().time() < deadline:
                history_resp = await client.get(history_url)
                history_resp.raise_for_status()
                history = history_resp.json() or {}
                entry = history.get(prompt_id) or {}
                outputs = entry.get("outputs") or {}
                if outputs:
                    break
                await asyncio.sleep(poll_interval)

            if not outputs:
                raise HTTPException(status_code=504, detail="Timed out waiting for ComfyUI outputs")
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        logger.exception("dm_comfy_generate upstream HTTP error")
        status = exc.response.status_code if exc.response is not None else 502
        detail = f"ComfyUI HTTP error {status}: {exc.response.text if exc.response is not None else exc}"
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        logger.exception("dm_comfy_generate upstream connection error")
        raise HTTPException(status_code=502, detail=f"ComfyUI connection error: {exc}") from exc
    except Exception as exc:
        logger.exception("dm_comfy_generate failed")
        raise HTTPException(status_code=500, detail=f"Failed to generate ComfyUI images: {exc}") from exc

    images: list[ComfyImage] = []
    for node_out in outputs.values():
        for img in (node_out.get("images") or []):
            filename = img.get("filename")
            if not filename:
                continue
            subfolder = img.get("subfolder", "")
            img_type = img.get("type", "output")
            query = urlencode(
                {"filename": filename, "subfolder": subfolder, "type": img_type},
                safe="/",
            )
            images.append(
                ComfyImage(
                    filename=filename,
                    subfolder=subfolder,
                    type=img_type,
                    view_url=f"{comfy_base_url}/view?{query}",
                )
            )

    logger.info(
        "dm_comfy_generate success prompt_id=%s image_count=%s",
        prompt_id,
        len(images),
    )
    return ComfyGenerateResponse(
        prompt_id=prompt_id,
        image_count=len(images),
        source_prompt=source_prompt,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        images=images,
    )


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
            "comfy_base_url": DEFAULT_COMFY_BASE_URL,
            "comfy_model_family": DEFAULT_COMFY_MODEL_FAMILY,
            "comfy_steps": DEFAULT_COMFY_STEPS,
            "comfy_width": DEFAULT_COMFY_WIDTH,
            "comfy_height": DEFAULT_COMFY_HEIGHT,
            "comfy_batch_size": DEFAULT_COMFY_BATCH_SIZE,
            "comfy_cfg": DEFAULT_COMFY_CFG,
            "comfy_sampler_name": DEFAULT_COMFY_SAMPLER,
            "comfy_scheduler": DEFAULT_COMFY_SCHEDULER,
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
