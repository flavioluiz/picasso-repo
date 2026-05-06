import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.config import REPOSITORY_DIR, DB_PATH
from backend.models import Track
from backend import scanner

router = APIRouter()


def _sanitize_filename(name: str) -> str:
    # Remove path separators and dots at start
    name = name.replace("\\", "_").replace("/", "_")
    name = name.lstrip(".")
    # Keep only safe characters: alphanumeric, spaces, hyphens, underscores, dots
    name = re.sub(r"[^\w\s.-]", "", name)
    # Collapse multiple spaces
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = "untitled"
    return name


def _safe_music_subdir(base_dir: Path, target_dir: str | None) -> Path:
    music_dir = base_dir / "Musics"
    if not target_dir:
        return music_dir

    parts = [
        safe
        for raw in re.split(r"[\\/]+", target_dir)
        if raw not in ("", ".", "..")
        for safe in [_sanitize_filename(raw)]
        if safe
    ]
    if parts and parts[0].lower() == "musics":
        parts = parts[1:]
    return music_dir.joinpath(*parts) if parts else music_dir


def _row_to_track(row: sqlite3.Row) -> Track:
    return Track(
        path=row["path"],
        title=row["title"],
        artist=row["artist"],
        album=row["album"],
        genre=row["genre"],
        year=row["year"],
        duration=row["duration"],
        bitrate=row["bitrate"],
        size=row["size"],
        mtime=row["mtime"],
        has_cover=bool(row["has_cover"]),
    )


@router.post("/upload", response_model=list[Track])
async def upload_files(
    files: list[UploadFile] = File(...),
    target_dir: Optional[str] = Form(None),
):
    base_dir = Path(REPOSITORY_DIR)
    dest_dir = _safe_music_subdir(base_dir, target_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for upload in files:
        if not upload.filename:
            continue
        lower = upload.filename.lower()
        if not lower.endswith(".mp3"):
            raise HTTPException(status_code=400, detail=f"Only MP3 files allowed: {upload.filename}")

        safe_name = _sanitize_filename(upload.filename)
        dest_path = dest_dir / safe_name

        with open(dest_path, "wb") as f:
            shutil.copyfileobj(upload.file, f)

        saved_paths.append(dest_path)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        tracks: list[Track] = []
        for sp in saved_paths:
            scanner.sync_single_file(conn, base_dir, sp)
            rel = str(sp.relative_to(base_dir))
            cur = conn.execute("SELECT * FROM tracks WHERE path = ?", (rel,))
            row = cur.fetchone()
            if row:
                tracks.append(_row_to_track(row))
        return tracks
    finally:
        conn.close()
