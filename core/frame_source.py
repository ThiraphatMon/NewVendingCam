"""
core/frame_source.py — อ่านเฟรมจากกล้องหรือไฟล์วิดีโอใน thread แยก (ถือเฉพาะเฟรมล่าสุด)

  - บังคับขนาดเฟรมเป็น FRAME_W x FRAME_H เสมอ (พิกัด ROI และการวาดทั้งหมดอ้างอิงขนาดนี้)
  - เปิดครั้งเดียวตอนเริ่มโปรแกรม — START/STOP ไม่เปิด/ปิดกล้อง
  - reader thread อ่านเฟรมตลอด เก็บแค่เฟรมล่าสุด + เวลา (slot ขนาด 1) → main loop ไม่ติดอยู่ใน cap.read()
    กล้องค้างแค่ไหน คำสั่ง START/STOP ก็ยังถูกประมวลผล
  - read() คืน:
      เฟรมใหม่          → ประมวลผลตามปกติ (เฟรมเดิมไม่ถูกคืนซ้ำ — กันเฟรมซ้ำถูกนับว่า ROI นิ่ง)
      None              → camera gap: กล้องหลุด / วิดีโอจบ (กำลังเปิดใหม่) / ไม่มีเฟรมใหม่เกิน CAMERA_STALL_SEC
      NO_NEW_FRAME      → ยังไม่มีเฟรมใหม่ (รอได้ไม่เกิน READ_WAIT_SEC) แต่ยังไม่ถือว่าค้าง
  - กล้องค้าง (cap.read() ไม่คืน) → log + เริ่ม reader รุ่นใหม่ (เปิดกล้องใหม่)
    thread เก่าที่ค้างจะเลิกเองเมื่อ read() คืน (ไม่ release cap จาก thread อื่น — OpenCV ไม่ปลอดภัย)
  - ไฟล์วิดีโอ: reader หน่วงให้เล่นตาม FPS จริง ไม่ให้ timer ที่อิงเวลาจริงเพี้ยน; จบไฟล์ → เปิดใหม่ (วนซ้ำ)
"""

import threading
import time

import cv2
from config import FRAME_W, FRAME_H, CAMERA_RECONNECT_SEC, CAMERA_STALL_SEC
from utils.logger import get_logger

logger = get_logger("frame_source")

# ยังไม่มีเฟรมใหม่ แต่กล้องยังไม่ถือว่าค้าง (main ประมวลผลคำสั่งแล้วรอบถัดไป ไม่ตรวจจับซ้ำ)
NO_NEW_FRAME = object()

# read() รอเฟรมใหม่ได้นานสุดเท่านี้ (กัน main loop วนเปล่าเปลือง CPU / ให้คำสั่งถูกประมวลผลสม่ำเสมอ)
READ_WAIT_SEC = 0.1


