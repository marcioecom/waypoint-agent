from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    gateway_url: str = ""
    gateway_token: str = ""
    timezone: str = "America/Sao_Paulo"
    sqlite_path: Path = Path("data/agent.sqlite")


settings = Settings()
