"""
AI Dungeon Master FastAPI sidecar.

Endpoints:
  POST /dm/turn   — LangGraph multi-step turn (returns tool calls + narration)
  POST /dm/speak  — Kokoro TTS (returns WAV audio bytes)
  GET  /dm/voices — List available TTS voices
  GET  /health

Start with:
  uvicorn ai_dm.main:app --port 8765 --reload
"""
import functools
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from ai_dm.graph import build_graph
from ai_dm.backends import ollama, grok
from ai_dm.logging_config import configure_logging


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


_load_env_files()
log_path = configure_logging()
logger = logging.getLogger("ai_dm.main")

DEFAULT_OLLAMA_ENDPOINT = _env_first(
    "AI_DM_OLLAMA_ENDPOINT", "OLLAMA_ENDPOINT", default="http://localhost:11434"
)
DEFAULT_OLLAMA_MODEL = _env_first(
    "AI_DM_OLLAMA_MODEL", "OLLAMA_MODEL", default="qwen2.5:14b-instruct-q4_K_M"
)
DEFAULT_GROK_MODEL = _env_first(
    "AI_DM_GROK_MODEL", "GROK_MODEL", "XAI_MODEL", default="grok-3-mini"
)

app = FastAPI(title="AI DM LangGraph Sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup():
    logger.info("AI DM sidecar startup complete log_file=%s", log_path)


@app.middleware("http")
async def _request_logging(request: Request, call_next):
    response = await call_next(request)
    logger.info("request completed method=%s path=%s status=%s",
                request.method, request.url.path, response.status_code)
    return response


# ---------------------------------------------------------------------------
# /dm/turn
# ---------------------------------------------------------------------------

class TurnRequest(BaseModel):
    backend: str = "ollama"
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
    backend = (req.backend or "ollama").strip().lower()
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
    }
