import asyncio
import json

from travel_agent.agent.memory import AgentMemory, current_thread_id
from travel_agent.agent.tools.search import search_tool


def _leg(route: list[str], day: str) -> dict:
    return {
        "route": route,
        "departureTime": f"{day}T08:00:00",
        "arrivalTime": f"{day}T18:00:00",
        "stops": max(len(route) - 2, 0),
        "segments": [{"carrierName": "LATAM"}],
    }


def kiwi_payload(destination_iata: str) -> dict:
    return {
        "query": f"Palmas → {destination_iata} on 14/08/2027, returning 21/08/2027",
        "currency": "BRL",
        "resultsCount": 1,
        "itineraries": [
            {
                "priceFormatted": "R$ 2.100,00",
                "bookingUrl": f"https://kiwi/{destination_iata.lower()}",
                "outbound": _leg(["PMW", "GRU", destination_iata], "2027-08-14"),
                "inbound": _leg([destination_iata, "GRU", "PMW"], "2027-08-21"),
            }
        ],
    }


class FakeKiwi:
    """Responde SCL só quando a query já veio desambiguada; senão RAI."""

    def __init__(self, always: str | None = None):
        self.calls: list[dict] = []
        self.always = always

    async def ainvoke(self, args: dict) -> dict:
        self.calls.append(args)
        if self.always:
            return kiwi_payload(self.always)
        fly_to = str(args["flyTo"])
        folded = fly_to.casefold()
        dest = "SCL" if "chile" in folded or fly_to.upper() == "SCL" else "RAI"
        return kiwi_payload(dest)


def _search(memory: AgentMemory, kiwi: FakeKiwi, fly_to: str, thread_id: str = "wa-1"):
    tool = search_tool(memory, kiwi)
    token = current_thread_id.set(thread_id)
    try:
        raw = asyncio.run(
            tool.ainvoke(
                {
                    "fly_from": "Palmas",
                    "fly_to": fly_to,
                    "departure_date": "14/08/2027",
                    "return_date": "21/08/2027",
                    "adults": 2,
                }
            )
        )
    finally:
        current_thread_id.reset(token)
    return json.loads(raw)


def test_santiago_search_goes_to_chile_not_cape_verde(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    kiwi = FakeKiwi()
    payload = _search(memory, kiwi, "Santiago")

    assert kiwi.calls[0]["flyTo"] == "Santiago, Chile"
    assert payload["destination"] == "Santiago, Chile"
    assert payload["offers"]
    assert "SCL" in payload["offers"][0]["route"]
    assert "RAI" not in payload["offers"][0]["route"]
    assert memory.trips.get("wa-1")["destination"] == "Santiago, Chile"


def test_chile_santiago_keeps_country_in_brief_and_query(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    kiwi = FakeKiwi()
    payload = _search(memory, kiwi, "Chile Santiago")

    assert kiwi.calls[0]["flyTo"] == "Santiago, Chile"
    assert payload["arrivalAirports"] == ["SCL"]
    assert memory.trips.get("wa-1")["destination"] == "Santiago, Chile"


def test_mismatch_retries_iata_and_does_not_return_wrong_offers(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    kiwi = FakeKiwi(always="RAI")
    payload = _search(memory, kiwi, "Santiago")

    assert [call["flyTo"] for call in kiwi.calls] == ["Santiago, Chile", "SCL"]
    assert payload["offers"] == []
    assert payload["resultsCount"] == 0
    assert "RAI" in payload["note"]
    assert "Chile" in payload["note"]
    assert "Não apresente" in payload["note"]


def test_explicit_cape_verde_is_not_rewritten_to_chile(tmp_path):
    memory = AgentMemory.create(tmp_path / "agent.sqlite")
    kiwi = FakeKiwi()
    payload = _search(memory, kiwi, "Santiago Cabo Verde")

    assert kiwi.calls[0]["flyTo"] == "RAI"
    assert payload["offers"]
    assert "RAI" in payload["offers"][0]["route"]
    assert memory.trips.get("wa-1")["destination"] == "RAI"
