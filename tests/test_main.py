import os
import sqlite3
import tempfile
import json
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), "test_picasso_main.db")
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
        import shutil
        shutil.rmtree(datalog_dir)
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    datalog_dir = os.path.join(REPOSITORY_DIR, CAR_DATALOG_SUBDIR)
    if os.path.exists(datalog_dir):
        import shutil
        shutil.rmtree(datalog_dir)


def _make_session_dir(repo_dir, device="dev1", vin="VIN999"):
    d = Path(repo_dir) / CAR_DATALOG_SUBDIR / device / "2026" / "05" / "07" / vin
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_jsonl(path, samples):
    with open(path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")


def _sample():
    return {
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


def test_sync_endpoint_includes_car_log_counts():
    from backend.main import app

    repo_dir = Path(REPOSITORY_DIR)
    d = _make_session_dir(repo_dir)
    _write_jsonl(d / "s1.jsonl", [_sample()])
    client = TestClient(app)
    resp = client.post("/api/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "synced_car_log_sessions" in data
    assert "updated_car_log_sessions" in data
    assert data["synced_car_log_sessions"] >= 1


def test_sync_endpoint_returns_zeros_when_car_datalog_empty():
    from backend.main import app

    client = TestClient(app)
    resp = client.post("/api/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced_car_log_sessions"] == 0
    assert data["updated_car_log_sessions"] == 0


def test_sync_endpoint_graceful_on_car_datalog_failure():
    from backend.main import app

    with patch("backend.carlog_scanner.sync_car_datalog", side_effect=RuntimeError("boom")):
        client = TestClient(app)
        resp = client.post("/api/sync")
        assert resp.status_code == 200
        data = resp.json()
        assert data["synced_car_log_sessions"] == 0
        assert data["updated_car_log_sessions"] == 0
        assert "synced_tracks" in data
        assert "synced_playlists" in data
