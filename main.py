"""
main.py — main loop ของ VendingCam (ยืนยันสินค้า 1 ชิ้นต่อรอบ START–STOP ผ่าน Redis)

ลำดับต่อ iteration (App.step):
  อ่านเฟรม → ประมวลคำสั่ง START/STOP + ผลส่ง S0 (ก่อนดูผลตรวจจับเสมอ) → timeout รอบ
  → (มีเฟรม) background/diff → mask → ก้อน → tracker → ตัดสินวัตถุที่นิ่งครบเกณฑ์:
       ACTIVE              → ยืนยัน (ภาพ → DB → latch → S0 → daily log)
       CONFIRMED_WAIT_STOP → ภาพ anomaly EXTRA_AFTER_CONFIRM (ไม่นับยอด)
       WAIT_START (เฝ้าดู) → ภาพ anomaly OUTSIDE_CYCLE (ไม่นับยอด)

  - main loop เป็นเจ้าของ state ของรอบตัวเดียว (core/cycle.py) — Redis worker แค่ส่งเหตุการณ์มา
  - กล้องเปิดครั้งเดียวตอนเริ่ม START/STOP ไม่เปิด/ปิดกล้อง
  - ไม่มีเฟรม (กล้องหลุด) ก็ยังประมวลผล STOP / timeout ได้
รายละเอียดการตรวจจับอยู่ใน core/ (frame_source, background, detect, tracker) — ไม่เปลี่ยนจากเดิม
"""

import argparse
import os
import signal
import sqlite3
import threading
import time
import cv2
import numpy as np
import config
from config import (
    FRAME_W, FRAME_H, CAMERA_INDEX, MACHINE_ID, HEADLESS, SEND_INTERVAL, ROI_CONFIG_PATH,
    MOT_THRESH, MIN_AREA, MAX_BLOB_ROI_RATIO,
    MORPH_OPEN_KSIZE, MORPH_DILATE_KSIZE, MORPH_DILATE_ITER,
    GROUP_MODE, GROUP_DIST, GROUP_OVERLAP_PAD,
    CAPTURE_HOLD_SEC, CYCLE_TIMEOUT_SEC, CONTROL_MODE, CLOUD_ENABLED, EVIDENCE_DIR,
    DAILY_LOG_DIR, ANOMALY_MIN_INTERVAL_SEC, ANOMALY_MAX_PER_HOUR,
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_CTRL_KEY, REDIS_RESPONSE_KEY,
    REDIS_CONNECT_TIMEOUT_SEC, REDIS_SOCKET_TIMEOUT_SEC,
    STATE_DB_PATH, COUNT_TIMEZONE, CLEAN_BG_STABLE_FRAMES,
)
from api.redis_controller import Command, LinkStatus, RedisController, SendResult, make_client
from core import cycle as cyc
from core.background import BackgroundModel, find_env_change
from core.cycle import AnomalyLimiter, CycleMachine
from core.detect import build_fgmask, contour_boxes, drop_large_boxes, group_close_boxes
from core.frame_source import FrameSource
from core.roi import ROIManager
from core.tracker import MemoryTracker, is_motion_in_roi
from utils import daily_log, image_saver
from utils.disk_cleanup import start_cleanup_thread
from utils.logger import get_logger
from utils.state_store import R_EXPIRED, R_FAILED, StateStore, StateStoreError
from ui.overlay import render_overlay

logger = get_logger("main")

# บันทึกภาพ/DB ล้มเหลว → รอกี่วินาทีก่อนลองยืนยันใหม่ (ของยังนิ่งอยู่) กันเขียนดิสก์ทุกเฟรม
CONFIRM_RETRY_SEC = 1.0

# [WATCH] เฝ้าดูนอกรอบ: freeze bg ได้นานสุดกี่วินาที แล้วปลดกลับไปเรียนรู้ (กันค้าง freeze)
WATCH_TIMEOUT_SEC = 25.0

