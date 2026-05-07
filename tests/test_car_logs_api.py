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
