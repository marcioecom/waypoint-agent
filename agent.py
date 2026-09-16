from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver


async def build_agent():
    client = MultiServerMCPClient(
        {
            "travel_server": {
                "transport": "streamable_http",
                # "transport": "sse",
                "url": "https://mcp.kiwi.com",
                "timeout": 30_000,
            }
        }
    )

    tools = await client.get_tools()

    agent = create_agent(
        "gpt-5-nano",
        tools=tools,
        checkpointer=InMemorySaver(),
        system_prompt="You are a travel agent. No follow up questions.",
    )

    return agent