# ชนิดภาพ anomaly (ไม่นับยอด ไม่ส่ง S0)
OUTSIDE_CYCLE = "OUTSIDE_CYCLE"              # ไม่มีรอบ แต่มีวัตถุนิ่งครบเกณฑ์
EXTRA_AFTER_CONFIRM = "EXTRA_AFTER_CONFIRM"  # ยืนยันแล้ว เจอวัตถุใหม่นิ่งอีก (น่าสงสัย)
NO_CONFIRM_AT_CLOSE = "NO_CONFIRM_AT_CLOSE"  # ปิดรอบโดยไม่ได้ยืนยัน
_ANOMALY_LABELS = {
    OUTSIDE_CYCLE: "OUTSIDE CYCLE",
    EXTRA_AFTER_CONFIRM: "SUSPICIOUS (extra after confirm)",
    NO_CONFIRM_AT_CLOSE: "NO CONFIRM AT CLOSE",
}


def start_cloud_services(machine_id):
    """เริ่ม thread ฝั่ง cloud (เฉพาะ CLOUD_ENABLED=1) — โหมด START–STOP ไม่ใช้ order listener"""
    from api.client import push_default_roi, register_machine, start_roi_polling
    from api.retry_queue import start_retry_thread

    start_retry_thread()
    threading.Thread(target=register_machine, args=(machine_id,), daemon=True).start()
    threading.Thread(
        target=push_default_roi, args=(machine_id, ROI_CONFIG_PATH), daemon=True
    ).start()
    start_roi_polling(machine_id)


def detect_objects(diff, roi_manager, roi_mask):
    """diff → motion mask ใน ROI → กล่องของ (รวมก้อนที่แตกแล้ว)
    คืน (fgmask, detected[(cx, cy, w, h)], env_change)"""
    # OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียวที่ขาด) — ดู core/detect.py
    fgmask = build_fgmask(
        diff, MOT_THRESH, MORPH_OPEN_KSIZE, MORPH_DILATE_KSIZE, MORPH_DILATE_ITER
    )
    fgmask = cv2.bitwise_and(fgmask, roi_mask)

    # [NOISE] contour เล็กกว่า MIN_AREA ถูกตัดทิ้ง
    # [ENV CHANGE] ก้อนใหญ่เกิน MAX_BLOB_ROI_RATIO ของ ROI = แสง/bg เปลี่ยน → ไม่ส่งเข้า tracker
    roi_areas = roi_manager.get_roi_areas(fgmask.shape)
    env_change = find_env_change(fgmask, roi_areas)
    raw_boxes = contour_boxes(fgmask, MIN_AREA)
    if env_change:
        raw_boxes = drop_large_boxes(raw_boxes, roi_areas, MAX_BLOB_ROI_RATIO)

    # [MULTI-ITEM] รวมกล่องที่ใกล้กัน (ของชิ้นเดียวแตกหลาย contour)
    merged = group_close_boxes(
        raw_boxes, max_dist=GROUP_DIST, overlap_pad=GROUP_OVERLAP_PAD, mode=GROUP_MODE
    )
    detected = [(int(x + w / 2), int(y + h / 2), w, h) for x, y, w, h in merged]
    return fgmask, detected, env_change


def find_landed(tracked, now):
    """[CAPTURE-ON-LANDING] วัตถุที่ลงจอดแล้ว (นิ่ง) ครบ CAPTURE_HOLD_SEC — คืน obj_id ตัวแรก หรือ None

    ของที่กำลังตกจะขยับ (MOVING/DETECTING) → ยังไม่จับ
    นิ่งครบ LANDING_STABLE_FRAMES → SHAPE_CONFIRMED → นิ่งต่ออีก CAPTURE_HOLD_SEC → ผ่านเกณฑ์
    """
    for obj_id, obj in tracked.items():
        if (
            obj["state"] == "SHAPE_CONFIRMED"
            and (now - obj.get("shape_confirmed_time", now)) >= CAPTURE_HOLD_SEC
        ):
            return obj_id
    return None


