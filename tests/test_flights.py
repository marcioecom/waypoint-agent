from flights import compress_search_payload, mcp_search_args, offer_from_itinerary


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
    assert compressed["resultsCount"] == 10
    assert len(compressed["offers"]) == 5
    assert "Copie price/route" in compressed["note"]


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
