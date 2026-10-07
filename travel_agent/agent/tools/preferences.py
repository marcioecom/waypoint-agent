from __future__ import annotations

from langchain.tools import tool

from travel_agent.agent.memory import AgentMemory, current_thread_id


def preference_tool(memory: AgentMemory):
    @tool
    def save_user_preferences(
        home_city: str | None = None,
        cabin: str | None = None,
        currency: str | None = None,
        adults: int | None = None,
        notes: str | None = None,
    ) -> str:
        """Salva preferências estáveis (origem habitual, classe, moeda, adultos)."""
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
            return "Nada para salvar."
        summary = ", ".join(f"{key}={value}" for key, value in saved.items())
        return f"Preferências salvas: {summary}"

    return save_user_preferences