class App:
    """เจ้าของ state ทั้งหมดของ main loop (test สร้างตรง ๆ ด้วย fake source / controller / clock ได้)

    clock : wall clock สำหรับการตรวจจับ (tracker ใช้ time.time ภายใน จึงต้องเป็นนาฬิกาเดียวกัน)
    mono  : monotonic สำหรับ timeout ของรอบ
    """

    def __init__(
        self, machine_id, source, roi_manager, store, controller,
        headless=True, evidence_dir=EVIDENCE_DIR, daily_log_dir=DAILY_LOG_DIR,
        clock=time.time, mono=time.monotonic,
    ):
        self.machine_id = machine_id
        self.source = source
        self.roi_manager = roi_manager
        self.store = store
        self.controller = controller
        self.headless = headless
        self.evidence_dir = evidence_dir
        self.daily_log_dir = daily_log_dir
        self.clock = clock
        self.mono = mono

        self.cm = CycleMachine(CYCLE_TIMEOUT_SEC)
        self.tracker = MemoryTracker()
        self.bg = BackgroundModel()
        self.running = True
        self.last_cmd_seq = 0          # seq ของคำสั่งล่าสุดที่ประมวลผลแล้ว
        self.confirm_retry_at = 0.0    # หลังบันทึกล้มเหลว ห้ามลองใหม่ก่อนเวลานี้
        self.camera_ok = None
        self.redis_up = None
        self.today_count = store.count_today()
        self._count_checked_at = 0.0
        self.last_send_time = 0.0
        self.frame = None              # เฟรมล่าสุด (ใช้ถ่ายภาพ NO_CONFIRM_AT_CLOSE ตอนปิดรอบ)
        self.frame_gray = None         # เฟรมล่าสุดแบบ gray (START ใช้เป็นพื้นหลังได้ถ้าไม่มี clean_bg ที่ valid)
        self.watch_since = None        # [WATCH] เวลาเริ่มเฝ้าดูนอกรอบ (None = ไม่ได้เฝ้า)
        self.anomaly_limiter = AnomalyLimiter(ANOMALY_MIN_INTERVAL_SEC, ANOMALY_MAX_PER_HOUR)

        # [RECOVERY] process ก่อนหน้าตายกลางรอบ → ปิดเป็น INTERRUPTED + S0 ค้างหมดอายุ
        # แล้วเริ่มที่ WAIT_START ทันที (เหมือนตัวเก่าที่ restart แล้วรับ START ใหม่ได้เลย)
        interrupted = store.recover_open_cycles()
        if interrupted:
            short = ", ".join(c[:8] for c in interrupted)
            logger.warning(
                f"♻️ พบรอบค้างจากก่อน restart ({short}) → บันทึกเป็น INTERRUPTED "
                f"(ไม่ส่ง S0 ของรอบเก่า) แล้วเริ่มที่ WAIT_START"
            )
        # [DAILY LOG] สร้างไฟล์ของวันนี้ใหม่จาก DB (ซ่อมบรรทัดที่ขาด/ซ้ำหลัง crash)
        today = store.today()
        n = daily_log.rebuild(self.daily_log_dir, store, today)
        logger.info(f"📊 ยอดวันนี้ ({today}) = {self.today_count} (daily log {n} บรรทัด)")

    # ── 1 iteration ─────────────────────────────────────────────────────────
    def step(self):
        """คืน (frame, fgmask, tracked) สำหรับวาดจอ (frame=None ถ้าไม่มีเฟรม)"""
        frame = self.source.read()
        now = self.clock()
        self.frame = frame
        # START ใช้เฟรมนี้เป็นพื้นหลังของรอบได้ (ถ้ายังไม่มี clean_bg ที่ valid) → แปลงก่อนรับคำสั่ง
        self.frame_gray = (
            None if frame is None else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        )

        # คำสั่ง / ผลส่ง S0 ก่อนผลตรวจจับเสมอ (STOP ที่มาระหว่างอ่านเฟรมต้องมีผลก่อนยืนยัน)
        self._handle_inbox(now)
        result = self.cm.tick(self.mono())
        if result:
            self._apply(result, now)

        if frame is None:
            self._on_no_frame()
            return None, None, {}
        if self.camera_ok is not True:
            if self.camera_ok is False:
                logger.info("📷 กล้องกลับมาแล้ว")
            self.camera_ok = True

        if CLOUD_ENABLED and SEND_INTERVAL > 0 and now - self.last_send_time >= SEND_INTERVAL:
            from api.client import submit_frame

            submit_frame(self.machine_id, frame)
            self.last_send_time = now

        frame_gray = self.frame_gray
        self.roi_manager.reload_if_changed()
        roi_mask = self.roi_manager.build_mask(frame_gray.shape)
        idle = self.cm.state == cyc.WAIT_START
        diff = self.bg.update(frame_gray, now, idle=idle, roi_mask=roi_mask)
        if diff is None:
            return frame, None, {}

        fgmask, detected, env_change = detect_objects(diff, self.roi_manager, roi_mask)
        if env_change and self.bg.frozen:
            self.bg.restore_snapshot()
        if env_change and idle:
            self.bg.mark_scene_changed()  # [WATCH] clean_bg ก่อน env change ห้ามใช้ตอน START
        if env_change and self.cm.can_confirm() and self.bg.roi_still():
            self._rebaseline_settled_env(frame_gray, now)
            return frame, fgmask, {}
        tracked = self.tracker.update(detected)

        if self.cm.state == cyc.WAIT_START:
            self._watch(tracked, now)

        if find_landed(tracked, now) is not None:
            if self.cm.can_confirm():
                if now >= self.confirm_retry_at:
                    self._confirm(frame, frame_gray, now)
            elif self.cm.state == cyc.CONFIRMED_WAIT_STOP:
                self._capture_anomaly(EXTRA_AFTER_CONFIRM, frame, frame_gray, now)
            elif self.cm.state == cyc.WAIT_START and self.watch_since is not None:
                self._capture_anomaly(OUTSIDE_CYCLE, frame, frame_gray, now)
        return frame, fgmask, tracked

    # ── คำสั่งและผลจาก Redis worker ─────────────────────────────────────────
    def _handle_inbox(self, now):
        for ev in self.controller.drain():
            if isinstance(ev, Command):
                self.last_cmd_seq = ev.seq
                mono = self.mono()
                if ev.text == "START":
                    result = self.cm.on_start(mono)
                else:
                    result = self.cm.on_stop(mono)
                logger.info(f"📥 {ev.text} (#{ev.seq} จาก {ev.source})")
                self._apply(result, now)
            elif isinstance(ev, LinkStatus):
                self.redis_up = ev.up
                if not ev.up and self.cm.is_open():
                    self.cm.on_redis_gap()
                    logger.warning(f"⚠️ Redis ขาดระหว่างรอบ {self.cm.cycle_id[:8]} ({ev.error})")
            elif isinstance(ev, SendResult):
                self._on_send_result(ev)

    def _on_send_result(self, ev):
        state = ev.state
        if state == R_FAILED and not self.cm.is_current_open(ev.cycle_id):
            state = R_EXPIRED
        try:
            self.store.set_response_state(ev.cycle_id, state, ev.error or None)
        except sqlite3.Error as e:
            logger.error(f"❌ บันทึกสถานะ S0 ({state}) ไม่ได้: {e}")
        if state != "ENQUEUED":
            logger.warning(f"📤 S0 ของรอบ {ev.cycle_id[:8]} → {state} {ev.error}")

    def _apply(self, result, now):
        """ทำ I/O ตามผลของ CycleMachine (ปิดรอบก่อนเปิดรอบใหม่เสมอ)"""
        if result.anomaly:
            logger.warning(f"⚠️ [{result.anomaly}] {result.note}")
        elif result.note:
            logger.info(f"🔁 {result.note}")
        if result.closed:
            self._on_closed(result.closed, now)
        if result.opened:
            self._on_opened(result.opened, now)

    def _on_opened(self, cycle_id, now):
        try:
            self.store.open_cycle(cycle_id)
        except sqlite3.Error as e:
            # รอบนี้ยืนยันไม่ได้ (confirm จะหา cycle ใน DB ไม่เจอ) แต่ยังรับ STOP ได้ตามปกติ
            logger.critical(f"❌ บันทึกรอบใหม่ลง DB ไม่ได้: {e}")

        # [BG] ใช้พื้นหลังก่อน START ตรึงไว้ทั้งรอบ + ล้าง tracker (ห้ามพาวัตถุจากก่อน START มา)
        self.tracker.clear_all()
        if self.watch_since is not None:
            # START ระหว่างเฝ้าดูนอกรอบ: ไม่ใช้ bg ที่ freeze ไว้ตอนเริ่มเฝ้า (อาจเป็นฉากก่อนลูกค้าหยิบของ)
            logger.info("👀 START ระหว่างเฝ้าดูนอกรอบ → เลิกเฝ้า ใช้ clean_bg ล่าสุด / เฟรมปัจจุบันเป็นพื้นหลังของรอบ")
            self.watch_since = None
        if self.bg.bg is None or self.frame_gray is None:
            # ยังไม่มีพื้นหลังเลย (กล้องเพิ่งเริ่ม / หลุด) → ห้ามใช้เฟรมหลัง START เป็นพื้นหลัง
            self.cm.on_camera_lost()
            logger.warning(f"⛔ รอบ {cycle_id[:8]}: ไม่มีพื้นหลังก่อน START → BLOCKED_WAIT_STOP")
        else:
            self.bg.start_cycle(self.frame_gray, now, reason=f"START {cycle_id[:8]}")
        logger.info(f"▶️ เปิดรอบ {cycle_id[:8]} (state={self.cm.state})")

    def _on_closed(self, closed, now):
        try:
            self.store.close_cycle(closed.cycle_id, closed.outcome, closed.reason)
        except sqlite3.Error as e:
            logger.critical(f"❌ บันทึกการปิดรอบลง DB ไม่ได้: {e}")
        # S0 ที่ยังไม่ได้ส่งของรอบนี้ห้ามส่งอีก
        self.controller.revoke(closed.cycle_id)
        if not closed.confirmed:
            # [ANOMALY c] ปิดรอบโดยไม่ได้ยืนยัน → ภาพสภาพถาดตอนปิดรอบ 1 ภาพ (ไม่จำกัดความถี่)
            self._save_anomaly(NO_CONFIRM_AT_CLOSE, closed.cycle_id, self.frame)
        # [RESET] ล้าง tracker → ปลด freeze + grace (ดูดมือที่ค้างในเฟรมเข้า bg ก่อน)
        self.tracker.clear_all()
        if self.bg.frozen:
            self.bg.unfreeze(now)
        self.bg.invalidate_clean_bg()
        logger.info(f"⏹️ ปิดรอบ {closed.cycle_id[:8]} → {closed.outcome} ({closed.reason})")

    def _on_no_frame(self):
        if self.camera_ok is not False:
            logger.warning("📷 ไม่มีเฟรมจากกล้อง")
        self.camera_ok = False
        if self.cm.on_camera_lost():
            logger.warning(
                f"⛔ กล้องหลุดระหว่างรอบ {self.cm.cycle_id[:8]} → BLOCKED_WAIT_STOP (ไม่ยืนยันจนปิดรอบ)"
            )
        self.bg.clear()  # กล้องหลุด → เริ่ม background ใหม่
        self.tracker.clear_all()
        self.watch_since = None

    # ── การยืนยัน ────────────────────────────────────────────────────────────
    def _confirm(self, frame, frame_gray, now):
        """ภาพ → DB (transaction เดียว) → latch → S0 — ล้มเหลวขั้นไหน = ไม่มียอด ไม่มี S0"""
        cycle_id = self.cm.cycle_id
        t0 = time.perf_counter()

        path = image_saver.save_evidence(
            frame, image_saver.CONFIRMED, "CONFIRMED", cycle_id, base_dir=self.evidence_dir,
        )
        if path is None:
            logger.error(f"❌ [EVIDENCE FAULT] รอบ {cycle_id[:8]}: บันทึกภาพไม่ได้ → ไม่ยืนยัน (ลองใหม่ถ้าของยังนิ่ง)")
            self.confirm_retry_at = now + CONFIRM_RETRY_SEC
            return
        try:
            conf = self.store.confirm(cycle_id, path)
        except sqlite3.Error as e:
            logger.error(f"❌ [STORAGE FAULT] รอบ {cycle_id[:8]}: บันทึก DB ไม่ได้ ({e}) → ไม่ยืนยัน")
            self.confirm_retry_at = now + CONFIRM_RETRY_SEC
            _remove_quietly(path)  # ภาพที่ไม่มี confirmation อ้างถึง
            return

        self.cm.mark_confirmed()
        self.today_count = conf.daily_sequence
        self.controller.request_s0(cycle_id, self.last_cmd_seq)
        daily_log.append(self.daily_log_dir, conf)

        # [RESET MOTION] เฟรมนี้เป็น bg ใหม่ + tracker ลืมของชิ้นนี้ → motion หลังยืนยันเป็นของใหม่
        self.bg.rebaseline(frame_gray, now)
        self.tracker.clear_all()
        ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"📸 ยืนยันสินค้า รอบ {cycle_id[:8]} — ยอดวันนี้ {conf.daily_sequence} "
            f"(บันทึก {ms:.0f}ms) → ส่ง S0"
        )

    def _rebaseline_settled_env(self, frame_gray, now):
        """[ENV SETTLED] รอบ ACTIVE: env change ค้าง (พื้นหลังของรอบต่างจากฉากเกิน MAX_BLOB_ROI_RATIO)
        แต่ ROI นิ่งเฟรมต่อเฟรมครบ CLEAN_BG_STABLE_FRAMES แล้ว → ฉากใหม่สงบแล้ว ตั้งเป็นพื้นหลังของรอบ
        เช่น START ตอน slat ยังเปิด (เฟรมปัจจุบันเป็นพื้นหลัง) แล้ว slat ปิด → ไม่งั้นมองไม่เห็นอะไรทั้งรอบ
        ต้องเป็น env change ที่ "ยังค้าง" ตอนนิ่ง (ของตกที่ก้อน motion ใหญ่ชั่วขณะ พอตกถึงพื้นก้อนเล็กลง → ไม่เข้าเงื่อนไข)
        ทำได้หลายครั้งต่อรอบ แต่ต้องนิ่งก่อนทุกครั้ง"""
        self.bg.rebaseline(frame_gray, now)
        self.tracker.clear_all()
        logger.info(
            f"🔄 รอบ {self.cm.cycle_id[:8]}: env change สงบแล้ว (ROI นิ่ง {CLEAN_BG_STABLE_FRAMES} เฟรม) "
            f"→ ตั้งพื้นหลังของรอบใหม่เป็นเฟรมนี้"
        )

    # ── เฝ้าดูนอกรอบ / anomaly ───────────────────────────────────────────────
    def _watch(self, tracked, now):
        """[WATCH] WAIT_START: มี motion ใน ROI → freeze bg (ใช้ clean_bg ก่อนมี motion)
        เพื่อให้วัตถุที่วางนิ่งไม่ถูกกลืนเข้า bg ก่อนครบเกณฑ์ → ถ่ายภาพ OUTSIDE_CYCLE ได้
        ปลด freeze เมื่อ ROI นิ่ง (เฟรมต่อเฟรม) ครบ CLEAN_BG_STABLE_FRAMES และไม่มีวัตถุค้าง
        หรือเฝ้าครบ WATCH_TIMEOUT_SEC (ไม่เปิดรอบ ไม่นับยอด)
        ไม่จบแค่เพราะ tracker ว่างเฟรมเดียว (env change / slat เปิด ทำให้ไม่มีกล่องได้ ทั้งที่ยังหยิบอยู่)
        ต้องไม่มีวัตถุค้างด้วย ไม่งั้นของที่วางนิ่งจะเลิกเฝ้าก่อนครบเกณฑ์ OUTSIDE_CYCLE"""
        if self.watch_since is None:
            if is_motion_in_roi(tracked) and not self.bg.in_grace(now) and not self.bg.frozen:
                self.bg.freeze(now, reason="เฝ้าดูนอกรอบ")
                self.watch_since = now
            return
        if self.bg.roi_still() and not tracked:
            self._end_watch(now, f"ROI นิ่งครบ {CLEAN_BG_STABLE_FRAMES} เฟรม")
        elif now - self.watch_since >= WATCH_TIMEOUT_SEC:
            self._end_watch(now, f"เฝ้าครบ {WATCH_TIMEOUT_SEC:.0f}s")

    def _end_watch(self, now, why):
        logger.info(f"👀 จบการเฝ้าดูนอกรอบ ({why}) → ปลด freeze")
        self.watch_since = None
        self.tracker.clear_all()
        self.bg.unfreeze(now)

    def _capture_anomaly(self, kind, frame, frame_gray, now):
        """[ANOMALY a/b] วัตถุนิ่งครบเกณฑ์นอกช่วงยืนยัน → ภาพ (จำกัดความถี่) ไม่นับยอด ไม่ส่ง S0
        ถ่ายหรือไม่ก็ตาม: rebaseline + ล้าง tracker (เหมือนหลังยืนยัน) → ไม่จับวัตถุเดิมซ้ำทุกเฟรม"""
        cycle_id = self.cm.cycle_id
        if self.anomaly_limiter.allow(self.mono()):
            self._save_anomaly(kind, cycle_id, frame)
        else:
            logger.info(f"🔕 [{kind}] วัตถุนิ่งครบเกณฑ์ แต่เกินโควตาภาพ anomaly → ไม่ถ่าย")
        self.bg.rebaseline(frame_gray, now)
        self.tracker.clear_all()

    def _save_anomaly(self, kind, cycle_id, frame):
        path = None
        if frame is not None:
            path = image_saver.save_evidence(
                frame, image_saver.ANOMALY, kind, cycle_id,
                base_dir=self.evidence_dir, label=_ANOMALY_LABELS[kind],
            )
        try:
            self.store.record_anomaly(kind, cycle_id, path)
        except sqlite3.Error as e:
            logger.error(f"❌ บันทึก anomaly {kind} ลง DB ไม่ได้: {e}")
        where = f"รอบ {cycle_id[:8]}" if cycle_id else "นอกรอบ"
        logger.warning(f"🚩 ANOMALY {kind} ({where}) — ไม่นับยอด ภาพ: {path or 'ไม่มี (ไม่มีเฟรม)'}")

    def view(self):
        """ข้อมูลสำหรับ overlay"""
        now = self.clock()
        if now - self._count_checked_at >= 1.0:
            # อ่านยอดจาก DB ทุก 1 วินาที → ข้ามเที่ยงคืนแล้วยอดบนจอกลับเป็นของวันใหม่
            self.today_count = self.store.count_today()
            self._count_checked_at = now
        return {
            "state": self.cm.state,
            "watching": self.watch_since is not None,
            "cycle_id": self.cm.cycle_id,
            "today_count": self.today_count,
            "redis_up": self.redis_up,
            "camera_ok": self.camera_ok,
            "bg_frozen": self.bg.frozen,
            "keyboard": not self.controller.enabled,
        }

    # ── loop หลัก ────────────────────────────────────────────────────────────
    def run(self):
        while self.running:
            frame, fgmask, tracked = self.step()
            if frame is not None:
                if not self.headless:
                    render_overlay(frame, self.view(), tracked, self.roi_manager, FRAME_W, FRAME_H)
                self.source.pace()

            if not self.headless:
                if frame is not None:
                    cv2.imshow("Vending System", frame)
                    if fgmask is not None:
                        cv2.imshow("Motion Mask", fgmask)
                self._handle_key(cv2.waitKey(1) & 0xFF)

    def _handle_key(self, key):
        if key == ord("q"):
            self.running = False
        elif key == ord("s"):
            self.controller.inject("START")
        elif key == ord("x"):
            self.controller.inject("STOP")
        elif key == ord("r"):
            # ล้างพื้นหลัง + tracker ด้วยมือ (เหมือนกล้องหลุด) — ไม่แตะรอบ / ยอด
            self.tracker.clear_all()
            self.bg.clear()


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--machine", type=str, default=MACHINE_ID)
    args = parser.parse_args()

    logger.info(f"🖥️ ระบบทำงานในชื่อตู้: {args.machine}")
    logger.info(f"🖥️ โหมด: {'HEADLESS (Pi)' if HEADLESS else 'DISPLAY (PC)'} / คำสั่งจาก {CONTROL_MODE}")
    logger.info(config.summary())

    try:
        store = StateStore(STATE_DB_PATH, args.machine, COUNT_TIMEZONE)
    except StateStoreError as e:
        logger.critical(str(e))
        raise SystemExit(f"{e}\n   → ห้ามลบไฟล์ DB เพื่อให้บูตผ่าน: สำรองไฟล์แล้วแจ้งผู้ดูแล")

    controller = RedisController(
        lambda: make_client(
            REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
            REDIS_CONNECT_TIMEOUT_SEC, REDIS_SOCKET_TIMEOUT_SEC,
        ),
        ctrl_key=REDIS_CTRL_KEY,
        response_key=REDIS_RESPONSE_KEY,
        enabled=(CONTROL_MODE == "redis"),
    )
    source = FrameSource(CAMERA_INDEX)
    roi_manager = ROIManager(FRAME_W, FRAME_H, config_path=ROI_CONFIG_PATH)
    start_cleanup_thread()
    if CLOUD_ENABLED:
        start_cloud_services(args.machine)
    else:
        logger.info("☁️ CLOUD_ENABLED=0 — ไม่เริ่ม register / ROI polling / ภาพสด / retry queue")

    # เปิดหน้าต่างแบบปรับขนาดได้ (WINDOW_NORMAL) แทน AUTOSIZE ที่ล็อกขนาดตายตัว
    if not HEADLESS:
        for name in ("Vending System", "Motion Mask"):
            cv2.namedWindow(name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(name, FRAME_W, FRAME_H)

    app = App(args.machine, source, roi_manager, store, controller, headless=HEADLESS)

    def _shutdown(signum, _frame):
        logger.info(f"🛑 ได้รับ signal {signum} → ปิดโปรแกรม")
        app.running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    controller.start()
    try:
        app.run()
    finally:
        controller.stop()
        source.release()
        store.close()
        if not HEADLESS:
            cv2.destroyAllWindows()
        logger.info("👋 ปิดโปรแกรมแล้ว")


if __name__ == "__main__":
    main()
