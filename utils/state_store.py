"""
utils/state_store.py — แหล่งจริงของรอบ / การยืนยัน / ยอดรายวัน (SQLite)

  - ยอดรายวันคำนวณจากตาราง confirmations เท่านั้น (log รายวันเป็นแค่ภาพสะท้อน สร้างใหม่ได้)
  - การยืนยัน + daily_sequence + S0 intent อยู่ใน transaction เดียว → ไม่มียอดครึ่ง ๆ
  - DB เปิดไม่ได้ / เสีย → StateStoreError (main หยุดพร้อมข้อความ) ห้ามเริ่มนับจาก 0 เงียบ ๆ
  - ใช้จาก main loop thread เดียวเท่านั้น (Redis worker ไม่เขียน DB เอง)

cloud_outbox: event ขึ้นเว็บที่รอส่ง (worker ของ api/cloud.py อ่าน/อัปเดตผ่าน CloudOutbox ด้วย connection ของตัวเอง)
  เพิ่มด้วย CREATE TABLE IF NOT EXISTS ตอนเปิด DB (ไม่เปลี่ยน user_version) → DB เดิมใช้ต่อได้
  และ rollback ไปโปรแกรมรุ่นก่อนก็ยังเปิด DB นี้ได้ (รุ่นก่อนไม่รู้จักตารางนี้ก็ไม่เป็นไร)

เวลา: เก็บ *_at_utc เป็น ISO-8601 UTC, local_date เป็นวันตาม COUNT_TIMEZONE (เช่น Asia/Bangkok)
      ณ เวลายืนยัน → วันของยอดไม่ขึ้นกับ timezone ของ host
"""

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 1

# สถานะการส่ง S0 ของแต่ละรอบ
R_PENDING = "PENDING"    # commit แล้ว รอ worker ส่ง
R_ENQUEUED = "ENQUEUED"  # LPUSH สำเร็จ (Redis รับแล้ว ≠ controller อ่านแล้ว)
R_FAILED = "FAILED"      # ส่งไม่ถึง Redis แน่นอน (retry ได้ถ้ารอบยังเปิด)
R_UNKNOWN = "UNKNOWN"    # timeout / ไม่รู้ผล → ห้าม retry (อาจได้ S0 ซ้ำ)
R_EXPIRED = "EXPIRED"    # รอบปิด / restart ก่อนส่งสำเร็จ → ห้ามส่งอีก

# สถานะ event ใน cloud_outbox
O_PENDING = "PENDING"  # รอส่ง (ส่งไม่สำเร็จ → ยัง PENDING พร้อม next_attempt_at ตาม backoff)
O_SENT = "SENT"        # เว็บตอบ 2xx แล้ว (ภาพในเครื่องไม่ถูกลบ)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id        TEXT PRIMARY KEY,
    machine_id      TEXT NOT NULL,
    started_at_utc  TEXT NOT NULL,
    closed_at_utc   TEXT,
    outcome         TEXT,
    reason          TEXT
);
CREATE TABLE IF NOT EXISTS confirmations (
    id                INTEGER PRIMARY KEY,
    cycle_id          TEXT NOT NULL UNIQUE REFERENCES cycles(cycle_id),
    machine_id        TEXT NOT NULL,
    confirmed_at_utc  TEXT NOT NULL,
    local_date        TEXT NOT NULL,
    daily_sequence    INTEGER NOT NULL,
    evidence_path     TEXT NOT NULL,
    UNIQUE (machine_id, local_date, daily_sequence)
);
CREATE TABLE IF NOT EXISTS anomalies (
    id             INTEGER PRIMARY KEY,
    kind           TEXT NOT NULL,
    cycle_id       TEXT,
    at_utc         TEXT NOT NULL,
    local_date     TEXT NOT NULL,
    evidence_path  TEXT
);
CREATE TABLE IF NOT EXISTS responses (
    cycle_id    TEXT NOT NULL UNIQUE REFERENCES cycles(cycle_id),
    payload     TEXT NOT NULL,
    state       TEXT NOT NULL,
    last_error  TEXT,
    updated_at  TEXT NOT NULL
);
"""

# เพิ่มภายหลัง (ไม่ bump SCHEMA_VERSION — ดู docstring ต้นไฟล์)
_OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS cloud_outbox (
    id               INTEGER PRIMARY KEY,
    event_id         TEXT NOT NULL UNIQUE,
    cycle_id         TEXT,
    event            TEXT NOT NULL,
    payload          TEXT NOT NULL,
    image_path       TEXT,
    state            TEXT NOT NULL,
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    next_attempt_at  REAL NOT NULL DEFAULT 0,
    created_at_utc   TEXT NOT NULL,
    updated_at_utc   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cloud_outbox_due ON cloud_outbox (state, next_attempt_at);
"""


