from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    dynamic_prompt,
    wrap_model_call,
)
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import trim_messages
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kiwi import latest_search_result, load_search_tool, render_reply
from prompts import SYSTEM_PROMPT
from settings import settings


class DhayReply(BaseModel):
    """Conversation text or references to verified flight results, never invented offers."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["question", "offers", "detail", "unavailable", "out_of_scope", "ack"]
    message: str = Field(max_length=800)
    offer_ids: list[str] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.kind in {"offers", "detail"}:
            if not self.offer_ids or self.message:
                raise ValueError("Selecione offer_ids reais e deixe message vazio.")
        elif self.offer_ids:
            raise ValueError("Somente offers/detail podem selecionar itinerários.")
        elif self.kind in {"question", "ack"} and not self.message.strip():
            raise ValueError("Escreva uma mensagem de conversa curta.")
        return self


@dynamic_prompt
def current_context(request):
    today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    return (
        SYSTEM_PROMPT
        + f"\nCONTEXTO DA APLICAÇÃO\nData atual: {today}. Fuso: {settings.timezone}."
    )


@wrap_model_call
async def bounded_history(request, handler):
    # Keep whole turns/tool pairs; do not pay for the complete persistent transcript.
    messages = trim_messages(
        request.messages,
        max_tokens=16_000,
        token_counter="approximate",
        start_on="human",
        include_system=True,
    )
    if not messages:
        raise ValueError("A mensagem excede o contexto permitido.")
    return await handler(request.override(messages=messages))


async def build_agent(checkpointer):
    search = await load_search_tool()
    model = ChatOpenAI(
        model="gpt-5-nano",
        api_key=settings.openai_api_key or None,
        timeout=settings.agent_timeout_seconds,
        max_retries=0,
        reasoning_effort="low",
        model_kwargs={"parallel_tool_calls": False},
    )
    return create_agent(
        model,
        tools=[search],
        checkpointer=checkpointer,
        middleware=[
            current_context,
            bounded_history,
            ToolCallLimitMiddleware(
                tool_name="search-flight", run_limit=2, exit_behavior="error"
            ),
            ModelCallLimitMiddleware(run_limit=6, exit_behavior="error"),
        ],
        response_format=ProviderStrategy(DhayReply.model_json_schema(), strict=True),
        name="dhay",
    )


def reply_text(response: dict) -> str:
    reply = DhayReply.model_validate(response["structured_response"])
    return render_reply(reply.model_dump(), latest_search_result(response["messages"]))
