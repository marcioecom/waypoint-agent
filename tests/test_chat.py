import asyncio

from langgraph.errors import GraphRecursionError

from travel_agent.agent.reply import AgentReply
from travel_agent.services.chat import (
    FALLBACK,
    INVOKE_TIMEOUT_S,
    RECURSION_LIMIT,
    _deliver,
    as_text,
    run_agent,
)


def test_as_text_joins_blocks():
    assert as_text("olá") == "olá"
    assert as_text(["a", {"text": "b"}, {"type": "ignore"}]) == "a\nb"


def test_recursion_limit_triggers_fallback(monkeypatch):
    seen: dict[str, object] = {}

    class FakeAgent:
        async def ainvoke(self, _input, config):
            seen["recursion_limit"] = config.get("recursion_limit")
            raise GraphRecursionError("Recursion limit of 40 reached")

    sent: list[str] = []

    async def fake_send(_jid: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("travel_agent.services.chat.send_message", fake_send)

    async def _run():
        await _deliver(FakeAgent(), "wa-1", "bom dia")

    asyncio.run(_run())
    assert seen["recursion_limit"] == RECURSION_LIMIT
    assert sent == [FALLBACK]


def test_invoke_timeout_triggers_fallback(monkeypatch):
    monkeypatch.setattr("travel_agent.services.chat.INVOKE_TIMEOUT_S", 0.05)

    class SlowAgent:
        async def ainvoke(self, _input, config):
            await asyncio.sleep(1)
            return {"structured_response": AgentReply(message="tarde", offers=[])}

    sent: list[str] = []

    async def fake_send(_jid: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("travel_agent.services.chat.send_message", fake_send)

    async def _run():
        await _deliver(SlowAgent(), "wa-1", "bom dia")

    asyncio.run(_run())
    assert sent == [FALLBACK]


def test_run_agent_passes_recursion_limit_on_success():
    class FakeAgent:
        async def ainvoke(self, _input, config):
            assert config["recursion_limit"] == RECURSION_LIMIT
            return {
                "structured_response": AgentReply(
                    message="Bom dia! Tá pensando em viajar pra onde?",
                    offers=[],
                )
            }

    async def _run():
        return await run_agent(FakeAgent(), "wa-1", "bom dia")

    assert asyncio.run(_run()) == "Bom dia! Tá pensando em viajar pra onde?"
    assert INVOKE_TIMEOUT_S > 0
