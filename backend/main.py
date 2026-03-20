import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from backend.database import engine, run_startup_migrations
from backend.models import Base
from backend.routers import auth, monitors, settings, tweets
from backend.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables and start scheduler
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_startup_migrations()
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()


app = FastAPI(
    title="Twitter Monitor",
    description="监控 Twitter/X 博主推文更新",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(auth.router)
app.include_router(monitors.router)
app.include_router(tweets.router)
app.include_router(settings.router)


# Manual trigger endpoint
@app.post("/api/check-now", tags=["system"])
async def trigger_check():
    """Manually trigger a check for all monitors."""
    from backend.database import async_session
    from backend.services.monitor import run_all_checks

    async with async_session() as db:
        summary = await run_all_checks(db)

    failed = len(summary["failures"])
    if failed:
        message = f"Check finished with {failed} failed monitor(s)."
    else:
        message = "Check completed"

    return {"ok": failed == 0, "message": message, "summary": summary}


@app.get("/api/health", tags=["system"])
async def health():
    return {"status": "ok"}


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def serve_frontend(full_path: str):
    if not FRONTEND_DIST_DIR.exists():
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Frontend dist not found. Build frontend first.",
            },
        )

    if full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    dist_root = FRONTEND_DIST_DIR.resolve()
    requested_path = (dist_root / full_path.lstrip("/")).resolve()

    try:
        requested_path.relative_to(dist_root)
    except ValueError:
        return FileResponse(FRONTEND_DIST_DIR / "index.html")

    if full_path and requested_path.is_file():
        return FileResponse(requested_path)

    return FileResponse(FRONTEND_DIST_DIR / "index.html")
