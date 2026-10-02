import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from agent import build_agent
from middlewares.auth import GatewayAuthMiddleware
from routers import message_routers_v1

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
    app.state.agent = await build_agent()
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(GatewayAuthMiddleware)
app.include_router(message_routers_v1.router, prefix="/v1")


@app.get("/")
async def root():
    return {"messsage": GREETING_MESSAGE}
