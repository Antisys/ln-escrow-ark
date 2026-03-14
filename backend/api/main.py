"""
trustMeBro-ARK API — Decentralized escrow service using Lightning Network and Ark.
"""
import asyncio
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

project_root = Path(__file__).parent.parent.parent

# Configure structured logging (call before any other imports that use logging)
from backend.api.logging_config import setup_logging, request_id_var
setup_logging()

logger = logging.getLogger(__name__)

import uuid

from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

from backend.api.routes import health, deals, qr, websockets
from backend.api.routes import ark_escrow
try:
    from backend.api.routes import auth
except ImportError:
    auth = None
from backend.api.security import SecurityHeadersMiddleware, RateLimitMiddleware
from backend.config import VERSION

# Load environment
load_dotenv(project_root / '.env')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    app.state.escrow_service = True  # Ark mode — placeholder for health check

    # Non-custodial architecture safety check: warn if oracle keys are not independent
    from backend.config import DEV_ORACLE_KEYS
    oracle_env = os.environ.get("ORACLE_PUBKEYS", "")
    oracle_keys = [k.strip() for k in oracle_env.split(",") if k.strip()]
    if len(oracle_keys) == 0:
        logger.warning("ORACLE_PUBKEYS not set — disputes cannot be resolved!")
    elif len(set(oracle_keys)) < len(oracle_keys):
        logger.warning("ORACLE_PUBKEYS contains duplicate keys — disputes are NOT independent!")
    elif len(oracle_keys) < 3:
        logger.warning("ORACLE_PUBKEYS has %d key(s), need exactly 3!", len(oracle_keys))
    else:
        logger.info("Oracle keys: %d independent arbitrators configured", len(oracle_keys))

    # CUSTODIAL: Invariant 4 check — detect known dev oracle keys
    dev_key_matches = [k for k in oracle_keys if k in DEV_ORACLE_KEYS]
    if dev_key_matches:
        logger.critical(
            "CUSTODIAL: Using DEV oracle keys — all 3 keys controlled by service operator "
            "(%d of %d keys are known dev keys). Invariant 4 violated.",
            len(dev_key_matches), len(oracle_keys),
        )

    # Reconcile deals stuck in intermediate states from previous crash
    from backend.tasks.reconcile import reconcile_stuck_deals
    try:
        reconcile_stuck_deals()
    except Exception as e:
        logger.error("Reconciliation error (non-fatal): %s", e)

    # Start background timeout handler
    from backend.tasks.timeout_handler import timeout_loop
    timeout_task = asyncio.create_task(timeout_loop())

    # Start Ark oracle listener
    try:
        from backend.ark.oracle_listener import OracleListener
        oracle_listener = OracleListener()
        app.state.oracle_listener = oracle_listener
        logger.info("Ark oracle listener started (%d relays)", len(oracle_listener.relays))
    except Exception as e:
        logger.error("Ark oracle listener failed to start: %s", e)
        app.state.oracle_listener = None

    yield

    # Shutdown — wait for in-flight payouts before cancelling tasks
    from backend.api.shutdown import drain
    await drain(timeout=30)

    timeout_task.cancel()
    if getattr(app.state, 'oracle_listener', None):
        await app.state.oracle_listener.stop_all()


app = FastAPI(
    title="trustMeBro-ARK API",
    description="Decentralized escrow service using Lightning Network and Ark",
    version=VERSION,
    lifespan=lifespan
)

# Security middleware (order matters - first added = last executed)
# Rate limiting
if os.getenv('DISABLE_RATE_LIMIT', 'false').lower() != 'true':
    app.add_middleware(RateLimitMiddleware)
    logger.info("Rate limiting enabled")

# Security headers
app.add_middleware(SecurityHeadersMiddleware)
logger.info("Security headers enabled")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv('CORS_ORIGINS', 'https://localhost:8001').split(','),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID middleware — sets a unique ID per request for log correlation
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        rid = uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

app.add_middleware(RequestIdMiddleware)

# Debug: log validation errors with request body
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: FastAPIRequest, exc: RequestValidationError):
    body = await request.body()
    logger.warning("422 %s %s body=%s errors=%s", request.method, request.url.path, body[:500], exc.errors())
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(deals.router, prefix="/deals", tags=["Deals"])
app.include_router(ark_escrow.router, prefix="/deals", tags=["Ark Escrow"])
if auth:
    app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(qr.router, tags=["QR"])
app.include_router(websockets.router, tags=["WebSocket"])


if __name__ == '__main__':
    import uvicorn

    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', '8000'))

    uvicorn.run(
        "backend.api.main:app",
        host=host,
        port=port,
        reload=os.getenv('API_RELOAD', 'false').lower() == 'true'
    )
