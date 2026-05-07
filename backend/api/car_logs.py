import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from backend.config import REPOSITORY_DIR, DB_PATH
from backend.models import CarLogSessionSummary, CarLogSessionDetail, CarLogFieldStats

router = APIRouter()


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
            conditions.append("device_name = ?")
            params.append(device)

        if vin:
            conditions.append("vin = ?")
            params.append(vin)

        if date_from:
            conditions.append("started_at >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("started_at <= ?")
            params.append(date_to)

        if has_gps is not None:
            conditions.append("gps_seen = ?")
            params.append(1 if has_gps else 0)

        if has_wifi is not None:
            conditions.append("wifi_seen = ?")
            params.append(1 if has_wifi else 0)

        if q:
            pattern = f"%{q}%"
            conditions.append(
                "(session_id LIKE ? OR device_name LIKE ? OR vin LIKE ? OR vehicle LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cur = conn.execute(
            f"""
            SELECT * FROM car_log_sessions
            {where}
            ORDER BY started_at DESC
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


@router.get("/car-logs/sessions/{session_id}/raw")
async def download_session_raw(session_id: str):
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

    full_path = Path(REPOSITORY_DIR) / row["relative_path"]
    try:
        if not full_path.resolve().is_relative_to(Path(REPOSITORY_DIR).resolve()):
            raise HTTPException(status_code=404, detail="Invalid path")
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Raw file not found on disk")

    filename = f"{session_id}.jsonl"
    return FileResponse(
        path=str(full_path),
        media_type="application/x-jsonlines",
        filename=filename,
    )
