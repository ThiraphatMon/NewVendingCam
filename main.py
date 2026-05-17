import cv2
import torch
import time
import argparse
from config import (
    FRAME_W,
    FRAME_H,
    CAMERA_INDEX,
    MIN_AREA,
    GROUP_DIST,
    DROP_TIMEOUT,
    CONFIRM_TIME,
    CONFIRMED_HOLD_TIMEOUT,
    MACHINE_ID,
)
import threading
from api.client import fetch_remote_roi, push_default_roi
from core.tracker import MemoryTracker, group_close_boxes
from core.state_machine import VendingStateMachine
from core.roi import ROIManager
from utils.logger import get_logger
from utils.disk_cleanup import start_cleanup_thread

logger = get_logger("main")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", type=str, default=MACHINE_ID)
    args = parser.parse_args()

    print(f"🖥️ ระบบทำงานในชื่อตู้: {args.machine}")

    start_cleanup_thread()

    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    roi_manager = ROIManager(actual_w, actual_h, config_path="data/roi_config.json")

    threading.Thread(
        target=push_default_roi,
        args=(args.machine, "data/roi_config.json"),
        daemon=True,
    ).start()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"🚀 เริ่มระบบประมวลผลด้วย: {device.type.upper()}")

    tracker = MemoryTracker()
    sm = VendingStateMachine()
    sm.machine_id = args.machine

    def roi_polling_task():
        while True:
            try:
                fetch_remote_roi(sm.machine_id)
            except Exception as e:
                print(f"⚠️ roi_polling_task error: {e}")
            time.sleep(10)

    threading.Thread(target=roi_polling_task, daemon=True).start()

    bg_tensor = None
    LR = 0.1
    MOT_THRESH = 25
    bg_frozen = False
    RECONNECT_DELAY = 2

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️ กล้องหลุด กำลัง reconnect...")
            cap.release()
            time.sleep(RECONNECT_DELAY)
            cap = cv2.VideoCapture(CAMERA_INDEX)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            bg_tensor = None
            bg_frozen = False
            continue

        frame = cv2.flip(frame, 1)
        now = time.time()

        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_tensor = torch.from_numpy(frame_gray).to(device).float()

        if bg_tensor is None:
            bg_tensor = frame_tensor.clone()
            continue

        diff = torch.abs(frame_tensor - bg_tensor)
        mask_tensor = torch.where(
            diff > MOT_THRESH,
            torch.tensor(255.0, device=device),
            torch.tensor(0.0, device=device),
        )

        if not bg_frozen:
            bg_tensor = (1 - LR) * bg_tensor + LR * frame_tensor

        fgmask = mask_tensor.byte().cpu().numpy()

        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, k5)
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_DILATE, k5, iterations=2)

        roi_manager.reload_if_changed()
        roi_mask = roi_manager.build_mask(fgmask.shape)
        fgmask = cv2.bitwise_and(fgmask, roi_mask)

        contours, _ = cv2.findContours(
            fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        raw_boxes = [
            cv2.boundingRect(c) for c in contours if cv2.contourArea(c) > MIN_AREA
        ]

        merged = group_close_boxes(raw_boxes, max_dist=GROUP_DIST)
        detected = [(int(x + w / 2), int(y + h / 2), w, h) for x, y, w, h in merged]
        tracked = tracker.update(detected)

        motion_in_roi = any(
            obj["state"] in ("MOVING", "DETECTING", "SHAPE_CONFIRMED")
            or "WAITING" in obj["state"]
            for obj in tracked.values()
        )

        if motion_in_roi and sm.state == "IDLE":
            if not bg_frozen:
                bg_frozen = True
                print("🧊 Background FROZEN — พบวัตถุใน ROI")
            sm.trigger("motion_in_ROI")

        if sm.state == "DROP_DETECTED":
            for obj_id, obj in tracked.items():
                # [CHANGE 1] trigger เมื่อ SHAPE_CONFIRMED แทน CONFIRMED_STOP
                if (
                    obj["state"] == "SHAPE_CONFIRMED"
                    and (now - obj.get("shape_confirmed_time", now)) >= CONFIRM_TIME
                ):
                    sm.trigger("still_in_ROI", obj_id=obj_id, frame=frame)
                    break
            if sm.drop_time and (now - sm.drop_time) > DROP_TIMEOUT:
                sm.trigger("timeout")

        def do_reset():
            sm.reset()
            tracker.clear_all()
            nonlocal bg_frozen, bg_tensor
            bg_frozen = False
            bg_tensor = None
            print("🌅 Background UNFROZEN — กลับสู่ IDLE")

        if sm.state == "EVIDENCE_CAPTURED":
            landed_obj = tracked.get(sm.land_obj_id)
            hold_elapsed = now - sm.capture_time

            # [CHANGE 2] Force reset ถ้าค้างนานเกิน CONFIRMED_HOLD_TIMEOUT
            if hold_elapsed >= CONFIRMED_HOLD_TIMEOUT:
                print(f"⏰ Force reset หลังค้าง {CONFIRMED_HOLD_TIMEOUT}s")
                do_reset()
            elif landed_obj:
                # วัตถุยังอยู่ → track กรอบสีเขียว + แสดง auto-reset countdown
                cx, cy = landed_obj["centroid"]
                w, h = landed_obj["shape"]
                time_left = max(0, CONFIRMED_HOLD_TIMEOUT - hold_elapsed)
                cv2.rectangle(
                    frame,
                    (cx - w // 2, cy - h // 2),
                    (cx + w // 2, cy + h // 2),
                    (0, 255, 0),
                    3,
                )
                cv2.putText(
                    frame,
                    f"CONFIRMED  (auto-reset {time_left:.0f}s)",
                    (cx - w // 2, cy - h // 2 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.40,
                    (0, 255, 0),
                    1,
                )
            else:
                # วัตถุออกจาก ROI → reset ทันที
                print("✅ วัตถุออกจาก ROI → RESET")
                do_reset()

        roi_manager.draw(frame)
        color = (
            (0, 255, 0)
            if sm.state == "EVIDENCE_CAPTURED"
            else (0, 200, 255) if sm.state == "DROP_DETECTED" else (150, 150, 150)
        )

        if bg_frozen:
            cv2.putText(
                frame,
                "BG FROZEN",
                (10, actual_h - 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 200, 0),
                1,
            )

        cv2.rectangle(frame, (actual_w - 255, 5), (actual_w - 5, 80), (20, 20, 20), -1)
        cv2.putText(
            frame,
            sm.state,
            (actual_w - 245, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

        sc = {
            "CONFIRMED_STOP": (0, 255, 0),
            "SHAPE_CONFIRMED": (0, 255, 0),
            "MOVING": (0, 0, 255),
            "DETECTING": (0, 140, 255),
        }

        for obj_id, obj in tracked.items():
            if sm.state == "EVIDENCE_CAPTURED" and obj_id == sm.land_obj_id:
                continue
            cx, cy = obj["centroid"]
            w, h = obj["shape"]
            state = obj["state"]
            box_color = (
                (0, 165, 255) if "WAITING" in state else sc.get(state, (0, 0, 255))
            )
            cv2.rectangle(
                frame,
                (cx - w // 2, cy - h // 2),
                (cx + w // 2, cy + h // 2),
                box_color,
                2,
            )
            cv2.putText(
                frame,
                f"ID:{obj_id} {state[:12]}",
                (cx - w // 2, cy - h // 2 - 6),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.38,
                box_color,
                1,
            )

        cv2.imshow("Vending System", frame)
        cv2.imshow("Motion Mask", fgmask)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("r"):
            sm.reset()
            tracker.clear_all()
            bg_tensor = None
            bg_frozen = False

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
