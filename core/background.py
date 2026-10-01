"""
core/background.py — background model สำหรับหา motion (รวมสถานะ bg ทั้งหมดไว้ที่เดียว)

วงจรของ background:
  IDLE         → bg เรียนรู้ตามแสงช้า ๆ (BG_LEARNING_RATE)
                 + เก็บ clean_bg (ช่องรับของว่าง ไม่มี motion) ไว้ทุก CLEAN_BG_INTERVAL วินาที
  เจอ motion   → freeze(): หยุดเรียนรู้ และดึง bg กลับไปที่ clean_bg (ก่อนมือ/ของเข้ามา)
  capture ได้  → rebaseline(): เอาเฟรมปัจจุบันทั้งภาพเป็น bg ใหม่ → ของชิ้นถัดไปเป็น motion ใหม่
  env change   → restore_snapshot(): ดึง bg ตอน freeze กลับมา
  reset        → unfreeze(): กลับมาเรียนรู้ + grace period (ดูดมือที่ค้างในเฟรมเข้า bg ก่อน)
  กล้องหลุด    → clear(): เริ่มใหม่หมด
"""

import cv2
import numpy as np
from config import (
    MOT_THRESH,
    BG_LEARNING_RATE,
    BG_RELEARN_RATE,
    RESET_GRACE_SEC,
    CLEAN_BG_INTERVAL,
    MAX_BLOB_ROI_RATIO,
)
from utils.logger import get_logger, LogThrottle

logger = get_logger("background")

# env change ที่ค้างอยู่จะเกิดทุกเฟรม → log ได้ไม่เกิน 1 ครั้งต่อ 5 วินาที
_env_log = LogThrottle(5.0)
_restore_log = LogThrottle(5.0)


