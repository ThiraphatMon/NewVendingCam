import requests
import os
import threading
import time
import cv2
from config import CLOUD_API_URL, API_KEY, ROI_CONFIG_PATH, ROI_POLL_INTERVAL
import json
from utils.logger import get_logger, LogThrottle

logger = get_logger("client")

# ส่งภาพสดทุก 1 วิ → ตอนเน็ตหลุดจะ error ทุกวิ จึงจำกัด log ไว้ 1 ครั้งต่อ 60 วินาที
_frame_err_log = LogThrottle(60.0)


def _headers():
    """สร้าง header พร้อม API Key ถ้ามีการตั้งค่า"""
    h = {}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def post_event(payload, image_path=None):
    """
    ส่ง event ไปยัง server
    return True  → ส่งสำเร็จ (status 200-299)
    return False → ส่งไม่สำเร็จ (network error หรือ status อื่น)
    """
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as img_file:
                files = {"landed_image": img_file}
                resp = requests.post(
                    CLOUD_API_URL,
                    data=payload,
                    files=files,
                    headers=_headers(),
                    timeout=10,
                )
        else:
            resp = requests.post(
                CLOUD_API_URL,
                data=payload,
                headers=_headers(),
                timeout=10,
            )

        logger.info(f"☁️ Cloud Response: {resp.status_code} - {resp.text}")

        # ถือว่าสำเร็จเมื่อ status 2xx
        if 200 <= resp.status_code < 300:
            return True
        else:
            logger.warning(f"⚠️ Server ตอบกลับ status ผิดปกติ: {resp.status_code}")
            return False

    except Exception as e:
        logger.warning(f"⚠️ Cloud API Error (เน็ตอาจหลุด หรือ Server ปิดอยู่): {e}")
        return False


def register_machine(machine_id: str):
    """
    ลงทะเบียนตู้กับ Server โดยส่ง SYSTEM_ONLINE event ไปที่ POST /api/events
    Server จะ FirstOrCreate machine อัตโนมัติจาก machine_id ที่ส่งไป
    (Server ไม่มี POST /machines — สร้าง machine ผ่าน event endpoint เท่านั้น)
    """
    from datetime import datetime

    try:
        transaction_id = datetime.now().strftime(f"TXN-%Y%m%d-%H%M%S-{machine_id}")
        payload = {
            "machine_id": machine_id,
            "event": "SYSTEM_ONLINE",
            "transaction_id": transaction_id,
            "land_time": "",
        }
        resp = requests.post(
            CLOUD_API_URL,
            data=payload,
            headers=_headers(),
            timeout=5,
        )
        if resp.status_code == 200:
            logger.info(f"[{machine_id}] ✅ ลงทะเบียนตู้สำเร็จ (SYSTEM_ONLINE)")
        else:
            logger.warning(
                f"[{machine_id}] ⚠️ register_machine ล้มเหลว: {resp.status_code} - {resp.text}"
            )
    except Exception as e:
        logger.warning(f"[{machine_id}] ⚠️ register_machine error: {e}")


def fetch_remote_roi(machine_id):
    """ดึง ROI จาก Server แล้วเขียนทับ local file (ถ้ามีข้อมูล)"""
    try:
        base_url = CLOUD_API_URL.replace("/events", "")
        roi_url = f"{base_url}/machines/{machine_id}/roi"

        resp = requests.get(roi_url, headers=_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") != "no_config" and "roi_type" in data:
                with open(ROI_CONFIG_PATH, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def push_default_roi(machine_id: str, local_config_path: str = ROI_CONFIG_PATH):
    """
    ส่ง ROI default ของตู้นี้ขึ้น Server เฉพาะเมื่อ Server ยังไม่มีข้อมูล (no_config)
    เรียกครั้งเดียวตอน startup เท่านั้น
    """
    try:
        base_url = CLOUD_API_URL.replace("/events", "")
        roi_url = f"{base_url}/machines/{machine_id}/roi"

        check = requests.get(roi_url, headers=_headers(), timeout=5)
        if check.status_code == 200:
            data = check.json()
            if data.get("status") != "no_config":
                logger.info(f"[{machine_id}] ☁️ Server มี ROI อยู่แล้ว ใช้ค่าจาก Server")
                return

        if not os.path.exists(local_config_path):
            logger.warning(
                f"[{machine_id}] ⚠️ ไม่พบ {local_config_path} ไม่สามารถ push default ROI ได้"
            )
            return

        with open(local_config_path, "r", encoding="utf-8") as f:
            roi_data = json.load(f)

        resp = requests.put(
            roi_url,
            json=roi_data,
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=5,
        )
        if resp.status_code == 200:
            logger.info(f"[{machine_id}] ✅ Push default ROI ขึ้น Server สำเร็จ")
        else:
            logger.warning(f"[{machine_id}] ⚠️ Push default ROI ล้มเหลว: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[{machine_id}] ⚠️ push_default_roi error: {e}")


def start_roi_polling(machine_id):
    """เริ่ม background thread ดึง ROI จาก server ทุก ROI_POLL_INTERVAL วินาที"""

    def _loop():
        while True:
            try:
                fetch_remote_roi(machine_id)
            except Exception as e:
                logger.warning(f"⚠️ roi_polling_task error: {e}")
            time.sleep(ROI_POLL_INTERVAL)

    threading.Thread(target=_loop, daemon=True).start()


# ─────────────────────────────────────────────
# ภาพ realtime สำหรับ dashboard (เดิมอยู่ใน api/sent_frame.py)
# ─────────────────────────────────────────────
def send_frame(machine_id, frame):
    success, buffer = cv2.imencode(".jpg", frame)

    if not success:
        logger.warning("⚠️ Failed to encode realtime frame")
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

        _frame_err_log(logger.warning, f"⚠️ Send realtime frame failed: {resp.status_code} - {resp.text}")
        return False

    except Exception as e:
        _frame_err_log(logger.warning, f"⚠️ Send realtime frame error: {e}")
        return False