class FrameSource:
    def __init__(self, source, stall_sec=CAMERA_STALL_SEC, reconnect_sec=CAMERA_RECONNECT_SEC):
        self.source = source
        self.stall_sec = stall_sec
        self.reconnect_sec = reconnect_sec
        # กล้องจริง (ตัวเลข หรือ /dev/videoN) ส่งเฟรมตามอัตราของมันเอง — ไฟล์วิดีโอต้องหน่วงเอง
        self.is_video_file = isinstance(source, str) and not source.startswith("/dev/")

        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0            # เพิ่มทุกเฟรมใหม่จาก reader
        self._returned_seq = 0   # seq ของเฟรมที่ read() คืนไปล่าสุด
        self._last_frame_at = time.time()  # เวลาเฟรมล่าสุด (หรือเวลาเริ่ม reader รุ่นล่าสุด)
        self._down = False       # กล้องหลุด / ค้าง → read() คืน None จนกว่าจะได้เฟรมใหม่
        self._gen = 0            # รุ่นของ reader (กล้องค้าง → รุ่นใหม่ รุ่นเก่าเลิกเอง)
        self._closed = False
        self.open_count = 0
        self._start_reader()

    # ── reader thread ───────────────────────────────────────────────────────
    def _start_reader(self):
        self._gen += 1
        self._last_frame_at = time.time()
        threading.Thread(target=self._reader, args=(self._gen,), daemon=True,
                         name=f"camera-reader-{self._gen}").start()

    def _alive(self, gen):
        return not self._closed and gen == self._gen

    def _open(self):
        self.open_count += 1
        cap = cv2.VideoCapture(self.source)
        # หมายเหตุ: สำหรับไฟล์วิดีโอ cap.set(WIDTH/HEIGHT) จะไม่มีผล (ใช้ได้เฉพาะกล้องจริง)
        # จึง resize ทุกเฟรมอีกชั้น
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
        return cap

    def _frame_period(self, cap):
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps != fps:  # 0 / ค่าผิด / NaN
            fps = 30.0
        if self.is_video_file and self.open_count == 1:
            logger.info(f"video file @ {fps:.2f} FPS -> real-time playback pacing")
        return 1.0 / fps

    def _reader(self, gen):
        while self._alive(gen):
            cap = self._open()
            period = self._frame_period(cap)
            first = True
            deadline = time.time() + period
            while self._alive(gen):
                ret, frame = cap.read()
                if not self._alive(gen):
                    break
                if not ret:
                    logger.warning("camera disconnected -> reconnecting...")
                    self._mark_down()
                    break
                if first:
                    first = False
                    # log เวลาเฟรมแรกหลังเปิด (ใช้ sync เวลาคลิปใน integration test)
                    logger.debug(f"first frame after opening source FIRST_FRAME t={time.time():.3f}")
                if frame.shape[1] != FRAME_W or frame.shape[0] != FRAME_H:
                    frame = cv2.resize(frame, (FRAME_W, FRAME_H))
                with self._cond:
                    self._frame = frame
                    self._seq += 1
                    self._last_frame_at = time.time()
                    self._down = False
                    self._cond.notify_all()
                if self.is_video_file:
                    deadline = self._pace(deadline, period)
            cap.release()
            if self._alive(gen):
                time.sleep(self.reconnect_sec)

    @staticmethod
    def _pace(deadline, period):
        """หน่วงให้ไฟล์วิดีโอเล่นตามเฟรมเรตจริง คืน deadline ของเฟรมถัดไป"""
        sleep_time = deadline - time.time()
        if sleep_time > 0:
            time.sleep(sleep_time)
        deadline += period
        # ถ้าช้ากว่าเฟรมเรต (deadline หลุดไปแล้ว) รีเซ็ตกันสะสมหน่วง
        if deadline < time.time():
            deadline = time.time() + period
        return deadline

    def _mark_down(self):
        with self._cond:
            self._down = True
            self._frame = None
            self._cond.notify_all()

    # ── ฝั่ง main loop ──────────────────────────────────────────────────────
    def read(self):
        """เฟรม BGR ใหม่ (FRAME_W x FRAME_H) | None (camera gap — ผู้เรียกควรล้าง background) | NO_NEW_FRAME"""
        end = time.time() + READ_WAIT_SEC
        with self._cond:
            while self._seq == self._returned_seq:
                remaining = end - time.time()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            if self._seq != self._returned_seq and self._frame is not None:
                self._returned_seq = self._seq
                return self._frame
            self._returned_seq = self._seq
            if self._down:
                return None
            stalled_for = time.time() - self._last_frame_at
        if stalled_for < self.stall_sec:
            return NO_NEW_FRAME
        logger.warning(
                        f"camera stalled (no new frame) for {stalled_for:.1f}s (over CAMERA_STALL_SEC) -> reconnecting"
                    )
        self._mark_down()
        self._start_reader()
        return None

    def release(self):
        self._closed = True
        with self._cond:
            self._cond.notify_all()
