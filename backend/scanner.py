import sqlite3
from pathlib import Path
from typing import Tuple, List, Dict, Any

from mutagen.mp3 import MP3
from mutagen.id3 import ID3


def _metadata_from_filename(path: Path) -> tuple[str, str]:
    import re

    stem = re.sub(r"^\d+\s*[-_.]\s*", "", path.stem).strip()
    stem = re.sub(r"\s+", " ", stem)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip() or stem, artist.strip()
    return stem, ""


def scan_repository(repo_dir: Path) -> tuple[list[dict], list[dict]]:
    track_dicts: list[dict] = []
    playlist_dicts: list[dict] = []

    if not repo_dir.exists():
        return track_dicts, playlist_dicts

    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue
        lower = path.suffix.lower()
        if lower == ".mp3":
            track_dicts.append(extract_id3(path, repo_dir))
        elif lower in (".m3u", ".m3u8"):
            playlist_dicts.append({
                "path": str(path.relative_to(repo_dir)),
                "name": path.stem,
                "mtime": path.stat().st_mtime,
            })

    return track_dicts, playlist_dicts


def extract_id3(path: Path, repo_dir: Path | None = None) -> dict:
    if repo_dir is not None:
        try:
            rel_path = str(path.relative_to(repo_dir))
        except ValueError:
            rel_path = str(path)
    else:
        rel_path = str(path)
    stat = path.stat()
    size = stat.st_size
    mtime = stat.st_mtime

    title = None
    artist = None
    album = None
    genre = None
    year = None
    duration = None
    bitrate = None
    has_cover = False

    try:
        audio = MP3(str(path))
        if audio.info:
            duration = audio.info.length
            bitrate = audio.info.bitrate
        if audio.tags:
            tags = audio.tags
            title = tags.get("TIT2")
            if title:
                title = str(title)
            artist = tags.get("TPE1")
            if artist:
                artist = str(artist)
            album = tags.get("TALB")
            if album:
                album = str(album)
            genre = tags.get("TCON")
            if genre:
                genre = str(genre)
            year = tags.get("TDRC") or tags.get("TYER") or tags.get("DATE")
            if year:
                year_str = str(year)
                # Extract first 4-digit number
                import re
                m = re.search(r"(\d{4})", year_str)
                if m:
                    year = int(m.group(1))
                else:
                    year = None
            has_cover = any(k.startswith("APIC") for k in tags.keys())
    except Exception:
        pass

    fallback_title, fallback_artist = _metadata_from_filename(path)
    if not title and fallback_title:
        title = fallback_title
    if not artist and fallback_artist:
        artist = fallback_artist

    return {
        "path": rel_path,
        "title": title,
        "artist": artist,
        "album": album,
        "genre": genre,
        "year": year,
        "duration": duration,
        "bitrate": bitrate,
        "size": size,
        "mtime": mtime,
        "has_cover": has_cover,
    }


def parse_m3u(path: Path, repo_dir: Path | None = None) -> list[str]:
    tracks: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                resolved = _resolve_m3u_path(line, path, repo_dir)
                if resolved:
                    tracks.append(resolved)
    except Exception:
        pass
    return tracks


def _resolve_m3u_path(line: str, playlist_path: Path, repo_dir: Path | None) -> str | None:
    """Resolve a track path from an M3U entry to a repo-relative path.

    Tries several strategies:
    1. If absolute under repo_dir, make it relative.
    2. If relative to playlist dir exists, resolve it.
    3. If relative to repo_dir exists, keep it.
    4. Try common subfolders (Musics, mp3).
    """
    if repo_dir is None:
        return line

    # Strategy 1: absolute path inside repo_dir
    abs_path = Path(line)
    if abs_path.is_absolute():
        try:
            rel = abs_path.relative_to(repo_dir)
            if (repo_dir / rel).is_file():
                return str(rel)
        except ValueError:
            pass
        return None

    # Strategy 2: relative to playlist directory
    rel_to_pl = (playlist_path.parent / line).relative_to(repo_dir)
    if (repo_dir / rel_to_pl).is_file():
        return str(rel_to_pl)

    # Strategy 3: relative to repo_dir directly
    if (repo_dir / line).is_file():
        return line

    # Strategy 4: common subfolders
    for sub in ("Musics", "mp3"):
        candidate = f"{sub}/{line}"
        if (repo_dir / candidate).is_file():
            return candidate

    # Fallback: return as-is (will be filtered out later if track doesn't exist)
    return line


