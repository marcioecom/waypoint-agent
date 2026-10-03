import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from agent import build_agent
from chat import shutdown_runtime
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from middlewares.auth import GatewayAuthMiddleware
from routers import message_routers_v1
from settings import settings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

GREETING_MESSAGE = """Olá! Eu sou a Dhay, assistente de busca de voos da Waypoint Labs.

Manda origem, destino e datas que eu consulto opções no Kiwi."""


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn_string = settings.sqlite_conn_string()
    async with AsyncSqliteSaver.from_conn_string(conn_string) as checkpointer:
        app.state.checkpointer = checkpointer
        app.state.agent = await build_agent(checkpointer)
        try:
            yield
        finally:
            await shutdown_runtime()


app = FastAPI(lifespan=lifespan)
app.add_middleware(GatewayAuthMiddleware)
app.include_router(message_routers_v1.router, prefix="/v1")


@app.get("/")
async def root():
    return {"message": GREETING_MESSAGE}
