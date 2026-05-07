from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CarLogSessionSummary(BaseModel):
    session_id: str
    device_name: str
    vin: Optional[str] = None
    vehicle: Optional[str] = None
    relative_path: str
    file_size: int
    sample_count: int
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_s: Optional[float] = None
    first_logged_at: Optional[str] = None
    last_logged_at: Optional[str] = None
    first_sample_time: Optional[str] = None
    last_sample_time: Optional[str] = None
    wifi_seen: Optional[bool] = None
    gps_seen: Optional[bool] = None
    gps_fix_seen: Optional[bool] = None
    created_at: str
    updated_at: str


class CarLogFieldStats(BaseModel):
    field_path: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    avg_value: Optional[float] = None
    last_value: Optional[float] = None
    sample_count: Optional[int] = None


class CarLogSessionDetail(CarLogSessionSummary):
    fields: List[CarLogFieldStats] = Field(default_factory=list)


class CarLogSeries(BaseModel):
    field: str
    label: str
    unit: Optional[str] = None
    points: List[List[float]] = Field(default_factory=list)


class CarLogSeriesResponse(BaseModel):
    session: CarLogSessionSummary
    time_axis: str
    series: List[CarLogSeries]


class CarLogPreviewWarning(BaseModel):
    warning_type: str
    message: str


class CarLogPreviewResponse(BaseModel):
    first_samples: List[dict]
    last_samples: List[dict]
    sample_count: int
    total_lines: int
    invalid_lines: int
    warnings: List[CarLogPreviewWarning]


class CarLogStats(BaseModel):
    total_sessions: int
    total_space_bytes: int
    last_sync_at: Optional[str] = None


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
