import os
import sqlite3
import tempfile
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "test_picasso_car_logs_api.db")
os.environ["REPOSITORY_DIR"] = tempfile.mkdtemp()

from fastapi.testclient import TestClient

from backend.database import init_db, DB_PATH
from backend.config import REPOSITORY_DIR, CAR_DATALOG_SUBDIR


@pytest.fixture(autouse=True)
def fresh_db_and_repo():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    datalog_dir = os.path.join(REPOSITORY_DIR, CAR_DATALOG_SUBDIR)
    if os.path.exists(datalog_dir):
        shutil.rmtree(datalog_dir)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    datalog_dir = os.path.join(REPOSITORY_DIR, CAR_DATALOG_SUBDIR)
    if os.path.exists(datalog_dir):
        shutil.rmtree(datalog_dir)


def _make_session_dir(repo_dir, device="dev1", vin="VIN999"):
    d = Path(repo_dir) / CAR_DATALOG_SUBDIR / device / "2026" / "05" / "07" / vin
    d.mkdir(parents=True, exist_ok=True)
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
        "gps": {"connected": False, "speed": 0},
        "wifi": {"connected": True},
        "direct": {"rpm": 2000.0, "speed_kmh": 50, "coolant_temp_c": 80},
    }
    if overrides:
        base.update(overrides)
    base.update(kwargs)
    return base


def _sync(client):
    return client.post("/api/sync")


def _client():
    from backend.main import app
    return TestClient(app)


def test_list_sessions_empty():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_returns_sessions():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["session_id"] == "s1"


def test_list_sessions_filter_by_device():
    repo_dir = Path(REPOSITORY_DIR)
    d1 = _make_session_dir(repo_dir, device="device-a", vin="V1")
    d2 = _make_session_dir(repo_dir, device="device-b", vin="V1")
    _write_jsonl(d1 / "s1.jsonl", [_sample()])
    _write_jsonl(d2 / "s2.jsonl", [_sample(overrides={"device_name": "device-b"})])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"device": "device-a"})
    assert resp.status_code == 200
    data = resp.json()
    assert all(s["device_name"] == "device-a" for s in data)


def test_list_sessions_filter_by_device_partial_case_insensitive():
    repo_dir = Path(REPOSITORY_DIR)
    d1 = _make_session_dir(repo_dir, device="c3-picasso-2013", vin="V1")
    d2 = _make_session_dir(repo_dir, device="other-device", vin="V1")
    _write_jsonl(d1 / "s1.jsonl", [_sample()])
    _write_jsonl(d2 / "s2.jsonl", [_sample(overrides={"device_name": "other-device"})])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"device": "PICASSO"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["device_name"] == "c3-picasso-2013"


def test_list_sessions_filter_by_vin():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir, device="dev1", vin="VIN123")
    _write_jsonl(d / "s1.jsonl", [_sample(overrides={"vin": "VIN123"})])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"vin": "VIN123"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    resp2 = c.get("/api/car-logs/sessions", params={"vin": "NONEXISTENT"})
    assert len(resp2.json()) == 0


def test_list_sessions_filter_by_vin_partial_case_insensitive():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir, device="dev1", vin="VF7ABC123")
    _write_jsonl(d / "s1.jsonl", [_sample(overrides={"vin": "VF7ABC123"})])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"vin": "abc"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["vin"] == "VF7ABC123"


def test_list_sessions_filter_by_date_from():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"date_from": "2026-01-01"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    resp2 = c.get("/api/car-logs/sessions", params={"date_from": "2099-01-01"})
    assert len(resp2.json()) == 0


def test_list_sessions_filter_by_date_to():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"date_to": "2099-12-31"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    resp2 = c.get("/api/car-logs/sessions", params={"date_to": "2020-01-01"})
    assert len(resp2.json()) == 0


def test_list_sessions_filter_by_date_to_includes_whole_day():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"date_to": "2026-05-07"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_sessions_filter_by_has_gps():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    sample_no_gps = _sample()
    sample_no_gps["gps"]["connected"] = False
    sample_no_gps["time_context"]["gps_connected"] = False
    _write_jsonl(d / "s1.jsonl", [sample_no_gps])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"has_gps": True})
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_list_sessions_filter_by_has_wifi():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"has_wifi": True})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    resp2 = c.get("/api/car-logs/sessions", params={"has_wifi": False})
    assert len(resp2.json()) == 0


