import os
import sqlite3
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "test_picasso_commit1.db")
os.environ["REPOSITORY_DIR"] = tempfile.gettempdir()

from backend.database import init_db, get_db, DB_PATH


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def test_init_db_creates_all_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {r[0] for r in cur.fetchall()}
    conn.close()
    assert "car_log_sessions" in tables
    assert "car_log_session_fields" in tables
    assert "tracks" in tables
    assert "playlists" in tables
    assert "playlist_items" in tables


def test_car_log_sessions_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("PRAGMA table_info(car_log_sessions)")
    cols = {r[1]: r[2] for r in cur.fetchall()}
    conn.close()
    expected_cols = {
        "session_id", "device_name", "vin", "vehicle", "relative_path",
        "file_size", "sample_count", "started_at", "ended_at", "duration_s",
        "first_logged_at", "last_logged_at", "first_sample_time", "last_sample_time",
        "wifi_seen", "gps_seen", "gps_fix_seen", "created_at", "updated_at",
        "scan_mtime", "parser_version",
    }
    assert set(cols.keys()) == expected_cols
    assert cols["session_id"] == "TEXT"
    assert cols["device_name"] == "TEXT"
    assert cols["relative_path"] == "TEXT"
    assert cols["file_size"] == "INTEGER"
    assert cols["sample_count"] == "INTEGER"
    assert cols["duration_s"] == "REAL"
    assert cols["scan_mtime"] == "REAL"
    assert cols["parser_version"] == "INTEGER"


def test_car_log_session_fields_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("PRAGMA table_info(car_log_session_fields)")
    cols = {r[1]: r[2] for r in cur.fetchall()}
    conn.close()
    expected_cols = {
        "session_id", "field_path", "min_value", "max_value",
        "avg_value", "last_value", "sample_count",
    }
    assert set(cols.keys()) == expected_cols


def test_car_log_session_fields_fk_cascade():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO car_log_sessions (session_id, device_name, relative_path, file_size, sample_count, created_at, updated_at, scan_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "dev", "p/s1.jsonl", 100, 10, "2026-01-01", "2026-01-01", 0.0),
        )
        conn.execute(
            "INSERT INTO car_log_session_fields (session_id, field_path, min_value, max_value) VALUES (?, ?, ?, ?)",
            ("s1", "direct.rpm", 800.0, 3000.0),
        )
        conn.commit()

    with get_db() as conn:
        conn.execute("DELETE FROM car_log_sessions WHERE session_id = ?", ("s1",))
        conn.commit()

    with get_db() as conn:
        cur = conn.execute("SELECT COUNT(*) FROM car_log_session_fields WHERE session_id = ?", ("s1",))
        assert cur.fetchone()[0] == 0


def test_car_log_sessions_primary_key():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO car_log_sessions (session_id, device_name, relative_path, file_size, sample_count, created_at, updated_at, scan_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "dev", "p/s1.jsonl", 100, 10, "2026-01-01", "2026-01-01", 0.0),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO car_log_sessions (session_id, device_name, relative_path, file_size, sample_count, created_at, updated_at, scan_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("s1", "dev2", "p/s2.jsonl", 200, 20, "2026-01-02", "2026-01-02", 0.0),
            )


def test_car_log_sessions_relative_path_unique():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO car_log_sessions (session_id, device_name, relative_path, file_size, sample_count, created_at, updated_at, scan_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "dev", "p/s1.jsonl", 100, 10, "2026-01-01", "2026-01-01", 0.0),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO car_log_sessions (session_id, device_name, relative_path, file_size, sample_count, created_at, updated_at, scan_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("s2", "dev", "p/s1.jsonl", 200, 20, "2026-01-02", "2026-01-02", 0.0),
            )


def test_car_log_session_fields_composite_pk():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO car_log_sessions (session_id, device_name, relative_path, file_size, sample_count, created_at, updated_at, scan_mtime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("s1", "dev", "p/s1.jsonl", 100, 10, "2026-01-01", "2026-01-01", 0.0),
        )
        conn.execute(
            "INSERT INTO car_log_session_fields (session_id, field_path, min_value) VALUES (?, ?, ?)",
            ("s1", "direct.rpm", 800.0),
        )
        conn.execute(
            "INSERT INTO car_log_session_fields (session_id, field_path, min_value) VALUES (?, ?, ?)",
            ("s1", "direct.speed_kmh", 0.0),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO car_log_session_fields (session_id, field_path, min_value) VALUES (?, ?, ?)",
                ("s1", "direct.rpm", 900.0),
            )


def test_tracks_table_still_works():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO tracks (path, title, artist, size, mtime) VALUES (?, ?, ?, ?, ?)",
            ("test.mp3", "Test Song", "Artist", 1000, 0.0),
        )
        conn.commit()
        cur = conn.execute("SELECT title FROM tracks WHERE path = ?", ("test.mp3",))
        assert cur.fetchone()[0] == "Test Song"


def test_playlists_table_still_works():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO playlists (path, name, mtime, track_count) VALUES (?, ?, ?, ?)",
            ("test.m3u8", "Test", 0.0, 0),
        )
        conn.commit()
        cur = conn.execute("SELECT name FROM playlists WHERE path = ?", ("test.m3u8",))
        assert cur.fetchone()[0] == "Test"


def test_init_db_idempotent():
    init_db()
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    count_before = cur.fetchone()[0]
    init_db()
    cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
    count_after = cur.fetchone()[0]
    conn.close()
    assert count_before == count_after
