import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from chat import (
    TIMEOUT,
    _count_tool_calls,
    checkpoint_thread_id,
    estimate_cost_usd,
    run_agent,
    shutdown_runtime,
    turn_token_usage,
    validate_gateway_thread_id,
    validate_run_thread_id,
)
from settings import settings


def _usage(inp: int, out: int, total: int) -> dict:
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": total,
    }


class ThreadValidationTests(unittest.TestCase):
    def test_gateway_rejects_streamlit(self):
        tid = "streamlit-" + "a" * 32
        self.assertIsNotNone(validate_gateway_thread_id(tid))

    def test_run_accepts_streamlit_even_with_gateway_url(self):
        tid = "streamlit-" + "b" * 32
        with patch.object(settings, "gateway_url", "http://localhost:3000"):
            self.assertIsNone(validate_run_thread_id(tid))

    def test_run_accepts_direct_jid(self):
        self.assertIsNone(validate_run_thread_id("5511999999999@s.whatsapp.net"))


class MetricsTests(unittest.TestCase):
    def test_tool_calls_only_search_flight(self):
        messages = [
            HumanMessage(content="oi", id="turn-1"),
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "1", "name": "search-flight", "args": {}},
                    {"id": "2", "name": "DhayReply", "args": {}},
                ],
            ),
            ToolMessage(content="{}", tool_call_id="1"),
        ]
        self.assertEqual(_count_tool_calls(messages), 1)

    def test_partial_ai_usage_returns_all_none(self):
        messages = [
            HumanMessage(content="x", id="t1"),
            AIMessage(content="a", usage_metadata=_usage(10, 5, 15)),
            AIMessage.model_construct(content="b", usage_metadata={"input_tokens": 3}),
        ]
        usage = turn_token_usage(messages)
        self.assertIsNone(usage["input_tokens"])
        self.assertIsNone(usage["total_tokens"])

    def test_complete_usage_sums_all_ai_completions(self):
        messages = [
            AIMessage(content="a", usage_metadata=_usage(10, 5, 15)),
            AIMessage(content="b", usage_metadata=_usage(20, 8, 28)),
        ]
        usage = turn_token_usage(messages)
        self.assertEqual(usage["input_tokens"], 30)
        self.assertEqual(usage["output_tokens"], 13)
        self.assertEqual(usage["total_tokens"], 43)
        self.assertEqual(usage["cached_input_tokens"], 0)

    def test_cost_requires_rates_and_complete_usage(self):
        usage = {
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "total_tokens": 1_000_000,
            "cached_input_tokens": 0,
        }
        with patch.object(settings, "openai_input_cost_per_million", None):
            self.assertIsNone(estimate_cost_usd(usage))
        with patch.object(settings, "openai_input_cost_per_million", 1.0), patch.object(
            settings, "openai_cached_input_cost_per_million", 0.5
        ), patch.object(settings, "openai_output_cost_per_million", 2.0):
            self.assertEqual(estimate_cost_usd(usage), 1.0)


class RunAgentBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await shutdown_runtime()

    async def asyncTearDown(self):
        await shutdown_runtime()

    async def test_same_thread_runs_serialize(self):
        order: list[str] = []

        class SlowAgent:
            async def ainvoke(self, payload, config):
                order.append("start")
                await asyncio.sleep(0.05)
                order.append("end")
                turn_id = payload["messages"][-1].id
                return {
                    "messages": payload["messages"]
                    + [
                        AIMessage(
                            content="ok",
                            id="ai",
                            usage_metadata=_usage(1, 1, 2),
                        )
                    ],
                    "structured_response": {
                        "kind": "ack",
                        "message": "ok",
                        "offer_ids": [],
                    },
                }

        agent = SlowAgent()
        thread = "streamlit-" + "c" * 32

        with patch("chat._render_response", return_value="ok"):
            first = asyncio.create_task(run_agent(agent, thread, "one"))
            await asyncio.sleep(0.01)
            second = asyncio.create_task(run_agent(agent, thread, "two"))
            await asyncio.gather(first, second)

        self.assertEqual(order, ["start", "end", "start", "end"])

    async def test_timeout_then_next_call_succeeds(self):
        calls = {"n": 0}

        class FlakyAgent:
            async def ainvoke(self, payload, config):
                calls["n"] += 1
                if calls["n"] == 1:
                    await asyncio.sleep(0.2)
                return {
                    "messages": payload["messages"]
                    + [
                        AIMessage(
                            content="ok",
                            usage_metadata=_usage(2, 1, 3),
                        )
                    ],
                    "structured_response": {
                        "kind": "ack",
                        "message": "recovered",
                        "offer_ids": [],
                    },
                }

        agent = FlakyAgent()
        thread = "streamlit-" + "d" * 32

        with patch.object(settings, "agent_timeout_seconds", 0.05), patch(
            "chat._render_response", side_effect=lambda r: "recovered"
        ):
            first = await run_agent(agent, thread, "slow")
            second = await run_agent(agent, thread, "fast")

        self.assertEqual(first, TIMEOUT)
        self.assertEqual(second, "recovered")

    async def test_checkpoint_persists_after_reopen(self):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.graph.message import add_messages
        from typing_extensions import Annotated, TypedDict

        class State(TypedDict):
            messages: Annotated[list, add_messages]

        visits: list[str] = []

        def echo(state: State):
            last = state["messages"][-1].content
            visits.append(str(last))
            return {
                "messages": [
                    AIMessage(
                        content=f"seen:{last}",
                        usage_metadata=_usage(1, 1, 2),
                    )
                ]
            }

        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        thread_external = "5511888777666@s.whatsapp.net"
        cfg = {"configurable": {"thread_id": checkpoint_thread_id(thread_external)}}

        async with AsyncSqliteSaver.from_conn_string(path) as cp1:
            graph = StateGraph(State)
            graph.add_node("echo", echo)
            graph.add_edge(START, "echo")
            graph.add_edge("echo", END)
            app1 = graph.compile(checkpointer=cp1)
            await app1.ainvoke({"messages": [HumanMessage(content="first")]}, cfg)

        async with AsyncSqliteSaver.from_conn_string(path) as cp2:
            graph = StateGraph(State)
            graph.add_node("echo", echo)
            graph.add_edge(START, "echo")
            graph.add_edge("echo", END)
            app2 = graph.compile(checkpointer=cp2)
            out = await app2.ainvoke({"messages": [HumanMessage(content="second")]}, cfg)

        texts = [getattr(m, "content", "") for m in out["messages"]]
        self.assertIn("first", texts)
        self.assertIn("seen:second", texts)
        self.assertEqual(visits, ["first", "second"])

    async def test_threads_isolated_in_checkpoint(self):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from langgraph.graph import END, START, StateGraph
        from langgraph.graph.message import add_messages
        from typing_extensions import Annotated, TypedDict

        class State(TypedDict):
            messages: Annotated[list, add_messages]

        def echo(state: State):
            label = state["messages"][-1].content
            return {
                "messages": [
                    AIMessage(content=f"reply:{label}", usage_metadata=_usage(1, 1, 2))
                ]
            }

        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        async with AsyncSqliteSaver.from_conn_string(path) as cp:
            graph = StateGraph(State)
            graph.add_node("echo", echo)
            graph.add_edge(START, "echo")
            graph.add_edge("echo", END)
            app = graph.compile(checkpointer=cp)

            cfg_a = {
                "configurable": {
                    "thread_id": checkpoint_thread_id("5511111111111@s.whatsapp.net")
                }
            }
            cfg_b = {
                "configurable": {
                    "thread_id": checkpoint_thread_id("5511222222222@s.whatsapp.net")
                }
            }
            await app.ainvoke({"messages": [HumanMessage(content="A")]}, cfg_a)
            out_b = await app.ainvoke({"messages": [HumanMessage(content="B")]}, cfg_b)

        b_texts = [getattr(m, "content", "") for m in out_b["messages"]]
        self.assertNotIn("A", b_texts)
        self.assertIn("reply:B", b_texts)


if __name__ == "__main__":
    unittest.main()
