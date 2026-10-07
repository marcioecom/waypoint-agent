from __future__ import annotations

import json
import logging
from typing import Literal

from langchain.tools import BaseTool, tool

from travel_agent.agent.flights import compress_search_payload, mcp_search_args
from travel_agent.agent.memory import AgentMemory, current_thread_id
from travel_agent.agent.places import (
    arrival_airports,
    expected_arrival_iata,
    offers_for_destination,
    resolve_place,
)

logger = logging.getLogger(__name__)


def find_kiwi_search(tools: list[BaseTool]) -> BaseTool:
    for item in tools:
        if item.name in {"search-flight", "search_flight", "search-flights"}:
            return item
    names = ", ".join(sorted(t.name for t in tools)) or "(nenhuma)"
    raise RuntimeError(f"Tool Kiwi search-flight não encontrada. Disponíveis: {names}")


def search_tool(memory: AgentMemory, kiwi_search: BaseTool):
    @tool
    async def search_flights(
        fly_from: str,
        fly_to: str,
        departure_date: str,
        departure_date_to: str | None = None,
        return_date: str | None = None,
        return_date_to: str | None = None,
        nights_in_dst_from: int | None = None,
        nights_in_dst_to: int | None = None,
        adults: int = 1,
        cabin_class: Literal["M", "W", "C", "F"] = "M",
        currency: str = "BRL",
        sort: Literal["price", "duration", "quality", "date"] = "price",
    ) -> str:
        """Busca voos na Kiwi. Datas em dd/mm/yyyy.

        Preferências de uso:
        - Mês + estadia de N dias (ex.: “1 semana em janeiro, a mais barata”):
          departure_date/departure_date_to cobrindo o mês + nights_in_dst_from/to=N.
          Não peça semana específica e NÃO use return_date nesses casos.
        - Ida e volta com datas de volta explícitas: return_date / return_date_to.
        - Passe cidade com país (ou IATA se já souber): “Santiago, Chile”.
          Não invente IATA e não peça IATA ao usuário.
        """
        fly_from = resolve_place(fly_from)
        fly_to = resolve_place(fly_to)
        thread_id = current_thread_id.get()
        if thread_id:
            try:
                memory.trips.update(
                    thread_id,
                    origin=fly_from,
                    destination=fly_to,
                    trip_type=(
                        "round_trip"
                        if return_date or nights_in_dst_from is not None
                        else "one_way"
                    ),
                    date_from=departure_date,
                    date_to=departure_date_to or departure_date,
                    return_from=return_date,
                    return_to=return_date_to or return_date,
                    adults=adults,
                    currency=currency,
                    status="searched",
                )
            except Exception:
                # Não abortar a busca (evita checkpoint com tool_call pendente).
                logger.exception("trip brief update failed for %s", thread_id)

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
        expected = expected_arrival_iata(fly_to)
        offers = list(compressed.get("offers") or [])
        matched = offers_for_destination(offers, fly_to)

        if expected and not matched:
            iata = next(iter(expected))
            if iata.upper() != fly_to.strip().upper():
                retry_args = dict(args)
                retry_args["flyTo"] = iata
                compressed = await _run_search(kiwi_search, retry_args)
                offers = list(compressed.get("offers") or [])
                matched = offers_for_destination(offers, iata)

        if expected and not matched:
            got = ", ".join(arrival_airports(offers)) or "destino inesperado"
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
                        f"A busca não chegou em {fly_to} ({wanted}); "
                        f"os voos foram para {got}. "
                        "Não apresente essas rotas como se fossem o destino pedido. "
                        "Avise com honestidade."
                    ),
                },
                ensure_ascii=False,
            )

        compressed["offers"] = matched or offers
        compressed["destination"] = fly_to
        compressed["arrivalAirports"] = arrival_airports(compressed["offers"])
        if "status" not in compressed:
            compressed["status"] = "ok" if compressed["offers"] else "empty"
        return json.dumps(compressed, ensure_ascii=False)

    return search_flights


async def _run_search(kiwi_search: BaseTool, args: dict) -> dict:
    raw = await kiwi_search.ainvoke(args)
    return compress_search_payload(raw, limit=5)
