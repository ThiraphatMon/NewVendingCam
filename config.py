import os
from dotenv import load_dotenv

load_dotenv()

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
FRAME_W = 640
FRAME_H = 480
MIN_AREA = 150
GROUP_DIST = 100
STILL_DIST = 4
CONFIRM_TIME = 3.0
DROP_TIMEOUT = 10.0

# [CHANGE 2] ระยะเวลาสูงสุดที่ระบบจะค้างอยู่ใน EVIDENCE_CAPTURED
# ก่อน force reset — ป้องกันกรณีของค้างใน ROI นานเกินไป
CONFIRMED_HOLD_TIMEOUT = 20.0  # วินาที (ปรับได้)

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL", "http://152.42.198.78:5100/api/events")
API_KEY = os.getenv("API_KEY", "")
