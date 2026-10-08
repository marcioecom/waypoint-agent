from __future__ import annotations

from typing import Annotated, Literal

from langchain.tools import tool
from pydantic import Field

from travel_agent.agent.memory import AgentMemory, current_thread_id

NOTHING_CHANGED = (
    "Nenhum campo informado; nada foi salvo e nada mudou. "
    "Não chame esta ferramenta de novo neste turno. Responda ao usuário com AgentReply."
)


def _has_field(*values: object) -> bool:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


def preference_tool(memory: AgentMemory):
    @tool
    def save_user_preferences(
        home_city: Annotated[
            str | None,
            Field(
                default=None,
                description=(
                    'Origem habitual: IATA ("PMW") ou cidade simples ("Palmas"). Sem país.'
                ),
            ),
        ] = None,
        cabin: str | None = None,
        currency: Literal["BRL", "USD", "EUR"] | None = None,
        adults: int | None = None,
        notes: str | None = None,
    ) -> str:
        """Salva uma preferência estável que o usuário ACABOU de informar (origem habitual,
        classe, moeda, adultos). Preencha pelo menos um campo. Não use para cumprimento
        nem para “verificar” preferências: elas já estão no CONTEXTO."""
        if not _has_field(home_city, cabin, currency, adults, notes):
            return NOTHING_CHANGED
        thread_id = current_thread_id.get()
        if not thread_id:
            return "Não consegui associar as preferências a este chat."
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
        return f"Preferências salvas: {summary}"

    return save_user_preferences
