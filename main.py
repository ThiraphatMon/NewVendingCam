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
import time
import cv2
import numpy as np
import config
from config import (
    FRAME_W, FRAME_H, CAMERA_INDEX, MACHINE_ID, HEADLESS, ROI_CONFIG_PATH,
    MOT_THRESH, MIN_AREA, MAX_BLOB_ROI_RATIO,
    SHADOW_FILTER, SHADOW_NCC_WIN, SHADOW_NCC_THR, SHADOW_FLAT_VAR, SHADOW_MIN_AREA,
    MORPH_OPEN_KSIZE, MORPH_DILATE_KSIZE, MORPH_DILATE_ITER,
    GROUP_MODE, GROUP_DIST, GROUP_OVERLAP_PAD, LANDING_STABLE_FRAMES,
    CAPTURE_HOLD_SEC, CYCLE_TIMEOUT_SEC, CONTROL_MODE, EVIDENCE_DIR,
    DAILY_LOG_DIR, ANOMALY_MAX_PER_DAY,
    REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD, REDIS_CTRL_KEY, REDIS_RESPONSE_KEY,
    REDIS_CONNECT_TIMEOUT_SEC, REDIS_SOCKET_TIMEOUT_SEC,
    STATE_DB_PATH, COUNT_TIMEZONE, CLEAN_BG_STABLE_FRAMES, SEND_S0,
    ENV_SETTLE_REBASELINE, REMOVAL_CHECK, REMOVAL_EDGE_RATIO, REMOVAL_MATCH_RATIO, REMOVAL_UNCERTAIN_SEND_S0,
)
from api.cloud import item_landed_event
from api.redis_controller import Command, LinkStatus, RedisController, SendResult, make_client
from core import cycle as cyc
from core.background import BackgroundModel, find_env_change
from core.cycle import CycleMachine
from core.detect import build_fgmask, contour_boxes, drop_large_boxes, group_close_boxes
from core.frame_source import NO_NEW_FRAME, FrameSource
from core import removal
from core.roi import ROIManager
from core.tracker import MemoryTracker, is_motion_in_roi
from utils import daily_log, image_saver
from utils.disk_cleanup import start_cleanup_thread
from utils.logger import get_logger
from utils.state_store import R_EXPIRED, R_FAILED, StateStore, StateStoreError, pending_image_paths
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
POSSIBLE_REMOVAL = "POSSIBLE_REMOVAL"        # รอบ ACTIVE: วัตถุนิ่งที่ดูเหมือนของถูกหยิบออก → ไม่ยืนยัน
ENV_CHANGE = "ENV_CHANGE"                    # env change (ก้อนใหญ่เกิน MAX_BLOB_ROI_RATIO) — 1 ภาพต่อเหตุการณ์ ทุก state
# เหตุที่ปิดรอบ (ClosedCycle.reason ส่วนแรก) → ข้อความ log
_CLOSE_TRIGGERS = {"stop": "STOP received", "next_start": "next START received", "timeout": "cycle timeout"}
_ANOMALY_LABELS = {
    OUTSIDE_CYCLE: "OUTSIDE CYCLE",
    EXTRA_AFTER_CONFIRM: "SUSPICIOUS (extra after confirm)",
    NO_CONFIRM_AT_CLOSE: "NO CONFIRM AT CLOSE",
    POSSIBLE_REMOVAL: "POSSIBLE REMOVAL (not counted)",
    ENV_CHANGE: "ENV CHANGE",
}


def shadow_filter_on():
    return SHADOW_FILTER == "texture"


def shadow_summary():
    """1 บรรทัดตอน startup: ตัวกรองแสง/เงาที่ใช้"""
    if not shadow_filter_on():
        return "Shadow filter: off"
    return (
        f"Shadow filter: texture (win={SHADOW_NCC_WIN}, ncc>{SHADOW_NCC_THR:g}, flat_var<{SHADOW_FLAT_VAR:g}, "
        f"min blob {SHADOW_MIN_AREA}px instead of MIN_AREA {MIN_AREA}px)"
    )