def test_list_sessions_filter_by_q():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir, device="c3-picasso-2013")
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"q": "picasso"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
    resp2 = c.get("/api/car-logs/sessions", params={"q": "nonexistent_xyz"})
    assert len(resp2.json()) == 0


def test_list_sessions_pagination():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    for i in range(5):
        _write_jsonl(d / f"s{i}.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions", params={"skip": 0, "limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    resp2 = c.get("/api/car-logs/sessions", params={"skip": 2, "limit": 2})
    assert len(resp2.json()) == 2


def test_list_sessions_sorted_by_started_at_desc():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    s1 = _sample()
    s1["logged_at"] = "2026-05-07T10:00:00.000000+00:00"
    s1["time_context"]["logged_at"] = s1["logged_at"]
    s1["time_context"]["sample_time"] = "2026-05-07T10:00:00.000000+00:00"
    s2 = _sample()
    s2["logged_at"] = "2026-05-07T12:00:00.000000+00:00"
    s2["time_context"]["logged_at"] = s2["logged_at"]
    s2["time_context"]["sample_time"] = "2026-05-07T12:00:00.000000+00:00"
    _write_jsonl(d / "s1.jsonl", [s1])
    _write_jsonl(d / "s2.jsonl", [s2])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions")
    data = resp.json()
    if len(data) >= 2:
        assert data[0]["started_at"] >= data[1]["started_at"]


def test_get_session_detail_includes_fields():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "s1"
    assert "fields" in data
    assert isinstance(data["fields"], list)
    field_paths = [f["field_path"] for f in data["fields"]]
    assert "direct.rpm" in field_paths


def test_get_session_detail_not_found():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/nonexistent")
    assert resp.status_code == 404


def test_delete_session_removes_file_and_database_record():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    c = _client()
    _sync(c)

    resp = c.delete("/api/car-logs/sessions/s1")
    assert resp.status_code == 204
    assert not f.exists()

    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT 1 FROM car_log_sessions WHERE session_id = ?",
            ("s1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is None


def test_delete_session_not_found():
    c = _client()
    _sync(c)
    resp = c.delete("/api/car-logs/sessions/nonexistent")
    assert resp.status_code == 404


def test_delete_session_rejects_path_traversal_without_removing_external_file():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    external_file = repo_dir.parent / "outside.jsonl"
    external_file.write_text("preserve me", encoding="utf-8")
    c = _client()
    _sync(c)

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE car_log_sessions SET relative_path = ? WHERE session_id = ?",
        (str(external_file), "s1"),
    )
    conn.commit()
    conn.close()

    resp = c.delete("/api/car-logs/sessions/s1")
    assert resp.status_code == 404
    assert external_file.read_text(encoding="utf-8") == "preserve me"


def test_download_raw_returns_jsonl():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/raw")
    assert resp.status_code == 200
    assert "application/x-jsonlines" in resp.headers.get("content-type", "")
    assert resp.headers.get("content-disposition", "").endswith('s1.jsonl"')
    content = resp.text
    parsed = json.loads(content.strip().split("\n")[0])
    assert "session_id" in parsed


def test_download_raw_not_found():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/nonexistent/raw")
    assert resp.status_code == 404


def test_download_raw_file_missing_on_disk():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    c = _client()
    _sync(c)
    f.unlink()
    resp = c.get("/api/car-logs/sessions/s1/raw")
    assert resp.status_code == 404


def test_download_raw_rejects_path_traversal():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE car_log_sessions SET relative_path = ? WHERE session_id = ?",
        ("../../etc/passwd", "s1"),
    )
    conn.commit()
    conn.close()
    resp = c.get("/api/car-logs/sessions/s1/raw")
    assert resp.status_code == 404


def test_download_csv_returns_flattened_csv():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [
        _sample(overrides={"direct": {"rpm": 1200.5, "speed_kmh": 12}}),
        _sample(overrides={"direct": {"rpm": 1800.0, "speed_kmh": 34}}),
    ])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    assert resp.headers.get("content-disposition", "").endswith('s1.csv"')

    lines = resp.text.splitlines()
    assert len(lines) == 3
    header = lines[0].split(",")
    assert "session_id" in header
    assert "direct.rpm" in header
    assert "direct.speed_kmh" in header
    assert "time_context.sample_time" in header
    assert "1200.5" in resp.text
    assert "1800.0" in resp.text


