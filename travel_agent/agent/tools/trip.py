from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain.tools import tool
from pydantic import Field

from travel_agent.agent.memory import AgentMemory, current_thread_id

NOTHING_CHANGED = (
    "Nenhum campo informado; nada foi salvo e nada mudou. "
    "Não chame esta ferramenta de novo neste turno. Responda ao usuário com AgentReply."
)

_NEXT_STEP = (
    "Se origem, destino e datas estão no pedido, chame search_flights; senão AgentReply."
)


def _filled(**fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        out[key] = value
    return out


def _already_matches(current: dict[str, Any], incoming: dict[str, Any]) -> bool:
    if not incoming or not current:
        return False
    return all(current.get(key) == value for key, value in incoming.items())


def _brief_summary(brief: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in brief.items() if key != "status")


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
        adults: Annotated[
            int | None,
            Field(
                default=None,
                description="Adultos desta viagem. Não grave isso em save_user_preferences.",
            ),
        ] = None,
        currency: Literal["BRL", "USD", "EUR"] | None = None,
        notes: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    "Só preferências do usuário (ex.: “quer estar lá em 14/08/2027, 7 noites”). "
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
        """Atualiza o pedido ativo (origem, destino, datas, ida/volta, adultos).

        Uma vez por turno, com todos os campos novos juntos. Pedido novo: new_request=true
        e só o que o usuário disse agora. Se o PEDIDO ATIVO já reflete esta mensagem,
        não chame de novo — search_flights ou AgentReply.
        """
        incoming = _filled(
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
            notes=notes,
        )
        if not new_request and not incoming:
            return NOTHING_CHANGED
        thread_id = current_thread_id.get()
        if not thread_id:
            return "Não consegui associar o pedido a este chat."
        current = memory.trips.get(thread_id)
        if not new_request and _already_matches(current, incoming):
            summary = _brief_summary(current) or "sem campos novos"
            return (
                f"Nada mudou no pedido ativo: {summary}. "
                "Não chame esta ferramenta de novo neste turno. "
                f"{_NEXT_STEP}"
            )
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
            notes=notes,
        )
        if not saved:
            return NOTHING_CHANGED
        summary = _brief_summary(saved)
        return (
            f"Pedido ativo atualizado: {summary}. "
            "Já está salvo; não chame update_trip_brief de novo neste turno. "
            f"Se não há mais campo novo nesta mensagem: {_NEXT_STEP}"
        )

    return update_trip_brief
