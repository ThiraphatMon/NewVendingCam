"""
config.py — ค่าตั้งทั้งหมดของระบบ (อ่านจาก .env)

วิธีใช้สำหรับ admin
  - ปรับค่าที่ไฟล์ .env เท่านั้น (ไม่ต้องแก้ไฟล์นี้) แล้ว restart โปรแกรม / container
  - ค่าเรียงตามความสำคัญ: หมวด 1 ต้องตั้งทุกตู้ → หมวด 2 จูนบ่อย → ... → หมวด 6 ห้ามแก้
  - ค่าที่ไม่ได้ใส่ใน .env จะใช้ค่า default ในวงเล็บ
  - ตอนเริ่มโปรแกรมจะ print ค่าที่ใช้งานจริงทั้งหมด (ดูได้จาก `docker compose logs`)

ตัวย่อในคอมเมนต์
  ↑ = เพิ่มค่า   ↓ = ลดค่า   px = pixel บนภาพ 640x480
"""

import os
from dotenv import load_dotenv

load_dotenv()


# ── helper อ่านค่าจาก .env (แจ้ง error ชัด ๆ ถ้า admin ใส่ค่าผิดรูปแบบ) ─────────────
def _str(key, default):
    return os.getenv(key, default).strip().strip('"').strip("'")


def _int(key, default):
    raw = _str(key, str(default))
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"❌ .env: {key}={raw!r} ต้องเป็นจำนวนเต็ม")


def _float(key, default):
    raw = _str(key, str(default))
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"❌ .env: {key}={raw!r} ต้องเป็นตัวเลข")


def _bool(key, default):
    return _str(key, "1" if default else "0") in ("1", "true", "True", "yes")


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 1 — ตัวตนของตู้และการเชื่อมต่อ (ต้องตั้งทุกตู้)
# ═════════════════════════════════════════════════════════════════════════════

# ชื่อตู้ ต้องไม่ซ้ำกันในระบบ (ใช้กรอง order และแยกข้อมูลบน server)
MACHINE_ID = _str("MACHINE_ID_DEFAULT", "VENDING_01")

# endpoint รับ event เช่น http://<server>:5100/api/events
CLOUD_API_URL = _str("CLOUD_API_URL", "")

# WebSocket รับ order เช่น ws://<server>:5100/ws
WS_URL = _str("WS_URL", "ws://localhost:5100/ws")

# key ยืนยันตัวตนกับ server (เว้นว่างถ้า server ไม่ใช้)
API_KEY = _str("API_KEY", "")

# แหล่งภาพ: เลขกล้อง (0, 1, ...), อุปกรณ์กล้อง (/dev/video0) หรือ path ไฟล์วิดีโอสำหรับทดสอบ
#   ตัวเลข / /dev/... = กล้องจริง | อย่างอื่น = ไฟล์วิดีโอ (เล่นตาม FPS จริงและวนซ้ำ)
_cam = _str("CAMERA_INDEX", "0")
CAMERA_INDEX = int(_cam) if _cam.isdigit() else _cam

# 1 = ไม่มีจอ (Orange Pi / Docker) | 0 = เปิดหน้าต่าง debug (PC)
HEADLESS = _bool("HEADLESS", True)

# แหล่งคำสั่ง START/STOP
#   redis    = รับจาก Redis (ใช้งานจริง)
#   keyboard = ทดสอบบน PC ไม่ต่อ Redis: กด s = START, x = STOP บนหน้าต่าง (ต้อง HEADLESS=0)
#   (โหมด redis + HEADLESS=0 ก็กด s/x ได้เช่นกัน)
CONTROL_MODE = _str("CONTROL_MODE", "redis").lower()
if CONTROL_MODE not in ("redis", "keyboard"):
    raise SystemExit(f"❌ .env: CONTROL_MODE={CONTROL_MODE!r} ต้องเป็น redis หรือ keyboard")
if CONTROL_MODE == "keyboard" and HEADLESS:
    raise SystemExit("❌ .env: CONTROL_MODE=keyboard ต้องใช้คู่กับ HEADLESS=0 (ต้องมีหน้าต่างให้กดปุ่ม)")