def test_download_csv_skips_invalid_json_lines():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    with open(f, "a") as fh:
        fh.write("{bad json\n")
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/csv")
    assert resp.status_code == 200
    assert len(resp.text.splitlines()) == 2


def test_download_csv_not_found():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/nonexistent/csv")
    assert resp.status_code == 404


def test_download_csv_file_missing_on_disk():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    c = _client()
    _sync(c)
    f.unlink()
    resp = c.get("/api/car-logs/sessions/s1/csv")
    assert resp.status_code == 404


def test_download_csv_rejects_path_traversal():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE car_log_sessions SET relative_path = ? WHERE session_id = ?",
        ("../../etc/passwd", "s1"),
    )
    conn.commit()
    conn.close()
    resp = c.get("/api/car-logs/sessions/s1/csv")
    assert resp.status_code == 404


# --- Series endpoint tests ---


def _make_series_samples(count, start_time="2026-05-07T10:21:55.000000+00:00", interval_s=1.0, overrides=None):
    from datetime import datetime, timezone, timedelta
    base_dt = datetime.fromisoformat(start_time)
    samples = []
    for i in range(count):
        ts = base_dt + timedelta(seconds=interval_s * i)
        ts_str = ts.isoformat()
        s = _sample(overrides={
            "logged_at": ts_str,
            "time_context": {
                "sample_time": ts_str,
                "logged_at": ts_str,
                "wifi_connected": i % 2 == 0,
                "gps_connected": False,
                "gps_has_fix": False,
            },
            "direct": {
                "rpm": 800.0 + i * 100,
                "speed_kmh": 0 + i * 5,
                "coolant_temp_c": 70 + i,
            },
        })
        samples.append(s)
    return samples


def test_series_endpoint_returns_data():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(5))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session" in data
    assert "time_axis" in data
    assert "series" in data
    assert data["time_axis"] == "relative_s"
    assert len(data["series"]) == 1
    assert data["series"][0]["field"] == "direct.rpm"
    assert len(data["series"][0]["points"]) == 5


def test_series_multiple_fields():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(5))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm,direct.speed_kmh"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 2
    fields = [s["field"] for s in data["series"]]
    assert "direct.rpm" in fields
    assert "direct.speed_kmh" in fields


def test_series_requires_fields_param():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series")
    assert resp.status_code == 422


def test_series_empty_fields_returns_400():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": " , , "})
    assert resp.status_code == 400


def test_series_invalid_time_axis_returns_400():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "time_axis": "invalid"})
    assert resp.status_code == 400


def test_series_session_not_found():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/nonexistent/series", params={"fields": "direct.rpm"})
    assert resp.status_code == 404


def test_series_relative_s_starts_at_zero():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(5, interval_s=1.0))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "time_axis": "relative_s"})
    assert resp.status_code == 200
    data = resp.json()
    points = data["series"][0]["points"]
    assert abs(points[0][0]) < 0.001


def test_series_relative_s_intervals():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(5, interval_s=2.0))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "time_axis": "relative_s"})
    assert resp.status_code == 200
    data = resp.json()
    points = data["series"][0]["points"]
    assert len(points) == 5
    assert abs(points[1][0] - 2.0) < 0.01
    assert abs(points[2][0] - 4.0) < 0.01


def test_series_relative_s_ignores_clock_jump_after_wifi():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = []
    for i, (ts, wifi, confidence) in enumerate([
        ("2026-05-07T10:00:00.000000+00:00", False, "offline_unverified"),
        ("2026-05-07T10:00:02.000000+00:00", False, "offline_unverified"),
        ("2026-05-07T12:00:04.000000+00:00", True, "network_likely"),
        ("2026-05-07T12:00:06.000000+00:00", True, "network_likely"),
    ]):
        samples.append(_sample(overrides={
            "logged_at": ts,
            "time_context": {
                "sample_time": ts,
                "logged_at": ts,
                "wifi_connected": wifi,
                "gps_connected": False,
                "gps_has_fix": False,
                "clock_confidence": confidence,
            },
            "wifi": {"connected": wifi},
            "direct": {
                "rpm": 1000.0 + i,
                "speed_kmh": i,
                "coolant_temp_c": 70 + i,
            },
        }))
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get(
        "/api/car-logs/sessions/s1/series",
        params={"fields": "direct.rpm", "time_axis": "relative_s"},
    )
    assert resp.status_code == 200
    points = resp.json()["series"][0]["points"]
    assert [p[0] for p in points] == [0.0, 2.0, 4.0, 6.0]


