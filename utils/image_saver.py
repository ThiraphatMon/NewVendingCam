import cv2
import os
from datetime import datetime

# ── Phase 3+4: แยก 2 folder ────────────────────────────────────────────────
# WITH_ORDER    = ภาพที่จับได้ขณะมี order อยู่ (ของที่ลูกค้าสั่ง)
# WITHOUT_ORDER = ภาพที่จับได้โดยไม่มี order (motion ปกติ / สิ่งแปลกปลอม)
# ผู้ดูแลระบบสามารถเปิด folder WITHOUT_ORDER เพื่อตรวจสอบสิ่งผิดปกติได้
WITH_ORDER_DIR = "evidence_images/with_order"
WITHOUT_ORDER_DIR = "evidence_images/without_order"

os.makedirs(WITH_ORDER_DIR, exist_ok=True)
os.makedirs(WITHOUT_ORDER_DIR, exist_ok=True)


def save_evidence_image(frame, event_name, transaction_id, has_order: bool = False):
    """
    บันทึกภาพหลักฐาน

    Parameters
    ----------
    frame          : numpy array — frame ที่จะบันทึก
    event_name     : str — ชื่อ event เช่น LANDED_item1, ORDER_SUMMARY, NO_DROP
    transaction_id : str — TXN-YYYYMMDD-HHMMSS
    has_order      : bool
        True  → บันทึกลง evidence_images/with_order/
        False → บันทึกลง evidence_images/without_order/

    Returns
    -------
    filepath : str — path ของไฟล์ที่บันทึก
    """
    save_dir = WITH_ORDER_DIR if has_order else WITHOUT_ORDER_DIR

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{transaction_id}_{event_name}_{ts}.jpg"
    filepath = os.path.join(save_dir, filename)

    display_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    image_to_save = frame.copy()

    # ── label บนภาพ ──────────────────────────────────────────────────────────
    label = f"{event_name}: {display_time}"
    if has_order:
        label += " [ORDER]"

    cv2.putText(
        image_to_save,
        label,
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2,
    )

    cv2.imwrite(filepath, image_to_save)
    return filepath
