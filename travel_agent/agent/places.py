"""Desambigua origem/destino antes da Kiwi.

Cidades com homônimos perigosos (Santiago, Córdoba…) ganham o default
óbvio para quem viaja do Brasil, a menos que o usuário já tenha dado
país ou IATA. Também serve para checar se as ofertas chegaram no lugar
pedido.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_IATA_RE = re.compile(r"\b[A-Z]{3}\b")


def fold(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in stripped if unicodedata.category(char) != "Mn")


def _is_iata(text: str) -> bool:
    return len(text) == 3 and text.isascii() and text.isalpha()


def _has_name(folded: str, name: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", folded) is not None


@dataclass(frozen=True)
class Place:
    names: tuple[str, ...]
    default: str
    default_iata: frozenset[str]
    variants: tuple[tuple[tuple[str, ...], str, frozenset[str]], ...] = ()
    exclude: tuple[str, ...] = ()

    def matches(self, folded: str) -> bool:
        if any(token in folded for token in self.exclude):
            return False
        return any(_has_name(folded, name) for name in self.names)

    def resolve(self, folded: str) -> tuple[str, frozenset[str]]:
        for hints, query, iata in self.variants:
            if any(hint in folded for hint in hints):
                return query, iata
        return self.default, self.default_iata

    def iata_for_code(self, code: str) -> frozenset[str] | None:
        if code in self.default_iata:
            return self.default_iata
        for _hints, _query, iata in self.variants:
            if code in iata:
                return iata
        return None


# Poucos homônimos que a Kiwi costuma resolver errado para um usuário BR.
PLACES: tuple[Place, ...] = (
    Place(
        names=("santiago",),
        default="Santiago, Chile",
        default_iata=frozenset({"SCL"}),
        variants=(
            (
                ("cabo verde", "cape verde", "praia", "ilha de santiago", "rai"),
                "RAI",
                frozenset({"RAI"}),
            ),
            (("chile", "scl"), "Santiago, Chile", frozenset({"SCL"})),
        ),
        exclude=("compostela",),
    ),
    Place(
        names=("cordoba",),
        default="Córdoba, Argentina",
        default_iata=frozenset({"COR"}),
        variants=(
            (
                ("espanha", "spain", "espana", "odb"),
                "Córdoba, Espanha",
                frozenset({"ODB"}),
            ),
            (("argentina", "cor"), "Córdoba, Argentina", frozenset({"COR"})),
        ),
    ),
    Place(
        names=("san jose",),
        default="San José, Costa Rica",
        default_iata=frozenset({"SJO"}),
        variants=(
            (
                ("california", "eua", "usa", "estados unidos", "sjc"),
                "SJC",
                frozenset({"SJC"}),
            ),
            (("costa rica", "sjo"), "San José, Costa Rica", frozenset({"SJO"})),
        ),
    ),
)


def _match_place(folded: str) -> Place | None:
    for place in PLACES:
        if place.matches(folded):
            return place
    return None


def resolve_place(raw: str) -> str:
    """Devolve o texto que deve ir para a Kiwi / TripBrief."""
    text = raw.strip()
    if not text:
        return text
    if _is_iata(text):
        return text.upper()
    place = _match_place(fold(text))
    if place is None:
        return text
    query, _iata = place.resolve(fold(text))
    return query


def expected_arrival_iata(raw: str) -> frozenset[str] | None:
    """Aeroportos aceitáveis na chegada, ou None se não há como checar."""
    text = raw.strip()
    if not text:
        return None
    if _is_iata(text):
        code = text.upper()
        for place in PLACES:
            matched = place.iata_for_code(code)
            if matched:
                return matched
        return frozenset({code})
    place = _match_place(fold(text))
    if place is None:
        return None
    _query, iata = place.resolve(fold(text))
    return iata


def arrival_iata(route: str) -> str | None:
    """Último IATA do trecho de ida (`PMW → … → SCL · horário`)."""
    outbound = route.split("|", 1)[0]
    path = outbound.split("·", 1)[0]
    codes = _IATA_RE.findall(path.upper())
    return codes[-1] if codes else None


def offers_for_destination(
    offers: list[dict],
    destination: str,
) -> list[dict]:
    expected = expected_arrival_iata(destination)
    if not expected:
        return list(offers)
    matched: list[dict] = []
    for offer in offers:
        code = arrival_iata(str(offer.get("route") or ""))
        if code and code in expected:
            matched.append(offer)
    return matched


def arrival_airports(offers: list[dict]) -> list[str]:
    seen: list[str] = []
    for offer in offers:
        code = arrival_iata(str(offer.get("route") or ""))
        if code and code not in seen:
            seen.append(code)
    return seen