class StateStoreError(Exception):
    """DB ใช้งานไม่ได้ — ต้องหยุดโปรแกรม ไม่ใช่ข้ามไปนับต่อ"""


@dataclass
class Confirmation:
    cycle_id: str
    confirmed_at: datetime  # aware datetime ใน COUNT_TIMEZONE (ใช้เขียน daily log)
    local_date: str         # YYYY-MM-DD
    daily_sequence: int
    evidence_path: str


class StateStore:
    def __init__(self, path, machine_id, tz_name, clock=time.time):
        """clock: wall clock (epoch วินาที) — test ใส่ fake clock ได้"""
        self.path = path
        self.machine_id = machine_id
        self.tz = ZoneInfo(tz_name)
        self.clock = clock
        self.conn = self._open()

    # ── เปิด / ตรวจ DB ───────────────────────────────────────────────────────
    def _open(self):
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # isolation_level=None → คุม transaction เองด้วย BEGIN IMMEDIATE
            conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            ok = conn.execute("PRAGMA quick_check").fetchone()[0]
            if ok != "ok":
                raise StateStoreError(f"DB เสีย (quick_check: {ok})")
            conn.execute("PRAGMA journal_mode=WAL")
            # FULL: เขียนน้อยมาก (ไม่กี่ครั้งต่อรอบ) จึงเลือกความทนไฟดับมากกว่าความเร็ว
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                conn.executescript(_SCHEMA)
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION:
                raise StateStoreError(
                    f"schema version {version} ไม่ตรงกับโปรแกรม ({SCHEMA_VERSION})"
                )
            conn.executescript(_OUTBOX_SCHEMA)
            return conn
        except StateStoreError as e:
            raise StateStoreError(f"❌ เปิด state DB ไม่ได้ ({self.path}): {e}") from e
        except (sqlite3.Error, OSError) as e:
            raise StateStoreError(f"❌ เปิด state DB ไม่ได้ ({self.path}): {e}") from e

    def close(self):
        self.conn.close()

    # ── เวลา ─────────────────────────────────────────────────────────────────
    def _now(self):
        """คืน (utc_iso, local aware datetime) ของเวลาปัจจุบัน"""
        utc = datetime.fromtimestamp(self.clock(), timezone.utc)
        return utc.isoformat(timespec="milliseconds"), utc.astimezone(self.tz)

    def today(self):
        return self._now()[1].date().isoformat()

    def _tx(self):
        return _Transaction(self.conn)

    # ── รอบ ──────────────────────────────────────────────────────────────────
    def open_cycle(self, cycle_id):
        utc, _ = self._now()
        with self._tx():
            self.conn.execute(
                "INSERT INTO cycles (cycle_id, machine_id, started_at_utc) VALUES (?, ?, ?)",
                (cycle_id, self.machine_id, utc),
            )

    def close_cycle(self, cycle_id, outcome, reason):
        """ปิดรอบ + S0 ที่ยังไม่ได้ส่ง (PENDING/FAILED) ของรอบนี้ → EXPIRED ใน transaction เดียว"""
        utc, _ = self._now()
        with self._tx():
            self.conn.execute(
                "UPDATE cycles SET closed_at_utc=?, outcome=?, reason=? "
                "WHERE cycle_id=? AND closed_at_utc IS NULL",
                (utc, outcome, reason, cycle_id),
            )
            self._expire_responses(utc, cycle_id)

    def recover_open_cycles(self):
        """startup: รอบที่ยังไม่ปิด (process ตายกลางรอบ) → INTERRUPTED และ S0 ค้างทั้งหมด → EXPIRED
        คืน list cycle_id ที่ถูกปิด (ว่าง = ไม่มีรอบค้าง)"""
        utc, _ = self._now()
        with self._tx():
            rows = self.conn.execute(
                "SELECT cycle_id FROM cycles WHERE closed_at_utc IS NULL"
            ).fetchall()
            ids = [r["cycle_id"] for r in rows]
            self.conn.execute(
                "UPDATE cycles SET closed_at_utc=?, outcome='INTERRUPTED', reason='restart' "
                "WHERE closed_at_utc IS NULL",
                (utc,),
            )
            # S0 ของ process ก่อนหน้าห้ามส่งอีก ไม่ว่าเป็นรอบไหน
            self._expire_responses(utc)
        return ids

    def get_cycle(self, cycle_id):
        row = self.conn.execute("SELECT * FROM cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
        return dict(row) if row else None

    # ── การยืนยัน ────────────────────────────────────────────────────────────
    def confirm(self, cycle_id, evidence_path):
        """บันทึกการยืนยัน 1 ครั้งของรอบ + daily_sequence + S0 intent (PENDING) ใน transaction เดียว

        - รอบต้องยังเปิดอยู่ ไม่งั้น raise (กันผลของรอบเก่า)
        - รอบเดิมยืนยันซ้ำ → sqlite3.IntegrityError (cycle_id UNIQUE) ยอดไม่เพิ่ม
        """
        utc, local = self._now()
        local_date = local.date().isoformat()
        with self._tx():
            row = self.conn.execute(
                "SELECT closed_at_utc FROM cycles WHERE cycle_id=?", (cycle_id,)
            ).fetchone()
            if row is None or row["closed_at_utc"] is not None:
                raise sqlite3.IntegrityError(f"รอบ {cycle_id} ไม่ได้เปิดอยู่")
            seq = self.conn.execute(
                "SELECT COALESCE(MAX(daily_sequence), 0) + 1 FROM confirmations "
                "WHERE machine_id=? AND local_date=?",
                (self.machine_id, local_date),
            ).fetchone()[0]
            self.conn.execute(
                "INSERT INTO confirmations (cycle_id, machine_id, confirmed_at_utc, "
                "local_date, daily_sequence, evidence_path) VALUES (?, ?, ?, ?, ?, ?)",
                (cycle_id, self.machine_id, utc, local_date, seq, evidence_path),
            )
            self.conn.execute(
                "INSERT INTO responses (cycle_id, payload, state, updated_at) "
                "VALUES (?, 'S0', ?, ?)",
                (cycle_id, R_PENDING, utc),
            )
        return Confirmation(cycle_id, local, local_date, seq, evidence_path)

    def count_for_date(self, local_date):
        return self.conn.execute(
            "SELECT COUNT(*) FROM confirmations WHERE machine_id=? AND local_date=?",
            (self.machine_id, local_date),
        ).fetchone()[0]

    def count_today(self):
        return self.count_for_date(self.today())

    def confirmations_for_date(self, local_date):
        """การยืนยันของวันนั้นเรียงตาม daily_sequence (ใช้สร้าง daily log ใหม่)"""
        rows = self.conn.execute(
            "SELECT * FROM confirmations WHERE machine_id=? AND local_date=? "
            "ORDER BY daily_sequence",
            (self.machine_id, local_date),
        ).fetchall()
        return [
            Confirmation(
                r["cycle_id"],
                datetime.fromisoformat(r["confirmed_at_utc"]).astimezone(self.tz),
                r["local_date"],
                r["daily_sequence"],
                r["evidence_path"],
            )
            for r in rows
        ]

    # ── S0 response ──────────────────────────────────────────────────────────
    def set_response_state(self, cycle_id, state, last_error=None):
        utc, _ = self._now()
        with self._tx():
            self.conn.execute(
                "UPDATE responses SET state=?, last_error=?, updated_at=? WHERE cycle_id=?",
                (state, last_error, utc, cycle_id),
            )

    def get_response(self, cycle_id):
        row = self.conn.execute(
            "SELECT * FROM responses WHERE cycle_id=?", (cycle_id,)
        ).fetchone()
        return dict(row) if row else None

    def _expire_responses(self, utc, cycle_id=None):
        sql = "UPDATE responses SET state=?, updated_at=? WHERE state IN (?, ?)"
        args = [R_EXPIRED, utc, R_PENDING, R_FAILED]
        if cycle_id is not None:
            sql += " AND cycle_id=?"
            args.append(cycle_id)
        self.conn.execute(sql, args)

    # ── cloud outbox ─────────────────────────────────────────────────────────
    def enqueue_cloud_event(self, event_id, cycle_id, event, payload, image_path):
        """เพิ่ม event รอส่งขึ้นเว็บ (event_id ซ้ำ → ไม่เพิ่ม) คืน True ถ้าเพิ่มใหม่
        next_attempt_at=0 → worker ส่งได้ทันที (ไม่ผูกกับนาฬิกาของ store)"""
        utc, _ = self._now()
        with self._tx():
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO cloud_outbox (event_id, cycle_id, event, payload, image_path, state, "
                "attempts, next_attempt_at, created_at_utc, updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)",
                (event_id, cycle_id, event, json.dumps(payload, ensure_ascii=False), image_path, O_PENDING, utc, utc),
            )
        return cur.rowcount == 1

    def count_pending_cloud_events(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM cloud_outbox WHERE state=?", (O_PENDING,)
        ).fetchone()[0]

    def cloud_events(self):
        """ทุกแถวของ outbox (ใช้ใน test / ตรวจสอบ)"""
        return [dict(r) for r in self.conn.execute("SELECT * FROM cloud_outbox ORDER BY id")]

    # ── anomaly ──────────────────────────────────────────────────────────────
    def record_anomaly(self, kind, cycle_id, evidence_path):
        utc, local = self._now()
        with self._tx():
            self.conn.execute(
                "INSERT INTO anomalies (kind, cycle_id, at_utc, local_date, evidence_path) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, cycle_id, utc, local.date().isoformat(), evidence_path),
            )


class CloudOutbox:
    """outbox ฝั่ง worker (thread ส่งขึ้นเว็บ) — connection ของตัวเอง ห้ามใช้ข้าม thread
    เวลา next_attempt_at เป็น epoch ของ wall clock (คงอยู่ข้าม restart)"""

    def __init__(self, path):
        # mode=rw: ไม่สร้าง DB เอง (StateStore ของ main เป็นคนสร้าง/ตรวจ DB)
        uri = "file:" + os.path.abspath(path).replace("\\", "/") + "?mode=rw"
        self.conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(_OUTBOX_SCHEMA)

    def close(self):
        self.conn.close()

    def next_due(self, now):
        row = self.conn.execute(
            "SELECT * FROM cloud_outbox WHERE state=? AND next_attempt_at<=? ORDER BY id LIMIT 1",
            (O_PENDING, now),
        ).fetchone()
        return dict(row) if row else None

    def next_attempt_at(self):
        """เวลาที่รายการค้างถัดไปส่งได้ (None = ไม่มีค้าง)"""
        return self.conn.execute(
            "SELECT MIN(next_attempt_at) FROM cloud_outbox WHERE state=?", (O_PENDING,)
        ).fetchone()[0]

    def _update(self, sql, args):
        utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self.conn.execute(sql, (*args[:-1], utc, args[-1]))

    def mark_sent(self, row_id):
        self._update(
            "UPDATE cloud_outbox SET state=?, attempts=attempts+1, last_error=NULL, updated_at_utc=? WHERE id=?",
            (O_SENT, row_id),
        )

    def mark_failed(self, row_id, error, next_attempt_at):
        self._update(
            "UPDATE cloud_outbox SET attempts=attempts+1, last_error=?, next_attempt_at=?, updated_at_utc=? "
            "WHERE id=?",
            (error, next_attempt_at, row_id),
        )


def pending_image_paths(path):
    """path ภาพของ event ที่ยังรอส่ง (disk_cleanup ห้ามลบ) — ไม่มี DB/ตาราง = ว่าง, DB อ่านไม่ได้ = raise"""
    if not os.path.exists(path):
        return set()
    conn = sqlite3.connect(path, timeout=5.0)
    try:
        rows = conn.execute(
            "SELECT image_path FROM cloud_outbox WHERE state=? AND image_path IS NOT NULL", (O_PENDING,)
        ).fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return set()
        raise
    finally:
        conn.close()
    return {r[0] for r in rows}


class _Transaction:
    """BEGIN IMMEDIATE ... COMMIT / ROLLBACK เมื่อมี exception"""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")
        return False
