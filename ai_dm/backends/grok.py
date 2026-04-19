import httpx

GROK_URL = "https://api.x.ai/v1/chat/completions"


async def chat_completion(api_key: str, model: str, messages: list, tools: list) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "tools": tools, "stream": False}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(GROK_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()
