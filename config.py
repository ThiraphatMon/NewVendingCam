import os
from dotenv import load_dotenv

load_dotenv()

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
FRAME_W = 640
FRAME_H = 480
MIN_AREA = 150
GROUP_DIST = 100
CONFIRM_TIME = 1
DROP_TIMEOUT = 25.0

# ระยะเวลาสูงสุดที่ระบบจะค้างอยู่ใน EVIDENCE_CAPTURED
# ก่อน force reset — ป้องกันกรณีของค้างใน ROI นานเกินไป
# ปรับเป็น 0.1 วินาที เพื่อเป็นการ track ทุก event / motion ที่เกิดขึ้น
# ปรับเป็น 15 วินาที เพื่อเป็น default ของ การตกค้างของสิ่งของ
CONFIRMED_HOLD_TIMEOUT = 15  # วินาที (ปรับได้)

# ระยะเวลาที่ confirmed item หายจาก ROI (ถูกบัง/slat) ก่อนจะถือว่าหายจริง
# ถ้ากลับมาปรากฏก่อน timeout → ยังอยู่, reset hold timeout ใหม่
# ตั้ง 5.0 วินาที = รองรับ slat เปิดนานสูงสุด ~5 วินาที
CONFIRMED_ITEM_GONE_TIMEOUT = 5.0  # วินาที (ปรับได้)

# อัตราส่วนขยายของกล่องที่ detect เทียบกับ confirmed_shape
# ถ้าใหญ่กว่านี้ → ถือว่าเป็น slat หรือสิ่งบังขนาดใหญ่ ไม่ใช่ของชิ้นใหม่
# ไม่ match กลับเข้า confirmed item → เริ่ม gone_since timer แทน
# (แยกจาก CONFIRMED_EXPAND_RATIO ที่ใช้ตรวจของชิ้นใหม่มาทับ ~1.35x)
SLAT_EXPAND_RATIO = 3.0  # เท่า (ปรับได้)

# สัดส่วนพื้นที่ blob ใน ROI area ที่ถือว่าเป็น env change (แสง/bg เปลี่ยน)
# ถ้า motion blob ใน ROI area ใดใหญ่กว่านี้ → ไม่ส่งเข้า tracker
# → restore bg_frozen_snapshot แทน (ไม่ trigger DROP_DETECTED)
# วัตถุจริงที่ตกจากตู้จะไม่มีทางใหญ่เกิน 50% ของ ROI area
MAX_BLOB_ROI_RATIO = 0.50  # สัดส่วน 0.0-1.0 (ปรับได้)

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL")
API_KEY = os.getenv("API_KEY", "")

# HEADLESS mode:
#   - ตั้งเป็น "0" ตอนทดสอบบน PC เพื่อเปิด imshow window
#   - ตั้งเป็น "1" ตอนรันบน Raspberry Pi (ไม่มีจอ)
#   - ค่า default เป็น "1" เพื่อความปลอดภัย
HEADLESS = os.getenv("HEADLESS", "1") == "1"

SEND_INTERVAL = 0.1