# Redis ของ controller (อยู่บนบอร์ดเดียวกัน) — ชื่อ key / DB ต้องตรงกับโปรแกรมเก่า
#   Docker ใช้ network_mode: host จึงใช้ 127.0.0.1 ได้เหมือนรันตรง
REDIS_HOST = _str("REDIS_HOST", "127.0.0.1")
REDIS_PORT = _int("REDIS_PORT", 6379)
REDIS_DB = _int("REDIS_DB", 0)
REDIS_PASSWORD = _str("REDIS_PASSWORD", "")
REDIS_CTRL_KEY = _str("REDIS_CTRL_KEY", "CTRL")          # รับ START/STOP (RPOP)
REDIS_RESPONSE_KEY = _str("REDIS_RESPONSE_KEY", "CAMERA")  # ส่ง S0 (LPUSH)
# timeout ต่อ Redis (วินาที) — Redis ค้างต้องไม่ทำให้กล้อง/STOP ค้าง
REDIS_CONNECT_TIMEOUT_SEC = _float("REDIS_CONNECT_TIMEOUT_SEC", 1.0)
REDIS_SOCKET_TIMEOUT_SEC = _float("REDIS_SOCKET_TIMEOUT_SEC", 1.0)

# 1 = เปิดส่งข้อมูลขึ้น cloud (register, ROI polling, ภาพสด, retry queue) | 0 = ทำงาน local อย่างเดียว
CLOUD_ENABLED = _bool("CLOUD_ENABLED", False)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 2 — ความไวและความเร็วในการจับของ (จูนบ่อยที่สุด เริ่มจากบนลงล่าง)
# ═════════════════════════════════════════════════════════════════════════════

# เวลาที่ของต้อง "นิ่ง" หลังลงจอด ก่อนถ่ายภาพนับ (วินาที)
#   ↓ จับไวขึ้น แต่เสี่ยงถ่ายตอนของยังเด้ง | ↑ ชัวร์ขึ้น แต่ลูกค้าหยิบเร็วจะพลาด
CAPTURE_HOLD_SEC = _float("CAPTURE_HOLD_SEC", 1.5)

# ความไวต่อการเปลี่ยนแปลงของภาพ (ค่าความต่างสีเทา 0-255)
#   ↓ (15-20) จับของสีจาง/กลืนพื้นได้ แต่ noise เยอะ | ↑ (30+) เงียบขึ้น แต่ของจางอาจหลุด
MOT_THRESH = _int("MOT_THRESH", 25)

# พื้นที่ก้อนเล็กสุดที่นับว่าเป็นของ (px²) — เล็กกว่านี้ถือเป็น noise
#   ของชิ้นเล็กหลุด → ↓ | จุด noise ถูกนับ → ↑
MIN_AREA = _int("MIN_AREA", 150)

# ก้อนที่ใหญ่เกินสัดส่วนนี้ของ ROI = แสง/พื้นหลังเปลี่ยน (env change) ไม่ใช่ของ (0.0-1.0)
#   ⚠ ของชิ้นใหญ่กว่าค่านี้จะไม่ถูกนับ — ถ้าตู้ขายของใหญ่ให้ ↑ หรือขยาย ROI
MAX_BLOB_ROI_RATIO = _float("MAX_BLOB_ROI_RATIO", 0.30)

# จำนวนเฟรมติดกันที่ตำแหน่งของต้องนิ่ง จึงถือว่า "ลงจอดแล้ว" (30 เฟรม ≈ 1 วินาที)
LANDING_STABLE_FRAMES = _int("LANDING_STABLE_FRAMES", 4)

# ระยะที่จุดกึ่งกลางของขยับได้ต่อเฟรมแล้วยังนับว่านิ่ง (px)
#   ⚠ ถ้า ↓ CAPTURE_HOLD_SEC ต่ำมาก ควร ↓ ค่านี้ด้วย (3-5) กันนับว่านิ่งระหว่างยังตก
CENTROID_STABLE_DIST = _int("CENTROID_STABLE_DIST", 10)

