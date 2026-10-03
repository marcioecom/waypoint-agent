import asyncio
import hashlib
import logging
import re
import time
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from gateway import send_message
from settings import settings

logger = logging.getLogger(__name__)

FALLBACK = "Não consegui processar sua mensagem agora. Tenta de novo daqui a pouco."
TIMEOUT = "Demorou mais que o esperado e interrompi a busca. Tenta de novo, por favor."

_CHECKPOINT_NS = "dhay:v1:"
_SEARCH_FLIGHT_TOOL = "search-flight"
_pending: set[asyncio.Task[None]] = set()
_locks: dict[str, asyncio.Lock] = {}
_lock_waiters: dict[str, int] = {}

JID_PATTERN = re.compile(r"^[\d]+(?::[\d]+)?@(s\.whatsapp\.net|lid)$")
STREAMLIT_THREAD_PATTERN = re.compile(r"^streamlit-[0-9a-f]{32}$", re.IGNORECASE)

CPF_PATTERN = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)
CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?(?:9\s*)?\d{4}[-\s]?\d{4}(?!\d)"
    r"|\+\d{10,15}(?!\d)",
)
PASSPORT_LABELED = re.compile(
    r"(?i)(passaporte|passport)\s*[:\s#-]*\s*([A-Z0-9]{6,12})"
)

_EMPTY_USAGE: dict[str, int | None] = {
    "input_tokens": None,
    "output_tokens": None,
    "total_tokens": None,
    "cached_input_tokens": None,
}


def checkpoint_thread_id(external_thread_id: str) -> dict[str, Any]:
    digest = hashlib.sha256(f"{_CHECKPOINT_NS}{external_thread_id}".encode()).hexdigest()
    return digest[:32]


def log_thread_ref(external_thread_id: str) -> dict[str, Any]:
    return checkpoint_thread_id(external_thread_id)[:12]


def validate_gateway_thread_id(thread_id: str) -> str | None:
    tid = thread_id.strip()
    if not tid or len(tid) > settings.max_thread_id_length:
        return "thread_id inválido"
    if JID_PATTERN.fullmatch(tid):
        return None
    return "thread_id inválido"


def validate_run_thread_id(thread_id: str) -> str | None:
    tid = thread_id.strip()
    if not tid or len(tid) > settings.max_thread_id_length:
        return "thread_id inválido"
    if JID_PATTERN.fullmatch(tid) or STREAMLIT_THREAD_PATTERN.fullmatch(tid):
        return None
    return "thread_id inválido"


def validate_message(message: str) -> str | None:
    text = message.strip()
    if not text:
        return "message vazia"
    if len(text) > settings.max_message_length:
        return "message muito longa"
    return None


def redact_pii(text: str) -> dict[str, Any]:
    out = PASSPORT_LABELED.sub(r"\1 [redacted]", text)
    out = EMAIL_PATTERN.sub("[redacted-email]", out)
    out = CPF_PATTERN.sub("[redacted-cpf]", out)
    out = CARD_PATTERN.sub("[redacted-card]", out)
    out = PHONE_PATTERN.sub("[redacted-phone]", out)
    return out


def _turn_messages(messages: list[Any], turn_id: str) -> list[Any]:
    start: int | None = None
    for index, msg in enumerate(messages):
        if getattr(msg, "type", None) == "human" and getattr(msg, "id", None) == turn_id:
            start = index
            break
    if start is None:
        return []
    return messages[start:]


