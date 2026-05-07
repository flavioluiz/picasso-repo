import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from backend.config import REPOSITORY_DIR, CAR_DATALOG_SUBDIR

logger = logging.getLogger(__name__)


def _flatten(obj: Any, prefix: str = "") -> Dict[str, Any]:
    result = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_key = f"{prefix}.{key}" if prefix else key
            result.update(_flatten(value, new_key))
    else:
        result[prefix] = obj
    return result


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_jsonl_file(file_path: Path, repo_dir: Path) -> Tuple[dict, list[dict]]:
    stat = file_path.stat()
    file_size = stat.st_size
    mtime = stat.st_mtime

    rel_path = str(file_path.relative_to(repo_dir))
    parts = file_path.relative_to(repo_dir / CAR_DATALOG_SUBDIR).parts
    device_name = parts[0] if len(parts) > 0 else ""
    path_vin = parts[4] if len(parts) > 4 else None
    session_id = file_path.stem

    field_stats: Dict[str, dict] = {}
    first_logged_at = None
    last_logged_at = None
    first_sample_time = None
    last_sample_time = None
    wifi_seen = False
    gps_seen = False
    gps_fix_seen = False
    sample_count = 0
    data_vehicle = None
    data_vin = None

    with open(file_path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            sample_count += 1
            flat = _flatten(obj)

            if data_vehicle is None:
                data_vehicle = flat.get("vehicle")
            if data_vin is None:
                data_vin = flat.get("vin")

            logged_at = flat.get("time_context.logged_at") or flat.get("logged_at")
            sample_time = flat.get("time_context.sample_time") or flat.get("sample_time")

            if logged_at is not None:
                if first_logged_at is None:
                    first_logged_at = str(logged_at)
                last_logged_at = str(logged_at)

            if sample_time is not None:
                if first_sample_time is None:
                    first_sample_time = str(sample_time)
                last_sample_time = str(sample_time)

            gps_connected = flat.get("gps.connected") or flat.get("time_context.gps_connected")
            if gps_connected:
                gps_seen = True

            gps_fix_val = (
                flat.get("time_context.gps_has_fix")
                or flat.get("gps.fix")
            )
            if gps_fix_val:
                gps_fix_seen = True

            wifi_conn = (
                flat.get("wifi.connected")
                or flat.get("time_context.wifi_connected")
            )
            if wifi_conn:
                wifi_seen = True

            for key, value in flat.items():
                if _is_numeric(value):
                    if key not in field_stats:
                        field_stats[key] = {
                            "min": value,
                            "max": value,
                            "sum": float(value),
                            "last": value,
                            "count": 1,
                        }
                    else:
                        fs = field_stats[key]
                        fs["min"] = min(fs["min"], value)
                        fs["max"] = max(fs["max"], value)
                        fs["sum"] += float(value)
                        fs["last"] = value
                        fs["count"] += 1

    vehicle = data_vehicle or device_name
    vin = data_vin or path_vin

    started_at = first_logged_at or first_sample_time
    ended_at = last_logged_at or last_sample_time
    duration_s = None
    if started_at and ended_at:
        try:
            t1 = datetime.fromisoformat(started_at)
            t2 = datetime.fromisoformat(ended_at)
            duration_s = (t2 - t1).total_seconds()
        except (ValueError, TypeError):
            pass

    now = datetime.now(timezone.utc).isoformat()

    session = {
        "session_id": session_id,
        "device_name": device_name,
        "vin": vin,
        "vehicle": vehicle,
        "relative_path": rel_path,
        "file_size": file_size,
        "sample_count": sample_count,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_s": duration_s,
        "first_logged_at": first_logged_at,
        "last_logged_at": last_logged_at,
        "first_sample_time": first_sample_time,
        "last_sample_time": last_sample_time,
        "wifi_seen": wifi_seen,
        "gps_seen": gps_seen,
        "gps_fix_seen": gps_fix_seen,
        "scan_mtime": mtime,
        "created_at": now,
        "updated_at": now,
    }

    field_records: List[dict] = []
    for field_path, stats in field_stats.items():
        field_records.append({
            "session_id": session_id,
            "field_path": field_path,
            "min_value": stats["min"],
            "max_value": stats["max"],
            "avg_value": stats["sum"] / stats["count"] if stats["count"] > 0 else None,
            "last_value": stats["last"],
            "sample_count": stats["count"],
        })

    return session, field_records


def scan_car_datalog(repo_dir: Path) -> list[Path]:
    datalog_dir = repo_dir / CAR_DATALOG_SUBDIR
    if not datalog_dir.exists():
        return []
    return sorted(datalog_dir.rglob("*.jsonl"))


def sync_car_datalog(db: sqlite3.Connection, repo_dir: Path) -> Tuple[int, int]:
    db.execute("PRAGMA foreign_keys = ON")

    jsonl_files = scan_car_datalog(repo_dir)
    synced = 0
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    disk_session_ids: set[str] = set()

    for file_path in jsonl_files:
        session_id = file_path.stem
        disk_session_ids.add(session_id)

        try:
            stat = file_path.stat()
        except OSError:
            logger.warning("Failed to stat car datalog file: %s", file_path, exc_info=True)
            continue

        cur = db.execute(
            "SELECT file_size, scan_mtime FROM car_log_sessions "
            "WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()

        if row is not None and row[0] == stat.st_size and row[1] == stat.st_mtime:
            continue

        try:
            session, field_records = _parse_jsonl_file(file_path, repo_dir)
        except Exception:
            logger.warning("Failed to parse car datalog file: %s", file_path, exc_info=True)
            continue

        if row is None:
            db.execute(
                """INSERT INTO car_log_sessions (
                    session_id, device_name, vin, vehicle, relative_path,
                    file_size, sample_count, started_at, ended_at, duration_s,
                    first_logged_at, last_logged_at, first_sample_time,
                    last_sample_time, wifi_seen, gps_seen, gps_fix_seen,
                    created_at, updated_at, scan_mtime
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session["session_id"],
                    session["device_name"],
                    session["vin"],
                    session["vehicle"],
                    session["relative_path"],
                    session["file_size"],
                    session["sample_count"],
                    session["started_at"],
                    session["ended_at"],
                    session["duration_s"],
                    session["first_logged_at"],
                    session["last_logged_at"],
                    session["first_sample_time"],
                    session["last_sample_time"],
                    session["wifi_seen"],
                    session["gps_seen"],
                    session["gps_fix_seen"],
                    session["created_at"],
                    session["updated_at"],
                    session["scan_mtime"],
                ),
            )
            synced += 1
        else:
            db.execute(
                """UPDATE car_log_sessions SET
                    device_name=?, vin=?, vehicle=?, relative_path=?,
                    file_size=?, sample_count=?, started_at=?, ended_at=?,
                    duration_s=?, first_logged_at=?, last_logged_at=?,
                    first_sample_time=?, last_sample_time=?,
                    wifi_seen=?, gps_seen=?, gps_fix_seen=?,
                    updated_at=?, scan_mtime=?
                WHERE session_id=?""",
                (
                    session["device_name"],
                    session["vin"],
                    session["vehicle"],
                    session["relative_path"],
                    session["file_size"],
                    session["sample_count"],
                    session["started_at"],
                    session["ended_at"],
                    session["duration_s"],
                    session["first_logged_at"],
                    session["last_logged_at"],
                    session["first_sample_time"],
                    session["last_sample_time"],
                    session["wifi_seen"],
                    session["gps_seen"],
                    session["gps_fix_seen"],
                    now,
                    session["scan_mtime"],
                    session["session_id"],
                ),
            )
            db.execute(
                "DELETE FROM car_log_session_fields WHERE session_id = ?",
                (session["session_id"],),
            )
            updated += 1

        for field in field_records:
            db.execute(
                """INSERT INTO car_log_session_fields (
                    session_id, field_path, min_value, max_value,
                    avg_value, last_value, sample_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, field_path) DO UPDATE SET
                    min_value=excluded.min_value,
                    max_value=excluded.max_value,
                    avg_value=excluded.avg_value,
                    last_value=excluded.last_value,
                    sample_count=excluded.sample_count""",
                (
                    field["session_id"],
                    field["field_path"],
                    field["min_value"],
                    field["max_value"],
                    field["avg_value"],
                    field["last_value"],
                    field["sample_count"],
                ),
            )

    if disk_session_ids:
        placeholders = ", ".join("?" for _ in disk_session_ids)
        db.execute(
            f"DELETE FROM car_log_sessions WHERE session_id NOT IN ({placeholders})",
            list(disk_session_ids),
        )
    else:
        db.execute("DELETE FROM car_log_sessions")

    db.commit()
    return synced, updated