# ความนิ่งแบบเข้ม (tracker): 1 = ขยับเกิน CENTROID_STABLE_DIST ระหว่างรอถ่าย → เริ่มนับนิ่งใหม่
#   และวัตถุที่หายไปแล้วกลับมาต้องนิ่งครบ LANDING_STABLE_FRAMES ใหม่ | 0 = แบบเดิม
#   (คลิปทดสอบ: เปิดแล้ว START→S0 ช้าลง ~0.15s ผลทุกสถานการณ์เหมือนเดิม)
STRICT_STABILITY = _bool("STRICT_STABILITY", True)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 3 — รอบ START–STOP
# ═════════════════════════════════════════════════════════════════════════════

# ไม่มี STOP ภายในกี่วินาทีหลัง START → ปิดรอบเอง (outcome TIMEOUT ไม่ส่งอะไรกลับ เหมือนตัวเก่า)
CYCLE_TIMEOUT_SEC = _float("CYCLE_TIMEOUT_SEC", 300)

# ── ค่าของระบบ order เดิม: ไม่มีผลในโหมด START–STOP (เก็บไว้ให้ .env เก่ายังอ่านได้) ──
#   ตั้งไว้ใน .env → ตอน startup จะ log เตือน (ดู inactive_warnings ท้ายไฟล์)

# รอของตกนานแค่ไหนหลังได้ order (วินาที) — เริ่มนับใหม่ทุกครั้งที่จับของได้ 1 ชิ้น
# หมดเวลา → สรุปผล completed / anomaly / no_drop ส่งขึ้น server
ORDER_WINDOW = _int("ORDER_WINDOW", 30)

# กรณีไม่มี order: จับของได้แล้ว ไม่มีอะไรขยับเพิ่มครบกี่วินาทีจึง reset กลับ IDLE
CONFIRMED_HOLD_TIMEOUT = _int("CONFIRMED_HOLD_TIMEOUT", 30)

# กรณีไม่มี order: เห็นการเคลื่อนไหวแต่ไม่มีของนิ่งเลยนานกี่วินาที → ส่ง NO_DROP แล้ว reset
DROP_TIMEOUT = _float("DROP_TIMEOUT", 25.0)

# 1 = มี order แล้วห้ามนับเกินจำนวนที่สั่ง (กันนับซ้ำ)
#   ⚠ เปิดไว้จะตรวจไม่พบกรณีตู้ปล่อยของเกิน order (ได้ completed แทน anomaly)
CAP_COUNT_TO_ORDER_QTY = _bool("CAP_COUNT_TO_ORDER_QTY", True)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 4 — ขั้นสูง: การแยกวัตถุและ background (ไม่ควรแตะถ้าไม่จำเป็น)
# ═════════════════════════════════════════════════════════════════════════════

# รวมก้อนที่แตกจากของชิ้นเดียวกลับเป็นชิ้นเดียว
#   GROUP_MODE: "distance" = รวมก้อนที่ขอบห่างกัน < GROUP_DIST | "overlap" = รวมเฉพาะก้อนที่ซ้อนกัน
#   ของ 2 ชิ้นถูกนับเป็นชิ้นเดียว → ↓ GROUP_DIST | ของชิ้นเดียวถูกนับเป็น 2 → ↑
GROUP_MODE = _str("GROUP_MODE", "distance").lower()
GROUP_DIST = _int("GROUP_DIST", 60)
GROUP_OVERLAP_PAD = _int("GROUP_OVERLAP_PAD", 4)

# morphology ทำความสะอาด mask (เลขคี่, 0 = ปิด)
#   OPEN ลบจุด noise → DILATE เชื่อมก้อนที่ขาดให้ตัน
MORPH_OPEN_KSIZE = _int("MORPH_OPEN_KSIZE", 5)
MORPH_DILATE_KSIZE = _int("MORPH_DILATE_KSIZE", 5)
MORPH_DILATE_ITER = _int("MORPH_DILATE_ITER", 2)

