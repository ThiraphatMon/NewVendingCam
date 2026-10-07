import requests
import os
import cv2
from config import CLOUD_API_URL, API_KEY, ROI_CONFIG_PATH, REALTIME_JPEG_QUALITY
import json
from utils.json_file import read_json, write_json_atomic
from utils.logger import get_logger, LogThrottle

logger = get_logger("client")

# ส่งภาพสดทุก 1 วิ → ตอนเน็ตหลุดจะ error ทุกวิ จึงจำกัด log ไว้ 1 ครั้งต่อ 60 วินาที
_frame_err_log = LogThrottle(60.0)


def _base_url():
    """http://host/api/events → http://host/api (ฐานของ endpoint อื่น ๆ)"""
    return CLOUD_API_URL.replace("/events", "")


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

        logger.info(f"cloud response: {resp.status_code} - {resp.text}")

        # ถือว่าสำเร็จเมื่อ status 2xx
        if 200 <= resp.status_code < 300:
            return True
        else:
            logger.warning(f"server returned unexpected status: {resp.status_code}")
            return False

    except Exception as e:
        logger.warning(f"cloud API error (network down or server off?): {e}")
        return False


def send_event(payload, image_path=None, timeout=10):
    """ส่ง event (+ ภาพ landed_image ถ้ามีไฟล์) — คืน None ถ้าสำเร็จ (2xx) ไม่งั้นข้อความ error
    ไม่ลบภาพในเครื่อง (ภาพหลักฐานเป็นของ local เสมอ)"""
    try:
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                files = {"landed_image": (os.path.basename(image_path), f, "image/jpeg")}
                resp = requests.post(CLOUD_API_URL, data=payload, files=files, headers=_headers(), timeout=timeout)
        else:
            if image_path:
                logger.warning(f"image {image_path} not found -> upload event {payload.get('event')} without image")
            resp = requests.post(CLOUD_API_URL, data=payload, headers=_headers(), timeout=timeout)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    if 200 <= resp.status_code < 300:
        return None
    return f"HTTP {resp.status_code}: {resp.text[:200]}"


def register_machine(machine_id: str):
    """
    ลงทะเบียนตู้กับ Server โดยส่ง SYSTEM_ONLINE event ไปที่ POST /api/events
    Server จะ FirstOrCreate machine อัตโนมัติจาก machine_id ที่ส่งไป
    (Server ไม่มี POST /machines — สร้าง machine ผ่าน event endpoint เท่านั้น)
    คืน True ถ้าสำเร็จ (2xx) — ผู้เรียกลองใหม่เอง (api/cloud.py backoff)
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
        if 200 <= resp.status_code < 300:
            logger.info(f"[{machine_id}] machine registered (SYSTEM_ONLINE)")
            return True
        logger.warning(
            f"[{machine_id}] register_machine failed: {resp.status_code} - {resp.text[:200]}"
        )
    except Exception as e:
        logger.warning(f"[{machine_id}] register_machine error: {e}")
    return False


def fetch_remote_roi(machine_id, local_config_path=ROI_CONFIG_PATH):
    """ดึง ROI จาก Server แล้วเขียนทับ local file — เฉพาะเมื่อข้อมูลต่างจากไฟล์เดิม
    (ลดการเขียน eMMC ทุก 10 วิ และ ROIManager จะ reload เฉพาะตอนเปลี่ยนจริง)"""
    try:
        roi_url = f"{_base_url()}/machines/{machine_id}/roi"

        resp = requests.get(roi_url, headers=_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") != "no_config" and "roi_type" in data:
                if read_json(local_config_path) != data:
                    write_json_atomic(local_config_path, data)
                    logger.info(f"[{machine_id}] new ROI from server -> updated {local_config_path}")
    except Exception:
        pass


def push_default_roi(machine_id: str, local_config_path: str = ROI_CONFIG_PATH):
    """
    ส่ง ROI default ของตู้นี้ขึ้น Server เฉพาะเมื่อ Server ยังไม่มีข้อมูล (no_config)
    ทำตอน startup — คืน True เมื่อจบงาน (Server มี ROI แล้ว / push สำเร็จ / ไม่มีไฟล์ในเครื่อง)
    False = เน็ต/Server มีปัญหา → ผู้เรียกลองใหม่ (api/cloud.py backoff)
    ถาม Server ไม่สำเร็จ (ไม่ใช่ 200) → ไม่ push (กันทับ ROI ที่ Server มีอยู่แล้ว)
    """
    try:
        roi_url = f"{_base_url()}/machines/{machine_id}/roi"

        check = requests.get(roi_url, headers=_headers(), timeout=5)
        if check.status_code != 200:
            logger.warning(f"[{machine_id}] cannot get ROI from server: {check.status_code}")
            return False
        data = check.json()
        if data.get("status") != "no_config":
            logger.info(f"[{machine_id}] server already has ROI -> use server ROI")
            return True

        if not os.path.exists(local_config_path):
            logger.warning(
                f"[{machine_id}] {local_config_path} not found -> cannot push default ROI"
            )
            return True

        with open(local_config_path, "r", encoding="utf-8") as f:
            roi_data = json.load(f)

        resp = requests.put(
            roi_url,
            json=roi_data,
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=5,
        )
        if 200 <= resp.status_code < 300:
            logger.info(f"[{machine_id}] default ROI pushed to server")
            return True
        logger.warning(f"[{machine_id}] push default ROI failed: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[{machine_id}] push_default_roi error: {e}")
    return False


# ─────────────────────────────────────────────
# ภาพ realtime สำหรับ dashboard (เดิมอยู่ใน api/sent_frame.py)
# ─────────────────────────────────────────────
def send_frame(machine_id, frame, quality=None):
    """ส่งภาพสดขนาดเดิม (640x480 — เว็บใช้วาด ROI) ที่คุณภาพ REALTIME_JPEG_QUALITY (เฉพาะภาพสด)"""
    q = REALTIME_JPEG_QUALITY if quality is None else quality
    success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(q)])

    if not success:
        logger.warning("failed to encode live image")
        return False

    try:
        url = f"{_base_url()}/machines/{machine_id}/realtime-image"

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

        _frame_err_log(logger.warning, f"send live image failed: {resp.status_code} - {resp.text}")
        return False

    except Exception as e:
        _frame_err_log(logger.warning, f"send live image error: {e}")
        return False
