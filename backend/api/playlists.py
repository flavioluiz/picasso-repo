import sqlite3
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import REPOSITORY_DIR, DB_PATH
from backend.models import Playlist, PlaylistCreate, PlaylistUpdate, Track
from backend import scanner

router = APIRouter()


class AddTrackRequest(BaseModel):
    track_path: str
    position: Optional[int] = None


def _row_to_playlist(row: sqlite3.Row) -> Playlist:
    return Playlist(
        path=row["path"],
        name=row["name"],
        mtime=row["mtime"],
        track_count=row["track_count"] or 0,
    )


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


def _write_m3u(full_path: Path, track_paths: list[str]) -> None:
    with open(full_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for tp in track_paths:
            f.write(f"{tp}\n")


def _rebuild_playlist_items(db: sqlite3.Connection, playlist_path: str, track_paths: list[str]) -> None:
    db.execute("DELETE FROM playlist_items WHERE playlist_path = ?", (playlist_path,))
    position = 0
    for track_path in track_paths:
        cur = db.execute("SELECT 1 FROM tracks WHERE path = ?", (track_path,))
        if cur.fetchone():
            db.execute(
                "INSERT INTO playlist_items (playlist_path, track_path, position) VALUES (?, ?, ?)",
                (playlist_path, track_path, position),
            )
            position += 1
    db.execute(
        "UPDATE playlists SET track_count = ?, mtime = ? WHERE path = ?",
        (position, Path(REPOSITORY_DIR).joinpath(playlist_path).stat().st_mtime, playlist_path),
    )
    db.commit()


def _get_playlist_tracks(db: sqlite3.Connection, playlist_path: str) -> list[Track]:
    cur = db.execute(
        """
        SELECT t.* FROM tracks t
        JOIN playlist_items pi ON t.path = pi.track_path
        WHERE pi.playlist_path = ?
        ORDER BY pi.position
        """,
        (playlist_path,),
    )
    return [_row_to_track(r) for r in cur.fetchall()]


@router.get("/playlists", response_model=list[Playlist])
async def list_playlists():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM playlists ORDER BY path")
        return [_row_to_playlist(r) for r in cur.fetchall()]
    finally:
        conn.close()


@router.get("/playlists/{path:path}")
async def get_playlist(path: str):
    decoded = urllib.parse.unquote(path)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM playlists WHERE path = ?", (decoded,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playlist not found")
        playlist = _row_to_playlist(row)
        tracks = _get_playlist_tracks(conn, decoded)
        return {"playlist": playlist, "tracks": tracks}
    finally:
        conn.close()


@router.post("/playlists", response_model=Playlist)
async def create_playlist(body: PlaylistCreate):
    filename = f"{body.name}.m3u8"
    full_path = Path(REPOSITORY_DIR) / filename
    if full_path.exists():
        raise HTTPException(status_code=409, detail="Playlist already exists")

    _write_m3u(full_path, [])
    mtime = full_path.stat().st_mtime

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            "INSERT INTO playlists (path, name, mtime, track_count) VALUES (?, ?, ?, ?)",
            (filename, body.name, mtime, 0),
        )
        conn.commit()
        return Playlist(path=filename, name=body.name, mtime=mtime, track_count=0)
    finally:
        conn.close()


@router.put("/playlists/{path:path}", response_model=Playlist)
async def update_playlist(path: str, body: PlaylistUpdate):
    decoded = urllib.parse.unquote(path)
    old_full_path = Path(REPOSITORY_DIR) / decoded
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM playlists WHERE path = ?", (decoded,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playlist not found")

        new_path = decoded
        new_full_path = old_full_path
        new_name = row["name"]

        if body.name is not None and body.name != row["name"]:
            new_name = body.name
            new_path = f"{body.name}.m3u8"
            new_full_path = Path(REPOSITORY_DIR) / new_path
            if new_full_path.exists():
                raise HTTPException(status_code=409, detail="Target playlist already exists")
            # Rename file
            old_full_path.rename(new_full_path)
            # Update DB: delete old, insert new (because FK cascade on delete)
            track_paths = scanner.parse_m3u(new_full_path, Path(REPOSITORY_DIR))
            conn.execute("DELETE FROM playlists WHERE path = ?", (decoded,))
            conn.execute(
                "INSERT INTO playlists (path, name, mtime, track_count) VALUES (?, ?, ?, ?)",
                (new_path, new_name, new_full_path.stat().st_mtime, len(track_paths)),
            )
            conn.commit()
            _rebuild_playlist_items(conn, new_path, track_paths)

        if body.track_order is not None:
            full_path = new_full_path
            _write_m3u(full_path, body.track_order)
            _rebuild_playlist_items(conn, new_path, body.track_order)

        cur = conn.execute("SELECT * FROM playlists WHERE path = ?", (new_path,))
        row = cur.fetchone()
        return _row_to_playlist(row)
    finally:
        conn.close()


@router.post("/playlists/{path:path}/tracks")
async def add_track_to_playlist(path: str, body: AddTrackRequest):
    decoded = urllib.parse.unquote(path)
    full_path = Path(REPOSITORY_DIR) / decoded
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM playlists WHERE path = ?", (decoded,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playlist not found")

        track_paths = scanner.parse_m3u(full_path, Path(REPOSITORY_DIR))
        pos = body.position if body.position is not None else len(track_paths)
        pos = max(0, min(pos, len(track_paths)))
        track_paths.insert(pos, body.track_path)
        _write_m3u(full_path, track_paths)
        _rebuild_playlist_items(conn, decoded, track_paths)

        playlist = _row_to_playlist(
            conn.execute("SELECT * FROM playlists WHERE path = ?", (decoded,)).fetchone()
        )
        tracks = _get_playlist_tracks(conn, decoded)
        return {"playlist": playlist, "tracks": tracks}
    finally:
        conn.close()


@router.delete("/playlists/{path:path}/tracks/{position}")
async def remove_track_from_playlist(path: str, position: int):
    decoded = urllib.parse.unquote(path)
    full_path = Path(REPOSITORY_DIR) / decoded
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM playlists WHERE path = ?", (decoded,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Playlist not found")

        track_paths = scanner.parse_m3u(full_path, Path(REPOSITORY_DIR))
        if position < 0 or position >= len(track_paths):
            raise HTTPException(status_code=400, detail="Invalid position")
        track_paths.pop(position)
        _write_m3u(full_path, track_paths)
        _rebuild_playlist_items(conn, decoded, track_paths)

        playlist = _row_to_playlist(
            conn.execute("SELECT * FROM playlists WHERE path = ?", (decoded,)).fetchone()
        )
        tracks = _get_playlist_tracks(conn, decoded)
        return {"playlist": playlist, "tracks": tracks}
    finally:
        conn.close()


@router.delete("/playlists/{path:path}")
async def delete_playlist(path: str):
    decoded = urllib.parse.unquote(path)
    full_path = Path(REPOSITORY_DIR) / decoded

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("DELETE FROM playlists WHERE path = ?", (decoded,))
        conn.commit()
    finally:
        conn.close()

    if full_path.exists():
        try:
            full_path.unlink()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")

    return {"deleted": True}
