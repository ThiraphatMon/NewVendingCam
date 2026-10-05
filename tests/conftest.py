"""fixtures ร่วม: นาฬิกาปลอม, กล้องปลอม, controller ปลอม, เฟรมสังเคราะห์ และตัวสร้าง App"""

import json
import types

import numpy as np
import pytest

import core.tracker
from api.redis_controller import Command, SendResult
from core.frame_source import NO_NEW_FRAME
from core.roi import ROIManager
from utils.state_store import StateStore

FPS = 30.0
BG_GRAY = 60
OBJ_GRAY = 220
ROI_RECT = {"x": 100, "y": 100, "w": 400, "h": 300}


class FakeClock:
    """ใช้ทั้ง wall clock และ monotonic (เริ่มที่ 06:45:12 UTC = 13:45:12 ไทย 05/10/2026)"""

    def __init__(self, t=1_791_182_712.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


class FakeSource:
    """กล้องปลอม: คืนเฟรมที่ตั้งไว้ (None = กล้องหลุด/ค้าง, NO_NEW_FRAME = ยังไม่มีเฟรมใหม่) และนับการ open/release"""

    def __init__(self):
        self.frame = None
        self.open_count = 1  # เปิดครั้งเดียวตอนสร้าง (เหมือน FrameSource)
        self.release_count = 0
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.frame is None or self.frame is NO_NEW_FRAME:
            return self.frame
        return self.frame.copy()

    def release(self):
        self.release_count += 1


class FakeController:
    """แทน RedisController: test ใส่คำสั่งเอง และ S0 สำเร็จทันที (นับไว้ใน s0)"""

    enabled = True

    def __init__(self):
        self.inbox = []
        self.seq = 0
        self.s0 = []
        self.revoked = []

    def push(self, text):
        self.seq += 1
        self.inbox.append(Command(self.seq, text, 0.0))

    inject = push

    def drain(self):
        items, self.inbox = self.inbox, []
        return items

    def request_s0(self, cycle_id, after_seq):
        self.s0.append(cycle_id)
        self.inbox.append(SendResult(cycle_id, "ENQUEUED"))

    def revoke(self, cycle_id):
        self.revoked.append(cycle_id)


def empty_frame():
    return np.full((480, 640, 3), BG_GRAY, np.uint8)


def frame_with(*centers, size=60):
    """เฟรมที่มีวัตถุสี่เหลี่ยมสว่างที่ตำแหน่ง centers [(cx, cy), ...]"""
    f = empty_frame()
    half = size // 2
    for cx, cy in centers:
        f[cy - half:cy + half, cx - half:cx + half] = OBJ_GRAY
    return f


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    # tracker ใช้ time.time() ภายใน → ชี้ไปนาฬิกาเดียวกัน (ไม่แก้ logic ของ tracker)
    monkeypatch.setattr(core.tracker, "time", types.SimpleNamespace(time=c))
    return c


@pytest.fixture
def env(tmp_path, clock):
    """สภาพแวดล้อมของ App ใน tmp_path ทั้งหมด"""
    roi_path = tmp_path / "roi_config.json"
    roi_path.write_text(json.dumps({
        "frame": {"width": 640, "height": 480}, "roi_type": "rect", "rect": ROI_RECT,
    }))
    ns = types.SimpleNamespace(
        tmp=tmp_path,
        clock=clock,
        db_path=str(tmp_path / "data" / "vending_state.sqlite3"),
        evidence_dir=str(tmp_path / "evidence_images"),
        daily_dir=str(tmp_path / "logs" / "item_drops"),
        roi=ROIManager(640, 480, config_path=str(roi_path)),
        source=FakeSource(),
    )
    ns.open_store = lambda: StateStore(ns.db_path, "VENDING_01", "Asia/Bangkok", clock=clock)
    return ns


@pytest.fixture
def make_app(env):
    from main import App

    def _make(controller=None, store=None):
        app = App(
            "VENDING_01", env.source, env.roi, store or env.open_store(),
            controller or FakeController(),
            headless=True, evidence_dir=env.evidence_dir, daily_log_dir=env.daily_dir,
            clock=env.clock, mono=env.clock,
        )
        return app

    return _make


def run_frames(app, env, frame, n):
    """ป้อนเฟรมเดิม n ครั้ง เดินนาฬิกาตาม FPS"""
    env.source.frame = frame
    for _ in range(n):
        env.clock.advance(1 / FPS)
        app.step()


def settle(app, env, sec=1.0):
    """ถาดว่างนิ่ง ๆ ให้ bg + clean_bg พร้อม"""
    run_frames(app, env, empty_frame(), int(sec * FPS))


# วัตถุนิ่งจนผ่านเกณฑ์ยืนยัน: 4 เฟรมจน SHAPE_CONFIRMED + 1.5s (CAPTURE_HOLD_SEC) + เผื่อ
FRAMES_TO_CONFIRM = int(2.0 * FPS)
