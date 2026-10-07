from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from travel_agent.settings import settings

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(authorization: str | None = Header(default=None)) -> None:
    expected = settings.admin_token
    if not expected:
        raise HTTPException(status_code=401, detail="unauthorized")
    received = ""
    if authorization and authorization.startswith("Bearer "):
        received = authorization.removeprefix("Bearer ")
    if len(received) != len(expected) or not secrets.compare_digest(received, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.delete("/threads/{thread_id:path}", dependencies=[Depends(require_admin)])
async def reset_thread(thread_id: str, request: Request):
    await request.app.state.memory.reset_thread(thread_id)
    return {"ok": True, "thread_id": thread_id}
