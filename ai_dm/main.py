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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from ai_dm.graph import build_graph
from ai_dm.backends import ollama, grok

app = FastAPI(title="AI DM LangGraph Sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# /dm/turn
# ---------------------------------------------------------------------------

class TurnRequest(BaseModel):
    backend: str = "ollama"
    endpoint: str = "http://localhost:11434"
    model: str = "qwen2.5:14b-instruct-q4_K_M"
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
    if req.backend == "ollama":
        llm_call = functools.partial(
            ollama.chat_completion, endpoint=req.endpoint, model=req.model
        )
    elif req.backend == "grok":
        if not req.api_key:
            raise HTTPException(status_code=400, detail="api_key required for grok backend")
        llm_call = functools.partial(
            grok.chat_completion, api_key=req.api_key, model=req.model
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
        raise HTTPException(status_code=500, detail=str(exc))

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
    return {"status": "ok", "tts": tts_available}