# tracker: ระยะไกลสุดที่ยังถือว่าเป็นของชิ้นเดิมจากเฟรมก่อน (px)
TRACK_MATCH_DIST = _int("TRACK_MATCH_DIST", 150)

# tracker: ก้อนหายไปได้กี่เฟรมก่อนลบทิ้ง (กันภาพกระพริบ)
GHOST_FRAME_TOLERANCE = _int("GHOST_FRAME_TOLERANCE", 2)

# ความเร็วที่ background ปรับตามแสงตอนปกติ (0-1, ↑ = ปรับเร็ว)
BG_LEARNING_RATE = _float("BG_LEARNING_RATE", 0.1)

# หลัง reset: ช่วงพักที่ไม่รับ motion ใหม่ (วินาที) และความเร็วปรับ bg ระหว่างพัก
# (ให้ภาพมือลูกค้าที่ยังค้างในเฟรมถูกกลืนเข้า background ก่อน)
RESET_GRACE_SEC = _float("RESET_GRACE_SEC", 1.5)
BG_RELEARN_RATE = _float("BG_RELEARN_RATE", 0.3)

# เก็บภาพ "ช่องรับของว่าง" (clean_bg = เฟรมปัจจุบัน) ทุกกี่วินาที ตอนไม่มีรอบและ ROI นิ่ง
#   START ใช้ clean_bg ที่เก็บหลังการเปลี่ยนแปลงครั้งล่าสุดเป็นพื้นหลังของรอบ (ไม่มี → เฟรมปัจจุบัน)
CLEAN_BG_INTERVAL = _float("CLEAN_BG_INTERVAL", 0.5)
# "ROI นิ่ง" = พิกเซลใน ROI ที่เปลี่ยนจากเฟรมก่อนหน้า ไม่เกินสัดส่วนนี้ของพื้นที่ ROI (0.002 = 0.2%)
#   ติดกันกี่เฟรม — ยอม noise ของกล้อง/การบีบอัดภาพ แต่ของที่กำลังตก/มือจะเกินเสมอ
#   ใช้ร่วมกับ: watch mode จบ, ตั้งพื้นหลังรอบใหม่หลัง env change สงบ
#   (คลิปทดสอบ: ถาดนิ่งเปลี่ยนสูงสุด 42 px จาก ROI 34,112 px = 0.12%)
#   ⚠ log "baseline ไม่แน่นอน" ตอน START ทั้งที่ถาดนิ่ง → ↑ ratio เล็กน้อย | มือขยับช้าถูกนับว่านิ่ง → ↓
CLEAN_BG_MAX_MOTION_RATIO = _float("CLEAN_BG_MAX_MOTION_RATIO", 0.002)
CLEAN_BG_STABLE_FRAMES = _int("CLEAN_BG_STABLE_FRAMES", 5)

# รอบ ACTIVE: env change ค้างแต่ ROI นิ่งครบ CLEAN_BG_STABLE_FRAMES → ตั้งพื้นหลังของรอบใหม่เป็นเฟรมนั้น
#   (เช่น START ตอน slat ยังเปิด แล้ว slat ปิด) 0 = ปิด (มองไม่เห็นอะไรจนจบรอบถ้า env change ค้าง)
ENV_SETTLE_REBASELINE = _bool("ENV_SETTLE_REBASELINE", True)

