import math
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    gateway_url: str = ""
    gateway_token: str = ""

    checkpoint_path: Path = Path("data/dhay.sqlite")
    timezone: str = "America/Sao_Paulo"
    agent_timeout_seconds: float = 90.0
    agent_recursion_limit: int = 25
    max_message_length: int = 8000
    max_thread_id_length: int = 128

    # USD per 1M tokens; omit all three to skip cost (no default pricing).
    openai_input_cost_per_million: float | None = None
    openai_cached_input_cost_per_million: float | None = None
    openai_output_cost_per_million: float | None = None

    @field_validator("agent_timeout_seconds")
    @classmethod
    def validate_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("agent_timeout_seconds deve ser finito e > 0")
        return value

    @field_validator(
        "agent_recursion_limit",
        "max_message_length",
        "max_thread_id_length",
    )
    @classmethod
    def validate_positive_int(cls, value: int) -> int:
        if value < 1:
            raise ValueError("deve ser >= 1")
        return value

    @field_validator(
        "openai_input_cost_per_million",
        "openai_cached_input_cost_per_million",
        "openai_output_cost_per_million",
    )
    @classmethod
    def validate_optional_rate(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value < 0:
            raise ValueError("taxa OpenAI deve ser finita e >= 0")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"timezone inválido: {value}") from exc
        return value

    def ensure_checkpoint_dir(self) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    def sqlite_conn_string(self) -> str:
        self.ensure_checkpoint_dir()
        return str(self.checkpoint_path.resolve())

    def openai_rates_configured(self) -> bool:
        return (
            self.openai_input_cost_per_million is not None
            and self.openai_cached_input_cost_per_million is not None
            and self.openai_output_cost_per_million is not None
        )


settings = Settings()
