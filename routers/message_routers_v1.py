from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

router = APIRouter(prefix="/messages", tags=["messages"])


def get_agent(request: Request):
    return request.app.state.agent


class ChatRequest(BaseModel):
    message: str
    thread_id: str


@router.post("")
async def invoke_agent(payload: ChatRequest, agent=Depends(get_agent)):
    config: RunnableConfig = {"configurable": {"thread_id": payload.thread_id}}

    response = await agent.ainvoke(
        {"messages": [HumanMessage(content=payload.message)]},
        config,
    )

    return {"messages": response["messages"][-1]}
