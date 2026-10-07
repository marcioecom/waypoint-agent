import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from travel_agent.agent.middleware import (
    collapse_older_search_results,
    dedupe_search_flights,
    prior_search_signatures,
    search_signature,
)
from travel_agent.agent.reply import SEARCH_BUDGET_FALLBACK, text_from_response


def test_search_signature_normalizes_currency_and_blanks():
    left = search_signature(
        {
            "fly_from": "Palmas",
            "fly_to": "Denpasar, Indonesia",
            "departure_date": "01/10/2027",
            "departure_date_to": "31/10/2027",
            "currency": "brl",
            "return_date": "",
            "adults": 1,
        }
    )
    right = search_signature(
        {
            "fly_from": "Palmas",
            "fly_to": "Denpasar, Indonesia",
            "departure_date": "01/10/2027",
            "departure_date_to": "31/10/2027",
            "currency": "BRL",
            "return_date": None,
            "adults": 1,
        }
    )
    assert left == right


def test_prior_search_signatures_skips_current_tool_call():
    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_flights",
                        "args": {
                            "fly_from": "Palmas",
                            "fly_to": "Bali",
                            "departure_date": "01/11/2026",
                            "currency": "BRL",
                        },
                        "id": "call-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "search_flights",
                        "args": {
                            "fly_from": "Palmas",
                            "fly_to": "Bali",
                            "departure_date": "01/11/2026",
                            "currency": "BRL",
                        },
                        "id": "call-2",
                        "type": "tool_call",
                    },
                ],
            )
        ]
    }
    seen = prior_search_signatures(state, exclude_tool_call_id="call-2")
    assert len(seen) == 1


def test_dedupe_search_flights_blocks_identical_query():
    args = {
        "fly_from": "Palmas",
        "fly_to": "Denpasar, Indonesia",
        "departure_date": "01/10/2027",
        "departure_date_to": "31/10/2027",
        "nights_in_dst_from": 7,
        "nights_in_dst_to": 7,
        "adults": 1,
        "cabin_class": "M",
        "currency": "BRL",
        "sort": "price",
    }
    request = type(
        "Req",
        (),
        {
            "tool_call": {
                "name": "search_flights",
                "args": args,
                "id": "call-2",
                "type": "tool_call",
            },
            "state": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "search_flights",
                                "args": args,
                                "id": "call-1",
                                "type": "tool_call",
                            },
                            {
                                "name": "search_flights",
                                "args": args,
                                "id": "call-2",
                                "type": "tool_call",
                            },
                        ],
                    )
                ]
            },
        },
    )()

    async def handler(_request):
        raise AssertionError("duplicate search should not execute")

    async def _run():
        return await dedupe_search_flights.awrap_tool_call(request, handler)

    result = asyncio.run(_run())
    assert isinstance(result, ToolMessage)
    payload = json.loads(result.content)
    assert payload["status"] == "duplicate"
    assert result.status == "error"


def test_dedupe_search_flights_allows_first_query():
    request = type(
        "Req",
        (),
        {
            "tool_call": {
                "name": "search_flights",
                "args": {
                    "fly_from": "Palmas",
                    "fly_to": "Denpasar, Indonesia",
                    "departure_date": "01/10/2027",
                    "currency": "BRL",
                },
                "id": "call-1",
                "type": "tool_call",
            },
            "state": {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "search_flights",
                                "args": {
                                    "fly_from": "Palmas",
                                    "fly_to": "Denpasar, Indonesia",
                                    "departure_date": "01/10/2027",
                                    "currency": "BRL",
                                },
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            },
        },
    )()

    async def handler(_request):
        return ToolMessage(
            content='{"status":"ok","offers":[]}',
            tool_call_id="call-1",
            name="search_flights",
        )

    async def _run():
        return await dedupe_search_flights.awrap_tool_call(request, handler)

    result = asyncio.run(_run())
    assert json.loads(result.content)["status"] == "ok"


def test_collapse_older_search_results_keeps_last_two():
    messages = [HumanMessage(content="bali")]
    for index in range(4):
        messages.append(
            ToolMessage(
                content=json.dumps({"status": "empty", "offers": [], "n": index}),
                tool_call_id=f"c{index}",
                name="search_flights",
            )
        )
    compacted = collapse_older_search_results(messages, keep_last=2)
    payloads = [json.loads(message.content) for message in compacted[1:]]
    assert payloads[0]["status"] == "omitted"
    assert payloads[1]["status"] == "omitted"
    assert payloads[2]["n"] == 2
    assert payloads[3]["n"] == 3


def test_text_from_response_maps_model_limit_to_friendly_fallback():
    text = text_from_response(
        {"messages": [AIMessage(content="Model call limits exceeded: run limit (8/8)")]},
        lambda content: content if isinstance(content, str) else str(content),
    )
    assert text == SEARCH_BUDGET_FALLBACK
