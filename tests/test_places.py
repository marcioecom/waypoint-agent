from travel_agent.agent.places import (
    arrival_airports,
    arrival_iata,
    expected_arrival_iata,
    offers_for_destination,
    resolve_place,
)


def test_santiago_defaults_to_chile():
    assert resolve_place("Santiago") == "Santiago, Chile"
    assert resolve_place("chile santiago") == "Santiago, Chile"
    assert resolve_place("Santiago do Chile") == "Santiago, Chile"
    assert expected_arrival_iata("Santiago") == frozenset({"SCL"})
    assert expected_arrival_iata("Santiago, Chile") == frozenset({"SCL"})


def test_santiago_cabo_verde_stays_rai():
    assert resolve_place("Santiago Cabo Verde") == "RAI"
    assert resolve_place("ilha de Santiago") == "RAI"
    assert resolve_place("Praia Santiago") == "RAI"
    assert expected_arrival_iata("RAI") == frozenset({"RAI"})


def test_santiago_de_compostela_is_not_chile():
    assert resolve_place("Santiago de Compostela") == "Santiago de Compostela"
    assert expected_arrival_iata("Santiago de Compostela") is None


def test_known_iata_is_kept():
    assert resolve_place("scl") == "SCL"
    assert resolve_place("RAI") == "RAI"
    assert expected_arrival_iata("SCL") == frozenset({"SCL"})


def test_unambiguous_city_is_unchanged():
    assert resolve_place("Palmas") == "Palmas"
    assert resolve_place("São Paulo") == "São Paulo"
    assert expected_arrival_iata("São Paulo") is None


def test_arrival_iata_reads_last_outbound_airport():
    route = (
        "PMW → CNF → GRU → CMN → RAI · 14/08 10:00 → 15/08 08:00"
        " | volta: RAI → OXB → CMN → GRU → PMW · 21/08 09:00 → 22/08 18:00"
    )
    assert arrival_iata(route) == "RAI"
    assert arrival_iata("PMW → SCL · 08:00 → 14:00") == "SCL"


def test_offers_for_destination_drops_cape_verde_when_chile_was_asked():
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
    assert offers_for_destination([rai], "Santiago, Chile") == []
    assert offers_for_destination([rai, scl], "Santiago") == [scl]
    assert arrival_airports([rai]) == ["RAI"]
