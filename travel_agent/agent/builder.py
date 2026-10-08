from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware.types import dynamic_prompt
from langchain.agents.structured_output import ToolStrategy
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

from travel_agent.agent.memory import AgentMemory, current_thread_id
from travel_agent.agent.middleware import compact_history, guard_post_search
from travel_agent.agent.prompt import build_system_prompt
from travel_agent.agent.reply import AgentReply
from travel_agent.agent.tools import (
    find_kiwi_search,
    preference_tool,
    search_tool,
    trip_tool,
)
from travel_agent.settings import settings


async def build_agent(memory: AgentMemory):
    client = MultiServerMCPClient(
        {
            "travel_server": {
                "transport": "streamable_http",
                "url": "https://mcp.kiwi.com",
                "timeout": 30_000,
            }
        }
    )
    mcp_tools = await client.get_tools()
    kiwi_search = find_kiwi_search(mcp_tools)

    tools = [
        search_tool(kiwi_search),
        trip_tool(memory),
        preference_tool(memory),
    ]

    @dynamic_prompt
    def current_context(request):
        thread_id = current_thread_id.get()
        return build_system_prompt(
            memory.prefs.prompt_block(thread_id),
            memory.trips.prompt_block(thread_id),
        )

    model = ChatOpenAI(
        model=settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
        verbosity=settings.openai_verbosity,
    )
    return create_agent(
        model,
        tools=tools,
        checkpointer=memory.checkpointer,
        middleware=[
            current_context,
            compact_history,
            guard_post_search,
        ],
        response_format=ToolStrategy(AgentReply),
        name="dhay",
    )
