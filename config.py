import os
from dotenv import load_dotenv

# โหลดตัวแปรจากไฟล์ .env
load_dotenv()

CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
FRAME_W = 640
FRAME_H = 480
MIN_AREA = 150
GROUP_DIST = 100
STILL_DIST = 4
CONFIRM_TIME = 3.0
RESET_DELAY = 5.0
DROP_TIMEOUT = 10.0

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL", "http://152.42.198.78:5100/api/events")
API_KEY = os.getenv("API_KEY", "")
