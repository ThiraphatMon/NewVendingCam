import cv2
import requests
from config import CLOUD_API_URL
from api.client import _headers


def send_frame(machine_id, frame):
    success, buffer = cv2.imencode(".jpg", frame)

    if not success:
        print("⚠️ Failed to encode realtime frame")
        return False

    try:
        base_url = CLOUD_API_URL.replace("/events", "")
        url = f"{base_url}/machines/{machine_id}/realtime-image"

        files = {
            "image": ("realtime.jpg", buffer.tobytes(), "image/jpeg")
        }

        resp = requests.post(
            url,
            files=files,
            headers=_headers(),
            timeout=2,
        )

        if 200 <= resp.status_code < 300:
            return True

        print(f"⚠️ Send realtime frame failed: {resp.status_code} - {resp.text}")
        return False

    except Exception as e:
        print(f"⚠️ Send realtime frame error: {e}")
        return False