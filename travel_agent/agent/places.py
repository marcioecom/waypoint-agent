"""Checa se as ofertas chegaram no IATA pedido.

Não reescreve cidade nem país. Homônimos (Santiago, Bali) o modelo
desambigua pelo IATA na tool. Só filtramos quando o destino já é um
código de 3 letras.
"""

from __future__ import annotations

import re

_IATA_RE = re.compile(r"\b[A-Z]{3}\b")


def _is_iata(text: str) -> bool:
    return len(text) == 3 and text.isascii() and text.isalpha()


def expected_arrival_iata(raw: str) -> frozenset[str] | None:
    """Aeroportos aceitáveis na chegada, só se o destino já for IATA."""
    text = raw.strip()
    if _is_iata(text):
        return frozenset({text.upper()})
    return None


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
