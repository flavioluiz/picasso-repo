import os
import shutil
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, TYER, TDRC

from backend.config import REPOSITORY_DIR, DB_PATH
from backend.models import Track, TrackUpdate
from backend import scanner

router = APIRouter()


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


@router.get("/tracks", response_model=list[Track])
async def list_tracks(
    q: Optional[str] = Query(None),
    missing_title: bool = Query(False),
    missing_artist: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(10000, ge=1, le=10000),
):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        conditions = []
        params = []
        if q:
            pattern = f"%{q}%"
            conditions.append(
                "(path LIKE ? OR title LIKE ? OR artist LIKE ? OR album LIKE ? OR genre LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern, pattern])
        missing_title_condition = "(title IS NULL OR TRIM(title) = '')"
        missing_artist_condition = "(artist IS NULL OR TRIM(artist) = '')"
        if missing_title and missing_artist:
            conditions.append(f"({missing_title_condition} OR {missing_artist_condition})")
        elif missing_title:
            conditions.append(missing_title_condition)
        elif missing_artist:
            conditions.append(missing_artist_condition)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cur = conn.execute(
            f"""
            SELECT * FROM tracks
            {where}
            ORDER BY mtime DESC, path
            LIMIT ? OFFSET ?
            """,
            (*params, limit, skip),
        )
        rows = cur.fetchall()
        return [_row_to_track(r) for r in rows]
    finally:
        conn.close()


@router.get("/tracks/{path:path}/cover")
async def get_cover(path: str):
    decoded = urllib.parse.unquote(path)
    full_path = Path(REPOSITORY_DIR) / decoded
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        audio = MP3(str(full_path))
        if not audio.tags:
            raise HTTPException(status_code=404, detail="No cover art")
        apic = None
        for key in audio.tags.keys():
            if key.startswith("APIC"):
                apic = audio.tags[key]
                break
        if apic is None:
            raise HTTPException(status_code=404, detail="No cover art")

        mime = apic.mime if apic.mime else "image/jpeg"
        return Response(content=apic.data, media_type=mime)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read cover: {e}")


@router.get("/tracks/{path:path}", response_model=Track)
async def get_track(path: str):
    decoded = urllib.parse.unquote(path)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM tracks WHERE path = ?", (decoded,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Track not found")
        return _row_to_track(row)
    finally:
        conn.close()


@router.put("/tracks/{path:path}", response_model=Track)
async def update_track(path: str, update: TrackUpdate):
    decoded = urllib.parse.unquote(path)
    full_path = Path(REPOSITORY_DIR) / decoded
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        # Atomic write: copy to temp, edit temp, then rename
        tmp_path = full_path.with_suffix(".mp3.tmp")
        shutil.copy2(str(full_path), str(tmp_path))
        audio = MP3(str(tmp_path))
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags

        if update.title is not None:
            tags["TIT2"] = TIT2(encoding=3, text=update.title)
        if update.artist is not None:
            tags["TPE1"] = TPE1(encoding=3, text=update.artist)
        if update.album is not None:
            tags["TALB"] = TALB(encoding=3, text=update.album)
        if update.genre is not None:
            tags["TCON"] = TCON(encoding=3, text=update.genre)
        if update.year is not None:
            tags["TDRC"] = TDRC(encoding=3, text=str(update.year))

        audio.save(str(tmp_path))
        os.replace(str(tmp_path), str(full_path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update tags: {e}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        scanner.sync_single_file(conn, Path(REPOSITORY_DIR), full_path)
        cur = conn.execute("SELECT * FROM tracks WHERE path = ?", (decoded,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Track not found after sync")
        return _row_to_track(row)
    finally:
        conn.close()


@router.delete("/tracks/{path:path}")
async def delete_track(path: str):
    decoded = urllib.parse.unquote(path)
    full_path = Path(REPOSITORY_DIR) / decoded

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("DELETE FROM playlist_items WHERE track_path = ?", (decoded,))
        conn.execute("DELETE FROM tracks WHERE path = ?", (decoded,))
        conn.commit()
    finally:
        conn.close()

    if full_path.exists():
        try:
            full_path.unlink()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")

    return {"deleted": True}
