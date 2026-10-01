"""
core/frame_source.py — อ่านเฟรมจากกล้องหรือไฟล์วิดีโอ

  - บังคับขนาดเฟรมเป็น FRAME_W x FRAME_H เสมอ (พิกัด ROI และการวาดทั้งหมดอ้างอิงขนาดนี้)
  - กล้องหลุด / วิดีโอจบ → ปิดแล้วเปิดใหม่ (ไฟล์วิดีโอจะวนเล่นซ้ำ)
  - ไฟล์วิดีโอ: หน่วงให้เล่นตาม FPS จริง (pace) ไม่ให้ timer ที่อิงเวลาจริงเพี้ยน
"""

import time
import cv2
from config import FRAME_W, FRAME_H, CAMERA_RECONNECT_SEC
from utils.logger import get_logger

logger = get_logger("frame_source")


class FrameSource:
    def __init__(self, source):
        self.source = source
        self.cap = self._open()

        # ── Playback pacing (เฉพาะไฟล์วิดีโอ) ─────────────────────────────────
        # อ่านไฟล์วิดีโอด้วย OpenCV จะได้เฟรมเร็วสุดเท่าที่ลูปไหว (ไม่ผูกกับ FPS คลิป)
        # ทำให้คลิปเล่นเร็วผิดปกติ และ timer ที่อิงเวลาจริงเพี้ยน จึงต้องหน่วงตาม FPS จริง
        # กล้องจริง (source เป็นตัวเลข) ไม่ต้องหน่วง เพราะมันส่งเฟรมตามอัตราของมันเอง
        self.is_video_file = isinstance(source, str)
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps != fps:  # 0 / ค่าผิด / NaN
            fps = 30.0
        self.frame_period = 1.0 / fps
        if self.is_video_file:
            logger.info(f"🎞️ Video file @ {fps:.2f} FPS → pacing playback ตามเวลาจริง")
        self._next_deadline = None  # ตั้งตอนอ่านเฟรมแรก

    def _open(self):
        cap = cv2.VideoCapture(self.source)
        # หมายเหตุ: สำหรับไฟล์วิดีโอ cap.set(WIDTH/HEIGHT) จะไม่มีผล (ใช้ได้เฉพาะกล้องจริง)
        # จึง resize ทุกเฟรมใน read() อีกชั้น
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
        return cap

    def read(self):
        """คืนเฟรม BGR ขนาด FRAME_W x FRAME_H
        หรือ None ถ้ากล้องหลุด (เปิดใหม่ให้แล้ว — ผู้เรียกควรล้าง background)"""
        if self._next_deadline is None:
            self._next_deadline = time.time() + self.frame_period

        ret, frame = self.cap.read()
        if not ret:
            logger.warning("⚠️ กล้องหลุด กำลัง reconnect...")
            self.cap.release()
            time.sleep(CAMERA_RECONNECT_SEC)
            self.cap = self._open()
            return None

        if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
            frame = cv2.resize(frame, (FRAME_W, FRAME_H))
        return frame

    def pace(self):
        """หน่วงให้ไฟล์วิดีโอเล่นตามเฟรมเรตจริง (กล้องจริงไม่ทำอะไร)"""
        if not self.is_video_file:
            return
        sleep_time = self._next_deadline - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
        self._next_deadline += self.frame_period
        # ถ้าประมวลผลช้ากว่าเฟรมเรต (deadline หลุดไปแล้ว) รีเซ็ตกันสะสมหน่วง
        if self._next_deadline < time.time():
            self._next_deadline = time.time() + self.frame_period

    def release(self):
        self.cap.release()
