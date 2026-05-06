from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class Track(BaseModel):
    path: str
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[int] = None
    duration: Optional[float] = None
    bitrate: Optional[int] = None
    size: Optional[int] = None
    mtime: Optional[float] = None
    has_cover: bool = False


class TrackUpdate(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    genre: Optional[str] = None
    year: Optional[int] = None


class Playlist(BaseModel):
    path: str
    name: str
    mtime: Optional[float] = None
    track_count: int = 0


class PlaylistCreate(BaseModel):
    name: str


class PlaylistUpdate(BaseModel):
    name: Optional[str] = None
    track_order: Optional[list[str]] = None


class YouTubeDownloadRequest(BaseModel):
    url: str
    as_playlist: bool = False
    target_dir: Optional[str] = None


class JobStatus(BaseModel):
    id: str
    status: str  # queued | running | completed | failed
    progress: int = Field(0, ge=0, le=100)
    message: Optional[str] = None
    tracks: list[Track] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
