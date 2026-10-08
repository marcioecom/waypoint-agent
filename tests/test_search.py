import asyncio
import json
import inspect

from travel_agent.agent.tools.search import search_tool


def _leg(route: list[str], day: str) -> dict:
    return {
        "route": route,
        "departureTime": f"{day}T08:00:00",
        "arrivalTime": f"{day}T18:00:00",
        "stops": max(len(route) - 2, 0),
        "segments": [{"carrierName": "LATAM"}],
    }


def kiwi_payload(destination_iata: str, *, results: int = 1) -> dict:
    itineraries = []
    if results:
        itineraries.append(
            {
                "priceFormatted": "R$ 2.100,00",
                "bookingUrl": f"https://kiwi/{destination_iata.lower()}",
                "outbound": _leg(["PMW", "GRU", destination_iata], "2027-08-14"),
                "inbound": _leg([destination_iata, "GRU", "PMW"], "2027-08-21"),
            }
        )
    return {
        "query": f"Palmas → {destination_iata} on 14/08/2027, returning 21/08/2027",
        "currency": "BRL",
        "resultsCount": results,
        "itineraries": itineraries,
    }


class FakeKiwi:
    def __init__(self, always: str | None = None, *, empty: bool = False):
        self.calls: list[dict] = []
        self.always = always
        self.empty = empty

    async def ainvoke(self, args: dict) -> dict:
        self.calls.append(args)
        if self.empty:
            return kiwi_payload(str(args["flyTo"]), results=0)
        if self.always:
            return kiwi_payload(self.always)
        fly_to = str(args["flyTo"])
        dest = fly_to.upper() if len(fly_to) == 3 else fly_to
        return kiwi_payload(dest if dest.isascii() else "GRU")


def _search(kiwi: FakeKiwi, fly_from: str, fly_to: str) -> dict:
    tool = search_tool(kiwi)
    raw = asyncio.run(
        tool.ainvoke(
            {
                "fly_from": fly_from,
                "fly_to": fly_to,
                "departure_date": "14/08/2027",
                "return_date": "21/08/2027",
                "adults": 2,
            }
        )
    )
    return json.loads(raw)


def _schema(tool) -> dict:
    return tool.get_input_schema().model_json_schema()


def test_city_or_iata_is_sent_as_is():
    kiwi = FakeKiwi(always="SCL")
    payload = _search(kiwi, "Palmas", "SCL")

    assert kiwi.calls[0]["flyTo"] == "SCL"
    assert kiwi.calls[0]["flyFrom"] == "Palmas"
    assert payload["status"] == "ok"
    assert payload["destination"] == "SCL"
    assert "SCL" in payload["offers"][0]["route"]
    assert len(kiwi.calls) == 1


def test_simple_city_name_is_not_rewritten_with_country():
    kiwi = FakeKiwi(always="GRU")
    payload = _search(kiwi, "Palmas", "São Paulo")

    assert kiwi.calls[0]["flyFrom"] == "Palmas"
    assert kiwi.calls[0]["flyTo"] == "São Paulo"
    assert payload["destination"] == "São Paulo"
    assert payload["status"] == "ok"


def test_empty_search_explains_next_step_not_wrong_destination():
    kiwi = FakeKiwi(empty=True)
    payload = _search(kiwi, "Palmas, Brasil", "Santiago, Chile")

    assert kiwi.calls[0]["flyTo"] == "Santiago, Chile"
    assert payload["status"] == "empty"
    assert payload["resultsCount"] == 0
    assert payload["offers"] == []
    assert "IATA" in payload["hint"]
    assert "Cidade, País" in payload["hint"]
    assert "destino inesperado" not in json.dumps(payload)


def test_iata_mismatch_does_not_retry_or_return_wrong_offers():
    kiwi = FakeKiwi(always="RAI")
    payload = _search(kiwi, "Palmas", "SCL")

    assert [call["flyTo"] for call in kiwi.calls] == ["SCL"]
    assert payload["status"] == "destination_mismatch"
    assert payload["offers"] == []
    assert payload["resultsCount"] == 0
    assert "RAI" in payload["note"]
    assert "Não apresente" in payload["note"]


def test_search_tool_does_not_write_the_brief():
    assert "memory" not in inspect.signature(search_tool).parameters


def test_search_flights_schema_describes_city_or_iata():
    tool = search_tool(FakeKiwi())
    props = _schema(tool)["properties"]
    assert "Palmas" in props["fly_from"]["description"]
    assert "Cidade, País" in props["fly_from"]["description"]
    assert "SCL" in props["fly_to"]["description"]
    assert "São Paulo" in props["fly_to"]["description"]
    assert set(props["currency"]["enum"]) == {"BRL", "USD", "EUR"}
    assert "Cidade, País" in tool.description
    assert "X − N" in props["departure_date"]["description"]
    assert "mão" in props["hand_bags"]["description"]
    assert "14/08/2027" in tool.description


def test_search_flights_passes_bags_through():
    kiwi = FakeKiwi(always="SCL")
    tool = search_tool(kiwi)
    raw = asyncio.run(
        tool.ainvoke(
            {
                "fly_from": "Palmas",
                "fly_to": "SCL",
                "departure_date": "07/08/2027",
                "departure_date_to": "14/08/2027",
                "nights_in_dst_from": 7,
                "nights_in_dst_to": 7,
                "adults": 2,
                "hand_bags": 1,
                "hold_bags": 0,
            }
        )
    )
    payload = json.loads(raw)
    assert kiwi.calls[0]["adults_hand_bags"] == 1
    assert kiwi.calls[0]["adults_hold_bags"] == 0
    assert kiwi.calls[0]["adults"] == 2
    assert payload["status"] == "ok"


def test_search_flights_omits_bags_by_default():
    kiwi = FakeKiwi(always="SCL")
    _search(kiwi, "Palmas", "SCL")
    assert kiwi.calls[0]["adults_hand_bags"] is None
    assert kiwi.calls[0]["adults_hold_bags"] is None
