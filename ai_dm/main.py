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
import time
import uuid
from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from ai_dm.graph import build_graph
from ai_dm.backends import ollama, grok
from ai_dm.logging_config import configure_logging

LOG_PATH = configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="AI DM LangGraph Sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    logger.info("AI DM sidecar startup complete log_file=%s", LOG_PATH)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "request completed id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        response.headers["x-request-id"] = request_id
        return response
    except Exception:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "request failed id=%s method=%s path=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise


# ---------------------------------------------------------------------------
# /dm/turn
# ---------------------------------------------------------------------------

class TurnRequest(BaseModel):
    backend: str = "ollama"
    endpoint: str = "http://localhost:11434"
    model: str = "qwen2.5:14b-instruct-q4_K_M"
    max_output_tokens: int | None = None
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
    logger.info(
        "dm_turn start backend=%s model=%s endpoint=%s max_output_tokens=%s history_count=%s game_state_chars=%s",
        req.backend,
        req.model,
        req.endpoint,
        req.max_output_tokens,
        len(req.history or []),
        len(req.game_state or ""),
    )
    if req.backend == "ollama":
        llm_call = functools.partial(
            ollama.chat_completion,
            endpoint=req.endpoint,
            model=req.model,
            max_output_tokens=req.max_output_tokens,
        )
    elif req.backend == "grok":
        if not req.api_key:
            raise HTTPException(status_code=400, detail="api_key required for grok backend")
        llm_call = functools.partial(
            grok.chat_completion,
            api_key=req.api_key,
            model=req.model,
            max_output_tokens=req.max_output_tokens,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {req.backend}")

    graph = build_graph(llm_call)
    initial_state = {
        "scenario":          req.scenario,
        "game_state":        req.game_state,
        "history":           req.history,
        "plan":              "",
        "tool_calls":        [],
        "validation_errors": [],
        "retry_count":       0,
        "narration":         "",
    }

    try:
        final_state = await graph.ainvoke(initial_state)
    except Exception as exc:
        logger.exception(
            "dm_turn failed backend=%s model=%s endpoint=%s",
            req.backend,
            req.model,
            req.endpoint,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info(
        "dm_turn success tool_calls=%s validation_errors=%s retry_count=%s narration_chars=%s",
        len(final_state["tool_calls"] or []),
        len(final_state["validation_errors"] or []),
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
    logger.info(
        "dm_speak start voice=%s speed=%s text_chars=%s",
        req.voice,
        req.speed,
        len(req.text or ""),
    )
    try:
        from ai_dm.tts import synthesize
        loop = asyncio.get_event_loop()
        wav_bytes = await loop.run_in_executor(
            None, synthesize, req.text, req.voice, req.speed
        )
    except ImportError:
        logger.warning("dm_speak unavailable: kokoro not installed")
        raise HTTPException(
            status_code=503,
            detail="Kokoro TTS not installed. Run: pip install kokoro soundfile",
        )
    except Exception as exc:
        logger.exception("dm_speak failed voice=%s speed=%s", req.voice, req.speed)
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("dm_speak success bytes=%s", len(wav_bytes or b""))
    return Response(content=wav_bytes, media_type="audio/wav")


@app.get("/dm/voices")
def dm_voices():
    try:
        from ai_dm.tts import AVAILABLE_VOICES
        logger.info("dm_voices success count=%s", len(AVAILABLE_VOICES))
        return {"voices": AVAILABLE_VOICES}
    except ImportError:
        logger.warning("dm_voices unavailable: kokoro not installed")
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
    result = {"status": "ok", "tts": tts_available, "log_file": str(LOG_PATH)}
    logger.debug("health check tts=%s", tts_available)
    return result
