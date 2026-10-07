import secrets

from fastapi.responses import JSONResponse

from travel_agent.settings import settings


class GatewayAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/v1/messages"):
            await self.app(scope, receive, send)
            return
        if not _authorized(scope):
            response = JSONResponse({"detail": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _bearer(scope) -> str:
    for key, value in scope["headers"]:
        if key == b"authorization":
            header = value.decode()
            if header.startswith("Bearer "):
                return header.removeprefix("Bearer ")
            return ""
    return ""


def _authorized(scope) -> bool:
    expected = settings.gateway_token
    if not expected:
        return True
    received = _bearer(scope)
    if len(received) != len(expected):
        return False
    return secrets.compare_digest(received, expected)