def _tool_call_name(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        return str(tool_call.get("name") or "")
    return str(getattr(tool_call, "name", None) or "")


def _count_tool_calls(messages: list[Any]) -> int:
    count = 0
    for msg in messages:
        if getattr(msg, "type", None) != "ai":
            continue
        for tool_call in getattr(msg, "tool_calls", None) or []:
            if _tool_call_name(tool_call) == _SEARCH_FLIGHT_TOOL:
                count += 1
    return count


def _usage_field(meta: object, key: str) -> int | None:
    if isinstance(meta, dict):
        value = meta.get(key)
    else:
        value = getattr(meta, key, None)
    return value if isinstance(value, int) else None


def _message_usage_complete(meta: object | None) -> bool:
    if meta is None:
        return False
    return (
        _usage_field(meta, "input_tokens") is not None
        and _usage_field(meta, "output_tokens") is not None
        and _usage_field(meta, "total_tokens") is not None
    )


def _cached_input_tokens(meta: object) -> int:
    for key in ("cache_read_input_tokens", "cached_input_tokens"):
        value = _usage_field(meta, key)
        if value is not None and value >= 0:
            return value
    details: object | None
    if isinstance(meta, dict):
        details = meta.get("input_token_details")
    else:
        details = getattr(meta, "input_token_details", None)
    if isinstance(details, dict):
        for key in ("cache_read", "cached", "cached_tokens"):
            value = details.get(key)
            if isinstance(value, int) and value >= 0:
                return value
    return 0


def usage_is_complete(usage: dict[str, int | None]) -> bool:
    return (
        isinstance(usage.get("input_tokens"), int)
        and isinstance(usage.get("output_tokens"), int)
        and isinstance(usage.get("total_tokens"), int)
    )


def _normalize_usage(usage: dict[str, int | None]) -> dict[str, int | None]:
    if not usage_is_complete(usage):
        return usage
    out = dict(usage)
    cached = out.get("cached_input_tokens")
    input_tokens = out["input_tokens"]
    if not isinstance(cached, int) or cached < 0:
        out["cached_input_tokens"] = 0
    elif isinstance(input_tokens, int) and cached > input_tokens:
        out["cached_input_tokens"] = 0
    return out


def turn_token_usage(messages: list[Any]) -> dict[str, int | None]:
    ai_messages = [
        msg for msg in messages if getattr(msg, "type", None) == "ai"
    ]
    if not ai_messages:
        return dict(_EMPTY_USAGE)
    for msg in ai_messages:
        if not _message_usage_complete(getattr(msg, "usage_metadata", None)):
            return dict(_EMPTY_USAGE)
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
    }
    for msg in ai_messages:
        meta = getattr(msg, "usage_metadata", None)
        assert meta is not None
        totals["input_tokens"] += _usage_field(meta, "input_tokens") or 0
        totals["output_tokens"] += _usage_field(meta, "output_tokens") or 0
        totals["total_tokens"] += _usage_field(meta, "total_tokens") or 0
        totals["cached_input_tokens"] += _cached_input_tokens(meta)
    return _normalize_usage(totals)


def estimate_cost_usd(usage: dict[str, int | None]) -> float | None:
    if not settings.openai_rates_configured() or not usage_is_complete(usage):
        return None
    normalized = _normalize_usage(usage)
    input_tokens = normalized["input_tokens"]
    output_tokens = normalized["output_tokens"]
    cached = normalized["cached_input_tokens"]
    assert isinstance(input_tokens, int)
    assert isinstance(output_tokens, int)
    assert isinstance(cached, int)
    regular = input_tokens - cached
    cost = (
        (regular / 1_000_000) * settings.openai_input_cost_per_million
        + (cached / 1_000_000) * settings.openai_cached_input_cost_per_million
        + (output_tokens / 1_000_000) * settings.openai_output_cost_per_million
    )
    return round(cost, 6)


def _render_response(response: dict[str, Any]) -> dict[str, Any]:
    from agent import reply_text

    return reply_text(response).strip()


def _turn_log(
    *,
    thread_ref: str,
    latency_ms: int,
    tool_calls: int,
    outcome: str,
    usage: dict[str, int | None],
) -> dict[str, Any]:
    usage_norm = _normalize_usage(usage) if usage_is_complete(usage) else usage
    log: dict[str, Any] = {
        "thread_ref": thread_ref,
        "outcome": outcome,
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "input_tokens": usage_norm.get("input_tokens"),
        "output_tokens": usage_norm.get("output_tokens"),
        "cached_input_tokens": usage_norm.get("cached_input_tokens"),
        "total_tokens": usage_norm.get("total_tokens"),
    }
    cost = estimate_cost_usd(usage_norm)
    if cost is not None:
        log["estimated_cost_usd"] = cost
    return log


