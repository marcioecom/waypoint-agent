from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import wrap_model_call
from langchain_core.messages import AIMessage, trim_messages


def drop_stale_tool_history(messages: list) -> list:
    """Tira JSON de busca/brief de turnos anteriores; mantém o que o usuário viu."""
    last_human = None
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "human":
            last_human = index
    if last_human is None:
        return list(messages)

    kept: list = []
    for index, message in enumerate(messages):
        if index >= last_human:
            kept.append(message)
            continue
        kind = getattr(message, "type", None)
        if kind in {"human", "system"}:
            kept.append(message)
            continue
        if kind == "ai":
            visible = _visible_prior_ai(message)
            if visible is not None:
                kept.append(visible)
    return kept


def _visible_prior_ai(message: Any) -> AIMessage | None:
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        if _call_name(call) != "AgentReply":
            continue
        args = _call_args(call)
        text = str(args.get("message") or "").strip() or _ai_text(message)
        if text:
            return AIMessage(content=text)
        return None
    text = _ai_text(message)
    if text and not tool_calls:
        return message
    return None


def _call_name(call: Any) -> str:
    if isinstance(call, dict):
        return str(call.get("name") or "")
    return str(getattr(call, "name", "") or "")


def _call_args(call: Any) -> dict:
    raw = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _ai_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str) and block.strip():
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(part for part in parts if part).strip()
    return ""


@wrap_model_call
async def compact_history(request, handler):
    messages = drop_stale_tool_history(list(request.messages))
    messages = trim_messages(
        messages,
        max_tokens=12_000,
        token_counter="approximate",
        start_on="human",
        include_system=True,
    )
    return await handler(request.override(messages=messages))
