import asyncio
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from travel_agent.agent import SYSTEM_PROMPT, build_system_prompt
from travel_agent.agent.prompt import upcoming_months
from travel_agent.agent.memory import (
    AgentMemory,
    Preferences,
    TripBrief,
    current_thread_id,
    open_memory,
    state_db_path,
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


def test_trip_brief_new_request_replaces_previous_trip(tmp_path):
    trips = TripBrief(tmp_path / "agent.sqlite")
    trips.update(
        "chat-1",
        origin="Palmas",
        destination="SCL",
        date_from="01/08/2027",
        date_to="31/08/2027",
        notes="quer estar lá em 16/08",
        status="searched",
    )
    trips.update(
        "chat-1",
        new_request=True,
        origin="Palmas",
        destination="São Paulo",
        status="collecting",
    )
    saved = trips.get("chat-1")
    assert saved["origin"] == "Palmas"
    assert saved["destination"] == "São Paulo"
    assert saved["status"] == "collecting"
    assert "date_from" not in saved
    assert "date_to" not in saved
    assert "notes" not in saved


def test_trip_brief_merge_keeps_dates_without_new_request(tmp_path):
    trips = TripBrief(tmp_path / "agent.sqlite")
    trips.update(
        "chat-1",
        origin="Palmas",
        destination="SCL",
        date_from="01/08/2027",
        notes="quer estar lá em 16/08",
    )
    trips.update("chat-1", destination="SCL", status="ready")
    saved = trips.get("chat-1")
    assert saved["date_from"] == "01/08/2027"
    assert saved["notes"] == "quer estar lá em 16/08"
    assert saved["status"] == "ready"


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
    assert "CONTINUIDADE" in SYSTEM_PROMPT
    assert "update_trip_brief" in SYSTEM_PROMPT
    assert "save_user_preferences" in SYSTEM_PROMPT
    assert "Olá! Como posso ajudar?" in SYSTEM_PROMPT
    assert "Cumprimentar de volta é ok" in SYSTEM_PROMPT
    assert "Todo turno termina com AgentReply" in SYSTEM_PROMPT
    assert "bom dia" in SYSTEM_PROMPT
    assert "Nenhuma preferência salva” não é motivo" in SYSTEM_PROMPT
    assert "Cidade, País" in SYSTEM_PROMPT
    assert "levam país" not in SYSTEM_PROMPT
    assert "new_request" in SYSTEM_PROMPT
    assert "Nunca assuma São Paulo" in SYSTEM_PROMPT
    assert "fly_from=" in SYSTEM_PROMPT
    assert '*negrito*' in SYSTEM_PROMPT
    assert "nov/2026" in prompt
    assert "dez/2026" in prompt
    assert "jan/2027" in prompt
    assert "Próximos meses" in prompt
    assert upcoming_months(
        datetime(2026, 10, 8, tzinfo=ZoneInfo("America/Sao_Paulo"))
    ).startswith("out/2026, nov/2026")
    assert "Status:" not in prompt


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
    assert "pelo menos um campo" in tool.description
    assert "cumprimento" in tool.description.casefold()


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
            }
        )
    finally:
        current_thread_id.reset(token)
    assert "Palmas" in result
    assert "não chame update_trip_brief de novo" in result.casefold()
    assert "search_flights" in result
    assert "AgentReply" in result
    assert memory.trips.get("wa-2")["destination"] == "São Paulo"


