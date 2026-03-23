import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api_gateway.config import settings
from api_gateway.routers import chat_router, features, file_router, interactions, jobs, pricing, reports, review_router, weight_price, websocket_router
from api_gateway.routers.account_router import router as account_router
from api_gateway.utils.rabbitmq_client import rabbitmq_client
from shared.logging_config import get_logger, setup_logging
from shared.logging_middleware import LoggingMiddleware


load_dotenv()

setup_logging(
    level=settings.LOG_LEVEL,
    enable_console=True,
    enable_file=True,
    enable_json=settings.ENABLE_JSON_LOG,
)
logger = get_logger(__name__)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Unified backend starting")

    try:
        await rabbitmq_client.connect()
    except Exception as exc:
        logger.warning("RabbitMQ connect failed: %s", exc)

    try:
        from api_gateway.utils.redis_client import redis_client

        await redis_client.connect()
    except Exception as exc:
        logger.warning("Redis connect failed: %s", exc)

    try:
        from agents.action_handlers import ActionHandlerFactory

        ActionHandlerFactory.initialize_handlers()
    except Exception as exc:
        logger.warning("Action handlers init skipped: %s", exc)

    try:
        from api_gateway.websocket import manager

        manager.subscriber_task = asyncio.create_task(manager.start_redis_subscriber())
    except Exception as exc:
        logger.warning("WebSocket redis subscriber skipped: %s", exc)

    yield

    try:
        from api_gateway.websocket import manager

        if getattr(manager, "subscriber_task", None):
            manager.subscriber_task.cancel()
    except Exception:
        pass

    try:
        from api_gateway.utils.redis_client import redis_client

        await redis_client.close()
    except Exception:
        pass

    try:
        await rabbitmq_client.close()
    except Exception:
        pass

    logger.info("Unified backend stopped")


app = FastAPI(
    title="mold_main unified backend",
    version=settings.APP_VERSION,
    description="Merged API gateway for moldCost, mold_cost-main and mold_cost_account_python",
    lifespan=lifespan,
)
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS_LIST or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_SERVER_ERROR",
            "message": "服务端内部错误",
            "detail": str(exc) if settings.DEBUG else None,
        },
    )


app.include_router(features.router)
app.include_router(pricing.router)
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(websocket_router.router, tags=["websocket"])
app.include_router(interactions.router)
app.include_router(review_router.router)
app.include_router(chat_router.router)
app.include_router(file_router.router)
app.include_router(reports.router)
app.include_router(weight_price.router)
app.include_router(account_router)

try:
    from speech_services.main import router as speech_router

    app.include_router(speech_router)
    logger.info("Speech services router mounted into unified backend")
except Exception as exc:
    logger.warning("Speech services router skipped: %s", exc)


@app.get("/")
async def root():
    return {
        "message": "mold_main unified backend is running",
        "version": settings.APP_VERSION,
        "port": settings.UNIFIED_PORT,
        "sources": ["moldCost", "mold_cost-main", "mold_cost_account_python"],
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "port": settings.UNIFIED_PORT,
        "rabbitmq": "connected" if rabbitmq_client.connection else "disconnected",
    }
