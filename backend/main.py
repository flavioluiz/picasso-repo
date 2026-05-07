import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, DB_PATH
from backend.config import REPOSITORY_DIR
from backend import scanner
from backend import carlog_scanner
from backend.api import tracks, playlists, upload, youtube, car_logs

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        scanner.sync_database(conn, Path(REPOSITORY_DIR))
        carlog_scanner.sync_car_datalog(conn, Path(REPOSITORY_DIR))
    except Exception:
        logger.warning("Scanner failed during startup", exc_info=True)
    finally:
        conn.close()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(tracks.router, prefix="/api")
app.include_router(playlists.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(youtube.router, prefix="/api")
app.include_router(car_logs.router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/api/sync")
async def sync():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    car_synced = 0
    car_updated = 0
    try:
        scanner.sync_database(conn, Path(REPOSITORY_DIR))
        try:
            car_synced, car_updated = carlog_scanner.sync_car_datalog(conn, Path(REPOSITORY_DIR))
        except Exception:
            logger.warning("Car datalog sync failed", exc_info=True)
        cur = conn.execute("SELECT COUNT(*) FROM tracks")
        synced_tracks = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM playlists")
        synced_playlists = cur.fetchone()[0]
    finally:
        conn.close()
    return {
        "synced_tracks": synced_tracks,
        "synced_playlists": synced_playlists,
        "synced_car_log_sessions": car_synced,
        "updated_car_log_sessions": car_updated,
    }


app.mount("/repo", StaticFiles(directory=REPOSITORY_DIR), name="repo")
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