def test_empty_save_user_preferences_points_to_agent_reply(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = preference_tool(memory)
    token = current_thread_id.set("wa-empty")
    try:
        result = tool.invoke(
            {
                "home_city": None,
                "cabin": None,
                "currency": None,
                "adults": None,
                "notes": None,
            }
        )
    finally:
        current_thread_id.reset(token)
    assert "Nada para salvar" not in result
    assert "nada mudou" in result.casefold()
    assert "Não chame esta ferramenta de novo neste turno" in result
    assert "AgentReply" in result
    assert memory.prefs.get("wa-empty") == {}


def test_empty_update_trip_brief_points_to_agent_reply(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = trip_tool(memory)
    token = current_thread_id.set("wa-empty-trip")
    try:
        result = tool.invoke({})
    finally:
        current_thread_id.reset(token)
    assert "nada mudou" in result.casefold()
    assert "Não chame esta ferramenta de novo neste turno" in result
    assert "AgentReply" in result
    assert memory.trips.get("wa-empty-trip") == {}


def test_update_trip_brief_new_request_clears_old_dates(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = trip_tool(memory)
    token = current_thread_id.set("wa-new")
    try:
        tool.invoke(
            {
                "origin": "Palmas",
                "destination": "SCL",
                "date_from": "01/08/2027",
                "date_to": "31/08/2027",
                "notes": "buscas anteriores não retornaram",
            }
        )
        result = tool.invoke(
            {
                "new_request": True,
                "origin": "Palmas",
                "destination": "São Paulo",
            }
        )
    finally:
        current_thread_id.reset(token)
    saved = memory.trips.get("wa-new")
    assert "São Paulo" in result
    assert saved["destination"] == "São Paulo"
    assert "date_from" not in saved
    assert "notes" not in saved


def test_update_trip_brief_schema_describes_new_request_and_notes(tmp_path):
    tool = trip_tool(AgentMemory.create(tmp_path / "agent.sqlite"))
    props = tool.get_input_schema().model_json_schema()["properties"]
    assert "new_request" in props
    assert "zera" in props["new_request"]["description"].casefold()
    assert "resultados de busca" in props["notes"]["description"].casefold()
    assert "Palmas" in props["origin"]["description"]
    assert "status" not in props
    assert "save_user_preferences" in props["adults"]["description"]


def test_open_memory_uses_sqlite_checkpointer(tmp_path):
    async def _run():
        async with open_memory(tmp_path / "agent.sqlite") as memory:
            assert memory.checkpointer is not None
            assert memory.state_path == state_db_path(tmp_path / "agent.sqlite")
            assert memory.path != memory.state_path
            memory.prefs.update("jid@s.whatsapp.net", home_city="BH")
            assert memory.prefs.get("jid@s.whatsapp.net")["home_city"] == "BH"
            memory.trips.update("jid@s.whatsapp.net", origin="BH", destination="SP")
            assert memory.trips.get("jid@s.whatsapp.net")["origin"] == "BH"

    asyncio.run(_run())


def test_state_and_checkpointer_use_separate_files(tmp_path):
    checkpoint = tmp_path / "agent.sqlite"
    memory = AgentMemory.create(checkpoint)
    assert memory.path == checkpoint
    assert memory.state_path == tmp_path / "agent-state.sqlite"
    assert memory.prefs.path == memory.state_path
    assert memory.trips.path == memory.state_path


def test_concurrent_trip_updates_do_not_raise(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")

    def _write(i: int) -> None:
        memory.trips.update(
            "chat-race",
            origin="Palmas",
            destination="São Paulo",
            notes=f"n{i}",
            status="searched",
        )

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_write, range(20)))

    saved = memory.trips.get("chat-race")
    assert saved["origin"] == "Palmas"
    assert saved["status"] == "searched"
    assert saved["notes"].startswith("n")


def _count_rows(path, table: str, thread_id: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def test_reset_thread_clears_prefs_brief_and_checkpoints(tmp_path):
    async def _run():
        checkpoint = tmp_path / "agent.sqlite"
        async with open_memory(checkpoint) as memory:
            jid = "5511999999999@s.whatsapp.net"
            other = "other@s.whatsapp.net"
            memory.prefs.update(jid, home_city="Palmas")
            memory.trips.update(jid, origin="Palmas", destination="Santiago, Chile")
            memory.prefs.update(other, home_city="Recife")
            conn = sqlite3.connect(checkpoint)
            conn.execute(
                "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
                "VALUES (?, '', 'c1', ?, ?)",
                (jid, b"x", b"{}"),
            )
            conn.execute(
                "INSERT INTO writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value) "
                "VALUES (?, '', 'c1', 't1', 0, 'msg', ?)",
                (jid, b"x"),
            )
            conn.commit()
            conn.close()

            await memory.reset_thread(jid)
            await memory.reset_thread(jid)

            assert memory.prefs.get(jid) == {}
            assert memory.trips.get(jid) == {}
            assert memory.prefs.get(other)["home_city"] == "Recife"
            assert _count_rows(checkpoint, "checkpoints", jid) == 0
            assert _count_rows(checkpoint, "writes", jid) == 0

    asyncio.run(_run())


def test_identical_update_trip_brief_is_noop(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = trip_tool(memory)
    token = current_thread_id.set("wa-dup")
    try:
        first = tool.invoke(
            {
                "origin": "Palmas",
                "destination": "São Paulo",
                "trip_type": "round_trip",
            }
        )
        again = tool.invoke(
            {
                "origin": "Palmas",
                "destination": "São Paulo",
                "trip_type": "round_trip",
            }
        )
    finally:
        current_thread_id.reset(token)
    assert "Pedido ativo atualizado" in first
    assert "nada mudou" in again.casefold()
    assert "Não chame esta ferramenta de novo neste turno" in again
    assert "AgentReply" in again
    assert memory.trips.get("wa-dup")["origin"] == "Palmas"


def test_identical_save_user_preferences_is_noop(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    tool = preference_tool(memory)
    token = current_thread_id.set("wa-dup-pref")
    try:
        first = tool.invoke({"home_city": "Palmas"})
        again = tool.invoke({"home_city": "Palmas"})
    finally:
        current_thread_id.reset(token)
    assert "Preferências salvas" in first
    assert "search_flights" in first
    assert "nada mudou" in again.casefold()
    assert "Não chame esta ferramenta de novo neste turno" in again
    assert memory.prefs.get("wa-dup-pref")["home_city"] == "Palmas"


def test_save_user_preferences_schema_is_for_stable_prefs(tmp_path):
    tool = preference_tool(AgentMemory.create(tmp_path / "agent.sqlite"))
    assert "TODAS as viagens" in tool.description
    assert "update_trip_brief" in tool.description
    props = tool.get_input_schema().model_json_schema()["properties"]
    assert "desta viagem" in props["adults"]["description"].casefold()


def test_prompt_covers_bottleneck_contracts():
    assert "X − N dias" in SYSTEM_PROMPT
    assert "07/08/2027" in SYSTEM_PROMPT
    assert "hand_bags=1" in SYSTEM_PROMPT
    assert "quer que eu busque" in SYSTEM_PROMPT.casefold()
    assert "abrir o link" in SYSTEM_PROMPT
    assert "no máximo 1× por turno" in SYSTEM_PROMPT.casefold()
    assert "De onde você sai?" in SYSTEM_PROMPT
    assert "uma semana em dezembro" in SYSTEM_PROMPT
    assert "Não peça IATA" in SYSTEM_PROMPT
    assert "vale pra SEMPRE" in SYSTEM_PROMPT
    assert "home_city" in SYSTEM_PROMPT
    assert "paralelo com search_flights" in SYSTEM_PROMPT
    assert "confira ida e volta" in SYSTEM_PROMPT.casefold()
    assert "Bom dia! Tá pensando em viajar pra onde?" in SYSTEM_PROMPT
