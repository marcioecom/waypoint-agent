from __future__ import annotations

from typing import Annotated, Literal

from langchain.tools import tool
from pydantic import Field

from travel_agent.agent.memory import AgentMemory, current_thread_id


def trip_tool(memory: AgentMemory):
    @tool
    def update_trip_brief(
        origin: Annotated[
            str | None,
            Field(
                default=None,
                description='Origem: IATA ("PMW") ou cidade simples ("Palmas"). Sem país.',
            ),
        ] = None,
        destination: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    'Destino: IATA ("SCL", "DPS") ou cidade simples ("São Paulo"). Sem país.'
                ),
            ),
        ] = None,
        trip_type: Literal["one_way", "round_trip"] | None = None,
        date_from: Annotated[
            str | None,
            Field(default=None, description="Início da ida, dd/mm/yyyy."),
        ] = None,
        date_to: Annotated[
            str | None,
            Field(default=None, description="Fim da janela de ida, dd/mm/yyyy."),
        ] = None,
        return_from: Annotated[
            str | None,
            Field(default=None, description="Início da volta, dd/mm/yyyy."),
        ] = None,
        return_to: Annotated[
            str | None,
            Field(default=None, description="Fim da janela de volta, dd/mm/yyyy."),
        ] = None,
        cabin: str | None = None,
        adults: int | None = None,
        currency: Literal["BRL", "USD", "EUR"] | None = None,
        status: Literal["collecting", "ready", "searched"] | None = None,
        notes: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Só preferências do usuário (ex.: “quer estar lá em 16/08”). "
                    "Nunca resultados de busca nem sugestões."
                ),
            ),
        ] = None,
        new_request: Annotated[
            bool,
            Field(
                default=False,
                description=(
                    "true quando o usuário muda origem ou destino "
                    "(“esquece isso”, “agora pra X”). Zera datas, estadia e notas; "
                    "envie só os campos do pedido novo."
                ),
            ),
        ] = False,
    ) -> str:
        """Atualiza o pedido ativo (origem, destino, datas, ida/volta, status).

        Pedido novo: new_request=true e só os campos que o usuário disse agora.
        """
        thread_id = current_thread_id.get()
        if not thread_id:
            return "Não consegui associar o pedido a este chat."
        saved = memory.trips.update(
            thread_id,
            new_request=new_request,
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
