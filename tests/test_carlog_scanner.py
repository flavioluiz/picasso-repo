import os
import sqlite3
import tempfile
import shutil
import json

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "test_picasso_carlog_scanner.db")
os.environ["REPOSITORY_DIR"] = tempfile.gettempdir()

from backend.database import init_db, DB_PATH
from backend.carlog_scanner import (
    _flatten,
    _is_numeric,
    _parse_jsonl_file,
    scan_car_datalog,
    sync_car_datalog,
)
from backend.config import CAR_DATALOG_SUBDIR


@pytest.fixture(autouse=True)
def fresh_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


@pytest.fixture
def repo_dir(tmp_path):
    return tmp_path


def _make_session_dir(repo_dir, device="dev1", vin="VIN999"):
    d = repo_dir / CAR_DATALOG_SUBDIR / device / "2026" / "05" / "07" / vin
    d.mkdir(parents=True)
    return d


def _write_jsonl(path, samples):
    with open(path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")


def _sample(overrides=None, **kwargs):
    base = {
        "logged_at": "2026-05-07T10:21:56.883400+00:00",
        "session_id": "session-2026-05-07T10-21-55Z",
        "device_name": "c3-picasso-2013",
        "vehicle": "Citroen C3 Picasso 2013 1.5 Flex",
        "vin": "VF7XXXXXXXX",
        "time_context": {
            "sample_time": "2026-05-07T10:21:55.932673+00:00",
            "logged_at": "2026-05-07T10:21:56.883400+00:00",
            "wifi_connected": True,
            "gps_connected": False,
            "gps_has_fix": False,
        },
        "gps": {
            "lat": None,
            "lon": None,
            "speed": 0,
            "altitude": None,
            "satellites": 0,
            "connected": False,
        },
        "wifi": {"connected": True},
        "direct": {
            "rpm": 2000.0,
            "speed_kmh": 50,
            "coolant_temp_c": 80,
        },
    }
    if overrides:
        base.update(overrides)
    base.update(kwargs)
    return base


def test_flatten_nested():
    result = _flatten({"a": {"b": {"c": 1}}, "d": 2})
    assert result == {"a.b.c": 1, "d": 2}


def test_flatten_empty():
    assert _flatten({}) == {}


def test_is_numeric_int():
    assert _is_numeric(42) is True


def test_is_numeric_float():
    assert _is_numeric(3.14) is True


def test_is_numeric_bool():
    assert _is_numeric(True) is False
    assert _is_numeric(False) is False


def test_is_numeric_none():
    assert _is_numeric(None) is False


def test_is_numeric_string():
    assert _is_numeric("42") is False


def test_parse_extracts_session_id(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    session, fields = _parse_jsonl_file(f, repo_dir)
    assert session["session_id"] == "session-2026-05-07T10-21-55Z"


def test_parse_extracts_device_name_from_path(repo_dir):
    d = _make_session_dir(repo_dir, device="my-device")
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["device_name"] == "my-device"


def test_parse_extracts_vin_from_data(repo_dir):
    d = _make_session_dir(repo_dir, vin="PATH_VIN")
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample(vin="DATA_VIN")])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["vin"] == "DATA_VIN"


def test_parse_vin_fallback_to_path(repo_dir):
    d = _make_session_dir(repo_dir, vin="PATH_VIN")
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample(vin=None)])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["vin"] == "PATH_VIN"


def test_parse_extracts_vehicle_from_data(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample(vehicle="Citroen C3 Picasso 2013 1.5 Flex")])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["vehicle"] == "Citroen C3 Picasso 2013 1.5 Flex"


def test_parse_vehicle_fallback_to_device_name(repo_dir):
    d = _make_session_dir(repo_dir, device="c3-picasso-2013")
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    sample = _sample()
    del sample["vehicle"]
    _write_jsonl(f, [sample])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["vehicle"] == "c3-picasso-2013"


