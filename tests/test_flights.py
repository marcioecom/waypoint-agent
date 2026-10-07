import json

from travel_agent.agent.flights import (
    compress_search_payload,
    mcp_search_args,
    offer_from_itinerary,
)


def test_offer_from_itinerary_formats_route_and_details():
    itinerary = {
        "priceFormatted": "R$ 1.200,00",
        "bookingUrl": "https://www.kiwi.com/deep?x=1",
        "baggage": {"cabinBag": 1, "checkedBag": 0, "personalItem": 1},
        "outbound": {
            "route": ["PMW", "GRU"],
            "departureTime": "2027-01-10T08:00:00",
            "arrivalTime": "2027-01-10T10:30:00",
            "stops": 0,
            "segments": [{"carrierName": "GOL", "carrier": "G3"}],
        },
        "inbound": {
            "route": ["GRU", "PMW"],
            "departureTime": "2027-01-20T18:00:00",
            "arrivalTime": "2027-01-20T20:10:00",
            "stops": 0,
            "segments": [{"carrierName": "GOL"}],
        },
    }
    offer = offer_from_itinerary(itinerary)
    assert offer["price"] == "R$ 1.200,00"
    assert "PMW → GRU" in offer["route"]
    assert "volta:" in offer["route"]
    assert "GOL" in offer["details"]
    assert "direto" in offer["details"]
    assert offer["booking_url"].startswith("https://www.kiwi.com/")


def test_compress_search_payload_limits_offers():
    payload = {
        "query": "Palmas → São Paulo",
        "currency": "BRL",
        "resultsCount": 10,
        "itineraries": [
            {
                "priceFormatted": f"R$ {i}",
                "bookingUrl": f"https://kiwi/{i}",
                "outbound": {
                    "route": ["PMW", "GRU"],
                    "departureTime": "2027-01-01T10:00:00",
                    "arrivalTime": "2027-01-01T12:00:00",
                    "stops": 0,
                    "segments": [{"carrierName": "LATAM"}],
                },
            }
            for i in range(8)
        ],
    }
    compressed = compress_search_payload(payload, limit=5)
    assert compressed["status"] == "ok"
    assert compressed["resultsCount"] == 10
    assert len(compressed["offers"]) == 5
    assert "Copie price/route" in compressed["note"]


def test_compress_empty_is_not_a_retry_command():
    compressed = compress_search_payload(
        {"resultsCount": 0, "itineraries": [], "error": None}
    )
    assert compressed["status"] == "empty"
    assert compressed["offers"] == []
    assert "tente de novo" not in compressed["note"].casefold()


def test_compress_preserves_provider_error():
    compressed = compress_search_payload(
        {
            "resultsCount": 0,
            "itineraries": [],
            "error": "Currency 'BRR' is not supported.",
        }
    )
    assert compressed["status"] == "provider_error"
    assert "BRR" in compressed["error"]
    assert "não diga que não há voos" in compressed["note"].casefold()


def test_compress_unwraps_mcp_content_blocks():
    """Regressão: MCP devolve list[{type,text}] e o wrapper zerava offers."""
    inner = {
        "query": "Palmas → São Paulo on 01/01/2027–31/01/2027",
        "currency": "BRL",
        "resultsCount": 15,
        "itineraries": [
            {
                "price": 953.0,
                "priceFormatted": "953 BRL",
                "bookingUrl": "https://kiwi.com/u/abc",
                "outbound": {
                    "route": ["PMW", "GRU"],
                    "departureTime": "2027-01-10T08:00:00",
                    "arrivalTime": "2027-01-10T10:30:00",
                    "stops": 0,
                    "segments": [{"carrierName": "GOL"}],
                },
                "inbound": {
                    "route": ["GRU", "PMW"],
                    "departureTime": "2027-01-17T18:00:00",
                    "arrivalTime": "2027-01-17T20:10:00",
                    "stops": 0,
                    "segments": [{"carrierName": "GOL"}],
                },
            }
        ],
    }
    payload = [{"type": "text", "text": json.dumps(inner)}]
    compressed = compress_search_payload(payload, limit=5)
    assert compressed["resultsCount"] == 15
    assert len(compressed["offers"]) == 1
    assert compressed["offers"][0]["price"] == "953 BRL"
    assert "PMW → GRU" in compressed["offers"][0]["route"]


def test_compress_unwraps_mcp_content_blocks_repr_string():
    inner = {
        "resultsCount": 2,
        "itineraries": [
            {
                "priceFormatted": "100 BRL",
                "bookingUrl": "https://kiwi.com/1",
                "outbound": {
                    "route": ["PMW", "GRU"],
                    "departureTime": "2027-01-01T10:00:00",
                    "arrivalTime": "2027-01-01T12:00:00",
                    "stops": 0,
                    "segments": [{"carrierName": "LATAM"}],
                },
            }
        ],
    }
    # Formato visto no LangSmith quando o content block chega como str(repr).
    payload = str([{"type": "text", "text": json.dumps(inner)}])
    compressed = compress_search_payload(payload, limit=3)
    assert compressed["resultsCount"] == 2
    assert compressed["offers"][0]["price"] == "100 BRL"


def test_mcp_search_args_fills_strict_schema():
    args = mcp_search_args(
        fly_from="Palmas",
        fly_to="São Paulo",
        departure_date="01/01/2027",
        departure_date_to="31/01/2027",
        return_date="31/01/2027",
    )
    assert args["flyFrom"] == "Palmas"
    assert args["currency"] == "BRL"
    assert args["locale"] == "pt"
    assert args["departureDateTo"] == "31/01/2027"
    assert args["children"] == 0
    assert args["select_airlines"] is None


def test_mcp_search_args_nights_clears_return_dates():
    args = mcp_search_args(
        fly_from="Palmas",
        fly_to="São Paulo",
        departure_date="01/01/2027",
        departure_date_to="31/01/2027",
        return_date="08/01/2027",
        return_date_to="07/02/2027",
        nights_in_dst_from=7,
        nights_in_dst_to=7,
    )
    assert args["nights_in_dst_from"] == 7
    assert args["nights_in_dst_to"] == 7
    assert args["returnDate"] is None
    assert args["returnDateTo"] is None
