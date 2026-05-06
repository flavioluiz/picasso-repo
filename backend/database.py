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