# แยก "ลูกค้าหยิบของออก" กับ "สินค้าตก" ก่อนยืนยันในรอบ (core/removal.py)
#   ของวางอยู่ก่อน START แล้วถูกหยิบออกระหว่างรอบ → รอยที่ของเคยอยู่ไม่ถูกยืนยันเป็นสินค้า (anomaly POSSIBLE_REMOVAL)
REMOVAL_CHECK = _bool("REMOVAL_CHECK", True)
# ความคมของ patch (ขอบ/ลาย) ลดเหลือต่ำกว่าสัดส่วนนี้ของพื้นหลังรอบ = "ดูเหมือนของหายไป"
#   (คลิปทดสอบ: ของตก ×1.52, หยิบออก ×0.40) | ของจริงถูกมองว่าหยิบออก → ↓ | รอยหยิบออกถูกยืนยัน → ↑ (ไม่เกิน 1.0)
REMOVAL_EDGE_RATIO = _float("REMOVAL_EDGE_RATIO", 0.6)
# patch ปัจจุบันต่างจาก "ฉากนิ่งก่อนหน้า" น้อยกว่าสัดส่วนนี้ของความต่างจากพื้นหลังรอบ = กลับไปเป็นฉากเดิม
REMOVAL_MATCH_RATIO = _float("REMOVAL_MATCH_RATIO", 0.5)
# ดูเหมือนหยิบออกแต่ไม่มีฉากก่อนหน้ายืนยัน (ไม่แน่ใจ): 0 = ไม่ส่ง S0 + anomaly (กัน S0 ผิด) | 1 = ยืนยันตามปกติ
REMOVAL_UNCERTAIN_SEND_S0 = _bool("REMOVAL_UNCERTAIN_SEND_S0", False)
# จำฉากนิ่งย้อนหลังกี่ฉาก (ภาพ gray 640x480 ฉากละ ~300KB)
SCENE_HISTORY_SIZE = _int("SCENE_HISTORY_SIZE", 10)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 5 — ระบบและการดูแลเครื่อง
# ═════════════════════════════════════════════════════════════════════════════

# ส่งภาพสดขึ้น dashboard ทุกกี่วินาที (0 = ปิด)
SEND_INTERVAL = _float("SEND_INTERVAL", 1)

# ดึง ROI จาก server ทุกกี่วินาที / เช็คไฟล์ ROI ในเครื่องว่าเปลี่ยนไหมทุกกี่วินาที
ROI_POLL_INTERVAL = _float("ROI_POLL_INTERVAL", 10)
ROI_CHECK_INTERVAL = _float("ROI_CHECK_INTERVAL", 5)

# ส่ง event ที่ค้าง (เน็ตหลุด) ซ้ำทุกกี่วินาที
RETRY_INTERVAL = _int("RETRY_INTERVAL", 60)

# รอกี่วินาทีก่อนต่อใหม่ เมื่อกล้อง / WebSocket หลุด
CAMERA_RECONNECT_SEC = _float("CAMERA_RECONNECT_SEC", 2)
# กล้องค้าง: ไม่มีเฟรมใหม่นานเกินกี่วินาที → ถือเป็นกล้องหลุด (รอบ ACTIVE → BLOCKED) แล้วเปิดกล้องใหม่
CAMERA_STALL_SEC = _float("CAMERA_STALL_SEC", 3.0)
WS_RECONNECT_SEC = _float("WS_RECONNECT_SEC", 5)

# ลบภาพหลักฐานที่เก่ากว่ากี่วัน / ตรวจลบทุกกี่ชั่วโมง (กัน eMMC เต็ม)
CLEANUP_KEEP_DAYS = _int("CLEANUP_KEEP_DAYS", 3)
CLEANUP_INTERVAL_HOURS = _int("CLEANUP_INTERVAL_HOURS", 1)

# ฐานข้อมูลรอบ / การยืนยัน / ยอดรายวัน (ต้องอยู่ใน volume ที่คงอยู่ ห้ามลบ)
STATE_DB_PATH = _str("STATE_DB_PATH", "data/vending_state.sqlite3")

# timezone ของยอดรายวันและ log item drop (ไม่ขึ้นกับเวลาของเครื่อง)
COUNT_TIMEZONE = _str("COUNT_TIMEZONE", "Asia/Bangkok")
try:
    from zoneinfo import ZoneInfo

    ZoneInfo(COUNT_TIMEZONE)
except Exception:
    raise SystemExit(f"❌ .env: COUNT_TIMEZONE={COUNT_TIMEZONE!r} ไม่รู้จัก (ต้องติดตั้ง tzdata)")

