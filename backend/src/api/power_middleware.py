from starlette.responses import JSONResponse
from ..services.runtime_power import RuntimePower
import asyncio


class PowerMiddleware:
    """ASGI gate runs before routing, database sync, indexing, or model work."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'] not in ('/', '/health', '/runtime/power', '/openapi.json'):
            if not await asyncio.to_thread(RuntimePower().enabled, fresh=True):
                await JSONResponse({'detail': 'Jarvis is powered off. Turn it on in Settings.', 'power_off': True}, status_code=503)(scope, receive, send)
                return
        await self.app(scope, receive, send)

