from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain.tools import tool
from pydantic import Field

from travel_agent.agent.memory import AgentMemory, current_thread_id

NOTHING_CHANGED = (
    "Nenhum campo informado; nada foi salvo e nada mudou. "
    "Não chame esta ferramenta de novo neste turno. Responda ao usuário com AgentReply."
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


def preference_tool(memory: AgentMemory):
    @tool
    def save_user_preferences(
        home_city: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    'Origem habitual: IATA ("PMW") ou cidade simples ("Palmas"). Sem país. '
                    "Use quando o usuário disser de onde sai, se ainda não houver home_city."
                ),
            ),
        ] = None,
        cabin: Annotated[
            str | None,
            Field(
                default=None,
                description='Só classe permanente (“sempre executiva”). Classe desta viagem → brief.',
            ),
        ] = None,
        currency: Literal["BRL", "USD", "EUR"] | None = None,
        adults: Annotated[
            int | None,
            Field(
                default=None,
                description=(
                    "Só se o usuário disser que SEMPRE viaja assim. "
                    "Adultos desta viagem → update_trip_brief + search_flights."
                ),
            ),
        ] = None,
        notes: Annotated[
            str | None,
            Field(
                default=None,
                description="Só hábito permanente. Bagagem desta viagem não entra aqui.",
            ),
        ] = None,
    ) -> str:
        """Salva o que vale para TODAS as viagens e o usuário acabou de dizer assim
        (origem habitual, moeda, “sempre executiva”). Preencha pelo menos um campo.
        Passageiros, bagagem e classe só desta viagem NÃO entram aqui — use
        update_trip_brief + search_flights. Não use para cumprimento nem para
        “verificar” preferências: elas já estão no CONTEXTO."""
        incoming = _filled(
            home_city=home_city,
            cabin=cabin,
            currency=currency,
            adults=adults,
            notes=notes,
        )
        if not incoming:
            return NOTHING_CHANGED
        thread_id = current_thread_id.get()
        if not thread_id:
            return "Não consegui associar as preferências a este chat."
        current = memory.prefs.get(thread_id)
        if current and all(current.get(key) == value for key, value in incoming.items()):
            summary = ", ".join(f"{key}={value}" for key, value in current.items())
            return (
                f"Nada mudou nas preferências: {summary}. "
                "Não chame esta ferramenta de novo neste turno. "
                "Ajuste desta viagem → search_flights; senão AgentReply."
            )
        saved = memory.prefs.update(
            thread_id,
            home_city=home_city,
            cabin=cabin,
            currency=currency,
            adults=adults,
            notes=notes,
        )
        if not saved:
            return NOTHING_CHANGED
        summary = ", ".join(f"{key}={value}" for key, value in saved.items())
        return (
            f"Preferências salvas: {summary}. Já está salvo; não chame de novo neste turno. "
            "Só o que vale sempre. Ajuste desta viagem (adultos, mala, datas) → "
            "search_flights na mesma volta; gravar prefs não substitui a busca."
        )

    return save_user_preferences