def detect_objects(diff, roi_manager, roi_mask, shadow_ref=None, frame_gray=None, roi_box=None):
    """diff → motion mask ใน ROI → กล่องของ (รวมก้อนที่แตกแล้ว)
    คืน (fgmask, detected[(cx, cy, w, h)], env_change)

    shadow_ref : [S22] ภาพนิ่งอ้างอิงลวดลาย (BackgroundModel.ncc_reference) ตัดเฉพาะ roi_box (x, y, w, h)
                 None = ไม่กรองแสง/เงา (ใช้ MIN_AREA) | มี = กรอง + ก้อนเล็กสุด SHADOW_MIN_AREA
    frame_gray : เฟรมปัจจุบัน (grayscale float32 ทั้งภาพ) ใช้คู่กับ shadow_ref"""
    shadow = None
    if shadow_ref is not None and frame_gray is not None and roi_box is not None:
        x, y, w, h = roi_box
        shadow = (shadow_ref, frame_gray[y:y + h, x:x + w], roi_box,
                  SHADOW_NCC_WIN, SHADOW_NCC_THR, SHADOW_FLAT_VAR)
    # [S22] ตัดแสง/เงา → OPEN (ลบ noise จุดเล็ก) → DILATE (เชื่อม mask ชิ้นเดียวที่ขาด) — ดู core/detect.py
    fgmask = build_fgmask(
        diff, MOT_THRESH, MORPH_OPEN_KSIZE, MORPH_DILATE_KSIZE, MORPH_DILATE_ITER, shadow=shadow
    )
    fgmask = cv2.bitwise_and(fgmask, roi_mask)

    # [NOISE] contour เล็กกว่า MIN_AREA ถูกตัดทิ้ง
    # [ENV CHANGE] ก้อนใหญ่เกิน MAX_BLOB_ROI_RATIO ของ ROI = แสง/bg เปลี่ยน → ไม่ส่งเข้า tracker
    roi_areas = roi_manager.get_roi_areas(fgmask.shape)
    env_change = find_env_change(fgmask, roi_areas)
    raw_boxes = contour_boxes(fgmask, MIN_AREA if shadow is None else SHADOW_MIN_AREA)
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
    cloud : api.cloud.CloudServices หรือ None (cloud ปิด) — main loop แค่ฝากเฟรม/งาน ไม่รอ network
    send_s0 : False = โหมดเก็บข้อมูล (ยืนยันตามปกติแต่ไม่ขอส่ง S0, DB เป็น NOT_SENT) — None = ตาม SEND_S0
    shadow_filter : [S22] True = กรองแสง/เงา (texture) | False = แบบเดิม — None = ตาม SHADOW_FILTER
    """

    def __init__(
        self, machine_id, source, roi_manager, store, controller,
        headless=True, evidence_dir=EVIDENCE_DIR, daily_log_dir=DAILY_LOG_DIR,
        clock=time.time, mono=time.monotonic, cloud=None, send_s0=None, shadow_filter=None,
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
        self.cloud = cloud
        self.send_s0 = SEND_S0 if send_s0 is None else send_s0
        self.shadow_filter = shadow_filter_on() if shadow_filter is None else shadow_filter

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
        self.frame = None              # เฟรมล่าสุด (ใช้ถ่ายภาพ NO_CONFIRM_AT_CLOSE ตอนปิดรอบ)
        self.fgmask = None             # [S22] motion mask ล่าสุด (log ขนาดก้อนตอนยืนยัน)
        self.frame_gray = None         # เฟรมล่าสุดแบบ gray (START ใช้เป็นพื้นหลังได้ถ้าไม่มี clean_bg ที่ valid)
        self.watch_since = None        # [WATCH] เวลาเริ่มเฝ้าดูนอกรอบ (None = ไม่ได้เฝ้า)
        self.cycle_t0 = None           # [TIMING] เวลา (clock) ที่เปิดรอบปัจจุบัน
        self.cycle_motion_at = None    # [TIMING] เฟรมแรกในรอบ ACTIVE ที่ tracker เห็นวัตถุ
        # [ANOMALY] เพดานภาพต่อวัน (ทุกชนิดรวม) — นับจาก DB ตอนเริ่มวัน/เริ่มโปรแกรม
        self.anomaly_day = None
        self.anomaly_images_today = 0
        self.anomaly_cap_warned = False
        # [ENV_CHANGE] ถ่ายแล้วรอ ROI นิ่ง (CLEAN_BG_STABLE_FRAMES เฟรม) ก่อน arm ใหม่ → env change ค้างหลายเฟรม = 1 ภาพ
        self.env_armed = True

        # [RECOVERY] process ก่อนหน้าตายกลางรอบ → ปิดเป็น INTERRUPTED + S0 ค้างหมดอายุ
        # แล้วเริ่มที่ WAIT_START ทันที (เหมือนตัวเก่าที่ restart แล้วรับ START ใหม่ได้เลย)
        interrupted = store.recover_open_cycles()
        if interrupted:
            short = ", ".join(c[:8] for c in interrupted)
            logger.warning(
                f"interrupted (program restarted): open cycle(s) {short} closed as INTERRUPTED "
                f"(no S0 for old cycles) -> WAIT_START"
            )
        # [DAILY LOG] สร้างไฟล์ของวันนี้ใหม่จาก DB (ซ่อมบรรทัดที่ขาด/ซ้ำหลัง crash)
        today = store.today()
        n = daily_log.rebuild(self.daily_log_dir, store, today)
        logger.info(f"today's count ({today}) = {self.today_count} (daily log {n} lines)")

    # ── 1 iteration ─────────────────────────────────────────────────────────
    def step(self):
        """คืน (frame, fgmask, tracked) สำหรับวาดจอ (frame=None ถ้าไม่มีเฟรม)"""
        frame = self.source.read()
        now = self.clock()
        fresh = frame is not NO_NEW_FRAME
        if fresh:
            self.frame = frame
            # START ใช้เฟรมนี้เป็นพื้นหลังของรอบได้ (ถ้ายังไม่มี clean_bg ที่ valid) → แปลงก่อนรับคำสั่ง
            self.frame_gray = (
                None if frame is None else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
            )

        # คำสั่ง / ผลส่ง S0 ก่อนผลตรวจจับเสมอ (STOP ที่มาระหว่างอ่านเฟรมต้องมีผลก่อนยืนยัน)
        # ทำทุกรอบแม้ไม่มีเฟรมใหม่ / กล้องค้าง
        self._handle_inbox(now)
        result = self.cm.tick(self.mono())
        if result:
            self._apply(result, now)

        if not fresh:
            # ยังไม่มีเฟรมใหม่ (ไม่ใช่กล้องค้าง) → ไม่ตรวจจับซ้ำกับเฟรมเดิม
            return None, None, {}

        if frame is None:
            self._on_no_frame()
            return None, None, {}
        if self.camera_ok is not True:
            if self.camera_ok is False:
                logger.info("camera back (frames received again)")
            self.camera_ok = True

        if self.cloud is not None and self.cloud.realtime_due(now):
            self.cloud.submit_frame(frame, now)

        frame_gray = self.frame_gray
        idle = self.cm.state == cyc.WAIT_START
        # [ROI] ROI ใหม่ (จากเว็บ/แก้ไฟล์) ระหว่างรอบ → รอใช้ตอนกลับ WAIT_START (ไม่เปลี่ยนเกณฑ์กลางรอบ)
        if self.roi_manager.reload_if_changed(allow_apply=idle):
            self._on_roi_changed(now)
        roi_mask = self.roi_manager.build_mask(frame_gray.shape)
        # [S22] ภาพนิ่งอ้างอิงลวดลาย (snapshot → clean_bg ที่ valid → bg ของ diff) เฉพาะกล่อง ROI
        #   เลือกก่อน bg.update (update เรียนรู้ทับ bg / เปลี่ยน clean_bg) จึง copy ไว้
        roi_box = shadow_ref = None
        ref = self.bg.ncc_reference() if self.shadow_filter else None
        if ref is not None:
            roi_box = cv2.boundingRect(roi_mask)
            x, y, w, h = roi_box
            shadow_ref = ref[y:y + h, x:x + w].copy()
        diff = self.bg.update(frame_gray, now, idle=idle, roi_mask=roi_mask)
        if diff is None:
            return frame, None, {}

        fgmask, detected, env_change = detect_objects(
            diff, self.roi_manager, roi_mask, shadow_ref, frame_gray, roi_box
        )
        self.fgmask = fgmask
        self._track_env_change(env_change, frame)
        if env_change and self.bg.frozen:
            self.bg.restore_snapshot()
        if env_change and idle:
            self.bg.mark_scene_changed()  # [WATCH] clean_bg ก่อน env change ห้ามใช้ตอน START
        if ENV_SETTLE_REBASELINE and env_change and self.cm.can_confirm() and self.bg.roi_still():
            self._rebaseline_settled_env(frame_gray, now)
            return frame, fgmask, {}
        tracked = self.tracker.update(detected)

        if self.cm.state == cyc.WAIT_START:
            self._watch(tracked, now)
        elif self.cm.can_confirm() and tracked and self.cycle_motion_at is None:
            self.cycle_motion_at = now

        landed = find_landed(tracked, now)
        if landed is not None:
            if self.cm.can_confirm():
                if now >= self.confirm_retry_at:
                    t_s3 = time.perf_counter()
                    is_removal = self._looks_like_removal(tracked[landed], frame_gray)
                    s3_ms = (time.perf_counter() - t_s3) * 1000
                    if is_removal:
                        self._capture_anomaly(POSSIBLE_REMOVAL, frame, frame_gray, now)
                    else:
                        self._confirm(frame, frame_gray, now, landed, tracked[landed], s3_ms)
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
                logger.info(f"{ev.text} received (#{ev.seq} from {ev.source})")
                self._apply(result, now)
            elif isinstance(ev, LinkStatus):
                self.redis_up = ev.up
                if not ev.up and self.cm.is_open():
                    self.cm.on_redis_gap()
                    logger.warning(f"[cycle {self.cm.cycle_id[:8]}] Redis disconnected during cycle ({ev.error})")
            elif isinstance(ev, SendResult):
                self._on_send_result(ev)

    def _on_send_result(self, ev):
        state = ev.state
        if state == R_FAILED and not self.cm.is_current_open(ev.cycle_id):
            state = R_EXPIRED
        try:
            self.store.set_response_state(ev.cycle_id, state, ev.error or None)
        except sqlite3.Error as e:
            logger.error(f"cannot save S0 state ({state}) to DB: {e}")
        if state != "ENQUEUED":
            logger.warning(f"[cycle {ev.cycle_id[:8]}] S0 -> {state} {ev.error}")

    def _apply(self, result, now):
        """ทำ I/O ตามผลของ CycleMachine (ปิดรอบก่อนเปิดรอบใหม่เสมอ)"""
        if result.anomaly:
            prefix = f"[cycle {self.cm.cycle_id[:8]}] " if self.cm.cycle_id else ""
            logger.warning(f"{prefix}[{result.anomaly}] {result.note}")
        elif result.note and not (result.closed or result.opened):
            logger.info(result.note)
        elif result.note:
            logger.debug(result.note)  # เปิด/ปิดรอบมี log ของตัวเองใน _on_opened / _on_closed
        if result.closed:
            self._on_closed(result.closed, now)
        if result.opened:
            self._on_opened(result.opened, now)

    def _on_opened(self, cycle_id, now):
        try:
            self.store.open_cycle(cycle_id)
        except sqlite3.Error as e:
            # รอบนี้ยืนยันไม่ได้ (confirm จะหา cycle ใน DB ไม่เจอ) แต่ยังรับ STOP ได้ตามปกติ
            logger.critical(f"[cycle {cycle_id[:8]}] cannot save new cycle to DB: {e}")

        # [BG] ใช้พื้นหลังก่อน START ตรึงไว้ทั้งรอบ + ล้าง tracker (ห้ามพาวัตถุจากก่อน START มา)
        self.tracker.clear_all()
        if self.watch_since is not None:
            # START ระหว่างเฝ้าดูนอกรอบ: ไม่ใช้ bg ที่ freeze ไว้ตอนเริ่มเฝ้า (อาจเป็นฉากก่อนลูกค้าหยิบของ)
            logger.info(
                f"[cycle {cycle_id[:8]}] START during outside-cycle watch -> stop watching, "
                f"use latest empty-tray background / current frame as cycle background"
            )
            self.watch_since = None
        if self.bg.bg is None or self.frame_gray is None:
            # ยังไม่มีพื้นหลังเลย (กล้องเพิ่งเริ่ม / หลุด) → ห้ามใช้เฟรมหลัง START เป็นพื้นหลัง
            self.cm.on_camera_lost()
            desc = "none - no background before START -> BLOCKED_WAIT_STOP"
        else:
            self.bg.start_cycle(self.frame_gray, now, reason=f"START {cycle_id[:8]}")
            desc = self.bg.start_desc
        self.cycle_t0 = now
        self.cycle_motion_at = None
        log = logger.info if self.cm.state == cyc.ACTIVE else logger.warning
        log(f"[cycle {cycle_id[:8]}] START received -> cycle opened (background: {desc})")

    def _on_closed(self, closed, now):
        try:
            self.store.close_cycle(closed.cycle_id, closed.outcome, closed.reason)
        except sqlite3.Error as e:
            logger.critical(f"[cycle {closed.cycle_id[:8]}] cannot save cycle close to DB: {e}")
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
        trigger, *gaps = closed.reason.split(";")
        what = _CLOSE_TRIGGERS.get(trigger, trigger)
        extra = f" ({', '.join(gaps)})" if gaps else ""
        logger.info(f"[cycle {closed.cycle_id[:8]}] {what} -> cycle closed: {closed.outcome}{extra}")

    def _on_no_frame(self):
        if self.camera_ok is not False:
            logger.warning("camera disconnected (no frame from camera)")
        self.camera_ok = False
        if self.cm.on_camera_lost():
            logger.warning(
                f"[cycle {self.cm.cycle_id[:8]}] camera disconnected during cycle -> BLOCKED_WAIT_STOP "
                f"(no confirm until cycle closed)"
            )
        self.bg.clear()  # กล้องหลุด → เริ่ม background ใหม่
        self.tracker.clear_all()
        self.watch_since = None

    # ── การยืนยัน ────────────────────────────────────────────────────────────
    def _confirm(self, frame, frame_gray, now, obj_id=None, obj=None, s3_ms=0.0):
        """ภาพ → DB (transaction เดียว) → latch → S0 → (cloud outbox) — ล้มเหลวขั้นไหน = ไม่มียอด ไม่มี S0
        cloud ทำหลัง S0 และล้มเหลวได้โดยไม่กระทบยอด/S0"""
        cycle_id = self.cm.cycle_id
        t0 = time.perf_counter()

        path = image_saver.save_evidence(
            frame, image_saver.CONFIRMED, "CONFIRMED", cycle_id, base_dir=self.evidence_dir,
        )
        if path is None:
            logger.error(
                f"[cycle {cycle_id[:8]}] [EVIDENCE FAULT] cannot save image -> not confirmed (retry if item still)"
            )
            self.confirm_retry_at = now + CONFIRM_RETRY_SEC
            return
        try:
            conf = self.store.confirm(cycle_id, path, send_s0=self.send_s0)
        except sqlite3.Error as e:
            logger.error(f"[cycle {cycle_id[:8]}] [STORAGE FAULT] cannot save to DB ({e}) -> not confirmed")
            self.confirm_retry_at = now + CONFIRM_RETRY_SEC
            _remove_quietly(path)  # ภาพที่ไม่มี confirmation อ้างถึง
            return

        self.cm.mark_confirmed()
        self.today_count = conf.daily_sequence
        if self.send_s0:
            self.controller.request_s0(cycle_id, self.last_cmd_seq)
        daily_log.append(self.daily_log_dir, conf)
        self._queue_item_landed(conf, obj_id)

        # [RESET MOTION] เฟรมนี้เป็น bg ใหม่ + tracker ลืมของชิ้นนี้ → motion หลังยืนยันเป็นของใหม่
        self.bg.rebaseline(frame_gray, now)
        self.tracker.clear_all()
        ms = (time.perf_counter() - t0) * 1000
        if obj is not None and self.cycle_t0 is not None:
            logger.info(self._timing_line(cycle_id, now, obj, s3_ms, ms))
        if obj is not None:
            logger.info(f"[cycle {cycle_id[:8]}] {self._size_text(obj)}")
        s0 = "S0 requested" if self.send_s0 else "S0 NOT SENT (observe mode)"
        logger.info(
            f"[cycle {cycle_id[:8]}] item confirmed, today's count {conf.daily_sequence} "
            f"(saved in {ms:.0f}ms) -> {s0}"
        )

    def _size_text(self, obj):
        """[S22] ขนาดก้อนที่ยืนยัน (เก็บขนาดสินค้าจริงจากตู้ไว้ตั้ง SHADOW_MIN_AREA / MIN_AREA)
        blob = จำนวนพิกเซล motion mask ในกล่องของวัตถุ (หลัง OPEN/DILATE)"""
        cx, cy = obj["centroid"]
        w, h = obj["shape"]
        blob = "?"
        if self.fgmask is not None:
            x0, y0 = max(0, int(cx - w / 2)), max(0, int(cy - h / 2))
            blob = int(cv2.countNonZero(self.fgmask[y0:y0 + int(h), x0:x0 + int(w)]))
        return f"item size: blob {blob}px, box {int(w)}x{int(h)} at ({int(cx)},{int(cy)})"

    def _timing_line(self, cycle_id, now, obj, s3_ms, save_ms):
        """[TIMING] 1 บรรทัดแยกช่วงเวลา START → เห็นวัตถุ → นิ่ง (เริ่มนับ hold) → ครบ hold → S3 → ยืนยัน
        เวลาเป็นวินาทีจาก START (นาฬิกาเฟรม) · t0 = epoch ของ START (e2e แปลงเป็นเวลาคลิป)"""
        t0 = self.cycle_t0
        motion = self.cycle_motion_at if self.cycle_motion_at is not None else obj["first_seen"]
        still = obj.get("shape_confirmed_time") or now
        frames_to_still = obj.get("still_frame", 0) - 1
        return (
            f"[cycle {cycle_id[:8]}] timing: START->motion {motion - t0:.2f}s, "
            f"START->item seen {obj['first_seen'] - t0:.2f}s, "
            f"seen->still {still - obj['first_seen']:.2f}s ({frames_to_still} frames, "
            f"LANDING_STABLE_FRAMES={LANDING_STABLE_FRAMES}, still resets {obj.get('still_resets', 0)}), "
            f"still->hold done {now - still:.2f}s (CAPTURE_HOLD_SEC={CAPTURE_HOLD_SEC:g}), "
            f"S3 {s3_ms:.0f}ms, save {save_ms:.0f}ms, START->confirm {now - t0:.2f}s t0={t0:.3f}"
        )

    def _queue_item_landed(self, conf, obj_id):
        """[CLOUD] ITEM_LANDED → cloud_outbox (worker ส่งเอง) — เฉพาะ CLOUD_SEND_EVENTS เปิด
        เขียน DB ไม่ได้ → แค่ log (ยอดและ S0 ทำไปแล้ว ไม่ย้อนกลับ)"""
        if self.cloud is None or not self.cloud.features["events"]:
            return
        event_id, payload = item_landed_event(self.machine_id, conf, obj_id)
        try:
            self.store.enqueue_cloud_event(event_id, conf.cycle_id, "ITEM_LANDED", payload, conf.evidence_path)
        except sqlite3.Error as e:
            logger.error(
                f"[cycle {conf.cycle_id[:8]}] cannot add ITEM_LANDED to outbox ({e}) -> no upload (count/S0 not affected)"
            )
            return
        self.cloud.notify_outbox()

    def _on_roi_changed(self, now):
        """ใช้ ROI ใหม่แล้ว (WAIT_START เท่านั้น) → ล้าง tracker / clean_bg / scene history ที่ผูกกับ ROI เดิม"""
        if self.watch_since is not None:
            self._end_watch(now, "ROI changed")
        self.tracker.clear_all()
        self.bg.forget_roi_history()
        logger.info(
            f"new ROI applied ({self.roi_manager.roi_type}) -> cleared tracker / empty-tray background / "
            f"scene history of old ROI"
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
            f"[cycle {self.cm.cycle_id[:8]}] env change settled (ROI still {CLEAN_BG_STABLE_FRAMES} frames) "
            f"-> background reset to this frame"
        )

    def _looks_like_removal(self, obj, frame_gray):
        """[REMOVAL] candidate ในรอบ ACTIVE เป็น "ของหายไป" (ลูกค้าหยิบออก) ไม่ใช่สินค้าตก?
        เทียบ patch กับพื้นหลังของรอบ + ฉากนิ่งก่อนวัตถุนี้ปรากฏ (core/removal.py)
        True = ไม่ยืนยัน (main ถ่าย anomaly POSSIBLE_REMOVAL + ตั้งพื้นหลังใหม่ รอบยัง ACTIVE รับของจริงต่อได้)"""
        if not REMOVAL_CHECK:
            return False
        box = removal.box_of(obj, frame_gray.shape)
        if box is None:
            return False
        v = removal.classify(
            frame_gray, self.bg.bg, self.bg.scenes_before(obj["first_seen"]), box,
            REMOVAL_EDGE_RATIO, REMOVAL_MATCH_RATIO, MOT_THRESH,
        )
        cycle = self.cm.cycle_id[:8]
        # log 1 บรรทัดทุกการตัดสิน (INFO ขึ้นไป) — เก็บค่าขอบ/เกณฑ์ตอนทดสอบสินค้าจริง
        detail = (
            f"{v.describe(REMOVAL_EDGE_RATIO)}, diff_prev match < {v.diff_base * REMOVAL_MATCH_RATIO:.1f} "
            f"(diff_bg x{REMOVAL_MATCH_RATIO:.2f})"
        )
        if v.kind == removal.ADDITION:
            logger.info(f"[cycle {cycle}] S3={v.kind} {detail} -> item added -> confirm")
            return False
        if v.kind == removal.UNCERTAIN and REMOVAL_UNCERTAIN_SEND_S0:
            logger.warning(
                f"[cycle {cycle}] S3={v.kind} {detail} -> uncertain -> confirm anyway (REMOVAL_UNCERTAIN_SEND_S0=1)"
            )
            return False
        why = "item removed" if v.kind == removal.REMOVAL else "uncertain (no previous scene to compare)"
        logger.warning(f"[cycle {cycle}] S3={v.kind} {detail} -> {why} -> not confirmed, no S0")
        return True

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
                self.bg.freeze(now, reason="outside-cycle watch")
                self.watch_since = now
            return
        if self.bg.roi_still() and not tracked:
            self._end_watch(now, f"ROI still {CLEAN_BG_STABLE_FRAMES} frames")
        elif now - self.watch_since >= WATCH_TIMEOUT_SEC:
            self._end_watch(now, f"watched {WATCH_TIMEOUT_SEC:.0f}s")

    def _end_watch(self, now, why):
        logger.info(f"outside-cycle watch ended ({why}) -> background unfrozen")
        self.watch_since = None
        self.tracker.clear_all()
        self.bg.unfreeze(now)

    def _capture_anomaly(self, kind, frame, frame_gray, now):
        """[ANOMALY a/b] วัตถุนิ่งครบเกณฑ์นอกช่วงยืนยัน → 1 ภาพต่อเหตุการณ์ ไม่นับยอด ไม่ส่ง S0
        แล้ว rebaseline + ล้าง tracker (เหมือนหลังยืนยัน) → วัตถุเดิมไม่ถูกจับซ้ำทุกเฟรม (กันซ้ำต่อเหตุการณ์)"""
        self._save_anomaly(kind, self.cm.cycle_id, frame)
        self.bg.rebaseline(frame_gray, now)
        self.tracker.clear_all()

    def _track_env_change(self, env_change, frame):
        """[ENV_CHANGE] 1 ภาพตอนเริ่ม env change (ทุก state, ผูก cycle_id ถ้าอยู่ในรอบ) — ไม่แตะตรรกะการตรวจจับ
        ไม่ถ่ายซ้ำจน ROI นิ่งครบ CLEAN_BG_STABLE_FRAMES (เกณฑ์เดียวกับ clean_bg) แล้ว env change ครั้งถัดไปจึงถ่ายใหม่
        ถ่ายเฉพาะตอนฉากกำลังเปลี่ยนจริง (ROI ไม่นิ่งเฟรมต่อเฟรม) — env change ที่ค้างขณะฉากนิ่ง (เช่น slat เปิดค้าง
        หรือ bg ค่อย ๆ เรียนรู้จนก้อนแกว่งรอบเกณฑ์ 30%) ไม่นับเป็นเหตุการณ์ใหม่"""
        if env_change and self.env_armed and not self.bg.roi_still():
            self.env_armed = False
            self._save_anomaly(ENV_CHANGE, self.cm.cycle_id if self.cm.is_open() else None, frame)
        elif not self.env_armed and self.bg.roi_still():
            self.env_armed = True

    def _anomaly_image_allowed(self):
        """[ANOMALY] เพดาน ANOMALY_MAX_PER_DAY ภาพต่อวัน (ทุกชนิดรวม วันตาม COUNT_TIMEZONE) — เตือนวันละครั้ง"""
        today = self.store.today()
        if today != self.anomaly_day:
            self.anomaly_day = today
            self.anomaly_cap_warned = False
            try:
                self.anomaly_images_today = self.store.count_anomaly_images(today)
            except sqlite3.Error:
                self.anomaly_images_today = 0
        if self.anomaly_images_today < ANOMALY_MAX_PER_DAY:
            return True
        if not self.anomaly_cap_warned:
            self.anomaly_cap_warned = True
            logger.warning(
                f"anomaly image limit reached: {self.anomaly_images_today} images today "
                f"(ANOMALY_MAX_PER_DAY={ANOMALY_MAX_PER_DAY}) -> no more anomaly images until tomorrow "
                f"(events still recorded in DB)"
            )
        return False

    def _save_anomaly(self, kind, cycle_id, frame, why_no_image="no frame"):
        path = None
        if frame is not None and not self._anomaly_image_allowed():
            why_no_image = f"ANOMALY_MAX_PER_DAY={ANOMALY_MAX_PER_DAY} reached"
        elif frame is not None:
            path = image_saver.save_evidence(
                frame, image_saver.ANOMALY, kind, cycle_id,
                base_dir=self.evidence_dir, label=_ANOMALY_LABELS[kind],
            )
            if path is not None:
                self.anomaly_images_today += 1
        try:
            self.store.record_anomaly(kind, cycle_id, path)
        except sqlite3.Error as e:
            logger.error(f"cannot save anomaly {kind} to DB: {e}")
        where = f"[cycle {cycle_id[:8]}] " if cycle_id else "[outside cycle] "
        logger.warning(f"{where}anomaly image {kind} (not counted): {path or f'none ({why_no_image})'}")

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
            # ไฟล์วิดีโอถูกหน่วงตาม FPS ใน reader thread ของ FrameSource แล้ว
            if frame is not None and not self.headless:
                render_overlay(frame, self.view(), tracked, self.roi_manager, FRAME_W, FRAME_H)

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

    logger.info(f"machine: {args.machine}")
    logger.info(f"mode: {'HEADLESS (Pi)' if HEADLESS else 'DISPLAY (PC)'} / commands from {CONTROL_MODE}")
    logger.info(config.summary())
    logger.info(
        "S0 response: ENABLED (SEND_S0=1)" if SEND_S0 else "S0 response: DISABLED (observe mode, SEND_S0=0)"
    )
    logger.info(shadow_summary())
    for warning in config.inactive_warnings():
        logger.warning(warning)

    try:
        store = StateStore(STATE_DB_PATH, args.machine, COUNT_TIMEZONE)
    except StateStoreError as e:
        logger.critical(str(e))
        raise SystemExit(f"{e}\n   -> do NOT delete the DB file to make it boot: back it up and contact the maintainer")

    controller = RedisController(
        lambda: make_client(
            REDIS_HOST, REDIS_PORT, REDIS_DB, REDIS_PASSWORD,
            REDIS_CONNECT_TIMEOUT_SEC, REDIS_SOCKET_TIMEOUT_SEC,
        ),
        ctrl_key=REDIS_CTRL_KEY,
        response_key=REDIS_RESPONSE_KEY,
        enabled=(CONTROL_MODE == "redis"),
        send_s0=SEND_S0,
    )
    source = FrameSource(CAMERA_INDEX)
    roi_manager = ROIManager(FRAME_W, FRAME_H, config_path=ROI_CONFIG_PATH)
    # ภาพที่ยังรอส่งขึ้นเว็บ (outbox PENDING) ห้ามลบแม้เก่าเกิน CLEANUP_KEEP_DAYS
    start_cleanup_thread(protected_paths=lambda: pending_image_paths(STATE_DB_PATH))
    # [CLOUD] เริ่มเฉพาะฟีเจอร์ที่เปิด (ปิดทั้งหมด = ไม่มี thread / HTTP เลย) — โหมด START–STOP ไม่ใช้ order listener
    features = config.cloud_features()
    logger.info(config.cloud_summary(features))
    cloud = None
    if any(features.values()):
        from api.cloud import CloudServices

        cloud = CloudServices(args.machine, features, roi_path=ROI_CONFIG_PATH, db_path=STATE_DB_PATH).start()
    pending = store.count_pending_cloud_events()
    if pending and not features["events"]:
        logger.warning(f"outbox has {pending} pending event(s) - ITEM_LANDED is off, upload paused (not deleted)")
    elif pending:
        logger.info(f"outbox has {pending} pending event(s) -> continue upload")

    # เปิดหน้าต่างแบบปรับขนาดได้ (WINDOW_NORMAL) แทน AUTOSIZE ที่ล็อกขนาดตายตัว
    if not HEADLESS:
        for name in ("Vending System", "Motion Mask"):
            cv2.namedWindow(name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(name, FRAME_W, FRAME_H)

    app = App(args.machine, source, roi_manager, store, controller, headless=HEADLESS, cloud=cloud)

    def _shutdown(signum, _frame):
        logger.info(f"signal {signum} received -> shutting down")
        app.running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    controller.start()
    try:
        app.run()
    finally:
        controller.stop()
        if cloud is not None:
            cloud.stop()
        source.release()
        store.close()
        if not HEADLESS:
            cv2.destroyAllWindows()
        logger.info("program stopped")


if __name__ == "__main__":
    main()
