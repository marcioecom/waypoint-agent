import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from chat import run_agent, schedule_reply
from settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])


def get_agent(request: Request):
    return request.app.state.agent


class ChatRequest(BaseModel):
    message: str
    thread_id: str


@router.post("")
async def invoke_agent(payload: ChatRequest, agent=Depends(get_agent)):
    logger.info("inbound %s: %s", payload.thread_id, payload.message[:80])

    # O gateway não fica esperando o modelo. A resposta volta por POST /messages.
    if settings.gateway_url:
        schedule_reply(agent, payload.thread_id, payload.message)
        return JSONResponse({"ok": True}, status_code=202)

    return {"messages": await run_agent(agent, payload.thread_id, payload.message)}
