import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from travel_agent.agent import build_agent
from travel_agent.agent.memory import open_memory
from travel_agent.api.auth import GatewayAuthMiddleware
from travel_agent.api.messages import router as messages_router
from travel_agent.settings import settings

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

GREETING_MESSAGE = """Olá! Você está falando com o Waypoint Labs, nosso laboratório de aplicações de IA no WhatsApp.

Experimentos disponíveis:
✈️ Planejador de voos
🧪 Novos protótipos"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with open_memory(settings.sqlite_path) as memory:
        app.state.memory = memory
        app.state.agent = await build_agent(memory)
        yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(GatewayAuthMiddleware)
app.include_router(messages_router, prefix="/v1")


@app.get("/")
async def root():
    return {"messsage": GREETING_MESSAGE}
