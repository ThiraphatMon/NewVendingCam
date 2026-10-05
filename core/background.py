"""
core/background.py — background model สำหรับหา motion (รวมสถานะ bg ทั้งหมดไว้ที่เดียว)

วงจรของ background:
  IDLE         → bg เรียนรู้ตามแสงช้า ๆ (BG_LEARNING_RATE)
                 + เก็บ clean_bg = เฟรมปัจจุบัน เมื่อ ROI นิ่ง "เฟรมต่อเฟรม" (เทียบเฟรมก่อนหน้า
                   ไม่ใช่เทียบ bg: พิกเซลเปลี่ยน ≤ CLEAN_BG_MAX_MOTION_RATIO ของ ROI ติดกัน
                   CLEAN_BG_STABLE_FRAMES เฟรม) ทุก CLEAN_BG_INTERVAL วินาที — เก็บได้ทั้งตอน freeze / grace
                 + ROI เปลี่ยนเกินเกณฑ์ / env change → clean_bg หมดสภาพ (valid=False) ทันที
  START        → start_cycle(): ใช้ clean_bg ที่ valid (เก็บหลังการเปลี่ยนแปลงล่าสุด)
                 ไม่มี → ใช้เฟรมปัจจุบัน (baseline ไม่แน่นอน เหมือนตัวเก่า)
  เฝ้าดูนอกรอบ → freeze(): หยุดเรียนรู้ และดึง bg กลับไปที่ clean_bg ล่าสุด (ก่อนมือ/ของเข้ามา)
  capture ได้  → rebaseline(): เอาเฟรมปัจจุบันทั้งภาพเป็น bg ใหม่ (และ clean_bg) → ของชิ้นถัดไปเป็น motion ใหม่
  env change   → restore_snapshot(): ดึง bg ตอน freeze กลับมา
  reset        → unfreeze(): กลับมาเรียนรู้ + grace period (ดูดมือที่ค้างในเฟรมเข้า bg ก่อน)
  กล้องหลุด    → clear(): เริ่มใหม่หมด
"""

from collections import deque

