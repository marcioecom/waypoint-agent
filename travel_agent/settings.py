from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    # none|minimal|low|medium|high — low é o sweet spot para WhatsApp + tools.
    openai_reasoning_effort: str = "low"
    openai_verbosity: str = "low"
    gateway_url: str = ""
    gateway_token: str = ""
    admin_token: str = ""
    timezone: str = "America/Sao_Paulo"
    sqlite_path: Path = Path("data/agent.sqlite")
    # Orçamento do agente por turno (limites executáveis, não só prompt).
    search_run_limit: int = 2
    model_run_limit: int = 8
    agent_recursion_limit: int = 25


settings = Settings()