class BackgroundModel:
    def __init__(self):
        self.clear()

    def clear(self):
        """ล้างทุกอย่าง — เฟรมถัดไปจะถูกใช้เป็น background ใหม่ทันที"""
        self.bg = None
        self.frozen = False
        self.snapshot = None  # snapshot ของ bg ตอนที่ freeze (ตอนเจอของชิ้นแรก)

        # [CLEAN BG] เก็บ snapshot ของ bg ที่ clean (ไม่มี motion) ไว้ล่วงหน้า
        # เพื่อใช้ตอน freeze แทน bg ที่อาจถูกดูดมือเข้าไปบางส่วนแล้ว
        self.clean_bg = None
        self.clean_bg_last_update = 0.0

        # [BUG FIX: มือถูก snapshot เป็น background ตอน reset]
        # หลัง reset มือผู้ใช้อาจยังอยู่ในเฟรม ถ้าล้าง bg ทันที เฟรมถัดไปจะ snapshot มือ
        # เป็น background ใหม่ → พอมือถอยออกกลายเป็น blob
        # แก้: ไม่ล้าง bg แต่ unfreeze ให้ re-learn เร็ว + ล็อก grace period
        # ระหว่าง grace period ห้าม trigger DROP_DETECTED ใหม่
        self.grace_until = 0.0  # timestamp สิ้นสุด grace period

    def in_grace(self, now):
        return now < self.grace_until

    def update(self, frame_gray, now, idle):
        """คืน diff (absdiff ระหว่างเฟรมกับ bg) หรือ None ถ้าเพิ่งตั้ง bg จากเฟรมนี้

        idle: state machine อยู่ IDLE หรือไม่ (เก็บ clean_bg เฉพาะตอน IDLE)
        """
        if self.bg is None:
            self.bg = frame_gray.copy()
            return None

        diff = cv2.absdiff(frame_gray, self.bg)

        if not self.frozen:
            # [BUG FIX] ระหว่าง grace period re-learn เร็วขึ้นเพื่อดูดมือเข้า background
            # ก่อนที่ระบบจะเปิดรับ motion ใหม่
            lr = BG_RELEARN_RATE if self.in_grace(now) else BG_LEARNING_RATE
            cv2.addWeighted(self.bg, 1 - lr, frame_gray, lr, 0, dst=self.bg)

            # [CLEAN BG] snapshot bg ที่สะอาด เฉพาะตอน IDLE + ไม่มี motion
            no_raw_motion = (
                cv2.countNonZero(
                    np.where(diff > MOT_THRESH, np.uint8(255), np.uint8(0))
                )
                == 0
            )
            if (
                idle
                and no_raw_motion
                and not self.in_grace(now)
                and (now - self.clean_bg_last_update) >= CLEAN_BG_INTERVAL
            ):
                self.clean_bg = self.bg.copy()
                self.clean_bg_last_update = now

        return diff

    def freeze(self):
        """เจอ motion ตอน IDLE → หยุดเรียนรู้ bg (ทำครั้งเดียวต่อรอบ)"""
        if self.frozen:
            return
        self.frozen = True
        # [CLEAN BG] ใช้ clean_bg (bg ก่อนมือเข้า) แทน bg ที่อาจถูกดูดมือไปแล้ว
        # ถ้ายังไม่มี clean_bg (เพิ่งเริ่มระบบ) → fallback ใช้ bg ปัจจุบัน
        src = self.clean_bg if self.clean_bg is not None else self.bg
        self.snapshot = src.copy()
        self.bg = src.copy()
        logger.info("🧊 Background FROZEN — ใช้ clean_bg ก่อนมี motion")

    def unfreeze(self, now):
        """reset กลับ IDLE → ไม่ล้าง bg แต่กลับมาเรียนรู้ + เข้า grace period
        ระหว่าง grace: re-learn เร็ว (BG_RELEARN_RATE) และห้าม trigger ของใหม่
        หลัง grace: กลับใช้ BG_LEARNING_RATE ปกติ พร้อมรับของชิ้นใหม่"""
        self.frozen = False
        self.grace_until = now + RESET_GRACE_SEC
        logger.info(f"🌅 Background UNFROZEN — grace period {RESET_GRACE_SEC}s")

    def rebaseline(self, frame_gray):
        """[RESET MOTION] หลัง capture สำเร็จ: เอาเฟรมปัจจุบัน "ทั้งภาพ" เป็น bg ใหม่
        → motion mask ว่างทันที ของชิ้นถัดไป (แม้ตกทับที่เดิม) เป็น motion ใหม่ → นับเป็นชิ้นใหม่ได้
        env ที่เปลี่ยนจากการกระแทก (แม้ก้อนที่ไม่เชื่อมกับตัววัตถุ) ก็ถูกกลืนหมด"""
        self.bg = frame_gray.copy()
        # อัปเดต snapshot ด้วย (กันกรณี env change restore ดึง bg เก่ากลับมา)
        self.snapshot = frame_gray.copy()

    def restore_snapshot(self):
        """env change ระหว่างจับของ → ดึง bg ตอน freeze กลับมา คืน True ถ้า restore ได้"""
        if self.snapshot is None:
            return False
        self.bg = self.snapshot.copy()
        _restore_log(logger.info, "🔄 BG restored to frozen snapshot")
        return True


def find_env_change(fgmask, roi_areas):
    """[LARGE MOTION] มี ROI area ไหนที่ motion รวมเกิน MAX_BLOB_ROI_RATIO ของพื้นที่ไหม
    ใหญ่เกิน → ถือว่าเป็น env change (แสง / bg เปลี่ยน) ไม่ใช่ของจริงที่ตก"""
    for roi_area in roi_areas:
        area_fgmask = cv2.bitwise_and(fgmask, roi_area["mask"])
        blob_px = int(cv2.countNonZero(area_fgmask))
        if blob_px > roi_area["area_px"] * MAX_BLOB_ROI_RATIO:
            _env_log(
                logger.info,
                f"⚡ Large motion detected — "
                f"blob={blob_px}px / roi={roi_area['area_px']}px "
                f"({blob_px / roi_area['area_px'] * 100:.0f}%) "
                f"→ env change",
            )
            return True
    return False
