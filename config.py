import os
from dotenv import load_dotenv

load_dotenv()

# CAMERA_INDEX รับได้ทั้งเลขกล้อง (0,1,...) และ path ไฟล์วิดีโอ
#   - เป็นตัวเลขล้วน  → กล้องจริง
#   - ไม่ใช่ตัวเลข     → path คลิป (เช่น C:\\...\\clip.mp4)
_cam_src = os.getenv("CAMERA_INDEX", "0").strip().strip('"').strip("'")
CAMERA_INDEX = int(_cam_src) if _cam_src.isdigit() else _cam_src
FRAME_W = 640
FRAME_H = 480
MIN_AREA = 150
GROUP_DIST = 200
CONFIRM_TIME = 1
DROP_TIMEOUT = 25.0

# ระยะเวลาสูงสุดที่ระบบจะค้างอยู่ใน EVIDENCE_CAPTURED
# ก่อน force reset — ป้องกันกรณีของค้างใน ROI นานเกินไป
CONFIRMED_HOLD_TIMEOUT = 20  # วินาที (ปรับได้)

# ระยะเวลาที่ confirmed item หายจาก ROI (ถูกบัง/slat) ก่อนจะถือว่าหายจริง
# ถ้ากลับมาปรากฏก่อน timeout → ยังอยู่, reset hold timeout ใหม่
CONFIRMED_ITEM_GONE_TIMEOUT = 5  # วินาที (ปรับได้)

# สัดส่วนพื้นที่ blob ใน ROI area ที่ถือว่าเป็น env change (แสง/bg เปลี่ยน)
MAX_BLOB_ROI_RATIO = 0.60  # สัดส่วน 0.0-1.0 (ปรับได้)

# ── Order Window ──────────────────────────────────────────────────────────────
# เวลารอของตกหลังได้รับ order (วินาที)
# - reset ทุกครั้งที่ confirm item ได้
# - หมดเวลา → สรุปผล order (completed / anomaly / no_drop)
ORDER_WINDOW = int(os.getenv("ORDER_WINDOW", "30"))  # วินาที (ปรับได้)

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL")
WS_URL = os.getenv("WS_URL", "ws://localhost:5100/ws")
API_KEY = os.getenv("API_KEY", "")

# HEADLESS mode:
#   - ตั้งเป็น "0" ตอนทดสอบบน PC เพื่อเปิด imshow window
#   - ตั้งเป็น "1" ตอนรันบน Raspberry Pi (ไม่มีจอ)
HEADLESS = os.getenv("HEADLESS", "1") == "1"

SEND_INTERVAL = 1