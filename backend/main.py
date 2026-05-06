import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.database import init_db, DB_PATH
from backend.config import REPOSITORY_DIR
from backend import scanner
from backend.api import tracks, playlists, upload, youtube


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        scanner.sync_database(conn, Path(REPOSITORY_DIR))
    finally:
        conn.close()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(tracks.router, prefix="/api")
app.include_router(playlists.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(youtube.router, prefix="/api")

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
    import sqlite3
    from pathlib import Path
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        scanner.sync_database(conn, Path(REPOSITORY_DIR))
        cur = conn.execute("SELECT COUNT(*) FROM tracks")
        synced_tracks = cur.fetchone()[0]
        cur = conn.execute("SELECT COUNT(*) FROM playlists")
        synced_playlists = cur.fetchone()[0]
    finally:
        conn.close()
    return {"synced_tracks": synced_tracks, "synced_playlists": synced_playlists}


app.mount("/repo", StaticFiles(directory=REPOSITORY_DIR), name="repo")
app.mount("/", StaticFiles(directory="frontend", html=True), name="static")
