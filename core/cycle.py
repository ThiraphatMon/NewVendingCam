"""
core/cycle.py — state machine ของรอบ START–STOP (1 รอบ = ยืนยันสินค้าได้สูงสุด 1 ครั้ง)

pure logic ล้วน: ไม่แตะกล้อง / Redis / ไฟล์ / DB — main loop เป็นเจ้าของ object นี้ตัวเดียว
แล้วเอาผลที่คืนกลับไปทำ I/O เอง (บันทึก DB, ถ่ายภาพ, ส่ง S0)
เวลา (now) เป็น monotonic ที่ผู้เรียกส่งเข้ามา → test ใช้ fake clock ได้

  WAIT_START ──START──▶ ACTIVE ──ยืนยันสำเร็จ──▶ CONFIRMED_WAIT_STOP
       ▲                  │ กล้องหลุด
       │                  ▼
       │           BLOCKED_WAIT_STOP
       └── STOP / ครบ CYCLE_TIMEOUT_SEC (ทุก active state)

ตอบสนองต่อลำดับคำสั่งเหมือน legacy_reference/main.py:
  - START ขณะ CONFIRMED_WAIT_STOP / BLOCKED_WAIT_STOP → ปิดรอบเดิม แล้วเปิดรอบใหม่ทันที
    (ตัวเก่าจบรอบเองหลังส่ง S0 หรือกล้องอ่านไม่ได้ แล้วรับ START ถัดไปได้เลย)
  - START ขณะ ACTIVE → ไม่มีผล (ตัวเก่า pop ทิ้ง) รอบเดิมเดินต่อ ไม่รีเซ็ตเวลา
  - STOP ขณะ WAIT_START → ไม่มีผล
  - restart ระหว่างรอบ → state_store ปิดรอบค้างเป็น INTERRUPTED แล้วเริ่มที่ WAIT_START

outcome ตอนปิดรอบ (เก็บใน DB เท่านั้น ไม่ส่งรหัสอื่นนอกจาก S0 ให้ controller):
  CONFIRMED    ยืนยันแล้ว (ปิดด้วย STOP / START ถัดไป / timeout — ดู reason)
  UNCONFIRMED  ไม่เจอสินค้า และภาพ/Redis ต่อเนื่องตลอดรอบ
  UNCERTAIN    ไม่เจอสินค้า แต่ระหว่างรอบกล้องหลุดหรือ Redis ขาด → บอกไม่ได้ว่าไม่มีของตกจริง
  TIMEOUT      ไม่เจอสินค้า และไม่มี STOP ภายใน CYCLE_TIMEOUT_SEC
  INTERRUPTED  รอบค้างจาก process ก่อน restart (state_store เป็นคนบันทึก)
"""

import uuid
from collections import deque
from dataclasses import dataclass

WAIT_START = "WAIT_START"
ACTIVE = "ACTIVE"
CONFIRMED_WAIT_STOP = "CONFIRMED_WAIT_STOP"
BLOCKED_WAIT_STOP = "BLOCKED_WAIT_STOP"

# state ที่ถือว่ามีรอบเปิดอยู่
OPEN_STATES = (ACTIVE, CONFIRMED_WAIT_STOP, BLOCKED_WAIT_STOP)


@dataclass
class ClosedCycle:
    """ข้อมูลรอบที่เพิ่งปิด — main เอาไปบันทึก DB / ถ่ายภาพ NO_CONFIRM_AT_CLOSE"""
    cycle_id: str
    outcome: str
    reason: str
    confirmed: bool


@dataclass
class Result:
    """ผลของคำสั่ง/เหตุการณ์หนึ่งครั้ง (ฟิลด์ที่ไม่เกิดขึ้นเป็น None)

    closed  : รอบที่ถูกปิดในครั้งนี้
    opened  : cycle_id ของรอบใหม่ที่เปิดในครั้งนี้
    anomaly : protocol anomaly (เช่น START ซ้ำ) — main log ไว้ ไม่มีผลกับยอด
    note    : ข้อความอธิบายสำหรับ operational log
    """
    closed: ClosedCycle = None
    opened: str = None
    anomaly: str = None
    note: str = ""


