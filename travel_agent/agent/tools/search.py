from __future__ import annotations

import json
import logging
from typing import Literal

from langchain.tools import BaseTool, tool

from travel_agent.agent.flights import compress_search_payload, mcp_search_args
from travel_agent.agent.memory import AgentMemory, current_thread_id

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
        - Aceite nomes de cidade; não invente IATA.
        """
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
        raw = await kiwi_search.ainvoke(args)
        compressed = compress_search_payload(raw, limit=5)
        return json.dumps(compressed, ensure_ascii=False)

    return search_flights
