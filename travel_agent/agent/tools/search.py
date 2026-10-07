from __future__ import annotations

import json
from typing import Literal

from langchain.tools import BaseTool, tool

from travel_agent.agent.flights import compress_search_payload, mcp_search_args
from travel_agent.agent.memory import AgentMemory, current_thread_id


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
        adults: int = 1,
        cabin_class: Literal["M", "W", "C", "F"] = "M",
        currency: str = "BRL",
        sort: Literal["price", "duration", "quality", "date"] = "price",
    ) -> str:
        """Busca voos na Kiwi. Datas em dd/mm/yyyy. Use faixas com *_to para mês inteiro."""
        thread_id = current_thread_id.get()
        if thread_id:
            memory.trips.update(
                thread_id,
                origin=fly_from,
                destination=fly_to,
                trip_type="round_trip" if return_date else "one_way",
                date_from=departure_date,
                date_to=departure_date_to or departure_date,
                return_from=return_date,
                return_to=return_date_to or return_date,
                adults=adults,
                currency=currency,
                status="searched",
            )

        args = mcp_search_args(
            fly_from=fly_from,
            fly_to=fly_to,
            departure_date=departure_date,
            departure_date_to=departure_date_to,
            return_date=return_date,
            return_date_to=return_date_to,
            adults=adults,
            cabin_class=cabin_class,
            currency=currency,
            sort=sort,
        )
        raw = await kiwi_search.ainvoke(args)
        compressed = compress_search_payload(raw, limit=5)
        return json.dumps(compressed, ensure_ascii=False)

    return search_flights
