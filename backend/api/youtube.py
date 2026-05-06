import asyncio
import json
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from mutagen.mp3 import MP3
from mutagen.id3 import TIT2, TPE1

from backend.config import REPOSITORY_DIR, DB_PATH
from backend.models import YouTubeDownloadRequest, JobStatus, Track
from backend import scanner


def _sanitize_path_part(part: str) -> str:
    part = part.replace("\\", "_").replace("/", "_").lstrip(".")
    part = re.sub(r"[^\w\s.-]", "", part)
    part = re.sub(r"\s+", " ", part).strip()
    return part


def _safe_music_subdir(target_dir: str | None) -> Path:
    music_dir = Path(REPOSITORY_DIR) / "Musics"
    if not target_dir:
        return music_dir

    parts = [
        safe
        for raw in re.split(r"[\\/]+", target_dir)
        if raw not in ("", ".", "..")
        for safe in [_sanitize_path_part(raw)]
        if safe
    ]
    if parts and parts[0].lower() == "musics":
        parts = parts[1:]
    return music_dir.joinpath(*parts) if parts else music_dir


def _yt_dlp_bin() -> str:
    venv_bin = Path(sys.executable).parent / "yt-dlp"
    if venv_bin.exists():
        return str(venv_bin)
    return "yt-dlp"

router = APIRouter()

_jobs: dict[str, JobStatus] = {}
_pending: list[str] = []
_running: set[str] = set()
_lock = asyncio.Lock()
_max_concurrent = 2
_max_jobs = 200


def _cleanup_old_jobs():
    """Keep only the most recent _max_jobs to avoid unbounded memory growth."""
    global _jobs, _job_params
    if len(_jobs) <= _max_jobs:
        return
    sorted_ids = sorted(_jobs.keys(), key=lambda jid: _jobs[jid].created_at or datetime.min)
    to_remove = sorted_ids[: len(_jobs) - _max_jobs]
    for jid in to_remove:
        del _jobs[jid]
        _job_params.pop(jid, None)


def _now() -> datetime:
    return datetime.utcnow()


def _find_mp3_files(directory: Path) -> set[Path]:
    if not directory.exists():
        return set()
    return set(directory.rglob("*.mp3"))


def _mp3_snapshot(directory: Path) -> dict[Path, tuple[int, float]]:
    return {
        path: (path.stat().st_size, path.stat().st_mtime)
        for path in _find_mp3_files(directory)
    }


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


def _tag_text(audio: MP3, key: str) -> str:
    if not audio.tags:
        return ""
    value = audio.tags.get(key)
    return str(value).strip() if value else ""


def _metadata_from_filename(path: Path) -> tuple[str, str]:
    stem = re.sub(r"^\d+\s*[-_.]\s*", "", path.stem).strip()
    stem = re.sub(r"\s+", " ", stem)
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip() or stem, artist.strip()
    return stem, ""


def _ensure_minimum_metadata(path: Path) -> None:
    try:
        audio = MP3(str(path))
        if audio.tags is None:
            audio.add_tags()

        current_title = _tag_text(audio, "TIT2")
        current_artist = _tag_text(audio, "TPE1")
        fallback_title, fallback_artist = _metadata_from_filename(path)

        changed = False
        if not current_title and fallback_title:
            audio.tags["TIT2"] = TIT2(encoding=3, text=fallback_title)
            changed = True
        if not current_artist and fallback_artist:
            audio.tags["TPE1"] = TPE1(encoding=3, text=fallback_artist)
            changed = True
        if changed:
            audio.save(str(path))
    except Exception:
        pass


def _info_contains_live_stream(info: object) -> bool:
    if isinstance(info, dict):
        is_live = info.get("is_live")
        live_status = info.get("live_status")
        if is_live or live_status in {"is_live", "is_upcoming", "post_live"}:
            return True
        entries = info.get("entries")
        if isinstance(entries, list):
            return any(_info_contains_live_stream(entry) for entry in entries)
    elif isinstance(info, list):
        return any(_info_contains_live_stream(entry) for entry in info)
    return False


async def _probe_media_info(url: str, as_playlist: bool) -> dict:
    cmd = [
        _yt_dlp_bin(),
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--skip-download",
        "--dump-single-json",
    ]
    if not as_playlist:
        cmd.append("--no-playlist")
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    stdout_str = stdout.decode("utf-8", errors="replace")
    stderr_str = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
      raise RuntimeError(f"yt-dlp probe failed with code {proc.returncode}: {stderr_str}")

    try:
        return json.loads(stdout_str)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse yt-dlp probe output: {e}")


def _refresh_job_tracks(job: JobStatus) -> JobStatus:
    if not job.tracks:
        return job

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        tracks = []
        for track in job.tracks:
            cur = conn.execute("SELECT * FROM tracks WHERE path = ?", (track.path,))
            row = cur.fetchone()
            if row:
                tracks.append(_row_to_track(row))
        job.tracks = tracks
        return job
    finally:
        conn.close()


