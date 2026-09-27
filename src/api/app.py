import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from src.api.routers import dashboard, history, meta, report
from src.utils.logger import setup_logger

logger = setup_logger()

API_PREFIX = "/api"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

DEFAULT_ORIGINS = (
    "http://localhost:4200,http://127.0.0.1:4200,"
    "http://localhost:4300,http://127.0.0.1:4300"
)


def _cors_origins() -> list[str]:
    raw = os.getenv("API_CORS_ORIGINS", DEFAULT_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """Build the FastAPI application with every router mounted."""
    application = FastAPI(
        title="BTC Market Analysis API",
        version="1.0.0",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    application.include_router(dashboard.router, prefix=API_PREFIX)
    application.include_router(meta.router, prefix=API_PREFIX)
    application.include_router(history.router, prefix=API_PREFIX)
    application.include_router(report.router, prefix=API_PREFIX)

    _register_index(application)
    _register_error_handlers(application)
    return application


def _register_index(application: FastAPI) -> None:
    """Expose the route table so the client can discover endpoints."""

    @application.get("/", tags=["meta"], summary="Endpoint index")
    def index() -> dict:
        groups: dict[str, list[dict]] = {}
        for route in application.routes:
            if not isinstance(route, APIRoute) or route.path == "/":
                continue
            methods = sorted(
                method for method in route.methods if method not in ("HEAD", "OPTIONS")
            )
            if not methods:
                continue
            group = route.tags[0] if route.tags else "other"
            groups.setdefault(group, []).append(
                {
                    "path": route.path,
                    "methods": methods,
                    "summary": route.summary or "",
                }
            )
        return {
            "name": application.title,
            "version": application.version,
            "docs": "/docs",
            "endpoints": groups,
        }


def _register_error_handlers(application: FastAPI) -> None:
    """Return JSON instead of a stack trace when something blows up."""

    @application.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(exc).__name__}: {exc}"},
        )


app = create_app()
