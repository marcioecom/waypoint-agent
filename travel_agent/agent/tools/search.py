from __future__ import annotations

import json
import logging
from typing import Annotated, Literal

from langchain.tools import BaseTool, tool
from pydantic import Field

from travel_agent.agent.flights import compress_search_payload, mcp_search_args
from travel_agent.agent.places import (
    arrival_airports,
    expected_arrival_iata,
    offers_for_destination,
)

logger = logging.getLogger(__name__)

_EMPTY_HINT = (
    "A Kiwi não retornou itinerários. Confira se origem/destino estão como "
    "cidade simples ou IATA (ex.: Palmas, PMW, SCL) — nunca “Cidade, País” — "
    "e se a data está na lista de Próximos meses (~12 meses). "
    "Não repita os mesmos argumentos; no máximo 1 tentativa diferente, "
    "senão responda ao usuário."
)


def find_kiwi_search(tools: list[BaseTool]) -> BaseTool:
    for item in tools:
        if item.name in {"search-flight", "search_flight", "search-flights"}:
            return item
    names = ", ".join(sorted(t.name for t in tools)) or "(nenhuma)"
    raise RuntimeError(f"Tool Kiwi search-flight não encontrada. Disponíveis: {names}")


def search_tool(kiwi_search: BaseTool):
    @tool
    async def search_flights(
        fly_from: Annotated[
            str,
            Field(
                description=(
                    'Origem: IATA ("PMW") ou cidade simples ("Palmas"). '
                    'Nunca "Cidade, País", nunca vírgula, nunca parênteses.'
                )
            ),
        ],
        fly_to: Annotated[
            str,
            Field(
                description=(
                    'Destino: IATA ("SCL", "DPS") ou cidade simples ("São Paulo"). '
                    "Homônimo → IATA (Santiago do Chile = SCL, Bali = DPS). "
                    'Nunca "Cidade, País".'
                )
            ),
        ],
        departure_date: Annotated[
            str,
            Field(description="Início da janela de ida, dd/mm/yyyy (ex.: 01/11/2026)."),
        ],
        departure_date_to: Annotated[
            str | None,
            Field(
                default=None,
                description="Fim da janela de ida, dd/mm/yyyy. No mês inteiro, o último dia.",
            ),
        ] = None,
        return_date: Annotated[
            str | None,
            Field(
                default=None,
                description="Volta explícita, dd/mm/yyyy. Não use junto com nights_in_dst_*.",
            ),
        ] = None,
        return_date_to: Annotated[
            str | None,
            Field(default=None, description="Fim da janela de volta, dd/mm/yyyy."),
        ] = None,
        nights_in_dst_from: Annotated[
            int | None,
            Field(default=None, description="Mínimo de noites no destino (ex.: 7)."),
        ] = None,
        nights_in_dst_to: Annotated[
            int | None,
            Field(default=None, description="Máximo de noites no destino (ex.: 7)."),
        ] = None,
        adults: int = 1,
        cabin_class: Literal["M", "W", "C", "F"] = "M",
        currency: Literal["BRL", "USD", "EUR"] = "BRL",
        sort: Literal["price", "duration", "quality", "date"] = "price",
    ) -> str:
        """Busca voos na Kiwi. Datas em dd/mm/yyyy.

        Preferências de uso:
        - Mês + estadia de N dias (ex.: “1 semana em janeiro, a mais barata”):
          departure_date/departure_date_to cobrindo o mês + nights_in_dst_from/to=N.
          Não peça semana específica e NÃO use return_date nesses casos.
        - Ida e volta com datas de volta explícitas: return_date / return_date_to.
        - Origem/destino: IATA (SCL) ou cidade simples (São Paulo). Nunca “Cidade, País”.
          Se o usuário der um código (PMW), use exatamente esse código.
        """
        args = mcp_search_args(
            fly_from=fly_from,
            fly_to=fly_to,
            departure_date=departure_date,
            departure_date_to=departure_date_to,
            return_date=return_date,
            return_date_to=return_date_to,
            nights_in_dst_from=nights_in_dst_from,
            nights_in_dst_to=nights_in_dst_to,
            adults=adults,
            cabin_class=cabin_class,
            currency=currency,
            sort=sort,
        )
        compressed = await _run_search(kiwi_search, args)
        offers = list(compressed.get("offers") or [])
        expected = expected_arrival_iata(fly_to)
        matched = offers_for_destination(offers, fly_to)

        if expected and offers and not matched:
            got = ", ".join(arrival_airports(offers)) or "outro aeroporto"
            wanted = ", ".join(sorted(expected))
            logger.warning(
                "flight destination mismatch: wanted %s (%s), got %s",
                fly_to,
                wanted,
                got,
            )
            return json.dumps(
                {
                    "status": "destination_mismatch",
                    "query": compressed.get("query"),
                    "destination": fly_to,
                    "resultsCount": 0,
                    "offers": [],
                    "arrivalAirports": arrival_airports(offers),
                    "note": (
                        f"A busca retornou voos chegando em {got}, não em {fly_to}. "
                        "Não apresente essas rotas como se fossem o destino pedido. "
                        "Avise com honestidade."
                    ),
                },
                ensure_ascii=False,
            )

        result = dict(compressed)
        result["offers"] = matched
        result["destination"] = fly_to
        result["arrivalAirports"] = arrival_airports(result["offers"])
        if result["offers"]:
            result["status"] = "ok"
        else:
            result["status"] = "empty"
            result["resultsCount"] = 0
            result["hint"] = _EMPTY_HINT
        return json.dumps(result, ensure_ascii=False)

    return search_flights


async def _run_search(kiwi_search: BaseTool, args: dict) -> dict:
    raw = await kiwi_search.ainvoke(args)
    return compress_search_payload(raw, limit=5)