def test_parse_wifi_seen_true(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["wifi_seen"] is True


def test_parse_wifi_seen_false(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    sample = _sample()
    sample["wifi"]["connected"] = False
    sample["time_context"]["wifi_connected"] = False
    _write_jsonl(f, [sample])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["wifi_seen"] is False


def test_parse_gps_seen_when_connected(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    sample = _sample()
    sample["gps"]["connected"] = True
    _write_jsonl(f, [sample])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["gps_seen"] is True


def test_parse_gps_seen_false_when_disconnected(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["gps_seen"] is False


def test_parse_gps_seen_via_time_context(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    sample = _sample()
    sample["gps"]["connected"] = False
    sample["time_context"]["gps_connected"] = True
    _write_jsonl(f, [sample])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["gps_seen"] is True


def test_parse_gps_fix_seen_via_time_context(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    sample = _sample()
    sample["time_context"]["gps_has_fix"] = True
    _write_jsonl(f, [sample])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["gps_fix_seen"] is True


def test_parse_gps_fix_seen_false_when_no_fix(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["gps_fix_seen"] is False


def test_parse_sample_count(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample() for _ in range(10)])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["sample_count"] == 10


def test_parse_duration(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    s1 = _sample()
    s2 = _sample()
    s2["logged_at"] = "2026-05-07T10:23:56.883400+00:00"
    s2["time_context"]["logged_at"] = "2026-05-07T10:23:56.883400+00:00"
    s2["time_context"]["sample_time"] = "2026-05-07T10:23:55.932673+00:00"
    _write_jsonl(f, [s1, s2])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["duration_s"] is not None
    assert abs(session["duration_s"] - 120.0) < 1.0


def test_parse_truncated_last_line(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    lines = [json.dumps(_sample()) for _ in range(5)]
    content = "\n".join(lines) + "\n" + '{"logged_at": "2026-05-07T1'
    with open(f, "w") as fh:
        fh.write(content)
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["sample_count"] == 5


def test_parse_empty_file(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    f.write_text("")
    session, fields = _parse_jsonl_file(f, repo_dir)
    assert session["sample_count"] == 0
    assert fields == []


def test_parse_file_size(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    session, _ = _parse_jsonl_file(f, repo_dir)
    assert session["file_size"] > 0


def test_field_stats_numeric(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    samples = [
        _sample(**{"direct.rpm": 1000.0, "direct.speed_kmh": 50}),
        _sample(**{"direct.rpm": 2000.0, "direct.speed_kmh": 60}),
        _sample(**{"direct.rpm": 3000.0, "direct.speed_kmh": 70}),
    ]
    _write_jsonl(f, samples)
    _, fields = _parse_jsonl_file(f, repo_dir)
    field_map = {r["field_path"]: r for r in fields}
    rpm = field_map["direct.rpm"]
    assert rpm["min_value"] == 1000.0
    assert rpm["max_value"] == 3000.0
    assert rpm["avg_value"] == 2000.0
    assert rpm["last_value"] == 3000.0
    assert rpm["sample_count"] == 3


def test_field_stats_excludes_bools(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "session-2026-05-07T10-21-55Z.jsonl"
    _write_jsonl(f, [_sample()])
    _, fields = _parse_jsonl_file(f, repo_dir)
    field_paths = [r["field_path"] for r in fields]
    assert "direct.mil_on" not in field_paths


def test_scan_finds_jsonl_files(repo_dir):
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    _write_jsonl(d / "s2.jsonl", [_sample()])
    files = scan_car_datalog(repo_dir)
    assert len(files) == 2


def test_scan_empty_dir(repo_dir):
    (repo_dir / CAR_DATALOG_SUBDIR).mkdir(parents=True)
    files = scan_car_datalog(repo_dir)
    assert files == []


def test_scan_missing_dir(repo_dir):
    files = scan_car_datalog(repo_dir)
    assert files == []


def test_sync_inserts_session(repo_dir):
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        synced, updated = sync_car_datalog(conn, repo_dir)
        assert synced == 1
        assert updated == 0
        cur = conn.execute("SELECT session_id FROM car_log_sessions")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "s1"
    finally:
        conn.close()


def test_sync_inserts_fields(repo_dir):
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT COUNT(*) FROM car_log_session_fields")
        assert cur.fetchone()[0] > 0
    finally:
        conn.close()


def test_sync_skips_unchanged(repo_dir):
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        s1, u1 = sync_car_datalog(conn, repo_dir)
        assert s1 == 1
        s2, u2 = sync_car_datalog(conn, repo_dir)
        assert s2 == 0
        assert u2 == 0
    finally:
        conn.close()


def test_sync_detects_change_by_size(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        sync_car_datalog(conn, repo_dir)
        _write_jsonl(f, [_sample(), _sample()])
        import time
        time.sleep(0.05)
        os.utime(f, (time.time(), time.time()))
        s, u = sync_car_datalog(conn, repo_dir)
        assert u == 1
    finally:
        conn.close()


def test_sync_removes_deleted_session(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        sync_car_datalog(conn, repo_dir)
        f.unlink()
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT COUNT(*) FROM car_log_sessions")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_sync_removes_orphaned_fields_on_update(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT COUNT(*) FROM car_log_session_fields")
        count_before = cur.fetchone()[0]
        assert count_before > 0
        sample_no_gps = _sample()
        del sample_no_gps["gps"]
        del sample_no_gps["direct"]
        _write_jsonl(f, [sample_no_gps])
        import time
        time.sleep(0.05)
        os.utime(f, (time.time(), time.time()))
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT field_path FROM car_log_session_fields")
        remaining = {r[0] for r in cur.fetchall()}
        assert "direct.rpm" not in remaining
        assert "gps.speed" not in remaining
    finally:
        conn.close()


def test_sync_cascade_deletes_fields(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT COUNT(*) FROM car_log_session_fields")
        assert cur.fetchone()[0] > 0
        f.unlink()
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT COUNT(*) FROM car_log_session_fields")
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_sync_multiple_sessions(repo_dir):
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    _write_jsonl(d / "s2.jsonl", [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        synced, _ = sync_car_datalog(conn, repo_dir)
        assert synced == 2
        cur = conn.execute("SELECT COUNT(*) FROM car_log_sessions")
        assert cur.fetchone()[0] == 2
    finally:
        conn.close()


def test_sync_handles_all_invalid_lines_file(repo_dir):
    d = _make_session_dir(repo_dir)
    good = d / "s1.jsonl"
    bad = d / "s2.jsonl"
    _write_jsonl(good, [_sample()])
    bad.write_text("not valid jsonl at all\nalso not json\n")
    conn = sqlite3.connect(DB_PATH)
    try:
        synced, _ = sync_car_datalog(conn, repo_dir)
        assert synced == 2
        cur = conn.execute(
            "SELECT sample_count FROM car_log_sessions WHERE session_id = ?", ("s2",)
        )
        assert cur.fetchone()[0] == 0
    finally:
        conn.close()


def test_sync_returns_tuple(repo_dir):
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        result = sync_car_datalog(conn, repo_dir)
        assert isinstance(result, tuple)
        assert len(result) == 2
    finally:
        conn.close()


def test_sync_preserves_session_when_reparse_fails(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT session_id FROM car_log_sessions WHERE session_id = ?", ("s1",))
        assert cur.fetchone() is not None
        f.write_text("CORRUPTED NON-JSON CONTENT !!!\n")
        import time
        time.sleep(0.05)
        os.utime(f, (time.time(), time.time()))
        sync_car_datalog(conn, repo_dir)
        cur = conn.execute("SELECT session_id FROM car_log_sessions WHERE session_id = ?", ("s1",))
        assert cur.fetchone() is not None
    finally:
        conn.close()


def test_sync_skips_unchanged_without_reparse(repo_dir):
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    conn = sqlite3.connect(DB_PATH)
    try:
        s1, u1 = sync_car_datalog(conn, repo_dir)
        assert s1 == 1
        assert u1 == 0
        s2, u2 = sync_car_datalog(conn, repo_dir)
        assert s2 == 0
        assert u2 == 0
        cur = conn.execute("SELECT updated_at FROM car_log_sessions WHERE session_id = ?", ("s1",))
        first_updated = cur.fetchone()[0]
        cur = conn.execute("SELECT updated_at FROM car_log_sessions WHERE session_id = ?", ("s1",))
        second_updated = cur.fetchone()[0]
        assert first_updated == second_updated
    finally:
        conn.close()