def test_series_sample_time_anchors_to_true_network_time_after_jump():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = []
    for i, (ts, wifi, confidence) in enumerate([
        ("2026-05-07T10:00:00.000000+00:00", False, "offline_unverified"),
        ("2026-05-07T10:00:02.000000+00:00", False, "offline_unverified"),
        ("2026-05-07T12:00:04.000000+00:00", True, "network_likely"),
    ]):
        samples.append(_sample(overrides={
            "logged_at": ts,
            "time_context": {
                "sample_time": ts,
                "logged_at": ts,
                "wifi_connected": wifi,
                "gps_connected": False,
                "gps_has_fix": False,
                "clock_confidence": confidence,
            },
            "wifi": {"connected": wifi},
            "direct": {
                "rpm": 1000.0 + i,
                "speed_kmh": i,
                "coolant_temp_c": 70 + i,
            },
        }))
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get(
        "/api/car-logs/sessions/s1/series",
        params={"fields": "direct.rpm", "time_axis": "sample_time"},
    )
    assert resp.status_code == 200
    points = resp.json()["series"][0]["points"]
    assert points[0][0] == points[2][0] - 4.0


def test_series_sample_time_is_unix_timestamp():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "time_axis": "sample_time"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["time_axis"] == "sample_time"
    points = data["series"][0]["points"]
    assert points[0][0] > 1e9


def test_series_logged_at_is_unix_timestamp():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "time_axis": "logged_at"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["time_axis"] == "logged_at"
    points = data["series"][0]["points"]
    assert points[0][0] > 1e9


def test_series_downsampling_respects_max_points():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(100, interval_s=1.0))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "max_points": 10})
    assert resp.status_code == 200
    data = resp.json()
    points = data["series"][0]["points"]
    assert len(points) <= 11


def test_series_downsampling_includes_first_and_last():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(50, interval_s=1.0))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "max_points": 10})
    assert resp.status_code == 200
    data = resp.json()
    points = data["series"][0]["points"]
    first_ts = points[0][0]
    last_ts = points[-1][0]
    assert first_ts < last_ts


def test_series_boolean_to_numeric():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = []
    for i in range(3):
        s = _sample(overrides={
            "logged_at": f"2026-05-07T10:21:5{i}:00.000000+00:00",
            "time_context": {
                "sample_time": f"2026-05-07T10:21:5{i}:00.000000+00:00",
                "logged_at": f"2026-05-07T10:21:5{i}:00.000000+00:00",
                "wifi_connected": i % 2 == 0,
                "gps_connected": False,
                "gps_has_fix": False,
            },
            "wifi": {"connected": i % 2 == 0},
        })
        samples.append(s)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "wifi.connected"})
    assert resp.status_code == 200
    data = resp.json()
    points = data["series"][0]["points"]
    values = [p[1] for p in points]
    assert all(v in (0.0, 1.0) for v in values)


def test_series_label_and_unit_mapping():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm,direct.speed_kmh,direct.coolant_temp_c"})
    assert resp.status_code == 200
    data = resp.json()
    series_map = {s["field"]: s for s in data["series"]}
    assert series_map["direct.rpm"]["label"] == "RPM"
    assert series_map["direct.rpm"]["unit"] == "rpm"
    assert series_map["direct.speed_kmh"]["label"] == "Speed"
    assert series_map["direct.speed_kmh"]["unit"] == "km/h"
    assert series_map["direct.coolant_temp_c"]["label"] == "Coolant Temp"
    assert series_map["direct.coolant_temp_c"]["unit"] == "\u00b0C"


def test_series_label_and_unit_fallback_for_unknown_field():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.some_random_field"})
    assert resp.status_code == 200
    data = resp.json()
    s = data["series"][0]
    assert s["label"] == "Some Random Field"


def test_series_response_matches_model():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session" in data
    assert "session_id" in data["session"]
    assert "started_at" in data["session"]
    assert "sample_count" in data["session"]
    assert data["time_axis"] == "relative_s"
    assert isinstance(data["series"], list)
    for s in data["series"]:
        assert "field" in s
        assert "label" in s
        assert "unit" in s
        assert "points" in s
        assert isinstance(s["points"], list)
        for p in s["points"]:
            assert isinstance(p, list)
            assert len(p) == 2
            assert isinstance(p[0], (int, float))
            assert isinstance(p[1], (int, float))


