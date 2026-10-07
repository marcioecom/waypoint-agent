import asyncio

from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from agent import _looks_like_cold_start, _offers_from_recent_tools, guard_post_search
from reply import AgentReply


def test_looks_like_cold_start_detects_reintro():
    assert _looks_like_cold_start(
        "Oi! Sou o Dhay, seu assistente de voos. Para começar, me passe: origem..."
    )
    assert not _looks_like_cold_start("Encontrei 3 opções de Palmas para São Paulo.")


def test_offers_from_recent_tools_reads_search_payload():
    messages = [
        AIMessage(content=""),
        ToolMessage(
            content=(
                '{"offers":[{"price":"R$ 900","route":"PMW → GRU","details":"GOL",'
                '"booking_url":"https://kiwi/x"}],"resultsCount":1}'
            ),
            tool_call_id="1",
            name="search_flights",
        ),
    ]
    offers = _offers_from_recent_tools(messages)
    assert len(offers) == 1
    assert offers[0].price == "R$ 900"


def test_guard_post_search_patches_empty_offers_after_search():
    request = type(
        "Req",
        (),
        {
            "messages": [
                ToolMessage(
                    content=(
                        '{"offers":[{"price":"R$ 900","route":"PMW → GRU",'
                        '"details":"GOL","booking_url":"https://kiwi/x"}]}'
                    ),
                    tool_call_id="1",
                    name="search_flights",
                )
            ]
        },
    )()

    async def handler(_request):
        return ModelResponse(
            result=[AIMessage(content="")],
            structured_response=AgentReply(
                message="Oi! Sou o Dhay. Para começar, me passe: origem...",
                offers=[],
            ),
        )

    async def _run():
        return await guard_post_search.awrap_model_call(request, handler)

    response = asyncio.run(_run())
    assert isinstance(response, ModelResponse)
    assert response.structured_response is not None
    assert len(response.structured_response.offers) == 1
    assert "Encontrei estas opções" in response.structured_response.message
