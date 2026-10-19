"""FastAPI app: CORS from ALLOWED_ORIGINS and passcode auth from DEMO_PASSCODE.

Auth fails closed: if DEMO_PASSCODE is unset, every protected route returns 503 instead of being open.
The passcode is compared in constant time. Only the health check, the API docs, CORS preflights, the Gmail
OAuth callback (state-checked), and the payment provider's consent callback (state-checked) and settlement webhook
(HMAC-checked) are public. The lifespan starts the Gmail poller (GMAIL_POLL).
"""

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.agent.context import ConversationStore
from app.anchoring import Chain
from app.api import (
    agent, anchors, audit, brief, businesses, clock, connections, demo_console, finance, financing, gateway, health, inbox, ledger,
    onboarding, payments, skills, trust,
)
from app.config import Settings, get_settings
from app.firewall.store import UnknownFactError
from app.ledger.schema import TenantError
from app.packs.loader import PackError
from app.services.gmail import ConnectError, GmailPoller
from app.services.onboarding import OnboardingError
from app.services.payments import PaymentsError
from app.services.runtime import ClockNotConfigured, Runtime

PASSCODE_HEADER = "X-Passcode"
# The Gmail OAuth callback is public: Google redirects the browser there without our header. It acts only on a
# one-time state this server issued (services/gmail.py).
# The payment provider calls the consent callback (state-checked) and the settlement webhook (HMAC-checked) the same
# way.
PUBLIC_PATHS = frozenset({"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json",
                          connections.CALLBACK_PATH, payments.CALLBACK_PATH})
PUBLIC_PREFIXES = (payments.WEBHOOK_PREFIX,)


def create_app(settings: Settings | None = None, anchor_chain: Chain | None = None) -> FastAPI:
    """`anchor_chain` replaces the testnet chain built from settings (tests)."""
    settings = settings or get_settings()
    # operationId = the route function's name, so a generated client gets readable method names.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        poller = GmailPoller(app.state.runtime, settings.gmail_poll_seconds) if settings.gmail_poll else None
        if poller:
            poller.start()
        yield
        if poller:
            poller.stop()

    app = FastAPI(title="sme-copilot API", version="0.1.0", generate_unique_id_function=lambda route: route.name,
                  lifespan=lifespan)
    passcode = settings.demo_passcode.get_secret_value()

    @app.middleware("http")
    async def require_passcode(request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in PUBLIC_PATHS or (
                request.method == "POST" and path.startswith(PUBLIC_PREFIXES)):
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

    app.state.runtime = Runtime(settings, anchor_chain)
    app.state.conversations = ConversationStore()
    for router in (health.router, businesses.router, ledger.router, finance.router, gateway.router, audit.router,
                   clock.router, agent.router, brief.router, inbox.router, financing.router, trust.router, anchors.router,
                   onboarding.router, skills.router, connections.router, payments.router):
        app.include_router(router)
    if settings.expose_test_routes:
        app.include_router(gateway.test_router)
    if settings.demo_mode:  # the console does not exist at all in normal mode
        app.include_router(demo_console.router)

    def error(status: int, prefix: str = ""):
        async def handler(_: Request, exc: Exception) -> JSONResponse:
            detail = exc.args[0] if exc.args else exc.__class__.__name__
            return JSONResponse({"detail": f"{prefix}{detail}"}, status_code=status)
        return handler

    app.add_exception_handler(TenantError, error(404))
    app.add_exception_handler(UnknownFactError, error(404, "unknown fact: "))
    app.add_exception_handler(PackError, error(422))
    app.add_exception_handler(ClockNotConfigured, error(503))
    app.add_exception_handler(OnboardingError, error(422))
    app.add_exception_handler(ConnectError, error(422))
    app.add_exception_handler(PaymentsError, error(422))

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
