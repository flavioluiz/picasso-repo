import sqlite3
import os
from contextlib import contextmanager

from backend.config import DB_PATH


def init_db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS car_log_sessions (
                session_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                vin TEXT,
                vehicle TEXT,
                relative_path TEXT NOT NULL UNIQUE,
                file_size INTEGER NOT NULL,
                sample_count INTEGER NOT NULL,
                started_at TEXT,
                ended_at TEXT,
                duration_s REAL,
                first_logged_at TEXT,
                last_logged_at TEXT,
                first_sample_time TEXT,
                last_sample_time TEXT,
                wifi_seen BOOLEAN,
                gps_seen BOOLEAN,
                gps_fix_seen BOOLEAN,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                scan_mtime REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS car_log_session_fields (
                session_id TEXT NOT NULL,
                field_path TEXT NOT NULL,
                min_value REAL,
                max_value REAL,
                avg_value REAL,
                last_value REAL,
                sample_count INTEGER,
                PRIMARY KEY (session_id, field_path)
            );
            CREATE TABLE IF NOT EXISTS tracks (
                path TEXT PRIMARY KEY,
                title TEXT,
                artist TEXT,
                album TEXT,
                genre TEXT,
                year INTEGER,
                duration REAL,
                bitrate INTEGER,
                size INTEGER,
                mtime REAL,
                has_cover BOOLEAN
            );
            CREATE TABLE IF NOT EXISTS playlists (
                path TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                mtime REAL,
                track_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS playlist_items (
                playlist_path TEXT NOT NULL,
                track_path TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (playlist_path, position),
                FOREIGN KEY (playlist_path) REFERENCES playlists(path) ON DELETE CASCADE,
                FOREIGN KEY (track_path) REFERENCES tracks(path) ON DELETE CASCADE
            );
        """)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
