import requests
import os
from config import CLOUD_API_URL, API_KEY
import json


def _headers():
    """สร้าง header พร้อม API Key ถ้ามีการตั้งค่า"""
    h = {}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def post_event(payload, image_path=None):
    try:
        if image_path and os.path.exists(image_path):
            # ใช้ with-statement เพื่อให้ปิด file handle อัตโนมัติ
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
        print(f"☁️ Cloud Response: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"⚠️ Cloud API Error (เน็ตอาจหลุด หรือ Golang ปิดอยู่): {e}")


def fetch_remote_roi(machine_id):
    """ดึง ROI จาก Server แล้วเขียนทับ local file (ถ้ามีข้อมูล)"""
    try:
        base_url = CLOUD_API_URL.replace("/events", "")
        roi_url = f"{base_url}/machines/{machine_id}/roi"

        resp = requests.get(roi_url, headers=_headers(), timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") != "no_config" and "roi_type" in data:
                with open("data/roi_config.json", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # เน็ตหลุดก็ปล่อยผ่านไป ใช้ของเก่าในเครื่อง
        pass


def push_default_roi(machine_id: str, local_config_path: str = "data/roi_config.json"):
    """
    ส่ง ROI default ของตู้นี้ขึ้น Server เฉพาะเมื่อ Server ยังไม่มีข้อมูล (no_config)
    เรียกครั้งเดียวตอน startup เท่านั้น
    """
    try:
        base_url = CLOUD_API_URL.replace("/events", "")
        roi_url = f"{base_url}/machines/{machine_id}/roi"

        # เช็คก่อนว่า server มี ROI อยู่แล้วหรือยัง
        check = requests.get(roi_url, headers=_headers(), timeout=5)
        if check.status_code == 200:
            data = check.json()
            if data.get("status") != "no_config":
                # Server มีค่าอยู่แล้ว ไม่ต้อง push ทับ
                print(f"[{machine_id}] ☁️ Server มี ROI อยู่แล้ว ใช้ค่าจาก Server")
                return

        # Server ยังว่าง → ส่ง local default ขึ้นไป
        if not os.path.exists(local_config_path):
            print(
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
            print(f"[{machine_id}] ✅ Push default ROI ขึ้น Server สำเร็จ")
        else:
            print(f"[{machine_id}] ⚠️ Push default ROI ล้มเหลว: {resp.status_code}")
    except Exception as e:
        print(f"[{machine_id}] ⚠️ push_default_roi error: {e}")
