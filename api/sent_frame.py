import requests
import cv2
from datetime import datetime

def send_frame(frame):
    success, buffer = cv2.imencode(".jpg", frame)

    if not success:
        print("Failed to encode frame")
        return

    files = {
        "image": ("latest.jpg", buffer.tobytes(), "image/jpeg")
    }

    data = {
        "camera_id": CAMERA_ID,
        "sent_at": datetime.now().isoformat()
    }

    try:
        requests.post(
            GO_API_FRAME_URL,
            files=files,
            data=data,
            timeout=3
        )
    except Exception as e:
        print("Send frame error:", e)