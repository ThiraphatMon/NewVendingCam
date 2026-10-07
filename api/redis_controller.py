"""
api/redis_controller.py — รับ START/STOP จาก Redis และส่ง S0 กลับ (protocol เดียวกับ legacy_reference/main.py)

  รับ : RPOP <REDIS_CTRL_KEY>  (ค่าเริ่มต้น CTRL, DB 0) — รับเฉพาะ "START" / "STOP" ตรงตัว
  ส่ง : LPUSH <REDIS_RESPONSE_KEY> "S0"  (ค่าเริ่มต้น CAMERA)
  ห้าม FLUSHDB / DEL / drain คิวทิ้ง — อ่านทีละรายการตามลำดับเท่านั้น

โครงสร้าง thread:
  worker thread ตัวเดียวคุย Redis ทั้งหมด → ส่งเหตุการณ์ให้ main loop ทาง inbox (queue ตามลำดับ)
  main loop เป็นเจ้าของ cycle state ตัวเดียว — worker ไม่เปลี่ยน state เอง
  Redis ล่ม / ช้า → worker backoff เอง ไม่ทำให้กล้องหรือการประมวลผล STOP ค้าง

กติกาการส่ง S0 (1 ครั้งต่อรอบ):
  - ปิด retry อัตโนมัติของ redis client ทั้งหมด (retry 0 ครั้ง)
  - PING ไม่ผ่าน = รู้แน่ว่ายังไม่ได้ส่ง LPUSH → FAILED แล้วลองใหม่ได้ เฉพาะขณะรอบยังได้รับอนุญาต
  - LPUSH error / timeout = ไม่รู้ว่าถึง Redis หรือยัง → UNKNOWN ห้ามส่งซ้ำ (อาจได้ S0 สองรายการ)
  - main เพิกถอน (revoke) ตอนปิดรอบ / worker pop START หรือ STOP ได้ก่อนส่ง → ไม่ส่ง (EXPIRED)

โหมดเก็บข้อมูล (send_s0=False / SEND_S0=0): ไม่เขียน response_key เลยไม่ว่ากรณีใด
  main ไม่ขอส่งอยู่แล้ว — ที่นี่กันซ้ำอีกชั้น: request_s0 ถูกทิ้ง และ worker ไม่มีทาง LPUSH
  ยังรับ CTRL ด้วย RPOP เหมือนเดิม
"""

import queue
import threading
import time
from dataclasses import dataclass

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from utils.logger import get_logger, LogThrottle

logger = get_logger("redis")

VALID_COMMANDS = ("START", "STOP")

# คำสั่งค้างใน inbox เกินนี้ → หยุด RPOP ก่อน (backpressure ไม่ทิ้งคำสั่ง)
INBOX_SOFT_LIMIT = 64

_bad_msg_log = LogThrottle(10.0)
_down_log = LogThrottle(30.0)


# ── เหตุการณ์ที่ worker ส่งให้ main loop (ผ่าน inbox ตามลำดับเวลา) ───────────────
@dataclass
class Command:
    seq: int        # ลำดับคำสั่งที่รับ (เพิ่มทีละ 1)
    text: str       # "START" / "STOP"
    received: float  # time.monotonic() ตอน pop
    source: str = "redis"  # "redis" / "keyboard"


@dataclass
class LinkStatus:
    up: bool
    error: str = ""


@dataclass
class SendResult:
    cycle_id: str
    state: str      # ENQUEUED / FAILED / UNKNOWN / EXPIRED (ชื่อเดียวกับ state_store)
    error: str = ""


@dataclass
class _SendRequest:
    cycle_id: str
    after_seq: int  # main ประมวลผลคำสั่งถึง seq นี้แล้วตอนขอส่ง
    failed_once: bool = False


def make_client(host, port, db, password, connect_timeout, socket_timeout):
    """redis client ที่ปิด retry อัตโนมัติ (กัน LPUSH ซ้ำ) และมี timeout ทุก operation"""
    return redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password or None,
        socket_connect_timeout=connect_timeout,
        socket_timeout=socket_timeout,
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
        retry_on_error=[],
        health_check_interval=0,
    )


