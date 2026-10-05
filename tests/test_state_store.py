"""tests ของ utils/state_store.py — SQLite จริงใน tmp_path, wall clock ปลอม"""

import sqlite3
from datetime import datetime, timezone

import pytest

from utils.state_store import (
    R_ENQUEUED, R_EXPIRED, R_PENDING, R_UNKNOWN, StateStore, StateStoreError,
)


class FakeWall:
    def __init__(self, iso_utc):
        self.t = datetime.fromisoformat(iso_utc).replace(tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


@pytest.fixture
def wall():
    # 05/10/2026 13:45:12 เวลาไทย = 06:45:12 UTC
    return FakeWall("2026-10-05T06:45:12")


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "data" / "vending_state.sqlite3")


def make(db_path, wall):
    return StateStore(db_path, "VENDING_01", "Asia/Bangkok", clock=wall)


def confirm_new(store, cid, path="img.jpg"):
    store.open_cycle(cid)
    return store.confirm(cid, path)


def test_three_confirmations_same_day_then_restart_continues(db_path, wall):
    store = make(db_path, wall)
    seqs = []
    for i in range(3):
        c = confirm_new(store, f"c{i}")
        seqs.append(c.daily_sequence)
        wall.advance(60)
    assert seqs == [1, 2, 3]
    assert store.count_today() == 3
    store.close()

    # restart วันเดิม → นับต่อ
    store = make(db_path, wall)
    assert store.count_today() == 3
    assert confirm_new(store, "c3").daily_sequence == 4


def test_thai_midnight_rollover_starts_at_one(db_path, wall):
    wall.t = FakeWall("2026-10-05T16:59:59")()  # 23:59:59 ไทย
    store = make(db_path, wall)
    a = confirm_new(store, "a")
    assert (a.local_date, a.daily_sequence) == ("2026-10-05", 1)
    wall.advance(2)  # 00:00:01 ไทย วันใหม่ (UTC ยังเป็นวันที่ 5)
    b = confirm_new(store, "b")
    assert (b.local_date, b.daily_sequence) == ("2026-10-06", 1)
    assert b.confirmed_at.strftime("%d/%m/%Y %H:%M:%S") == "06/10/2026 00:00:01"
    # ประวัติวันก่อนยังอยู่
    assert store.count_for_date("2026-10-05") == 1


def test_day_is_fixed_at_confirmation_time(db_path, wall):
    # START ก่อนเที่ยงคืน แต่ยืนยันหลังเที่ยงคืน → วันใหม่
    wall.t = FakeWall("2026-10-05T16:59:00")()
    store = make(db_path, wall)
    store.open_cycle("x")
    wall.advance(120)
    assert store.confirm("x", "p").local_date == "2026-10-06"


def test_confirmed_at_local_format(db_path, wall):
    c = confirm_new(make(db_path, wall), "c1")
    assert c.confirmed_at.strftime("%d/%m/%Y %H:%M:%S") == "05/10/2026 13:45:12"


def test_same_cycle_cannot_confirm_twice(db_path, wall):
    store = make(db_path, wall)
    confirm_new(store, "c1")
    with pytest.raises(sqlite3.IntegrityError):
        store.confirm("c1", "again.jpg")
    assert store.count_today() == 1
    # rollback ครบ: ไม่มี response แถวที่สอง และ DB ยังใช้ต่อได้
    assert confirm_new(store, "c2").daily_sequence == 2


def test_confirm_requires_open_cycle(db_path, wall):
    store = make(db_path, wall)
    with pytest.raises(sqlite3.IntegrityError):
        store.confirm("missing", "p")
    store.open_cycle("c1")
    store.close_cycle("c1", "UNCONFIRMED", "stop")
    with pytest.raises(sqlite3.IntegrityError):
        store.confirm("c1", "p")
    assert store.count_today() == 0


def test_confirm_creates_pending_s0_and_close_expires_it(db_path, wall):
    store = make(db_path, wall)
    confirm_new(store, "c1")
    assert store.get_response("c1")["state"] == R_PENDING
    store.close_cycle("c1", "CONFIRMED", "stop")
    assert store.get_response("c1")["state"] == R_EXPIRED
    cyc = store.get_cycle("c1")
    assert cyc["outcome"] == "CONFIRMED" and cyc["closed_at_utc"] is not None


def test_close_keeps_enqueued_and_unknown(db_path, wall):
    store = make(db_path, wall)
    confirm_new(store, "a")
    store.set_response_state("a", R_ENQUEUED)
    confirm_new(store, "b")
    store.set_response_state("b", R_UNKNOWN, "timeout")
    store.close_cycle("a", "CONFIRMED", "stop")
    store.close_cycle("b", "CONFIRMED", "stop")
    assert store.get_response("a")["state"] == R_ENQUEUED
    assert store.get_response("b")["state"] == R_UNKNOWN
    assert store.get_response("b")["last_error"] == "timeout"


def test_recover_open_cycles_marks_interrupted(db_path, wall):
    store = make(db_path, wall)
    store.open_cycle("done")
    store.close_cycle("done", "UNCONFIRMED", "stop")
    confirm_new(store, "hanging")  # ยืนยันแล้ว แต่ process ตายก่อนส่ง S0 / STOP
    store.close()

    store = make(db_path, wall)
    assert store.recover_open_cycles() == ["hanging"]
    cyc = store.get_cycle("hanging")
    assert cyc["outcome"] == "INTERRUPTED" and cyc["reason"] == "restart"
    assert store.get_response("hanging")["state"] == R_EXPIRED
    assert store.get_cycle("done")["outcome"] == "UNCONFIRMED"
    assert store.count_today() == 1  # ยอดที่ commit แล้วไม่หาย
    assert store.recover_open_cycles() == []


def test_anomaly_recorded(db_path, wall):
    store = make(db_path, wall)
    store.record_anomaly("OUTSIDE_CYCLE", None, "evidence_images/anomaly/x.jpg")
    store.open_cycle("c1")
    store.record_anomaly("NO_CONFIRM_AT_CLOSE", "c1", None)
    rows = store.conn.execute("SELECT kind, cycle_id, local_date FROM anomalies ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("OUTSIDE_CYCLE", None, "2026-10-05"),
        ("NO_CONFIRM_AT_CLOSE", "c1", "2026-10-05"),
    ]
    assert store.count_today() == 0  # anomaly ไม่นับยอด


def test_corrupt_db_raises_clear_error(db_path, wall, tmp_path):
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    with pytest.raises(StateStoreError, match="เปิด state DB ไม่ได้"):
        make(str(bad), wall)


def test_unknown_schema_version_raises(db_path, wall):
    store = make(db_path, wall)
    store.conn.execute("PRAGMA user_version=99")
    store.close()
    with pytest.raises(StateStoreError, match="schema version"):
        make(db_path, wall)


def test_wal_mode_enabled(db_path, wall):
    store = make(db_path, wall)
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_confirmations_for_date_ordered(db_path, wall):
    store = make(db_path, wall)
    for i in range(3):
        confirm_new(store, f"c{i}", f"p{i}")
        wall.advance(1)
    rows = store.confirmations_for_date("2026-10-05")
    assert [(r.daily_sequence, r.evidence_path) for r in rows] == [(1, "p0"), (2, "p1"), (3, "p2")]
    assert rows[0].confirmed_at.strftime("%H:%M:%S") == "13:45:12"
