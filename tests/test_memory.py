import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from travel_agent.agent import SYSTEM_PROMPT, build_system_prompt
from travel_agent.agent.memory import (
    AgentMemory,
    Preferences,
    TripBrief,
    current_thread_id,
    open_memory,
)
from travel_agent.agent.tools import preference_tool, trip_tool


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


def test_trip_brief_roundtrip_and_prompt(tmp_path):
    trips = TripBrief(tmp_path / "agent.sqlite")
    trips.update(
        "chat-1",
        origin="Palmas",
        destination="São Paulo",
        trip_type="round_trip",
        date_from="01/01/2027",
        date_to="31/01/2027",
        status="ready",
    )
    saved = trips.get("chat-1")
    assert saved["origin"] == "Palmas"
    assert saved["trip_type"] == "round_trip"
    block = trips.prompt_block("chat-1")
    assert "Palmas" in block
    assert "São Paulo" in block
    assert trips.prompt_block("other").startswith("Nenhum pedido ativo")


def test_system_prompt_includes_today_trip_and_preferences(tmp_path):
    prefs = Preferences(tmp_path / "agent.sqlite")
    trips = TripBrief(tmp_path / "agent.sqlite")
    prefs.update("t", home_city="Curitiba")
    trips.update("t", origin="Palmas", destination="São Paulo", status="collecting")
    prompt = build_system_prompt(
        prefs.prompt_block("t"),
        trips.prompt_block("t"),
        now=datetime(2026, 10, 7, tzinfo=ZoneInfo("America/Sao_Paulo")),
    )
    assert "Data atual: 2026-10-07" in prompt
    assert "Fuso: America/Sao_Paulo" in prompt
    assert "Curitiba" in prompt
    assert "PEDIDO ATIVO" in prompt
    assert "Palmas" in prompt
    assert "Continuidade" in SYSTEM_PROMPT
    assert "update_trip_brief" in SYSTEM_PROMPT
    assert "save_user_preferences" in SYSTEM_PROMPT
    assert "questionário" in SYSTEM_PROMPT.lower()


def test_save_user_preferences_tool_uses_thread_context(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = preference_tool(memory)
    token = current_thread_id.set("wa-1")
    try:
        result = tool.invoke({"home_city": "Recife", "cabin": "econômica"})
    finally:
        current_thread_id.reset(token)
    assert "Recife" in result
    assert memory.prefs.get("wa-1")["home_city"] == "Recife"
    assert "runtime" not in tool.args


def test_update_trip_brief_tool_uses_thread_context(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = trip_tool(memory)
    token = current_thread_id.set("wa-2")
    try:
        result = tool.invoke(
            {
                "origin": "Palmas",
                "destination": "São Paulo",
                "trip_type": "round_trip",
                "date_from": "01/01/2027",
                "status": "ready",
            }
        )
    finally:
        current_thread_id.reset(token)
    assert "Palmas" in result
    assert memory.trips.get("wa-2")["destination"] == "São Paulo"


def test_open_memory_uses_sqlite_checkpointer(tmp_path):
    async def _run():
        async with open_memory(tmp_path / "agent.sqlite") as memory:
            assert memory.checkpointer is not None
            memory.prefs.update("jid@s.whatsapp.net", home_city="BH")
            assert memory.prefs.get("jid@s.whatsapp.net")["home_city"] == "BH"
            memory.trips.update("jid@s.whatsapp.net", origin="BH", destination="SP")
            assert memory.trips.get("jid@s.whatsapp.net")["origin"] == "BH"

    asyncio.run(_run())
