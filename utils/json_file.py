"""
utils/json_file.py — อ่าน/เขียนไฟล์ JSON อย่างปลอดภัย (ใช้กับ data/roi_config.json)
"""

import json
import os


def read_json(path):
    """อ่าน JSON จากไฟล์ คืน None ถ้าไม่มีไฟล์หรืออ่านไม่ได้"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json_atomic(path, data):
    """เขียน JSON แบบ atomic: เขียนไฟล์ .tmp ให้เสร็จก่อน แล้วค่อย os.replace ทับของเดิม
    → ไฟดับ / อ่านพร้อมกันระหว่างเขียน จะไม่เจอไฟล์ครึ่ง ๆ (ได้ของเก่าหรือของใหม่ครบ ๆ เท่านั้น)
    หมายเหตุ: .tmp อยู่โฟลเดอร์เดียวกับไฟล์จริง (os.replace ข้าม filesystem / volume ไม่ได้)"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
