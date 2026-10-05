"""
core/cycle.py — state machine ของรอบ START–STOP (1 รอบ = ยืนยันสินค้าได้สูงสุด 1 ครั้ง)

pure logic ล้วน: ไม่แตะกล้อง / Redis / ไฟล์ / DB — main loop เป็นเจ้าของ object นี้ตัวเดียว
แล้วเอาผลที่คืนกลับไปทำ I/O เอง (บันทึก DB, ถ่ายภาพ, ส่ง S0)
เวลา (now) เป็น monotonic ที่ผู้เรียกส่งเข้ามา → test ใช้ fake clock ได้

  WAIT_START ──START──▶ ACTIVE ──ยืนยันสำเร็จ──▶ CONFIRMED_WAIT_STOP
       ▲                  │ กล้องหลุด                 │ START (เหมือนตัวเก่า: ปิดรอบเดิม + เปิดรอบใหม่)
       │                  ▼                          │
       │           BLOCKED_WAIT_STOP                 │
       └── STOP / ครบ CYCLE_TIMEOUT_SEC ─────────────┘  (ทุก active state)

  RECOVERY_BLOCKED: restart แล้วเจอรอบค้างใน DB → STOP ถัดไป หรือครบ CYCLE_TIMEOUT_SEC
                    ปลดกลับ WAIT_START / START ระหว่างนี้ = anomaly ไม่เปิดรอบ

outcome ตอนปิดรอบ (เก็บใน DB เท่านั้น ไม่ส่งรหัสอื่นนอกจาก S0 ให้ controller):
  CONFIRMED    ยืนยันแล้ว (ปิดด้วย STOP / START ถัดไป / timeout — ดู reason)
  UNCONFIRMED  ไม่เจอสินค้า และภาพ/Redis ต่อเนื่องตลอดรอบ
  UNCERTAIN    ไม่เจอสินค้า แต่ระหว่างรอบกล้องหลุดหรือ Redis ขาด → บอกไม่ได้ว่าไม่มีของตกจริง
  TIMEOUT      ไม่เจอสินค้า และไม่มี STOP ภายใน CYCLE_TIMEOUT_SEC
  INTERRUPTED  รอบค้างจาก process ก่อน restart (state_store เป็นคนบันทึก)
"""

import uuid
from dataclasses import dataclass

WAIT_START = "WAIT_START"
ACTIVE = "ACTIVE"
CONFIRMED_WAIT_STOP = "CONFIRMED_WAIT_STOP"
BLOCKED_WAIT_STOP = "BLOCKED_WAIT_STOP"
RECOVERY_BLOCKED = "RECOVERY_BLOCKED"

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
        self.recovery_since = None  # monotonic ตอนเข้า RECOVERY_BLOCKED
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
            return Result(opened=self._open(now), note="เปิดรอบใหม่")

        if self.state == CONFIRMED_WAIT_STOP:
            # เหมือนตัวเก่า: ส่ง S0 แล้วพร้อมรับ START ถัดไปทันที (controller อาจไม่ส่ง STOP)
            closed = self._close("next_start")
            return Result(
                closed=closed, opened=self._open(now),
                note="START หลังยืนยันแล้ว → ปิดรอบเดิมและเปิดรอบใหม่",
            )

        if self.state == RECOVERY_BLOCKED:
            return Result(
                anomaly="START_DURING_RECOVERY",
                note="START ระหว่าง RECOVERY_BLOCKED → ไม่เปิดรอบ (รอ STOP ปลด block)",
            )

        # ACTIVE / BLOCKED_WAIT_STOP: ไม่เปิดรอบซ้อน ไม่ล้างอะไร
        return Result(
            anomaly="DUPLICATE_START",
            note=f"START ซ้ำขณะ {self.state} → ไม่เปิดรอบใหม่",
        )

    def on_stop(self, now):
        if self.is_open():
            return Result(closed=self._close("stop"), note="STOP → ปิดรอบ")
        if self.state == RECOVERY_BLOCKED:
            self._leave_recovery()
            return Result(note="STOP → ปลด RECOVERY_BLOCKED กลับ WAIT_START")
        return Result(note="STOP ขณะ WAIT_START → no-op")

    # ── เหตุการณ์ภายใน ───────────────────────────────────────────────────────
    def tick(self, now):
        """เรียกทุก iteration — ครบ CYCLE_TIMEOUT_SEC โดยไม่มี STOP → ปิดรอบเอง
        (RECOVERY_BLOCKED ก็หมดอายุด้วยค่าเดียวกัน กันตู้ค้างถ้า controller ไม่ส่ง STOP)"""
        if self.state == RECOVERY_BLOCKED and now - self.recovery_since >= self.timeout_sec:
            self._leave_recovery()
            return Result(
                note=f"RECOVERY_BLOCKED ครบ {self.timeout_sec:.0f}s ไม่มี STOP → กลับ WAIT_START",
            )
        if self.is_open() and now - self.started_at >= self.timeout_sec:
            return Result(
                closed=self._close("timeout"),
                note=f"ไม่มี STOP ภายใน {self.timeout_sec:.0f}s → ปิดรอบเอง",
            )
        return None

    def mark_confirmed(self):
        """เรียกหลัง DB commit การยืนยันสำเร็จแล้วเท่านั้น → latch ไม่ยืนยันซ้ำในรอบนี้"""
        if self.state != ACTIVE:
            raise RuntimeError(f"mark_confirmed ขณะ {self.state}")
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

    def enter_recovery(self, now):
        """startup เจอรอบค้างใน DB (state_store ปิดเป็น INTERRUPTED แล้ว) → block จน STOP / timeout"""
        self._clear_cycle()
        self.state = RECOVERY_BLOCKED
        self.recovery_since = now

    def _leave_recovery(self):
        self.state = WAIT_START
        self.recovery_since = None

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
