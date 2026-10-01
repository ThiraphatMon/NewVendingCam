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

# แหล่งภาพ: เลขกล้อง (0, 1, ...) หรือ path ไฟล์วิดีโอสำหรับทดสอบ
_cam = _str("CAMERA_INDEX", "0")
CAMERA_INDEX = int(_cam) if _cam.isdigit() else _cam

# 1 = ไม่มีจอ (Orange Pi / Docker) | 0 = เปิดหน้าต่าง debug (PC)
HEADLESS = _bool("HEADLESS", True)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 2 — ความไวและความเร็วในการจับของ (จูนบ่อยที่สุด เริ่มจากบนลงล่าง)
# ═════════════════════════════════════════════════════════════════════════════

# เวลาที่ของต้อง "นิ่ง" หลังลงจอด ก่อนถ่ายภาพนับ (วินาที)
#   ↓ จับไวขึ้น แต่เสี่ยงถ่ายตอนของยังเด้ง | ↑ ชัวร์ขึ้น แต่ลูกค้าหยิบเร็วจะพลาด
CAPTURE_HOLD_SEC = _float("CAPTURE_HOLD_SEC", 0.5)

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


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 3 — จังหวะเวลาของ order และการ reset
# ═════════════════════════════════════════════════════════════════════════════

# รอของตกนานแค่ไหนหลังได้ order (วินาที) — เริ่มนับใหม่ทุกครั้งที่จับของได้ 1 ชิ้น
# หมดเวลา → สรุปผล completed / anomaly / no_drop ส่งขึ้น server
ORDER_WINDOW = _int("ORDER_WINDOW", 30)

# กรณีไม่มี order: จับของได้แล้ว ไม่มีอะไรขยับเพิ่มครบกี่วินาทีจึง reset กลับ IDLE
CONFIRMED_HOLD_TIMEOUT = _int("CONFIRMED_HOLD_TIMEOUT", 20)

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

# เก็บภาพ "ช่องรับของว่าง" (clean background) ทุกกี่วินาที ตอน IDLE และไม่มี motion
CLEAN_BG_INTERVAL = _float("CLEAN_BG_INTERVAL", 0.5)

# 1 = เจอ env change → ใช้เฟรมปัจจุบันเป็น background ใหม่ทันที (พร้อมจับชิ้นถัดไป)
# 0 = พฤติกรรมเก่า (ดึง background ก่อนเจอของกลับมา)
ENV_CHANGE_REBASELINE = _bool("ENV_CHANGE_REBASELINE", True)


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
WS_RECONNECT_SEC = _float("WS_RECONNECT_SEC", 5)

# ลบภาพหลักฐานที่เก่ากว่ากี่วัน / ตรวจลบทุกกี่ชั่วโมง (กัน eMMC เต็ม)
CLEANUP_KEEP_DAYS = _int("CLEANUP_KEEP_DAYS", 3)
CLEANUP_INTERVAL_HOURS = _int("CLEANUP_INTERVAL_HOURS", 1)


# ═════════════════════════════════════════════════════════════════════════════
# หมวด 6 — ค่าคงที่ (ห้ามแก้ — พิกัด ROI ทั้งหมดอ้างอิงขนาดนี้)
# ═════════════════════════════════════════════════════════════════════════════

FRAME_W = 640
FRAME_H = 480
ROI_CONFIG_PATH = "data/roi_config.json"


# ── สรุปค่าที่ใช้งานจริง (main เรียกตอน startup) ──────────────────────────────
_SECRET_KEYS = {"API_KEY"}


def summary() -> str:
    lines = ["⚙️  Active config:"]
    for k, v in globals().items():
        if k.isupper() and not k.startswith("_"):
            shown = "***" if (k in _SECRET_KEYS and v) else v
            lines.append(f"   {k} = {shown}")
    return "\n".join(lines)
