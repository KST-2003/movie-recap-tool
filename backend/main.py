"""App wiring only: create the FastAPI app, add middleware, include every router, and the two app-level routes
(/, /health) plus the startup/cleanup housekeeping and the catch-all error handler. Every actual endpoint lives in
api/ (user-facing) or admin/ (the dashboard); business logic lives in services/."""
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

import sandbox
import storage
import usage as usage_log
from admin import router as admin_router
from api import accounts, catalog, files, jobs
from config import API_DOCS, CORS_ORIGINS, QUEUE_MODE
from db import Job, Session
from guard import RequestGuard

import logging


class _QuietPolling(logging.Filter):
    """The page polls /api/jobs/<id> every 1.5 s; those lines bury everything useful in the terminal."""
    def filter(self, record):
        msg = record.getMessage()
        return not ("GET /api/jobs/" in msg and '" 200' in msg)


logging.getLogger("uvicorn.access").addFilter(_QuietPolling())

usage_log.install()
sandbox.harden_process()   # Linux: children (ffmpeg ...) cannot read this process's environment / memory through /proc


# ---------- housekeeping ----------

def _cleanup_loop():
    while True:
        try:
            removed = storage.cleanup()
            if removed:
                print(f"[cleanup] removed {removed} old file(s)", flush=True)
        except Exception as exc:
            print(f"[cleanup] failed: {exc}", flush=True)
        time.sleep(3600)


def _fail_orphaned_jobs():
    """Jobs run in this process when there is no Redis queue, so a restart kills them. Without this they stay
    'running' forever and count against the user's active-job limit."""
    if QUEUE_MODE != "inline":
        return  # with RQ the jobs live in Redis and the workers keep running
    with Session() as s:
        stuck = s.execute(select(Job).where(Job.status.in_(("queued", "running")))).scalars().all()
        for job in stuck:
            job.status, job.stage, job.charged_seconds = "error", "Interrupted", 0.0
            job.error = "The server was restarted while this video was processing. Please upload it again."
        s.commit()
        if stuck:
            print(f"[startup] marked {len(stuck)} interrupted job(s) as failed", flush=True)


@asynccontextmanager
async def lifespan(_app):
    """Start-up work (the old @app.on_event("startup"), deprecated in FastAPI): runs once per server process, before the first request."""
    _fail_orphaned_jobs()
    if storage.BACKEND == "local":
        threading.Thread(target=_cleanup_loop, daemon=True).start()
    yield


app = FastAPI(title="Movie Recap Tool Backend", version="3.0.0", lifespan=lifespan,
             docs_url="/docs" if API_DOCS else None, redoc_url="/redoc" if API_DOCS else None,
             openapi_url="/openapi.json" if API_DOCS else None)
app.add_middleware(RequestGuard)   # BEFORE the CORS middleware: its 401 / 413 answers must still carry the CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in CORS_ORIGINS if o != "*"],   # explicit origins only: browsers refuse "*" together with cookies
    allow_credentials=True,   # the apps' session is an httpOnly cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(accounts.router)
app.include_router(jobs.router)
app.include_router(catalog.router)
app.include_router(files.router)


@app.get("/")
def read_root():
    return {"message": "Movie Recap Tool API", "version": app.version}


@app.get("/health")
def health():
    return {"ok": True}


@app.exception_handler(Exception)
async def _unexpected_error(request: Request, exc: Exception):
    """Anything nobody planned for: log it with a code, tell the caller only the code (never a traceback, path or SQL)."""
    import traceback
    ref = uuid.uuid4().hex[:8]
    print(f"[error {ref}] {request.method} {request.url.path}\n{''.join(traceback.format_exception(exc))}", flush=True)
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong. Please try again. If it keeps happening, quote this code: {ref}"})
