import httpx
import logging

GROK_URL = "https://api.x.ai/v1/chat/completions"
logger = logging.getLogger(__name__)


async def chat_completion(
    messages: list,
    tools: list,
    *,
    api_key: str,
    model: str,
    max_output_tokens: int | None = None,
) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "tools": tools, "stream": False}
    if isinstance(max_output_tokens, int) and max_output_tokens > 0:
        payload["max_tokens"] = max_output_tokens
    logger.info(
        "grok chat_completion start model=%s max_output_tokens=%s messages=%s tools=%s",
        model,
        max_output_tokens,
        len(messages or []),
        len(tools or []),
    )
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(GROK_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("grok chat_completion success")
            return data
        except Exception:
            logger.exception("grok chat_completion failed model=%s", model)
            raise
