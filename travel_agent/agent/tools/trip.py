from __future__ import annotations

from typing import Literal

from langchain.tools import tool

from travel_agent.agent.memory import AgentMemory, current_thread_id
from travel_agent.agent.places import resolve_place


def trip_tool(memory: AgentMemory):
    @tool
    def update_trip_brief(
        origin: str | None = None,
        destination: str | None = None,
        trip_type: Literal["one_way", "round_trip"] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        return_from: str | None = None,
        return_to: str | None = None,
        cabin: str | None = None,
        adults: int | None = None,
        currency: str | None = None,
        status: Literal["collecting", "ready", "searched"] | None = None,
        notes: str | None = None,
    ) -> str:
        """Atualiza o pedido ativo (origem, destino, datas, ida/volta, status)."""
        thread_id = current_thread_id.get()
        if not thread_id:
            return "Não consegui associar o pedido a este chat."
        if origin:
            origin = resolve_place(origin)
        if destination:
            destination = resolve_place(destination)
        saved = memory.trips.update(
            thread_id,
            origin=origin,
            destination=destination,
            trip_type=trip_type,
            date_from=date_from,
            date_to=date_to,
            return_from=return_from,
            return_to=return_to,
            cabin=cabin,
            adults=adults,
            currency=currency,
            status=status,
            notes=notes,
        )
        if not saved:
            return "Nada para atualizar no pedido."
        summary = ", ".join(f"{key}={value}" for key, value in saved.items())
        return f"Pedido ativo atualizado: {summary}"

    return update_trip_brief