# โฟลเดอร์ log ยอดรายวัน (1 ไฟล์ต่อวัน: YYYY-MM-DD.log)
DAILY_LOG_DIR = _str("DAILY_LOG_DIR", "logs/item_drops")

# ภาพหลักฐานความผิดปกติ (นอกรอบ / ของเพิ่มหลังยืนยัน): ถ่ายได้ไม่เกิน 1 ภาพต่อกี่วินาที / ต่อชั่วโมง
ANOMALY_MIN_INTERVAL_SEC = _float("ANOMALY_MIN_INTERVAL_SEC", 30)
ANOMALY_MAX_PER_HOUR = _int("ANOMALY_MAX_PER_HOUR", 20)
# เก็บภาพความผิดปกติกี่วัน (แยกจาก CLEANUP_KEEP_DAYS ของภาพที่ยืนยัน)
ANOMALY_KEEP_DAYS = _int("ANOMALY_KEEP_DAYS", 3)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 6 — ค่าคงที่ (ห้ามแก้ — พิกัด ROI ทั้งหมดอ้างอิงขนาดนี้)
# ═════════════════════════════════════════════════════════════════════════════

FRAME_W = 640
FRAME_H = 480
ROI_CONFIG_PATH = "data/roi_config.json"
EVIDENCE_DIR = "evidence_images"


# ── ค่าที่ตั้งใน .env แต่ไม่มีผล (main log เตือนตอน startup) ──────────────────────
# ระบบ order เดิม (WebSocket) ไม่ถูกเริ่มในโหมด START–STOP เลย
_ORDER_ONLY_KEYS = (
    "WS_URL", "WS_RECONNECT_SEC", "ORDER_WINDOW", "CONFIRMED_HOLD_TIMEOUT", "DROP_TIMEOUT",
    "CAP_COUNT_TO_ORDER_QTY",
)
# มีผลเฉพาะ CLOUD_ENABLED=1
_CLOUD_ONLY_KEYS = ("CLOUD_API_URL", "API_KEY", "SEND_INTERVAL", "ROI_POLL_INTERVAL", "RETRY_INTERVAL")
# มีผลเฉพาะ CONTROL_MODE=redis
_REDIS_ONLY_KEYS = (
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD", "REDIS_CTRL_KEY", "REDIS_RESPONSE_KEY",
    "REDIS_CONNECT_TIMEOUT_SEC", "REDIS_SOCKET_TIMEOUT_SEC",
)


def inactive_warnings(environ=None):
    """รายการข้อความเตือน: ค่าที่ admin ตั้งไว้ใน .env (ไม่ว่าง) แต่ไม่มีผลกับโหมดที่รันอยู่"""
    env = os.environ if environ is None else environ
    cloud = env.get("CLOUD_ENABLED", "0").strip().strip('"').strip("'") in ("1", "true", "True", "yes")
    mode = (env.get("CONTROL_MODE") or "redis").strip().strip('"').strip("'").lower()
    groups = [(_ORDER_ONLY_KEYS, "ระบบ order เดิม ไม่ใช้ในโหมด START–STOP")]
    if not cloud:
        groups.append((_CLOUD_ONLY_KEYS, "มีผลเฉพาะ CLOUD_ENABLED=1"))
    if mode != "redis":
        groups.append((_REDIS_ONLY_KEYS, "มีผลเฉพาะ CONTROL_MODE=redis"))
    out = []
    for keys, why in groups:
        found = [k for k in keys if env.get(k, "").strip()]
        if found:
            out.append(f"⚠️ .env: {', '.join(found)} ไม่มีผล ({why}) — ลบออกหรือใส่ # ได้")
    return out


# ── สรุปค่าที่ใช้งานจริง (main เรียกตอน startup) ──────────────────────────────
_SECRET_KEYS = {"API_KEY", "REDIS_PASSWORD"}


def summary() -> str:
    lines = ["⚙️  Active config:"]
    for k, v in globals().items():
        if k.isupper() and not k.startswith("_"):
            shown = "***" if (k in _SECRET_KEYS and v) else v
            lines.append(f"   {k} = {shown}")
    return "\n".join(lines)
