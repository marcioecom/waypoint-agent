import asyncio
import uuid

import streamlit as st
from dotenv import load_dotenv

from travel_agent.agent import build_agent
from travel_agent.agent.memory import AgentMemory
from travel_agent.services.chat import run_agent
from travel_agent.settings import settings

load_dotenv()

st.set_page_config(page_title="Travel Assistant", page_icon="✈️")


@st.cache_resource
async def get_agent():
    memory = AgentMemory.create(settings.sqlite_path)
    await memory.start()
    return await build_agent(memory)


async def main() -> None:
    st.title("✈️ Travel Assistant")
    st.caption("Busca de voos com a Dhay. Origem, destino e datas.")

    agent = await get_agent()
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
                answer = await run_agent(agent, st.session_state.thread_id, prompt)
            st.write(answer)
            st.session_state.chat_log.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    asyncio.run(main())