async def _start_next_pending():
    async with _lock:
        while _pending and len(_running) < _max_concurrent:
            job_id = _pending.pop(0)
            _running.add(job_id)
            asyncio.create_task(_process_job(job_id))


async def _process_job(job_id: str):
    try:
        async with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.message = "Starting download..."
            job.updated_at = _now()

        params = _job_params.get(job_id)
        if not params:
            raise ValueError("Job parameters missing")
        url = params["url"]
        as_playlist = params["as_playlist"]
        target_dir = params["target_dir"]

        probe = await _probe_media_info(url, as_playlist)
        if _info_contains_live_stream(probe):
            raise RuntimeError(
                "Live/radio streams are not supported because they can run indefinitely. "
                "Use a normal video or a finite playlist."
            )

        repo_dir = Path(REPOSITORY_DIR)
        dest_dir = _safe_music_subdir(target_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        before_files = _mp3_snapshot(dest_dir)

        cmd = [
            _yt_dlp_bin(),
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--embed-metadata",
        ]

        if as_playlist:
            cmd.extend([
                "-o", str(dest_dir / "%(playlist_index)s - %(title)s.%(ext)s"),
                "--yes-playlist",
            ])
        else:
            cmd.extend([
                "-o", str(dest_dir / "%(title)s.%(ext)s"),
            ])

        cmd.append(url)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise RuntimeError(f"yt-dlp exited with code {proc.returncode}: {stderr_str}")

        after_files = _mp3_snapshot(dest_dir)
        changed_files = sorted(
            [
                path
                for path, current in after_files.items()
                if before_files.get(path) != current
            ],
            key=lambda p: p.name,
        )
        if not changed_files and not as_playlist and after_files:
            changed_files = [max(after_files.keys(), key=lambda p: after_files[p][1])]

        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            tracks = []
            for mp3_path in changed_files:
                _ensure_minimum_metadata(mp3_path)
                scanner.sync_single_file(conn, repo_dir, mp3_path)
                rel = str(mp3_path.relative_to(repo_dir))
                cur = conn.execute("SELECT * FROM tracks WHERE path = ?", (rel,))
                row = cur.fetchone()
                if row:
                    tracks.append(_row_to_track(row))

            if as_playlist and changed_files:
                pl_name = dest_dir.name if target_dir else "youtube_playlist"
                pl_path = dest_dir / f"{pl_name}.m3u8"
                rel_paths = [str(p.relative_to(repo_dir)) for p in changed_files]
                with open(pl_path, "w", encoding="utf-8") as f:
                    f.write("#EXTM3U\n")
                    for rp in rel_paths:
                        f.write(f"{rp}\n")
                scanner.sync_single_file(conn, repo_dir, pl_path)
        finally:
            conn.close()

        async with _lock:
            if job_id in _jobs:
                _jobs[job_id].status = "completed"
                _jobs[job_id].progress = 100
                _jobs[job_id].message = f"Downloaded {len(changed_files)} file(s) to {dest_dir.relative_to(repo_dir)}.\n{stdout_str[:2000]}"
                _jobs[job_id].tracks = tracks
                _jobs[job_id].updated_at = _now()

    except FileNotFoundError:
        async with _lock:
            if job_id in _jobs:
                _jobs[job_id].status = "failed"
                _jobs[job_id].message = "yt-dlp not found. Please install yt-dlp."
                _jobs[job_id].updated_at = _now()
    except Exception as e:
        async with _lock:
            if job_id in _jobs:
                _jobs[job_id].status = "failed"
                _jobs[job_id].message = f"Error: {e}"
                _jobs[job_id].updated_at = _now()
    finally:
        async with _lock:
            _running.discard(job_id)
        await _start_next_pending()


# Parallel store for job parameters (not returned to client)
_job_params: dict[str, dict] = {}


@router.post("/youtube/download", response_model=JobStatus)
async def download(body: YouTubeDownloadRequest):
    job_id = str(uuid.uuid4())
    now = _now()
    job = JobStatus(
        id=job_id,
        status="queued",
        progress=0,
        message="Queued",
        created_at=now,
    )

    async with _lock:
        _cleanup_old_jobs()
        _jobs[job_id] = job
        _job_params[job_id] = {
            "url": body.url,
            "as_playlist": body.as_playlist,
            "target_dir": body.target_dir,
        }
        _pending.append(job_id)

    # Start processing if under max_concurrent
    await _start_next_pending()
    return job


@router.get("/youtube/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    async with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _refresh_job_tracks(job)


@router.get("/youtube/jobs", response_model=list[JobStatus])
async def list_jobs():
    async with _lock:
        sorted_jobs = sorted(
            _jobs.values(),
            key=lambda j: j.created_at or datetime.min,
            reverse=True,
        )
        return [_refresh_job_tracks(job) for job in sorted_jobs[:50]]
