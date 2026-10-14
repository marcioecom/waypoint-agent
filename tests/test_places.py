from travel_agent.agent.places import (
    arrival_airports,
    arrival_iata,
    expected_arrival_iata,
    offers_for_destination,
)


def test_only_iata_destination_has_expected_airports():
    assert expected_arrival_iata("SCL") == frozenset({"SCL"})
    assert expected_arrival_iata("scl") == frozenset({"SCL"})
    assert expected_arrival_iata("RAI") == frozenset({"RAI"})
    assert expected_arrival_iata("Santiago") is None
    assert expected_arrival_iata("Santiago, Chile") is None
    assert expected_arrival_iata("São Paulo") is None
    assert expected_arrival_iata("Bali") is None


def test_arrival_iata_reads_last_outbound_airport():
    route = (
        "PMW → CNF → GRU → CMN → RAI · 14/08 10:00 → 15/08 08:00"
        " | volta: RAI → OXB → CMN → GRU → PMW · 21/08 09:00 → 22/08 18:00"
    )
    assert arrival_iata(route) == "RAI"
    assert arrival_iata("PMW → SCL · 08:00 → 14:00") == "SCL"


def test_offers_for_destination_filters_only_when_iata_was_asked():
    rai = {
        "price": "R$ 9.000",
        "route": "PMW → CNF → GRU → CMN → RAI · 14/08 10:00 → 15/08 08:00",
        "details": "várias escalas",
        "booking_url": "https://kiwi/rai",
    }
    scl = {
        "price": "R$ 2.100",
        "route": "PMW → GRU → SCL · 14/08 08:00 → 14/08 18:00",
        "details": "LATAM, 1 escala",
        "booking_url": "https://kiwi/scl",
    }
    assert offers_for_destination([rai], "SCL") == []
    assert offers_for_destination([rai, scl], "SCL") == [scl]
    assert offers_for_destination([rai], "Santiago") == [rai]
    assert arrival_airports([rai]) == ["RAI"]
