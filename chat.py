import asyncio
import logging

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from gateway import send_message

logger = logging.getLogger(__name__)

FALLBACK = "Não consegui processar sua mensagem agora. Tenta de novo daqui a pouco."

_pending: set[asyncio.Task] = set()
_locks: dict[str, asyncio.Lock] = {}


def as_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(part for part in parts if part)
    return str(content)


async def run_agent(agent, thread_id: str, message: str) -> str:
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    response = await agent.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config,
    )
    return as_text(response["messages"][-1].content).strip()


async def _deliver(agent, thread_id: str, message: str) -> None:
    lock = _locks.setdefault(thread_id, asyncio.Lock())
    async with lock:
        try:
            text = await run_agent(agent, thread_id, message)
            if not text:
                raise RuntimeError("empty agent response")
        except Exception:
            logger.exception("agent failed for %s", thread_id)
            text = FALLBACK
        try:
            await send_message(thread_id, text)
        except Exception:
            logger.exception("undelivered to %s: %s", thread_id, text)


def schedule_reply(agent, thread_id: str, message: str) -> None:
    task = asyncio.create_task(_deliver(agent, thread_id, message))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
