import os
from dotenv import load_dotenv

load_dotenv()

# CAMERA_INDEX รับได้ทั้งเลขกล้อง (0,1,...) และ path ไฟล์วิดีโอ
_cam_src = os.getenv("CAMERA_INDEX", "0").strip().strip('"').strip("'")
CAMERA_INDEX = int(_cam_src) if _cam_src.isdigit() else _cam_src

FRAME_W = 640
FRAME_H = 480

MIN_AREA = int(os.getenv("MIN_AREA", "150"))

# ── Grouping (รวม contour ที่แตกของวัตถุเดียวกลับเป็นกล่องเดียว) ────────────────
# GROUP_DIST : ระยะห่าง (px) ระหว่างขอบกล่องที่ยังรวมเป็นชิ้นเดียว (โหมด distance)
#   - เล็ก (~40-60) → เชื่อมเฉพาะชิ้นส่วนของวัตถุเดียว, ของ 2 ชิ้นที่ตกห่างยังแยกกัน
#   - ใหญ่ (~100+) → เสี่ยง 2 ชิ้นกลายเป็นก้อนเดียว
GROUP_DIST = int(os.getenv("GROUP_DIST", "60"))

# GROUP_MODE : "distance" = รวมกล่องที่ขอบห่าง < GROUP_DIST | "overlap" = รวมเฉพาะที่ซ้อนทับ
GROUP_MODE = os.getenv("GROUP_MODE", "distance").strip().lower()

# ระยะ (px) ที่ยอมให้กล่องซ้อน/ชิดกันแล้วรวมเป็นชิ้นเดียว (โหมด overlap)
GROUP_OVERLAP_PAD = int(os.getenv("GROUP_OVERLAP_PAD", "4"))

DROP_TIMEOUT = 25.0

# ── Capture responsiveness (จับของให้ไว = "ของหยุดนิ่ง" คือ "ตกถึงที่แล้ว") ──────
# ของที่กำลังตกจะเคลื่อนที่ (ไม่นิ่ง) → พอถึงที่แล้วจะนิ่ง = จังหวะที่ควร capture

# LANDING_STABLE_FRAMES : จำนวนเฟรมที่ centroid ต้องนิ่งจึงถือว่า "ลงจอด"
#   - น้อยลง (2-3) → จับไวขึ้น แต่เสี่ยงจับตอนของเด้งกลางอากาศ
#   - มากขึ้น (6-8) → มั่นใจว่านิ่งจริง แต่ช้าลง
LANDING_STABLE_FRAMES = int(os.getenv("LANDING_STABLE_FRAMES", "4"))

# CAPTURE_HOLD_SEC : เวลาที่ต้องนิ่งเพิ่ม "หลัง" ลงจอดก่อน capture (0 = จับทันทีที่นิ่ง)
CAPTURE_HOLD_SEC = float(os.getenv("CAPTURE_HOLD_SEC", "2"))

# MIN_PRESENCE_SEC : เวลาขั้นต่ำที่ object ต้องอยู่ใน ROI ก่อน capture (กัน noise แวบเดียว)
MIN_PRESENCE_SEC = float(os.getenv("MIN_PRESENCE_SEC", "0.2"))

# CENTROID_STABLE_DIST : ระยะ (px) ที่ centroid ขยับได้ต่อเฟรมแล้วยังถือว่า "นิ่ง"
CENTROID_STABLE_DIST = int(os.getenv("CENTROID_STABLE_DIST", "10"))

# ── Detection tuning ──────────────────────────────────────────────────────────
# MOT_THRESH : ความไวการจับ motion (ค่า diff ของสีเทาที่ถือว่า "เปลี่ยน")
#   - ต่ำลง (5-18) → จับของชิ้นเล็ก/สีใกล้พื้นหลังได้ แต่ noise/แสงพุ่ง
#   - สูงขึ้น (25-30) → เงียบขึ้น กรอบแนบของจริง แต่ของจาง ๆ อาจหลุด
MOT_THRESH = int(os.getenv("MOT_THRESH", "25"))

# morphology kernel (เลขคี่). OPEN ลบ noise → DILATE เชื่อม mask ชิ้นเดียวที่ขาดให้ตัน
MORPH_OPEN_KSIZE = int(os.getenv("MORPH_OPEN_KSIZE", "5"))     # 0=ปิด
MORPH_DILATE_KSIZE = int(os.getenv("MORPH_DILATE_KSIZE", "5"))  # 0=ปิด
MORPH_DILATE_ITER = int(os.getenv("MORPH_DILATE_ITER", "2"))    # 0=ปิด

# ระยะสูงสุด (px) ที่ tracker ยอม match detection เข้ากับ object เดิม
TRACK_MATCH_DIST = int(os.getenv("TRACK_MATCH_DIST", "150"))

# ── Re-baseline on capture ─────────────────────────────────────────────────────
# capture ได้ → เอาเฟรมปัจจุบันทั้งภาพเป็น background ใหม่ → motion mask ว่างเปล่าทันที
# ของชิ้นถัดไป (แม้ตกทับที่เดิม) จะเป็น motion ใหม่ → นับเป็นชิ้นใหม่ได้
# กรอบเขียว confirm ค้างไว้ที่เดิม (overlay จาก captured_items) | 0 = ปิด (ไม่แนะนำ)
REBASELINE_ON_CAPTURE = os.getenv("REBASELINE_ON_CAPTURE", "1") == "1"

# ถ้ามี order → ห้ามนับเกินจำนวนที่สั่ง (กัน over-count 1→2→3)
CAP_COUNT_TO_ORDER_QTY = os.getenv("CAP_COUNT_TO_ORDER_QTY", "1") == "1"

# ระยะเวลาสูงสุดใน EVIDENCE_CAPTURED ก่อน reset (กรณีไม่มี order)
# "รอว่าไม่มีของตกเพิ่มอีกแล้วจริง" — ทุกครั้งที่มี motion/ของใหม่ ตัวนับถูกรีเซ็ต
CONFIRMED_HOLD_TIMEOUT = int(os.getenv("CONFIRMED_HOLD_TIMEOUT", "20"))  # วินาที

# สัดส่วนพื้นที่ blob ใน ROI area ที่ถือว่าเป็น env change (แสง/bg เปลี่ยน)
MAX_BLOB_ROI_RATIO = 0.40

# ── Order Window ──────────────────────────────────────────────────────────────
# เวลารอของตกหลังได้รับ order (วินาที) — reset ทุกครั้งที่ confirm item
# หมดเวลา → สรุปผล order (completed / anomaly / no_drop)
ORDER_WINDOW = int(os.getenv("ORDER_WINDOW", "30"))

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL")
WS_URL = os.getenv("WS_URL", "ws://localhost:5100/ws")
API_KEY = os.getenv("API_KEY", "")

# HEADLESS: "0" = เปิด imshow window (ทดสอบบน PC) | "1" = ไม่มีจอ (Raspberry Pi)
HEADLESS = os.getenv("HEADLESS", "1") == "1"

SEND_INTERVAL = 1
