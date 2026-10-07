import asyncio

import httpx

from travel_agent.settings import settings


async def send_message(jid: str, text: str) -> None:
    base = settings.gateway_url.rstrip("/")
    if not base:
        return

    headers = {}
    if settings.gateway_token:
        headers["Authorization"] = f"Bearer {settings.gateway_token}"

    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(2):
            try:
                response = await client.post(
                    f"{base}/messages",
                    json={"jid": jid, "text": text},
                    headers=headers,
                )
            except httpx.HTTPError:
                if attempt == 1:
                    raise
                await asyncio.sleep(1)
                continue
            if response.status_code == 503 and attempt == 0:
                await asyncio.sleep(1)
                continue
            response.raise_for_status()
            return
