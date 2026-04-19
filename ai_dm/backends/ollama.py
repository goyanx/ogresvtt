import json
import logging
import httpx

logger = logging.getLogger(__name__)


async def chat_completion(messages: list, tools: list, *, endpoint: str, model: str) -> dict:
    url = f"{endpoint}/v1/chat/completions"
    payload = {"model": model, "messages": messages, "tools": tools, "stream": False}
    logger.info(
        "ollama chat_completion start endpoint=%s model=%s messages=%s tools=%s",
        endpoint,
        model,
        len(messages or []),
        len(tools or []),
    )
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("ollama chat_completion success")
            return data
        except Exception:
            logger.exception("ollama chat_completion failed endpoint=%s model=%s", endpoint, model)
            raise
