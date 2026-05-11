import cv2
import os
from datetime import datetime

EVIDENCE_DIR = "evidence_images"
os.makedirs(EVIDENCE_DIR, exist_ok=True)


def save_evidence_image(frame, event_name, transaction_id):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{transaction_id}_{event_name}_{ts}.jpg"
    filepath = os.path.join(EVIDENCE_DIR, filename)

    display_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    image_to_save = frame.copy()
    cv2.putText(
        image_to_save,
        f"{event_name}: {display_time}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2,
    )

    cv2.imwrite(filepath, image_to_save)
    return filepath