class CycleMachine:
    def __init__(self, timeout_sec, new_id=None):
        self.timeout_sec = timeout_sec
        self._new_id = new_id or (lambda: uuid.uuid4().hex)
        self.state = WAIT_START
        self._clear_cycle()

    def _clear_cycle(self):
        self.cycle_id = None
        self.started_at = None  # monotonic
        # ระหว่างรอบเคยขาดข้อมูลไหม (ใช้ตัดสิน UNCERTAIN ตอนปิดรอบ)
        self.camera_gap = False
        self.redis_gap = False

    # ── สถานะ ──────────────────────────────────────────────────────────────
    def is_open(self):
        return self.state in OPEN_STATES

    def can_confirm(self):
        """ยืนยันได้เฉพาะ ACTIVE เท่านั้น (นอกรอบ / ยืนยันแล้ว / blocked = ห้าม)"""
        return self.state == ACTIVE

    def is_current_open(self, cycle_id):
        """cycle_id นี้ยังเป็นรอบที่เปิดอยู่ไหม — ใช้กัน S0/ผลของรอบเก่าย้อนมาในรอบใหม่"""
        return cycle_id is not None and self.is_open() and cycle_id == self.cycle_id

    # ── คำสั่งจาก controller ─────────────────────────────────────────────────
    def on_start(self, now):
        if self.state == WAIT_START:
            return Result(opened=self._open(now), note="START -> cycle opened")

        if self.state in (CONFIRMED_WAIT_STOP, BLOCKED_WAIT_STOP):
            # เหมือนตัวเก่า: จบรอบแล้ว (ส่ง S0 / กล้องเสีย) พร้อมรับ START ถัดไปทันที
            prev = self.state
            closed = self._close("next_start")
            return Result(
                closed=closed, opened=self._open(now),
                note=f"START while {prev} -> previous cycle closed ({closed.outcome}) and new cycle opened",
            )

        # ACTIVE: ไม่เปิดรอบซ้อน ไม่ล้างอะไร (ตัวเก่า pop ทิ้ง)
        return Result(
            anomaly="DUPLICATE_START",
            note="duplicate START (ignored) while ACTIVE -> current cycle continues",
        )

    def on_stop(self, now):
        if self.is_open():
            return Result(closed=self._close("stop"), note="STOP -> cycle closed")
        return Result(note="STOP while WAIT_START (no open cycle) -> ignored")

    # ── เหตุการณ์ภายใน ───────────────────────────────────────────────────────
    def tick(self, now):
        """เรียกทุก iteration — ครบ CYCLE_TIMEOUT_SEC โดยไม่มี STOP → ปิดรอบเอง"""
        if self.is_open() and now - self.started_at >= self.timeout_sec:
            return Result(
                closed=self._close("timeout"),
                note=f"cycle timeout: no STOP within {self.timeout_sec:.0f}s -> cycle closed",
            )
        return None

    def mark_confirmed(self):
        """เรียกหลัง DB commit การยืนยันสำเร็จแล้วเท่านั้น → latch ไม่ยืนยันซ้ำในรอบนี้"""
        if self.state != ACTIVE:
            raise RuntimeError(f"mark_confirmed while {self.state}")
        self.state = CONFIRMED_WAIT_STOP

    def on_camera_lost(self):
        """กล้องหลุด: ถ้ายังไม่ยืนยัน → ช่วงตรวจขาดความต่อเนื่อง ห้ามยืนยันจนปิดรอบ"""
        if self.is_open():
            self.camera_gap = True
        if self.state == ACTIVE:
            self.state = BLOCKED_WAIT_STOP
            return True
        return False

    def on_redis_gap(self):
        """Redis ขาดระหว่างรอบ: controller อาจส่ง STOP ที่เรายังไม่เห็น → จำไว้ตัดสิน UNCERTAIN"""
        if self.is_open():
            self.redis_gap = True

    # ── ภายใน ───────────────────────────────────────────────────────────────
    def _open(self, now):
        self._clear_cycle()
        self.cycle_id = self._new_id()
        self.started_at = now
        self.state = ACTIVE
        return self.cycle_id

    def _close(self, reason):
        confirmed = self.state == CONFIRMED_WAIT_STOP
        gaps = [g for g, on in (("camera_gap", self.camera_gap), ("redis_gap", self.redis_gap)) if on]
        if confirmed:
            outcome = "CONFIRMED"
        elif reason == "timeout":
            outcome = "TIMEOUT"
        elif gaps:
            outcome = "UNCERTAIN"
        else:
            outcome = "UNCONFIRMED"
        closed = ClosedCycle(
            cycle_id=self.cycle_id,
            outcome=outcome,
            reason=";".join([reason] + gaps),
            confirmed=confirmed,
        )
        self._clear_cycle()
        self.state = WAIT_START
        return closed


class AnomalyLimiter:
    """[ไม่ใช้แล้วตั้งแต่ S19 — ภาพ anomaly ทุกเหตุการณ์ได้ 1 ภาพ มีแค่เพดานต่อวันใน main.py] เก็บไว้เผื่อเปิดกลับ
    จำกัดความถี่ภาพ anomaly (OUTSIDE_CYCLE + EXTRA_AFTER_CONFIRM ใช้โควตาร่วมกัน)
    ไม่เกิน 1 ภาพต่อ min_interval วินาที และไม่เกิน max_per_hour ภาพใน 1 ชั่วโมงล่าสุด"""

    def __init__(self, min_interval, max_per_hour):
        self.min_interval = min_interval
        self.max_per_hour = max_per_hour
        self._times = deque()  # monotonic ของภาพที่อนุญาตใน 1 ชั่วโมงล่าสุด

    def allow(self, now):
        """คืน True และนับโควตา ถ้าถ่ายได้ตอนนี้"""
        while self._times and now - self._times[0] >= 3600:
            self._times.popleft()
        if self._times and now - self._times[-1] < self.min_interval:
            return False
        if len(self._times) >= self.max_per_hour:
            return False
        self._times.append(now)
        return True
