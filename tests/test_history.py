from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from travel_agent.agent.middleware import drop_stale_tool_history


def test_prior_search_json_is_dropped_but_human_and_reply_stay():
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="quero Santiago"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_flights",
                    "id": "s1",
                    "args": {"fly_from": "Palmas", "fly_to": "DPS"},
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"query":"Palmas → DPS","resultsCount":0,"offers":[]}',
            tool_call_id="s1",
            name="search_flights",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "AgentReply",
                    "id": "r1",
                    "args": {
                        "message": "Não achei Bali em novembro.",
                        "offers": [],
                    },
                    "type": "tool_call",
                }
            ],
        ),
        HumanMessage(content="esquece isso, São Paulo dezembro"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_flights",
                    "id": "s2",
                    "args": {"fly_from": "Palmas", "fly_to": "São Paulo"},
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status":"ok","offers":[{"price":"R$ 900"}]}',
            tool_call_id="s2",
            name="search_flights",
        ),
    ]

    kept = drop_stale_tool_history(messages)
    texts = [getattr(m, "content", "") for m in kept]
    names = [getattr(m, "name", "") or getattr(m, "type", "") for m in kept]

    assert "sys" in texts
    assert "quero Santiago" in texts
    assert "Não achei Bali em novembro." in texts
    assert "esquece isso, São Paulo dezembro" in texts
    assert any("Palmas → DPS" in str(t) for t in texts) is False
    assert any(n == "search_flights" for n in names)
    assert any("R$ 900" in str(t) for t in texts)


def test_current_turn_keeps_search_result():
    messages = [
        HumanMessage(content="Palmas para SCL"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_flights",
                    "id": "s1",
                    "args": {"fly_from": "Palmas", "fly_to": "SCL"},
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status":"ok","offers":[{"price":"R$ 2.100"}]}',
            tool_call_id="s1",
            name="search_flights",
        ),
    ]
    kept = drop_stale_tool_history(messages)
    assert len(kept) == 3
    assert kept[-1].content == '{"status":"ok","offers":[{"price":"R$ 2.100"}]}'
