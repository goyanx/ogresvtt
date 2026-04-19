import json
import httpx


async def chat_completion(endpoint: str, model: str, messages: list, tools: list) -> dict:
    url = f"{endpoint}/v1/chat/completions"
    payload = {"model": model, "messages": messages, "tools": tools, "stream": False}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()
