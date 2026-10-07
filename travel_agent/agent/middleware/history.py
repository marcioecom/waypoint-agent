from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import ToolMessage, trim_messages

from travel_agent.agent.middleware.limits import SEARCH_TOOL

_KEEP_FULL_SEARCH_RESULTS = 2
_OMITTED_SEARCH = {
    "status": "omitted",
    "resultsCount": 0,
    "offers": [],
    "note": "Resultado anterior omitido do contexto.",
}


def collapse_older_search_results(
    messages: list[Any],
    *,
    keep_last: int = _KEEP_FULL_SEARCH_RESULTS,
) -> list[Any]:
    """Mantém só as últimas N buscas completas; o resto vira resumo curto."""
    search_indexes = [
        index
        for index, message in enumerate(messages)
        if isinstance(message, ToolMessage)
        and (getattr(message, "name", "") or "") == SEARCH_TOOL
    ]
    if len(search_indexes) <= keep_last:
        return list(messages)

    omit = set(search_indexes[:-keep_last])
    compacted: list[Any] = []
    omitted_payload = json.dumps(_OMITTED_SEARCH, ensure_ascii=False)
    for index, message in enumerate(messages):
        if index not in omit:
            compacted.append(message)
            continue
        compacted.append(
            ToolMessage(
                content=omitted_payload,
                tool_call_id=message.tool_call_id,
                name=SEARCH_TOOL,
                status=getattr(message, "status", None) or "success",
            )
        )
    return compacted


@wrap_model_call
async def compact_history(request, handler):
    messages = collapse_older_search_results(request.messages)
    messages = trim_messages(
        messages,
        max_tokens=12_000,
        token_counter="approximate",
        start_on="human",
        include_system=True,
    )
    return await handler(request.override(messages=messages))
