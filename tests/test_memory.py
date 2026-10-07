import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from agent import SYSTEM_PROMPT, _preference_tool, build_system_prompt
from memory import AgentMemory, Preferences, current_thread_id, open_memory


def test_preferences_roundtrip(tmp_path):
    prefs = Preferences(tmp_path / "agent.sqlite")
    prefs.update("chat-1", home_city="São Paulo", cabin="econômica", adults=2)
    saved = prefs.get("chat-1")
    assert saved["home_city"] == "São Paulo"
    assert saved["cabin"] == "econômica"
    assert saved["adults"] == 2
    block = prefs.prompt_block("chat-1")
    assert "São Paulo" in block
    assert "econômica" in block
    assert prefs.prompt_block("other").startswith("Nenhuma preferência")


def test_preferences_merge_ignores_empty(tmp_path):
    prefs = Preferences(tmp_path / "agent.sqlite")
    prefs.update("chat-1", home_city="Recife", currency="BRL")
    prefs.update("chat-1", home_city="  ", cabin="executiva")
    saved = prefs.get("chat-1")
    assert saved["home_city"] == "Recife"
    assert saved["cabin"] == "executiva"
    assert saved["currency"] == "BRL"


def test_system_prompt_includes_today_and_preferences(tmp_path):
    prefs = Preferences(tmp_path / "agent.sqlite")
    prefs.update("t", home_city="Curitiba")
    prompt = build_system_prompt(
        prefs.prompt_block("t"),
        now=datetime(2026, 10, 7, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )
    assert "Data atual: 2026-10-07" in prompt
    assert "Fuso: America/Sao_Paulo" in prompt
    assert "Curitiba" in prompt
    assert "Nunca só ids" in SYSTEM_PROMPT
    assert "save_user_preferences" in SYSTEM_PROMPT
    assert "questionário" in SYSTEM_PROMPT.lower()


def test_save_user_preferences_tool_uses_thread_context(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = _preference_tool(memory)
    token = current_thread_id.set("wa-1")
    try:
        result = tool.invoke({"home_city": "Recife", "cabin": "econômica"})
    finally:
        current_thread_id.reset(token)
    assert "Recife" in result
    assert memory.prefs.get("wa-1")["home_city"] == "Recife"
    assert "runtime" not in tool.args


def test_open_memory_uses_sqlite_checkpointer(tmp_path):
    async def _run():
        async with open_memory(tmp_path / "agent.sqlite") as memory:
            assert memory.checkpointer is not None
            memory.prefs.update("jid@s.whatsapp.net", home_city="BH")
            assert memory.prefs.get("jid@s.whatsapp.net")["home_city"] == "BH"

    asyncio.run(_run())