def test_series_points_are_floats():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm,direct.speed_kmh"})
    assert resp.status_code == 200
    data = resp.json()
    for s in data["series"]:
        for p in s["points"]:
            assert isinstance(p[0], float)
            assert isinstance(p[1], float)


def test_series_max_points_default_is_1000():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(50))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"][0]["points"]) == 50


def test_series_no_downsampling_when_under_max_points():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(10))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "max_points": 100})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"][0]["points"]) == 10


def test_series_missing_field_returns_empty_points():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.nonexistent_field"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 1
    assert data["series"][0]["field"] == "direct.nonexistent_field"
    assert data["series"][0]["points"] == []


def test_series_session_metadata_in_response():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm"})
    assert resp.status_code == 200
    data = resp.json()
    session = data["session"]
    assert session["session_id"] == "s1"
    assert session["sample_count"] == 3
    assert session["started_at"] is not None


def test_series_integer_values_converted_to_float():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.speed_kmh"})
    assert resp.status_code == 200
    data = resp.json()
    for p in data["series"][0]["points"]:
        assert isinstance(p[1], float)


def test_series_max_points_param_override():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(200, interval_s=1.0))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm", "max_points": 2000})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"][0]["points"]) == 200


def test_series_multiple_fields_different_sample_counts():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(5)
    for i in range(3, 5):
        if "gps" in samples[i]:
            del samples[i]["gps"]
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm,gps.speed"})
    assert resp.status_code == 200
    data = resp.json()
    fields_map = {s["field"]: s for s in data["series"]}
    assert "direct.rpm" in fields_map
    assert "gps.speed" in fields_map
    assert len(fields_map["direct.rpm"]["points"]) == 5
    assert len(fields_map["gps.speed"]["points"]) <= 3


def test_series_default_time_axis_is_relative_s():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", _make_series_samples(3))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/series", params={"fields": "direct.rpm"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["time_axis"] == "relative_s"


# --- Preview endpoint tests ---


def test_preview_returns_first_and_last_samples():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(10)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert "first_samples" in data
    assert "last_samples" in data
    assert len(data["first_samples"]) == 3
    assert len(data["last_samples"]) == 3


def test_preview_first_samples_contain_line_and_data():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["first_samples"]) == 1
    sample = data["first_samples"][0]
    assert "line" in sample
    assert "data" in sample
    assert sample["line"] == 1
    assert isinstance(sample["data"], dict)


def test_preview_sample_count_matches_valid_lines():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(7)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sample_count"] == 7
    assert data["total_lines"] == 7
    assert data["invalid_lines"] == 0


def test_preview_detects_invalid_lines():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    lines = [json.dumps(_sample()) for _ in range(5)]
    content = "\n".join(lines) + "\nBAD LINE\nANOTHER BAD\n"
    f = d / "s1.jsonl"
    with open(f, "w") as fh:
        fh.write(content)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sample_count"] == 5
    assert data["invalid_lines"] == 2
    warning_types = [w["warning_type"] for w in data["warnings"]]
    assert "invalid_lines" in warning_types


def test_preview_invalid_lines_warning_message():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    lines = [json.dumps(_sample()) for _ in range(3)]
    content = "\n".join(lines) + "\n{" + '"bad"'
    f = d / "s1.jsonl"
    with open(f, "w") as fh:
        fh.write(content)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["invalid_lines"] >= 1
    invalid_warnings = [w for w in data["warnings"] if w["warning_type"] == "invalid_lines"]
    assert len(invalid_warnings) == 1
    assert "1" in invalid_warnings[0]["message"] or str(data["invalid_lines"]) in invalid_warnings[0]["message"]


def test_preview_no_overlap_when_few_samples():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(6)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["first_samples"]) == 5
    assert len(data["last_samples"]) == 1
    first_lines = [s["line"] for s in data["first_samples"]]
    last_lines = [s["line"] for s in data["last_samples"]]
    assert set(first_lines).isdisjoint(set(last_lines))


def test_preview_no_last_samples_when_few():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(3)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["first_samples"]) == 3
    assert len(data["last_samples"]) == 0


