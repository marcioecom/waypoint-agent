import asyncio
import atexit
import secrets
from contextlib import AsyncExitStack
from threading import Thread

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent import build_agent
from chat import run_agent, shutdown_runtime
from settings import settings

load_dotenv()

st.set_page_config(page_title="Dhay — voos", page_icon="✈️")


@st.cache_resource
def _runtime():
    # All cached async clients/checkpoints stay on one live loop across reruns.
    loop = asyncio.new_event_loop()
    thread = Thread(target=loop.run_forever, daemon=True)
    thread.start()
    stack = AsyncExitStack()

    async def bootstrap():
        checkpointer = await stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(settings.sqlite_conn_string())
        )
        return await build_agent(checkpointer)

    async def close():
        await shutdown_runtime()
        await stack.aclose()

    def cleanup():
        try:
            asyncio.run_coroutine_threadsafe(close(), loop).result(timeout=10)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=10)
            if not thread.is_alive():
                loop.close()

    try:
        agent = asyncio.run_coroutine_threadsafe(bootstrap(), loop).result(timeout=60)
    except Exception:
        cleanup()
        raise
    atexit.register(cleanup)
    return agent, loop


st.title("✈️ Dhay")
st.caption("Busca de voos via Kiwi. Só pergunte sobre passagens aéreas.")

agent, loop = _runtime()

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"streamlit-{secrets.token_hex(16)}"
if "chat_log" not in st.session_state:
    st.session_state.chat_log = []

for message in st.session_state.chat_log:
    with st.chat_message(message["role"]):
        st.text(message["content"])

if prompt := st.chat_input("Origem, destino, datas..."):
    st.session_state.chat_log.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.text(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Consultando voos..."):
            answer = asyncio.run_coroutine_threadsafe(
                run_agent(agent, st.session_state.thread_id, prompt), loop
            ).result(timeout=settings.agent_timeout_seconds + 5)
        st.text(answer)
        st.session_state.chat_log.append({"role": "assistant", "content": answer})
