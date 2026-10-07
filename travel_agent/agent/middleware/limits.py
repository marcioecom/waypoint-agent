"""Limites executáveis do agente — orçamento de busca e anti-loop.

Usa os middlewares oficiais do LangChain para contagem e um wrap_tool_call
idiomático para bloquear consultas idênticas no mesmo turno.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    wrap_tool_call,
)
from langchain_core.messages import AIMessage, ToolMessage

SEARCH_TOOL = "search_flights"

_SEARCH_SIGNATURE_KEYS = (
    "fly_from",
    "fly_to",
    "departure_date",
    "departure_date_to",
    "return_date",
    "return_date_to",
    "nights_in_dst_from",
    "nights_in_dst_to",
    "adults",
    "cabin_class",
    "currency",
    "sort",
)


def build_call_limit_middleware(
    *,
    search_run_limit: int,
    model_run_limit: int,
) -> list[Any]:
    """Middlewares oficiais: teto de search_flights e de chamadas ao modelo."""
    return [
        ModelCallLimitMiddleware(
            run_limit=model_run_limit,
            exit_behavior="end",
        ),
        ToolCallLimitMiddleware(
            tool_name=SEARCH_TOOL,
            run_limit=search_run_limit,
            # Bloqueia só search_flights e deixa o modelo finalizar (AgentReply).
            exit_behavior="continue",
        ),
    ]


def search_signature(args: dict[str, Any]) -> str:
    """Assinatura estável dos argumentos relevantes de search_flights."""
    normalized: dict[str, Any] = {}
    for key in _SEARCH_SIGNATURE_KEYS:
        value = args.get(key)
        if isinstance(value, str):
            value = value.strip()
            if key == "currency":
                value = value.upper()
            if not value:
                value = None
        normalized[key] = value
    return json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)


def _messages_from_state(state: Any) -> list[Any]:
    if isinstance(state, dict):
        messages = state.get("messages") or []
    else:
        messages = getattr(state, "messages", None) or []
    return list(messages)


def prior_search_signatures(state: Any, *, exclude_tool_call_id: str | None = None) -> set[str]:
    """Assinaturas de search_flights já pedidas neste histórico (exceto a atual)."""
    seen: set[str] = set()
    for message in _messages_from_state(state):
        if not isinstance(message, AIMessage):
            continue
        for tool_call in message.tool_calls or []:
            if tool_call.get("name") != SEARCH_TOOL:
                continue
            if exclude_tool_call_id and tool_call.get("id") == exclude_tool_call_id:
                continue
            args = tool_call.get("args") or {}
            if isinstance(args, dict):
                seen.add(search_signature(args))
    return seen


@wrap_tool_call
async def dedupe_search_flights(request, handler):
    """Não executa de novo a mesma consulta de voos no turno."""
    tool_call = request.tool_call
    if tool_call.get("name") != SEARCH_TOOL:
        return await handler(request)

    args = tool_call.get("args") or {}
    if not isinstance(args, dict):
        return await handler(request)

    signature = search_signature(args)
    if signature not in prior_search_signatures(
        request.state,
        exclude_tool_call_id=tool_call.get("id"),
    ):
        return await handler(request)

    return ToolMessage(
        content=json.dumps(
            {
                "status": "duplicate",
                "resultsCount": 0,
                "offers": [],
                "note": (
                    "Consulta idêntica já executada neste turno. "
                    "Não repita; finalize com AgentReply ou mude parâmetros."
                ),
            },
            ensure_ascii=False,
        ),
        tool_call_id=tool_call["id"],
        name=SEARCH_TOOL,
        status="error",
    )
