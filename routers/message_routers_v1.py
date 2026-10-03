import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from chat import (
    run_agent,
    schedule_reply,
    validate_gateway_thread_id,
    validate_message,
)
from settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])


def get_agent(request: Request):
    return request.app.state.agent


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


@router.post("")
async def invoke_agent(payload: ChatRequest, agent=Depends(get_agent)):
    thread_err = validate_gateway_thread_id(payload.thread_id)
    if thread_err:
        raise HTTPException(status_code=422, detail=thread_err)
    msg_err = validate_message(payload.message)
    if msg_err:
        raise HTTPException(status_code=422, detail=msg_err)

    logger.info("inbound accepted")

    if settings.gateway_url:
        schedule_reply(agent, payload.thread_id.strip(), payload.message.strip())
        return JSONResponse({"ok": True}, status_code=202)

    text = await run_agent(agent, payload.thread_id.strip(), payload.message.strip())
    return {"messages": text}
