from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

GREETING_MESSAGE = """Olá! Você está falando com o Waypoint Labs, nosso laboratório de aplicações de IA no WhatsApp.

Experimentos disponíveis:
✈️ Planejador de voos
🧪 Novos protótipos"""

app = FastAPI()


@app.get("/")
async def root():
    return {"messsage": GREETING_MESSAGE}
