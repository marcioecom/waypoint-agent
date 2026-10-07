from __future__ import annotations

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import trim_messages


@wrap_model_call
async def compact_history(request, handler):
    messages = trim_messages(
        request.messages,
        max_tokens=12_000,
        token_counter="approximate",
        start_on="human",
        include_system=True,
    )
    return await handler(request.override(messages=messages))