import cv2
import numpy as np
from config import (
    MOT_THRESH,
    BG_LEARNING_RATE,
    BG_RELEARN_RATE,
    RESET_GRACE_SEC,
    CLEAN_BG_INTERVAL,
    CLEAN_BG_MAX_MOTION_RATIO,
    CLEAN_BG_STABLE_FRAMES,
    MAX_BLOB_ROI_RATIO,
    MIN_AREA,
    SCENE_HISTORY_SIZE,
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

        # [CLEAN BG] เฟรมล่าสุดที่ ROI นิ่ง (ไม่มีมือ/ของกำลังเคลื่อน)
        #   clean_bg_valid: ยังไม่มีการเปลี่ยนแปลงหลังเก็บ → ใช้เป็นพื้นหลังของรอบตอน START ได้
        #   ไม่ valid แล้วก็ยังเก็บภาพไว้ให้ watch freeze ใช้ (ฉากก่อนมือ/ของเข้ามา)
        self.clean_bg = None
        self.clean_bg_valid = False
        self.clean_bg_last_update = 0.0
        self.prev_frame = None  # เฟรมก่อนหน้า (ตัดสินความนิ่งเฟรมต่อเฟรม)
        self.quiet_frames = 0  # จำนวนเฟรมติดกันที่ ROI นิ่ง (กล้องหลุด → clear() → เริ่มนับใหม่)
        # [SCENE HISTORY] ฉากนิ่งย้อนหลัง (เวลา, ภาพ uint8) — ใช้แยกหยิบออก/ใส่เข้า (core/removal.py)
        #   ฉากใหม่ต่างจากฉากล่าสุด ≥ MIN_AREA px ใน ROI → เพิ่ม | ไม่ต่าง → แทนที่ฉากล่าสุด (ตามแสงให้ทัน)
        self.scenes = deque(maxlen=max(1, SCENE_HISTORY_SIZE))
        self.scene_last_update = 0.0

        # [BUG FIX: มือถูก snapshot เป็น background ตอน reset]
        # หลัง reset มือผู้ใช้อาจยังอยู่ในเฟรม ถ้าล้าง bg ทันที เฟรมถัดไปจะ snapshot มือ
        # เป็น background ใหม่ → พอมือถอยออกกลายเป็น blob
        # แก้: ไม่ล้าง bg แต่ unfreeze ให้ re-learn เร็ว + ล็อก grace period
        # ระหว่าง grace period ห้าม trigger DROP_DETECTED ใหม่
        self.grace_until = 0.0  # timestamp สิ้นสุด grace period

    def in_grace(self, now):
        return now < self.grace_until

    def update(self, frame_gray, now, idle, roi_mask=None):
        """คืน diff (absdiff ระหว่างเฟรมกับ bg) หรือ None ถ้าเพิ่งตั้ง bg จากเฟรมนี้

        idle     : ไม่มีรอบเปิดอยู่หรือไม่ (เก็บ clean_bg เฉพาะตอนนี้ — รวมระหว่าง watch / grace)
        roi_mask : mask ของ ROI (uint8 255 = ใน ROI) — ใช้ตัดสินว่า "นิ่ง" เฉพาะใน ROI
                   None = ดูทั้งเฟรม
        """
        if self.bg is None:
            self.bg = frame_gray.copy()
            self.prev_frame = frame_gray.copy()
            return None

        diff = cv2.absdiff(frame_gray, self.bg)
        self._track_stillness(frame_gray, now, idle, roi_mask)

        if not self.frozen:
            # [BUG FIX] ระหว่าง grace period re-learn เร็วขึ้นเพื่อดูดมือเข้า background
            # ก่อนที่ระบบจะเปิดรับ motion ใหม่
            lr = BG_RELEARN_RATE if self.in_grace(now) else BG_LEARNING_RATE
            cv2.addWeighted(self.bg, 1 - lr, frame_gray, lr, 0, dst=self.bg)

        return diff

    def _track_stillness(self, frame_gray, now, idle, roi_mask):
        """[CLEAN BG] ความนิ่งเฟรมต่อเฟรมใน ROI (ไม่ขึ้นกับ bg ที่อาจ freeze / เรียนรู้ไม่ทัน)
        ยอม noise เล็กน้อย (การบีบอัดภาพ) — มือ / ของกำลังตก / slat เปิดปิด จะเกินเสมอ"""
        prev, self.prev_frame = self.prev_frame, frame_gray.copy()
        if prev is None:  # เฟรมแรกหลังกล้องหลุด → ยังไม่นับเป็นเฟรมนิ่ง
            self.quiet_frames = 0
            return
        raw = np.where(cv2.absdiff(frame_gray, prev) > MOT_THRESH, np.uint8(255), np.uint8(0))
        if roi_mask is not None:
            raw = cv2.bitwise_and(raw, roi_mask)
            area = cv2.countNonZero(roi_mask)
        else:
            area = raw.size
        if cv2.countNonZero(raw) <= area * CLEAN_BG_MAX_MOTION_RATIO:
            self.quiet_frames += 1
        else:
            self.mark_scene_changed()
        if self.quiet_frames >= CLEAN_BG_STABLE_FRAMES and (now - self.scene_last_update) >= CLEAN_BG_INTERVAL:
            self._record_scene(frame_gray, now, roi_mask)
        if (
            idle
            and self.quiet_frames >= CLEAN_BG_STABLE_FRAMES
            and (not self.clean_bg_valid or (now - self.clean_bg_last_update) >= CLEAN_BG_INTERVAL)
        ):
            self.clean_bg = frame_gray.copy()
            self.clean_bg_valid = True
            self.clean_bg_last_update = now

    def _record_scene(self, frame_gray, now, roi_mask):
        """[SCENE HISTORY] บันทึกฉากนิ่ง (ทุกสถานะ ไม่ใช่แค่ WAIT_START)"""
        img = np.clip(frame_gray, 0, 255).astype(np.uint8)
        self.scene_last_update = now
        if self.scenes:
            changed = cv2.absdiff(img, self.scenes[-1][1]) > MOT_THRESH
            if roi_mask is not None:
                changed &= roi_mask > 0
            if int(np.count_nonzero(changed)) < MIN_AREA:
                self.scenes[-1] = (now, img)
                return
        self.scenes.append((now, img))

    def scenes_before(self, t):
        """ฉากนิ่งที่บันทึกก่อนเวลา t (เช่นก่อนวัตถุ candidate เริ่มปรากฏ) ใหม่สุดก่อน"""
        return [img for ts, img in reversed(self.scenes) if ts < t]

    def roi_still(self):
        """ROI นิ่งเฟรมต่อเฟรมติดกันครบ CLEAN_BG_STABLE_FRAMES แล้วหรือยัง"""
        return self.quiet_frames >= CLEAN_BG_STABLE_FRAMES

    def mark_scene_changed(self):
        """ROI เปลี่ยนเกินเกณฑ์ / env change → clean_bg ไม่ใช่ฉากปัจจุบันแล้ว ห้ามใช้ตอน START
        (ภาพยังเก็บไว้ให้ watch freeze ใช้เป็นฉากก่อนมีการเปลี่ยนแปลง)
        clean_bg ใหม่ต้องนิ่งครบ CLEAN_BG_STABLE_FRAMES เฟรมหลังการเปลี่ยนแปลงนี้"""
        self.clean_bg_valid = False
        self.quiet_frames = 0

    def start_cycle(self, frame_gray, now, reason=""):
        """START: ตรึงพื้นหลังของรอบ (แทนที่ bg เดิมเสมอ แม้กำลัง freeze จาก watch อยู่)
        clean_bg valid → ใช้ clean_bg | ไม่มี (ฉากยังไม่นิ่ง) → เฟรมปัจจุบัน (baseline ไม่แน่นอน)
        คืน True ถ้าใช้ clean_bg"""
        self.frozen = True
        tag = f" [{reason}]" if reason else ""
        used_clean = self.clean_bg is not None and self.clean_bg_valid
        src = self.clean_bg if used_clean else frame_gray
        self.bg = src.copy()
        self.snapshot = src.copy()
        if used_clean:
            age = now - self.clean_bg_last_update
            logger.info(f"🧊 Background FROZEN{tag} — ใช้ clean_bg (อายุ {age:.1f}s)")
        else:
            logger.warning(
                f"🧊 Background FROZEN{tag} — ไม่มี clean_bg ที่นิ่งหลังการเปลี่ยนแปลงล่าสุด "
                f"→ ใช้เฟรมปัจจุบัน (baseline ไม่แน่นอน: มือ/ของที่อยู่ในเฟรมนี้จะกลายเป็นพื้นหลัง)"
            )
        return used_clean

    def freeze(self, now, reason=""):
        """[WATCH] หยุดเรียนรู้ bg (ทำครั้งเดียวจนกว่าจะ unfreeze) คืน True ถ้าใช้ clean_bg
        ใช้ clean_bg ล่าสุดแม้ไม่ valid แล้ว (เฟรมที่ทำให้เริ่มเฝ้าคือการเปลี่ยนแปลงเอง)
        reason: ข้อความบอกว่า freeze เพราะอะไร ใส่ใน log"""
        if self.frozen:
            return self.clean_bg is not None
        self.frozen = True
        # [CLEAN BG] ใช้ clean_bg (ฉากก่อนมือเข้า) แทน bg ที่อาจถูกดูดมือไปแล้ว
        # ถ้ายังไม่มี clean_bg (เพิ่งเริ่มระบบ / เพิ่งปิดรอบ) → fallback ใช้ bg ปัจจุบัน
        used_clean = self.clean_bg is not None
        src = self.clean_bg if used_clean else self.bg
        self.snapshot = src.copy()
        self.bg = src.copy()
        tag = f" [{reason}]" if reason else ""
        if used_clean:
            age = now - self.clean_bg_last_update
            logger.info(f"🧊 Background FROZEN{tag} — ใช้ clean_bg (อายุ {age:.1f}s)")
        else:
            logger.warning(
                f"🧊 Background FROZEN{tag} — fallback: ไม่มี clean_bg ใช้ bg ปัจจุบัน "
                f"(ถ้ามีมือ/ของที่ยังไม่ถูกกลืนเข้า bg อาจถูกตรวจ)"
            )
        return used_clean

    def unfreeze(self, now):
        """reset กลับ IDLE → ไม่ล้าง bg แต่กลับมาเรียนรู้ + เข้า grace period
        ระหว่าง grace: re-learn เร็ว (BG_RELEARN_RATE) และห้าม trigger ของใหม่
        หลัง grace: กลับใช้ BG_LEARNING_RATE ปกติ พร้อมรับของชิ้นใหม่"""
        self.frozen = False
        self.grace_until = now + RESET_GRACE_SEC
        logger.info(f"🌅 Background UNFROZEN — grace period {RESET_GRACE_SEC}s")

    def invalidate_clean_bg(self):
        """ปิดรอบ: clean_bg เก่า (ก่อนรอบ) ไม่ตรงกับถาดตอนนี้แล้ว (อาจมีของค้าง) → ทิ้ง
        START ถัดไปก่อนเก็บ clean_bg ใหม่ได้จะใช้เฟรมปัจจุบันแทน"""
        self.clean_bg = None
        self.clean_bg_valid = False

    def forget_roi_history(self):
        """ROI เปลี่ยน → ทิ้งสิ่งที่วัดใน ROI เดิม: clean_bg, การนับความนิ่ง, scene history
        (clean_bg ใหม่ / ฉากใหม่ต้องนิ่งครบ CLEAN_BG_STABLE_FRAMES ใน ROI ใหม่ก่อน)"""
        self.invalidate_clean_bg()
        self.quiet_frames = 0
        self.scenes.clear()
        self.scene_last_update = 0.0

    def rebaseline(self, frame_gray, now):
        """[RESET MOTION] หลัง capture สำเร็จ: เอาเฟรมปัจจุบัน "ทั้งภาพ" เป็น bg ใหม่
        → motion mask ว่างทันที ของชิ้นถัดไป (แม้ตกทับที่เดิม) เป็น motion ใหม่ → นับเป็นชิ้นใหม่ได้
        env ที่เปลี่ยนจากการกระแทก (แม้ก้อนที่ไม่เชื่อมกับตัววัตถุ) ก็ถูกกลืนหมด"""
        self.bg = frame_gray.copy()
        # อัปเดต snapshot ด้วย (กันกรณี env change restore ดึง bg เก่ากลับมา)
        self.snapshot = frame_gray.copy()
        # อัปเดต clean_bg ด้วย: ฉากนี้ (รวมของที่เพิ่งยืนยันซึ่งยังค้างในถาด) คือพื้นหลังที่ยอมรับแล้ว
        # → START ถัดไป freeze() จะไม่ดึง clean_bg ก่อนรอบเก่ากลับมา จนของรอบก่อนถูกยืนยันซ้ำ
        self.clean_bg = frame_gray.copy()
        self.clean_bg_valid = True
        self.clean_bg_last_update = now

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