class RedisController:
    def __init__(
        self,
        client_factory,
        ctrl_key="CTRL",
        response_key="CAMERA",
        poll_interval=0.05,
        backoff_min=0.5,
        backoff_max=5.0,
        enabled=True,
        send_s0=True,
    ):
        """client_factory: ฟังก์ชันสร้าง redis client (test ใส่ fakeredis ได้)
        enabled=False: ไม่เปิด worker (CONTROL_MODE=keyboard — รับคำสั่งจากปุ่มบน PC อย่างเดียว)
        send_s0=False: โหมดเก็บข้อมูล — ไม่เขียน response_key เลย"""
        self.client_factory = client_factory
        self.ctrl_key = ctrl_key
        self.response_key = response_key
        self.poll_interval = poll_interval
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self.enabled = enabled
        self.send_s0 = send_s0

        self.inbox = queue.Queue()
        self._wake = threading.Event()  # ปลุก worker ทันทีเมื่อมีคำขอส่ง S0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._seq = 0
        self._last_ctrl_seq = 0       # seq ของ START/STOP ล่าสุดที่ pop ได้
        self._allowed_cycle = None    # รอบที่ main อนุญาตให้ส่ง S0 ได้ตอนนี้
        self._request = None          # คำขอส่ง S0 ที่ค้างอยู่ (มีได้ทีละ 1)

        self.link_up = None  # None = ยังไม่เคยเชื่อมต่อ
        self._client = None
        self._backoff = backoff_min
        self._thread = None

    # ── เรียกจาก main thread ─────────────────────────────────────────────────
    def start(self):
        if not self.enabled:
            logger.info("⌨️ CONTROL_MODE=keyboard — ไม่เชื่อม Redis (ใช้ปุ่ม s/x บนหน้าต่าง)")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="redis-worker")
        self._thread.start()

    def stop(self, timeout=2.0):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def inject(self, text, source="keyboard"):
        """ส่งคำสั่งเข้า inbox เหมือนมาจาก Redis (ใช้กับปุ่ม s/x บน PC)"""
        with self._lock:
            self._seq += 1
            self._last_ctrl_seq = self._seq
            seq = self._seq
        self.inbox.put(Command(seq, text, time.monotonic(), source))

    def drain(self):
        """ดึงเหตุการณ์ทั้งหมดที่ค้างใน inbox (ตามลำดับ) — ไม่ block"""
        items = []
        while True:
            try:
                items.append(self.inbox.get_nowait())
            except queue.Empty:
                return items

    def request_s0(self, cycle_id, after_seq):
        """ขอส่ง S0 ของรอบนี้ (main เรียกหลัง DB commit การยืนยันแล้ว)
        after_seq: seq ของคำสั่งล่าสุดที่ main ประมวลผลแล้ว — ถ้า worker pop START/STOP
                   ใหม่กว่านี้ไปแล้ว แปลว่ารอบกำลังจะถูกปิด → ไม่ส่ง"""
        if not self.send_s0:
            # โหมดเก็บข้อมูล: main ไม่ควรเรียกอยู่แล้ว — ทิ้งคำขอ ไม่ส่งเหตุการณ์ (DB เป็น NOT_SENT อยู่แล้ว)
            logger.warning(f"S0 request ignored (cycle={cycle_id[:8]}): SEND_S0=0 observe mode")
            return
        with self._lock:
            old = self._request
            self._allowed_cycle = cycle_id
            self._request = _SendRequest(cycle_id, after_seq)
        if old is not None and old.cycle_id != cycle_id:
            self.inbox.put(SendResult(old.cycle_id, "EXPIRED", "มีคำขอของรอบใหม่แทน"))
        if not self.enabled:
            # keyboard mode ไม่มี Redis ให้ส่ง → บันทึกว่าส่งไม่ได้แน่นอน
            with self._lock:
                self._request = None
            self.inbox.put(SendResult(cycle_id, "EXPIRED", "CONTROL_MODE=keyboard ไม่มี Redis"))
            return
        self._wake.set()

    def revoke(self, cycle_id):
        """main ปิดรอบแล้ว → ห้ามส่ง S0 ของรอบนี้อีก (คำขอที่ยังไม่ได้ส่งจะกลายเป็น EXPIRED)"""
        with self._lock:
            if self._allowed_cycle == cycle_id:
                self._allowed_cycle = None
        self._wake.set()

    # ── worker thread ────────────────────────────────────────────────────────
    def _run(self):
        send = f"LPUSH {self.response_key}" if self.send_s0 else f"{self.response_key} disabled (SEND_S0=0)"
        logger.info(f"🔌 Redis worker เริ่มแล้ว (RPOP {self.ctrl_key} / {send})")
        while not self._stop.is_set():
            try:
                self._expire_if_revoked()
                if self._client is None and not self._connect():
                    self._sleep_backoff()
                    continue
                if self._service_request():
                    continue
                popped = self._poll_once()
                if not popped:
                    self._wake.wait(self.poll_interval)
                    self._wake.clear()
            except Exception as e:  # ห้าม worker ตาย ไม่ว่า error อะไร
                logger.exception(f"❌ Redis worker error ที่ไม่คาดคิด: {e}")
                self._drop_client(str(e))
                self._sleep_backoff()
        self._close_client()

    def _connect(self):
        try:
            client = self.client_factory()
            client.ping()
        except redis.RedisError as e:
            self._mark_down(f"เชื่อมต่อไม่ได้: {e}")
            return False
        self._client = client
        self._backoff = self.backoff_min
        if self.link_up is not True:
            logger.info("✅ เชื่อม Redis สำเร็จ")
            self.link_up = True
            self.inbox.put(LinkStatus(True))
        return True

    def _poll_once(self):
        """RPOP 1 รายการ คืน True ถ้าได้ข้อความ (ไม่ว่าถูกต้องหรือไม่)"""
        if self.inbox.qsize() >= INBOX_SOFT_LIMIT:
            return False  # main ยังไม่ดึงคำสั่ง → ยังไม่ pop เพิ่ม
        try:
            raw = self._client.rpop(self.ctrl_key)
        except redis.RedisError as e:
            self._drop_client(f"RPOP {self.ctrl_key} ล้มเหลว: {e}")
            return False
        if raw is None:
            return False  # คิวว่าง (ไม่ใช่ error)

        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        except UnicodeDecodeError:
            _bad_msg_log(logger.warning, f"⚠️ {self.ctrl_key}: ข้อความ decode ไม่ได้ {raw[:40]!r} → ไม่ตีความ")
            return True
        if text not in VALID_COMMANDS:
            _bad_msg_log(logger.warning, f"⚠️ {self.ctrl_key}: ข้อความไม่รู้จัก {text[:40]!r} → ไม่ตีความ")
            return True

        with self._lock:
            self._seq += 1
            self._last_ctrl_seq = self._seq
            seq = self._seq
        self.inbox.put(Command(seq, text, time.monotonic()))
        return True

    def _service_request(self):
        """ส่ง S0 ที่ค้าง (ถ้ามี) คืน True ถ้ามีการทำงาน"""
        with self._lock:
            req = self._request
            if req is None:
                return False
            allowed = self._allowed_cycle == req.cycle_id
            stale = self._last_ctrl_seq > req.after_seq
            if not allowed or stale:
                self._request = None
        if not allowed:
            self.inbox.put(SendResult(req.cycle_id, "EXPIRED", "รอบปิดก่อนส่ง S0"))
            return True
        if stale:
            logger.info(f"⏭️ ไม่ส่ง S0 (cycle={req.cycle_id[:8]}) — รับ START/STOP ใหม่มาก่อนส่ง")
            self.inbox.put(SendResult(req.cycle_id, "EXPIRED", "START/STOP มาก่อนส่ง S0"))
            return True

        # 1) PING: ไม่ผ่าน = ยังไม่ได้ส่ง LPUSH แน่นอน → retry ได้
        try:
            self._client.ping()
        except redis.RedisError as e:
            if not req.failed_once:
                req.failed_once = True
                self.inbox.put(SendResult(req.cycle_id, "FAILED", f"PING: {e}"))
            self._drop_client(f"PING ก่อนส่ง S0 ล้มเหลว: {e}")
            return True

        # 2) LPUSH ครั้งเดียว: error ใด ๆ = ไม่รู้ผล → UNKNOWN ไม่ส่งซ้ำ
        with self._lock:
            self._request = None
        if not self.send_s0:  # กันซ้ำ: โหมดเก็บข้อมูลห้ามเขียน response_key ไม่ว่าทางไหน
            return True
        try:
            self._client.lpush(self.response_key, "S0")
        except redis.RedisError as e:
            logger.error(f"❓ LPUSH S0 ไม่รู้ผล (cycle={req.cycle_id[:8]}): {e} → UNKNOWN ไม่ส่งซ้ำ")
            self.inbox.put(SendResult(req.cycle_id, "UNKNOWN", str(e)))
            self._drop_client(f"LPUSH ล้มเหลว: {e}")
            return True
        logger.info(f"📤 LPUSH {self.response_key} S0 สำเร็จ (cycle={req.cycle_id[:8]})")
        self.inbox.put(SendResult(req.cycle_id, "ENQUEUED"))
        return True

    def _expire_if_revoked(self):
        """คำขอที่ถูก revoke ระหว่าง Redis ล่ม → แจ้ง EXPIRED ทันที ไม่ต้องรอเชื่อมต่อได้"""
        with self._lock:
            req = self._request
            if req is None or self._allowed_cycle == req.cycle_id:
                return
            self._request = None
        self.inbox.put(SendResult(req.cycle_id, "EXPIRED", "รอบปิดก่อนส่ง S0"))

    def _mark_down(self, error):
        _down_log(logger.warning, f"⚠️ Redis: {error} (ลองใหม่ทุก ≤{self.backoff_max:.0f}s)")
        if self.link_up is not False:
            self.link_up = False
            self.inbox.put(LinkStatus(False, error))

    def _drop_client(self, error):
        self._close_client()
        self._mark_down(error)

    def _close_client(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    def _sleep_backoff(self):
        # รอแบบปลุกได้ (มีคำขอ revoke / stop) แต่ไม่ busy-loop
        self._stop.wait(self._backoff)
        self._backoff = min(self.backoff_max, self._backoff * 2)