def test_preview_n_param_default():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(20)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["first_samples"]) == 5
    assert len(data["last_samples"]) == 5


def test_preview_n_param_custom():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(30)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["first_samples"]) == 10
    assert len(data["last_samples"]) == 10


def test_preview_n_param_bounds():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/nonexistent/preview", params={"n": 0})
    assert resp.status_code == 422
    resp = c.get("/api/car-logs/sessions/nonexistent/preview", params={"n": 100})
    assert resp.status_code == 422


def test_preview_not_found():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/nonexistent/preview")
    assert resp.status_code == 404


def test_preview_file_changed_warning():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    c = _client()
    _sync(c)
    import time
    time.sleep(0.05)
    _write_jsonl(f, [_sample(), _sample()])
    os.utime(f, (time.time(), time.time()))
    time.sleep(0.05)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    warning_types = [w["warning_type"] for w in data["warnings"]]
    assert "file_changed" in warning_types


def test_preview_still_growing_warning_when_recent_mtime():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    f = d / "s1.jsonl"
    _write_jsonl(f, [_sample()])
    import time
    os.utime(f, (time.time(), time.time()))
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    warning_types = [w["warning_type"] for w in data["warnings"]]
    assert "still_growing" in warning_types


def test_preview_no_warnings_for_stable_file():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    samples = _make_series_samples(5)
    _write_jsonl(d / "s1.jsonl", samples)
    c = _client()
    _sync(c)
    import time
    old_mtime = time.time() - 600
    os.utime(d / "s1.jsonl", (old_mtime, old_mtime))
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    warning_types = [w["warning_type"] for w in data["warnings"]]
    assert "still_growing" not in warning_types
    assert "file_changed" not in warning_types


def test_preview_response_model_structure():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert "first_samples" in data
    assert "last_samples" in data
    assert "sample_count" in data
    assert "total_lines" in data
    assert "invalid_lines" in data
    assert "warnings" in data
    assert isinstance(data["warnings"], list)
    assert isinstance(data["sample_count"], int)
    assert isinstance(data["total_lines"], int)
    assert isinstance(data["invalid_lines"], int)


def test_preview_empty_lines_not_counted_as_invalid():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    lines = [json.dumps(_sample()) for _ in range(3)]
    content = "\n".join(lines) + "\n\n\n"
    f = d / "s1.jsonl"
    with open(f, "w") as fh:
        fh.write(content)
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/sessions/s1/preview", params={"n": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sample_count"] == 3
    assert data["invalid_lines"] == 0
    assert data["total_lines"] >= 3


# --- Stats endpoint tests (Commit 10) ---


def test_stats_endpoint_empty():
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sessions"] == 0
    assert data["total_space_bytes"] == 0
    assert data["last_sync_at"] is None


def test_stats_endpoint_returns_counts():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sessions"] == 1
    assert data["total_space_bytes"] > 0
    assert data["last_sync_at"] is not None


def test_stats_endpoint_multiple_sessions():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    for i in range(3):
        _write_jsonl(d / f"s{i}.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sessions"] == 3
    assert data["total_space_bytes"] > 0


def test_stats_endpoint_last_sync_updated():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    c = _client()
    _sync(c)
    resp1 = c.get("/api/car-logs/stats")
    assert resp1.status_code == 200
    first_sync = resp1.json()["last_sync_at"]
    assert first_sync is not None

    import time
    time.sleep(0.05)

    second_samples = [_sample(), _sample(overrides={"logged_at": "2026-05-07T10:22:56.883400+00:00"})]
    _write_jsonl(d / "s2.jsonl", second_samples)
    _sync(c)
    resp2 = c.get("/api/car-logs/stats")
    assert resp2.status_code == 200
    second_sync = resp2.json()["last_sync_at"]
    assert second_sync is not None
    assert second_sync >= first_sync


def test_stats_endpoint_space_sums_all_sessions():
    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    _write_jsonl(d / "s2.jsonl", [_sample(), _sample(overrides={"logged_at": "2026-05-07T10:22:56.883400+00:00"})])
    c = _client()
    _sync(c)
    resp = c.get("/api/car-logs/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_sessions"] == 2
    assert data["total_space_bytes"] > 0
    s1_size = (d / "s1.jsonl").stat().st_size
    s2_size = (d / "s2.jsonl").stat().st_size
    assert data["total_space_bytes"] == s1_size + s2_size
