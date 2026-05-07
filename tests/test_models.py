import pytest
from backend.models import (
    CarLogSessionSummary,
    CarLogSessionDetail,
    CarLogFieldStats,
    CarLogSeries,
    CarLogSeriesResponse,
    Track,
    Playlist,
)


def test_car_log_session_summary_required_fields():
    s = CarLogSessionSummary(
        session_id="s1",
        device_name="dev",
        relative_path="p/s1.jsonl",
        file_size=100,
        sample_count=10,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    assert s.session_id == "s1"
    assert s.vin is None
    assert s.vehicle is None
    assert s.started_at is None
    assert s.duration_s is None
    assert s.wifi_seen is None
    assert s.gps_seen is None
    assert s.gps_fix_seen is None


def test_car_log_session_summary_full():
    s = CarLogSessionSummary(
        session_id="s1",
        device_name="c3-picasso-2013",
        vin="935F...",
        vehicle="Citroen C3 Picasso 2013",
        relative_path="Car_datalog/c3-picasso-2013/2026/05/07/935F/session-2026-05-07T02-35-29Z.jsonl",
        file_size=4096,
        sample_count=164,
        started_at="2026-05-07T02:35:29Z",
        ended_at="2026-05-07T02:38:13Z",
        duration_s=163.9,
        first_logged_at="2026-05-07T02:35:29.519474+00:00",
        last_logged_at="2026-05-07T02:38:13.510790+00:00",
        first_sample_time="2026-05-07T02:35:29.519474+00:00",
        last_sample_time="2026-05-07T02:38:13.510790+00:00",
        wifi_seen=True,
        gps_seen=False,
        gps_fix_seen=False,
        created_at="2026-05-07T03:00:00Z",
        updated_at="2026-05-07T03:00:00Z",
    )
    assert s.session_id == "s1"
    assert s.wifi_seen is True
    assert s.gps_seen is False
    assert s.duration_s == 163.9


def test_car_log_field_stats():
    f = CarLogFieldStats(
        field_path="direct.rpm",
        min_value=800.0,
        max_value=3000.0,
        avg_value=1500.0,
        last_value=900.0,
        sample_count=164,
    )
    assert f.field_path == "direct.rpm"
    assert f.min_value == 800.0
    assert f.max_value == 3000.0


def test_car_log_field_stats_optional():
    f = CarLogFieldStats(field_path="direct.rpm")
    assert f.min_value is None
    assert f.max_value is None
    assert f.avg_value is None
    assert f.last_value is None
    assert f.sample_count is None


def test_car_log_session_detail_inherits_summary():
    d = CarLogSessionDetail(
        session_id="s1",
        device_name="dev",
        relative_path="p/s1.jsonl",
        file_size=100,
        sample_count=10,
        created_at="2026-01-01",
        updated_at="2026-01-01",
        fields=[
            CarLogFieldStats(field_path="direct.rpm", min_value=800, max_value=3000),
            CarLogFieldStats(field_path="direct.speed_kmh", min_value=0, max_value=120),
        ],
    )
    assert d.session_id == "s1"
    assert len(d.fields) == 2
    assert d.fields[0].field_path == "direct.rpm"


def test_car_log_session_detail_empty_fields():
    d = CarLogSessionDetail(
        session_id="s1",
        device_name="dev",
        relative_path="p/s1.jsonl",
        file_size=100,
        sample_count=10,
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )
    assert d.fields == []


def test_car_log_series():
    s = CarLogSeries(
        field="direct.rpm",
        label="RPM",
        unit="rpm",
        points=[[0.0, 850], [1.0, 900], [2.0, 1200]],
    )
    assert s.field == "direct.rpm"
    assert len(s.points) == 3
    assert s.points[0] == [0.0, 850]


def test_car_log_series_no_unit():
    s = CarLogSeries(field="direct.rpm", label="RPM")
    assert s.unit is None
    assert s.points == []


def test_car_log_series_response():
    session = CarLogSessionSummary(
        session_id="s1",
        device_name="dev",
        relative_path="p/s1.jsonl",
        file_size=100,
        sample_count=10,
        created_at="2026-01-01",
        updated_at="2026-01-01",
    )
    resp = CarLogSeriesResponse(
        session=session,
        time_axis="relative_s",
        series=[
            CarLogSeries(field="direct.rpm", label="RPM", unit="rpm", points=[[0, 850]]),
        ],
    )
    assert resp.session.session_id == "s1"
    assert resp.time_axis == "relative_s"
    assert len(resp.series) == 1


def test_track_model_unaffected():
    t = Track(path="test.mp3", title="Song", artist="Artist")
    assert t.path == "test.mp3"
    assert t.title == "Song"
    assert t.has_cover is False


def test_playlist_model_unaffected():
    p = Playlist(path="test.m3u8", name="My Playlist")
    assert p.path == "test.m3u8"
    assert p.track_count == 0
