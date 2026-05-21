import os
from dotenv import load_dotenv

load_dotenv()

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
FRAME_W = 640
FRAME_H = 480
MIN_AREA = 150
GROUP_DIST = 100
CONFIRM_TIME = 1.5
DROP_TIMEOUT = 60.0

# ระยะเวลาสูงสุดที่ระบบจะค้างอยู่ใน EVIDENCE_CAPTURED
# ก่อน force reset — ป้องกันกรณีของค้างใน ROI นานเกินไป
CONFIRMED_HOLD_TIMEOUT = 20  # วินาที (ปรับได้)

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL")
API_KEY = os.getenv("API_KEY", "")

# HEADLESS mode:
#   - ตั้งเป็น "0" ตอนทดสอบบน PC เพื่อเปิด imshow window
#   - ตั้งเป็น "1" ตอนรันบน Raspberry Pi (ไม่มีจอ)
#   - ค่า default เป็น "1" เพื่อความปลอดภัย
HEADLESS = os.getenv("HEADLESS", "1") == "1"