def sync_database(db: sqlite3.Connection, repo_dir: Path) -> None:
    db.execute("DELETE FROM playlist_items")
    db.execute("DELETE FROM playlists")
    db.execute("DELETE FROM tracks")
    db.commit()

    track_dicts, playlist_dicts = scan_repository(repo_dir)

    for track in track_dicts:
        db.execute(
            """
            INSERT INTO tracks (path, title, artist, album, genre, year, duration, bitrate, size, mtime, has_cover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track["path"],
                track["title"],
                track["artist"],
                track["album"],
                track["genre"],
                track["year"],
                track["duration"],
                track["bitrate"],
                track["size"],
                track["mtime"],
                track["has_cover"],
            ),
        )

    # Collect valid track paths for FK safety
    valid_track_paths = {t["path"] for t in track_dicts}

    for pl in playlist_dicts:
        db.execute(
            "INSERT INTO playlists (path, name, mtime, track_count) VALUES (?, ?, ?, ?)",
            (pl["path"], pl["name"], pl["mtime"], 0),
        )
        track_paths = parse_m3u(repo_dir / pl["path"], repo_dir)
        valid_items = []
        for track_path in track_paths:
            # Handle absolute paths that start with repo_dir
            abs_path = Path(track_path)
            if abs_path.is_absolute():
                try:
                    rel = abs_path.relative_to(repo_dir)
                    track_path = str(rel)
                except ValueError:
                    pass
            if track_path in valid_track_paths:
                valid_items.append(track_path)
        for position, track_path in enumerate(valid_items):
            db.execute(
                "INSERT INTO playlist_items (playlist_path, track_path, position) VALUES (?, ?, ?)",
                (pl["path"], track_path, position),
            )
        # Update track_count to reflect only valid tracks
        db.execute(
            "UPDATE playlists SET track_count = ? WHERE path = ?",
            (len(valid_items), pl["path"]),
        )

    db.commit()


def sync_single_file(db: sqlite3.Connection, repo_dir: Path, file_path: Path) -> None:
    if not file_path.exists():
        return

    lower = file_path.suffix.lower()
    if lower == ".mp3":
        track = extract_id3(file_path, repo_dir)
        db.execute(
            """
            INSERT INTO tracks (path, title, artist, album, genre, year, duration, bitrate, size, mtime, has_cover)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title,
                artist=excluded.artist,
                album=excluded.album,
                genre=excluded.genre,
                year=excluded.year,
                duration=excluded.duration,
                bitrate=excluded.bitrate,
                size=excluded.size,
                mtime=excluded.mtime,
                has_cover=excluded.has_cover
            """,
            (
                track["path"],
                track["title"],
                track["artist"],
                track["album"],
                track["genre"],
                track["year"],
                track["duration"],
                track["bitrate"],
                track["size"],
                track["mtime"],
                track["has_cover"],
            ),
        )
        db.commit()

    elif lower in (".m3u", ".m3u8"):
        rel_path = str(file_path.relative_to(repo_dir)) if file_path.is_relative_to(repo_dir) else str(file_path)
        mtime = file_path.stat().st_mtime
        db.execute(
            """INSERT INTO playlists (path, name, mtime, track_count) VALUES (?, ?, ?, ?)
             ON CONFLICT(path) DO UPDATE SET name=excluded.name, mtime=excluded.mtime, track_count=excluded.track_count""",
            (rel_path, file_path.stem, mtime, 0),
        )
        db.execute("DELETE FROM playlist_items WHERE playlist_path = ?", (rel_path,))
        track_paths = parse_m3u(file_path, repo_dir)
        valid_items = []
        for track_path in track_paths:
            abs_path = Path(track_path)
            if abs_path.is_absolute():
                try:
                    rel = abs_path.relative_to(repo_dir)
                    track_path = str(rel)
                except ValueError:
                    pass
            # Verify track exists in DB before inserting FK reference
            cur = db.execute("SELECT 1 FROM tracks WHERE path = ?", (track_path,))
            if cur.fetchone():
                valid_items.append(track_path)
        for position, track_path in enumerate(valid_items):
            db.execute(
                "INSERT INTO playlist_items (playlist_path, track_path, position) VALUES (?, ?, ?)",
                (rel_path, track_path, position),
            )
        db.execute(
            "UPDATE playlists SET track_count = ? WHERE path = ?",
            (len(valid_items), rel_path),
        )
        db.commit()