def _log_turn(log: dict[str, Any]) -> None:
    base = (
        "turn thread=%s outcome=%s latency_ms=%s tool_calls=%s "
        "input_tokens=%s output_tokens=%s cached_input_tokens=%s total_tokens=%s"
    )
    args = (
        log["thread_ref"],
        log["outcome"],
        log["latency_ms"],
        log["tool_calls"],
        log["input_tokens"],
        log["output_tokens"],
        log["cached_input_tokens"],
        log["total_tokens"],
    )
    cost = log.get("estimated_cost_usd")
    if cost is not None:
        logger.info(base + " estimated_cost_usd=%s", *args, cost)
    else:
        logger.info(base, *args)


def _acquire_lock(key: str) -> asyncio.Lock:
    _lock_waiters[key] = _lock_waiters.get(key, 0) + 1
    return _locks.setdefault(key, asyncio.Lock())


def _release_lock(key: str) -> None:
    remaining = _lock_waiters.get(key, 0) - 1
    if remaining <= 0:
        _lock_waiters.pop(key, None)
        _locks.pop(key, None)
    else:
        _lock_waiters[key] = remaining


async def _invoke_agent(
    agent,
    external_thread_id: str,
    message: str,
) -> tuple[str, dict[str, Any]]:
    thread_ref = log_thread_ref(external_thread_id)
    turn_id = f"turn-{uuid.uuid4().hex}"
    config: RunnableConfig = {
        "configurable": {"thread_id": checkpoint_thread_id(external_thread_id)},
        "recursion_limit": settings.agent_recursion_limit,
    }
    safe_message = redact_pii(message)
    started = time.monotonic()

    def _finish(outcome: str, tool_calls: int, usage: dict[str, int | None]) -> dict[str, Any]:
        log = _turn_log(
            thread_ref=thread_ref,
            latency_ms=int((time.monotonic() - started) * 1000),
            tool_calls=tool_calls,
            outcome=outcome,
            usage=usage,
        )
        _log_turn(log)
        return log

    try:
        response = await asyncio.wait_for(
            agent.ainvoke(
                {"messages": [HumanMessage(content=safe_message, id=turn_id)]},
                config,
            ),
            timeout=settings.agent_timeout_seconds,
        )
        turn_msgs = _turn_messages(response.get("messages", []), turn_id)
        usage = turn_token_usage(turn_msgs)
        tool_calls = _count_tool_calls(turn_msgs)
        text = _render_response(response)
        if not text:
            raise RuntimeError("empty agent response")
        log = _finish("ok", tool_calls, usage)
        return text, log
    except asyncio.TimeoutError:
        log = _finish("timeout", 0, dict(_EMPTY_USAGE))
        return TIMEOUT, log
    except asyncio.CancelledError:
        log = _finish("cancelled", 0, dict(_EMPTY_USAGE))
        raise
    except Exception as exc:
        logger.warning(
            "agent failed thread=%s outcome=error exc_type=%s",
            thread_ref,
            type(exc).__name__,
        )
        log = _finish("error", 0, dict(_EMPTY_USAGE))
        return FALLBACK, log


async def run_agent(agent, thread_id: str, message: str) -> str:
    thread_err = validate_run_thread_id(thread_id)
    if thread_err:
        raise ValueError(thread_err)
    message_err = validate_message(message)
    if message_err:
        raise ValueError(message_err)
    key = checkpoint_thread_id(thread_id)
    lock = _acquire_lock(key)
    try:
        async with lock:
            text, _log = await _invoke_agent(agent, thread_id, message)
            return text
    finally:
        _release_lock(key)


async def _deliver(agent, thread_id: str, message: str) -> None:
    key = checkpoint_thread_id(thread_id)
    lock = _acquire_lock(key)
    try:
        async with lock:
            try:
                text, _log = await _invoke_agent(agent, thread_id, message)
            except asyncio.CancelledError:
                raise
            except Exception:
                text = FALLBACK
            try:
                await send_message(thread_id, text)
            except Exception as exc:
                logger.warning(
                    "undelivered thread=%s exc_type=%s",
                    log_thread_ref(thread_id),
                    type(exc).__name__,
                )
    finally:
        _release_lock(key)


def schedule_reply(agent, thread_id: str, message: str) -> None:
    task = asyncio.create_task(_deliver(agent, thread_id, message))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def shutdown_runtime() -> None:
    tasks = list(_pending)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _pending.clear()
    _locks.clear()
    _lock_waiters.clear()
