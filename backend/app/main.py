"""FastAPI app: CORS from ALLOWED_ORIGINS and passcode auth from DEMO_PASSCODE.

Auth fails closed: if DEMO_PASSCODE is unset, every protected route returns 503 instead of being open.
The passcode is compared in constant time. Only the health check, the API docs and CORS preflights are public.
"""

import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.api import health
from app.config import Settings, get_settings

PASSCODE_HEADER = "X-Passcode"
PUBLIC_PATHS = frozenset({"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="sme-copilot API", version="0.1.0")
    passcode = settings.demo_passcode.get_secret_value()

    @app.middleware("http")
    async def require_passcode(request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        if not passcode:
            return JSONResponse({"detail": "Passcode not configured on server"}, status_code=503)
        supplied = request.headers.get(PASSCODE_HEADER, "")
        if not hmac.compare_digest(supplied.encode(), passcode.encode()):
            return JSONResponse({"detail": "Invalid or missing passcode"}, status_code=401)
        return await call_next(request)

    # Added after the auth middleware so it wraps it: 401s still carry CORS headers the browser can read.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)

    def openapi() -> dict:
        """Declare the passcode header so /docs shows an Authorize button."""
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "Passcode": {"type": "apiKey", "in": "header", "name": PASSCODE_HEADER}
        }
        schema["security"] = [{"Passcode": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi
    return app


app = create_app()
