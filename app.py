import asyncio
import uuid

from langchain_core.runnables import RunnableConfig
import streamlit as st
from dotenv import load_dotenv
from langchain.messages import HumanMessage

from agent import build_agent

load_dotenv()

st.set_page_config(page_title="Travel Assistant", page_icon="✈️")


@st.cache_resource
async def get_agent():
    agent = await build_agent()
    return agent


async def main() -> None:
    st.title("✈️ Travel Assistant")
    st.caption("Pergunte sobre reservas, politicas do hotel ou destinos.")

    agent = await get_agent()
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("chat_log", [])
    st.session_state.setdefault("thread_id", str(uuid.uuid4()))

    for message in st.session_state.chat_log:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    if prompt := st.chat_input("Digite sua pergunta"):
        st.session_state.chat_log.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Consultando o agente..."):
                config: RunnableConfig = {
                    "configurable": {"thread_id": st.session_state.thread_id}
                }

                result = await agent.ainvoke(
                    {
                        "messages": [
                            *st.session_state.messages,
                            HumanMessage(content=prompt),
                        ]
                    },
                    config,
                )

            st.session_state.messages = result["messages"]
            answer = result["messages"][-1].content
            st.write(answer)
            st.session_state.chat_log.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    asyncio.run(main())
