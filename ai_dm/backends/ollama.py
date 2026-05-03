import httpx
import os


def _env_float(name: str, default: float, minimum: float = 1.0, maximum: float = 3600.0) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _candidate_bases(endpoint: str) -> list[str]:
    base = endpoint.rstrip("/")
    candidates = [base]
    if base.endswith("/v1"):
        candidates.append(base[:-3])
    out = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            out.append(c)
            seen.add(c)
    return out


def _as_openai_shape(native: dict) -> dict:
    message = native.get("message") or {}
    return {
        "choices": [
            {
                "message": {
                    "content": message.get("content") or "",
                    "tool_calls": message.get("tool_calls") or [],
                }
            }
        ]
    }


async def _fetch_model_names(client: httpx.AsyncClient, base: str) -> list[str]:
    try:
        resp = await client.get(f"{base}/api/tags")
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models") or []
        return [m.get("name") for m in models if isinstance(m, dict) and m.get("name")]
    except Exception:
        return []


async def chat_completion(messages: list, tools: list, *, endpoint: str, model: str) -> dict:
    payload = {"model": model, "messages": messages, "tools": tools, "stream": False}
    attempts: list[tuple[str, int, str]] = []
    total_timeout = _env_float("AI_DM_OLLAMA_TIMEOUT_SECONDS", default=300.0)
    connect_timeout = _env_float("AI_DM_OLLAMA_CONNECT_TIMEOUT_SECONDS", default=10.0)
    write_timeout = _env_float("AI_DM_OLLAMA_WRITE_TIMEOUT_SECONDS", default=30.0)
    pool_timeout = _env_float("AI_DM_OLLAMA_POOL_TIMEOUT_SECONDS", default=30.0)
    timeout = httpx.Timeout(
        timeout=total_timeout,
        connect=connect_timeout,
        read=total_timeout,
        write=write_timeout,
        pool=pool_timeout,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        bases = _candidate_bases(endpoint)
        for base in bases:
            openai_url = f"{base}/v1/chat/completions"
            try:
                resp = await client.post(openai_url, json=payload)
            except httpx.ReadTimeout as exc:
                raise RuntimeError(
                    "Ollama request timed out while waiting for model output. "
                    f"endpoint={endpoint!r} model={model!r} timeout={total_timeout}s. "
                    "Increase AI_DM_OLLAMA_TIMEOUT_SECONDS or use a faster/smaller model."
                ) from exc
            if resp.status_code != 404:
                resp.raise_for_status()
                return resp.json()
            attempts.append((openai_url, resp.status_code, resp.text[:300]))

            native_url = f"{base}/api/chat"
            try:
                native_resp = await client.post(native_url, json=payload)
            except httpx.ReadTimeout as exc:
                raise RuntimeError(
                    "Ollama request timed out while waiting for model output. "
                    f"endpoint={endpoint!r} model={model!r} timeout={total_timeout}s. "
                    "Increase AI_DM_OLLAMA_TIMEOUT_SECONDS or use a faster/smaller model."
                ) from exc
            if native_resp.status_code != 404:
                native_resp.raise_for_status()
                return _as_openai_shape(native_resp.json())
            attempts.append((native_url, native_resp.status_code, native_resp.text[:300]))

        model_names: list[str] = []
        for base in bases:
            names = await _fetch_model_names(client, base)
            if names:
                model_names = names
                break

    details = "; ".join([f"{u} -> {s} body={b!r}" for (u, s, b) in attempts])
    installed = ", ".join(model_names) if model_names else "(unavailable)"
    raise RuntimeError(
        "Ollama request failed with 404 on all candidate endpoints. "
        f"endpoint={endpoint!r} model={model!r}. "
        f"Installed models: {installed}. Attempts: {details}"
    )
