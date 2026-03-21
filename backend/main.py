import uvicorn

from shared.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "api_gateway.main:app",
        host=settings.API_GATEWAY_HOST,
        port=settings.UNIFIED_PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower(),
    )
