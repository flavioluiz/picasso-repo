import csv
import io
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from backend.carlog_scanner import _correct_clock_timeline, _flatten, _is_numeric, _parse_timestamp
from backend.config import REPOSITORY_DIR, DB_PATH
from backend.models import (
    CarLogSessionSummary,
    CarLogSessionDetail,
    CarLogFieldStats,
    CarLogSeries,
    CarLogSeriesResponse,
    CarLogPreviewWarning,
    CarLogPreviewResponse,
    CarLogStats,
)

router = APIRouter()


def _row_get(row: sqlite3.Row, key: str, default=None):
    return row[key] if key in row.keys() else default


def _row_to_session_summary(row: sqlite3.Row) -> CarLogSessionSummary:
    return CarLogSessionSummary(
        session_id=row["session_id"],
        device_name=row["device_name"],
        vin=row["vin"],
        vehicle=row["vehicle"],
        relative_path=row["relative_path"],
        file_size=row["file_size"],
        sample_count=row["sample_count"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        duration_s=row["duration_s"],
        first_logged_at=row["first_logged_at"],
        last_logged_at=row["last_logged_at"],
        first_sample_time=row["first_sample_time"],
        last_sample_time=row["last_sample_time"],
        wifi_seen=bool(row["wifi_seen"]) if row["wifi_seen"] is not None else None,
        gps_seen=bool(row["gps_seen"]) if row["gps_seen"] is not None else None,
        gps_fix_seen=bool(row["gps_fix_seen"]) if row["gps_fix_seen"] is not None else None,
        total_distance_km=_row_get(row, "total_distance_km"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_field_stats(row: sqlite3.Row) -> CarLogFieldStats:
    return CarLogFieldStats(
        field_path=row["field_path"],
        min_value=row["min_value"],
        max_value=row["max_value"],
        avg_value=row["avg_value"],
        last_value=row["last_value"],
        sample_count=row["sample_count"],
    )


def _session_file_path(session_id: str) -> Path:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT relative_path FROM car_log_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
    finally:
        conn.close()

    repo_root = Path(REPOSITORY_DIR).resolve()
    full_path = (Path(REPOSITORY_DIR) / row["relative_path"]).resolve()
    try:
        if not full_path.is_relative_to(repo_root):
            raise HTTPException(status_code=404, detail="Invalid path")
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found on disk")
    if not full_path.is_file():
        raise HTTPException(status_code=400, detail="Session path is not a file")
    return full_path


def _csv_cell(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@router.get("/car-logs/stats", response_model=CarLogStats)
async def get_car_log_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(file_size), 0) AS total_size FROM car_log_sessions")
        row = cur.fetchone()
        total_sessions = row["cnt"]
        total_space_bytes = row["total_size"]
        cur = conn.execute("SELECT MAX(updated_at) AS last_sync FROM car_log_sessions")
        row2 = cur.fetchone()
        last_sync_at = row2["last_sync"]
        return CarLogStats(
            total_sessions=total_sessions,
            total_space_bytes=total_space_bytes,
            last_sync_at=last_sync_at,
        )
    finally:
        conn.close()


@router.get("/car-logs/sessions", response_model=list[CarLogSessionSummary])
async def list_sessions(
    device: Optional[str] = Query(None),
    vin: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    has_gps: Optional[bool] = Query(None),
    has_wifi: Optional[bool] = Query(None),
    q: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        conditions = []
        params = []

        if device:
            conditions.append("LOWER(s.device_name) LIKE LOWER(?)")
            params.append(f"%{device}%")

        if vin:
            conditions.append("LOWER(s.vin) LIKE LOWER(?)")
            params.append(f"%{vin}%")

        if date_from:
            conditions.append("s.started_at >= ?")
            params.append(date_from if "T" in date_from else f"{date_from}T00:00:00")

        if date_to:
            conditions.append("s.started_at <= ?")
            params.append(date_to if "T" in date_to else f"{date_to}T23:59:59")

        if has_gps is not None:
            conditions.append("s.gps_seen = ?")
            params.append(1 if has_gps else 0)

        if has_wifi is not None:
            conditions.append("s.wifi_seen = ?")
            params.append(1 if has_wifi else 0)

        if q:
            pattern = f"%{q}%"
            conditions.append(
                "(s.session_id LIKE ? OR s.device_name LIKE ? OR s.vin LIKE ? OR s.vehicle LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cur = conn.execute(
            f"""
            SELECT
                s.*,
                COALESCE(distance.last_value, distance.max_value) AS total_distance_km
            FROM car_log_sessions s
            LEFT JOIN car_log_session_fields distance
                ON distance.session_id = s.session_id
                AND distance.field_path = 'inferred.trip_distance_km'
            {where}
            ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, skip),
        )
        rows = cur.fetchall()
        return [_row_to_session_summary(r) for r in rows]
    finally:
        conn.close()


@router.get("/car-logs/sessions/{session_id}", response_model=CarLogSessionDetail)
async def get_session(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM car_log_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")

        summary = _row_to_session_summary(row)

        cur = conn.execute(
            "SELECT * FROM car_log_session_fields WHERE session_id = ? ORDER BY field_path",
            (session_id,),
        )
        field_rows = cur.fetchall()
        fields = [_row_to_field_stats(r) for r in field_rows]

        return CarLogSessionDetail(**summary.model_dump(), fields=fields)
    finally:
        conn.close()


@router.delete("/car-logs/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT relative_path FROM car_log_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")

        repo_root = Path(REPOSITORY_DIR).resolve()
        full_path = (Path(REPOSITORY_DIR) / row["relative_path"]).resolve()
        try:
            if not full_path.is_relative_to(repo_root):
                raise HTTPException(status_code=404, detail="Invalid path")
        except ValueError:
            raise HTTPException(status_code=404, detail="Invalid path")

        if full_path.exists():
            if not full_path.is_file():
                raise HTTPException(status_code=400, detail="Session path is not a file")
            full_path.unlink()

        conn.execute("DELETE FROM car_log_sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        return None
    finally:
        conn.close()


FIELD_LABELS: dict[str, tuple[str, str | None]] = {
    "direct.rpm": ("RPM", "rpm"),
    "direct.speed_kmh": ("Speed", "km/h"),
    "direct.coolant_temp_c": ("Coolant Temp", "°C"),
    "direct.intake_temp_c": ("Intake Temp", "°C"),
    "direct.engine_load_pct": ("Engine Load", "%"),
    "direct.throttle_pct": ("Throttle", "%"),
    "direct.timing_advance_deg": ("Timing Advance", "°"),
    "direct.short_fuel_trim_b1_pct": ("Short Fuel Trim B1", "%"),
    "direct.long_fuel_trim_b1_pct": ("Long Fuel Trim B1", "%"),
    "direct.o2_b1s1_voltage_v": ("O2 B1S1", "V"),
    "direct.o2_b1s2_voltage_v": ("O2 B1S2", "V"),
    "direct.fuel_level_pct": ("Fuel Level", "%"),
    "inferred.instant_km_l": ("Instant Consumption", "km/L"),
    "inferred.selected_fuel_rate_l_h": ("Fuel Rate", "L/h"),
    "inferred.trip_average_km_l": ("Trip Average", "km/L"),
    "gps.speed": ("GPS Speed", "km/h"),
    "gps.latitude": ("Latitude", "°"),
    "gps.longitude": ("Longitude", "°"),
    "gps.altitude_m": ("Altitude", "m"),
    "wifi.connected": ("Wi-Fi", None),
    "time_context.wifi_connected": ("Wi-Fi", None),
    "time_context.gps_connected": ("GPS Connected", None),
    "time_context.gps_has_fix": ("GPS Fix", None),
}

_UNIT_SUFFIXES: list[tuple[str, str]] = [
    ("_km_l", "km/L"),
    ("_kmh", "km/h"),
    ("_l_h", "L/h"),
    ("_temp_c", "°C"),
    ("_c", "°C"),
    ("_voltage_v", "V"),
    ("_v", "V"),
    ("_pct", "%"),
    ("_deg", "°"),
    ("_m", "m"),
]


def _get_label_and_unit(field_path: str) -> tuple[str, str | None]:
    if field_path in FIELD_LABELS:
        return FIELD_LABELS[field_path]
    label = field_path.split(".")[-1].replace("_", " ").title()
    unit = None
    for suffix, unit_str in _UNIT_SUFFIXES:
        if field_path.endswith(suffix):
            unit = unit_str
            break
    return label, unit


@router.get("/car-logs/sessions/{session_id}/series", response_model=CarLogSeriesResponse)
async def get_session_series(
    session_id: str,
    fields: str = Query(..., description="Comma-separated field paths"),
    time_axis: str = Query("relative_s", description="sample_time, logged_at, or relative_s"),
    max_points: int = Query(1000, ge=1, le=10000),
):
    if time_axis not in ("relative_s", "sample_time", "logged_at"):
        raise HTTPException(
            status_code=400,
            detail="time_axis must be one of: relative_s, sample_time, logged_at",
        )

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM car_log_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        summary = _row_to_session_summary(row)
        relative_path = row["relative_path"]
    finally:
        conn.close()

    full_path = Path(REPOSITORY_DIR) / relative_path
    try:
        if not full_path.resolve().is_relative_to(Path(REPOSITORY_DIR).resolve()):
            raise HTTPException(status_code=404, detail="Invalid path")
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found on disk")

    requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
    if not requested_fields:
        raise HTTPException(status_code=400, detail="At least one field is required")

    raw_samples: list[dict] = []

    with open(full_path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            flat = _flatten(obj)

            if time_axis == "sample_time":
                ts_str = (
                    flat.get("time_context.sample_time")
                    or flat.get("sample_time")
                )
            elif time_axis == "logged_at":
                ts_str = (
                    flat.get("time_context.logged_at")
                    or flat.get("logged_at")
                )
            else:
                ts_str = (
                    flat.get("time_context.sample_time")
                    or flat.get("sample_time")
                    or flat.get("time_context.logged_at")
                    or flat.get("logged_at")
                )

            if ts_str is None:
                continue

            ts = _parse_timestamp(ts_str)
            if ts is None:
                continue

            field_vals: dict[str, float | None] = {}
            for field in requested_fields:
                val = flat.get(field)
                if val is not None:
                    if isinstance(val, bool):
                        val = 1.0 if val else 0.0
                    elif _is_numeric(val):
                        val = float(val)
                    else:
                        val = None
                field_vals[field] = val

            raw_samples.append({
                "timestamp": ts_str,
                "raw_ts": ts,
                "field_vals": field_vals,
                "wifi_connected": (
                    flat.get("wifi.connected")
                    or flat.get("time_context.wifi_connected")
                ),
                "gps_has_fix": (
                    flat.get("time_context.gps_has_fix")
                    or flat.get("gps.fix")
                ),
                "clock_confidence": flat.get("time_context.clock_confidence"),
            })

    corrected_times = _correct_clock_timeline(raw_samples)
    samples: list[tuple[float, dict[str, float | None]]] = []
    ref_time: float | None = None
    for i, sample in enumerate(raw_samples):
        ts = corrected_times[i] if i < len(corrected_times) else sample["raw_ts"]
        if ts is None:
            continue
        if time_axis == "relative_s":
            if ref_time is None:
                ref_time = ts
            ts = ts - ref_time
        samples.append((ts, sample["field_vals"]))

    n = len(samples)
    if n == 0:
        series_list = []
        for field in requested_fields:
            label, unit = _get_label_and_unit(field)
            series_list.append(CarLogSeries(field=field, label=label, unit=unit, points=[]))
        return CarLogSeriesResponse(session=summary, time_axis=time_axis, series=series_list)

    if n > max_points:
        stride = max(1, n // max_points)
        indices = list(range(0, n, stride))
        if indices[-1] != n - 1:
            indices.append(n - 1)
    else:
        indices = list(range(n))

    series_list = []
    for field in requested_fields:
        label, unit = _get_label_and_unit(field)
        points: list[list[float]] = []
        for i in indices:
            ts, field_vals = samples[i]
            v = field_vals.get(field)
            if v is not None:
                points.append([ts, v])
        series_list.append(CarLogSeries(field=field, label=label, unit=unit, points=points))

    return CarLogSeriesResponse(session=summary, time_axis=time_axis, series=series_list)


@router.get("/car-logs/sessions/{session_id}/preview", response_model=CarLogPreviewResponse)
async def get_session_preview(
    session_id: str,
    n: int = Query(5, ge=1, le=50),
):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT * FROM car_log_sessions WHERE session_id = ?",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")
        relative_path = row["relative_path"]
        stored_file_size = row["file_size"]
        stored_scan_mtime = row["scan_mtime"]
    finally:
        conn.close()

    full_path = Path(REPOSITORY_DIR) / relative_path
    try:
        if not full_path.resolve().is_relative_to(Path(REPOSITORY_DIR).resolve()):
            raise HTTPException(status_code=404, detail="Invalid path")
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found on disk")

    all_parsed: list[tuple[int, dict]] = []
    total_lines = 0
    invalid_lines = 0

    with open(full_path, "r", encoding="utf-8") as fh:
        for line in fh:
            total_lines += 1
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                all_parsed.append((total_lines, obj))
            except json.JSONDecodeError:
                invalid_lines += 1

    sample_count = len(all_parsed)
    first_samples = [{"line": ln, "data": d} for ln, d in all_parsed[:n]]
    if sample_count > 2 * n:
        last_samples = [{"line": ln, "data": d} for ln, d in all_parsed[-n:]]
    elif sample_count > n:
        last_samples = [{"line": ln, "data": d} for ln, d in all_parsed[n:]]
    else:
        last_samples = []

    warnings: list[CarLogPreviewWarning] = []

    current_stat = full_path.stat()
    if current_stat.st_size != stored_file_size or current_stat.st_mtime != stored_scan_mtime:
        warnings.append(CarLogPreviewWarning(
            warning_type="file_changed",
            message=(
                f"File has changed since last scan "
                f"(stored: {stored_file_size} bytes, current: {current_stat.st_size} bytes)"
            ),
        ))

    if invalid_lines > 0:
        warnings.append(CarLogPreviewWarning(
            warning_type="invalid_lines",
            message=f"{invalid_lines} invalid line(s) were ignored during parsing",
        ))

    if current_stat.st_mtime > time.time() - 300:
        warnings.append(CarLogPreviewWarning(
            warning_type="still_growing",
            message="File was recently modified and may still be growing",
        ))

    return CarLogPreviewResponse(
        first_samples=first_samples,
        last_samples=last_samples,
        sample_count=sample_count,
        total_lines=total_lines,
        invalid_lines=invalid_lines,
        warnings=warnings,
    )


@router.get("/car-logs/sessions/{session_id}/raw")
async def download_session_raw(session_id: str):
    full_path = _session_file_path(session_id)

    filename = f"{session_id}.jsonl"
    return FileResponse(
        path=str(full_path),
        media_type="application/x-jsonlines",
        filename=filename,
    )


@router.get("/car-logs/sessions/{session_id}/csv")
async def download_session_csv(session_id: str):
    full_path = _session_file_path(session_id)

    rows: list[dict] = []
    fieldnames: list[str] = []
    seen_fields: set[str] = set()

    with open(full_path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            flat = {key: _csv_cell(value) for key, value in _flatten(obj).items()}
            for key in flat.keys():
                if key not in seen_fields:
                    seen_fields.add(key)
                    fieldnames.append(key)
            rows.append(flat)

    preferred_first = [
        "logged_at",
        "time_context.logged_at",
        "time_context.sample_time",
        "session_id",
        "device_name",
        "vehicle",
        "vin",
    ]
    ordered_fields = [f for f in preferred_first if f in seen_fields]
    ordered_fields.extend(f for f in fieldnames if f not in ordered_fields)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=ordered_fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    filename = f"{session_id}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
