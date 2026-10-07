from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelResponse

from travel_agent.agent.reply import AgentReply, FlightOffer


@wrap_model_call
async def guard_post_search(request, handler):
    """Se a busca trouxe offers e a reply final veio vazia/recomeçou, injeta ofertas."""
    response = await handler(request)
    if not isinstance(response, ModelResponse):
        return response

    structured = response.structured_response
    if structured is None:
        return response

    offers = getattr(structured, "offers", None)
    if offers:
        return response

    recent_offers = offers_from_recent_tools(request.messages)
    if not recent_offers:
        return response

    message = getattr(structured, "message", "") or ""
    if looks_like_cold_start(message):
        message = "Melhor que achei com o que a gente tinha:"
    patched = AgentReply(message=message, offers=recent_offers[:3])
    return replace(response, structured_response=patched)


def looks_like_cold_start(message: str) -> bool:
    text = message.casefold()
    markers = (
        "sou dhay",
        "sou o dhay",
        "para começar",
        "me passe:",
        "preciso de: origem",
        "assistente de voos",
    )
    return any(marker in text for marker in markers)


def offers_from_recent_tools(messages: list[Any]) -> list[FlightOffer]:
    collected: list[FlightOffer] = []
    for message in reversed(messages[-8:]):
        if getattr(message, "type", None) != "tool":
            continue
        name = getattr(message, "name", "") or ""
        if name and name not in {"search_flights", "search-flight"}:
            continue
        content = getattr(message, "content", "")
        try:
            payload = json.loads(content) if isinstance(content, str) else content
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        for item in payload.get("offers") or []:
            if not isinstance(item, dict):
                continue
            try:
                collected.append(FlightOffer.model_validate(item))
            except Exception:
                continue
        if collected:
            break
    return collected
