"""S12: ROI ใหม่ (จากเว็บ/แก้ไฟล์) ระหว่างรอบ → รอใช้ตอนกลับ WAIT_START แล้วล้างสิ่งที่ผูกกับ ROI เดิม"""

import json
import os

import pytest

import core.roi
from core import cycle as cyc
from conftest import FRAMES_TO_CONFIRM, ROI_RECT, FakeController, empty_frame, frame_with, run_frames, settle

ITEM = frame_with((300, 250))
NEW_RECT = {"x": 120, "y": 120, "w": 380, "h": 260}


@pytest.fixture(autouse=True)
def check_every_frame(monkeypatch):
    monkeypatch.setattr(core.roi, "ROI_CHECK_INTERVAL", 0.0)


def write_roi(env, rect):
    """เขียนไฟล์ ROI ใหม่ (เหมือน fetch_remote_roi) ให้ mtime ต่างจากที่โหลดไว้แน่นอน"""
    path = env.roi.config_path
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"frame": {"width": 640, "height": 480}, "roi_type": "rect", "rect": rect}, f)
    t = env.roi.last_mtime + 10
    os.utime(path, (t, t))


def test_roi_change_during_active_waits_until_wait_start(make_app, env, caplog):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 5)
    write_roi(env, NEW_RECT)
    run_frames(app, env, empty_frame(), 10)
    assert app.cm.state == cyc.ACTIVE and env.roi.rect == ROI_RECT
    assert caplog.text.count("new ROI found during cycle") == 1  # log ครั้งเดียว ไม่ทุกเฟรม
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.state == cyc.WAIT_START and env.roi.rect == NEW_RECT
    assert "new ROI applied (rect)" in caplog.text


def test_roi_change_in_confirmed_wait_stop_waits_and_confirm_unaffected(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, 10)
    write_roi(env, NEW_RECT)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and len(ctl.s0) == 1  # ยืนยันด้วย ROI เดิม
    run_frames(app, env, ITEM, 10)
    assert env.roi.rect == ROI_RECT
    ctl.push("STOP")
    run_frames(app, env, ITEM, 1)
    assert env.roi.rect == NEW_RECT


def test_roi_applied_in_wait_start_resets_roi_history(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env, sec=2.0)
    assert app.bg.clean_bg_valid and len(app.bg.scenes) >= 1
    run_frames(app, env, ITEM, 10)  # ของนอกรอบ → เฝ้าดู + tracker มีวัตถุ
    assert app.watch_since is not None and app.tracker.objects
    old_ids = set(app.tracker.objects)
    write_roi(env, NEW_RECT)
    run_frames(app, env, ITEM, 1)
    assert env.roi.rect == NEW_RECT
    assert app.watch_since is None
    assert not app.bg.clean_bg_valid and app.bg.clean_bg is None and len(app.bg.scenes) == 0
    assert not (set(app.tracker.objects) & old_ids)  # วัตถุเดิมถูกล้าง (เห็นใหม่ได้ id ใหม่)


def test_broken_roi_file_keeps_old_roi_without_reset(make_app, env):
    app = make_app(FakeController())
    settle(app, env, sec=2.0)
    path = env.roi.config_path
    with open(path, "w", encoding="utf-8") as f:
        f.write("{broken")
    t = env.roi.last_mtime + 10
    os.utime(path, (t, t))
    run_frames(app, env, empty_frame(), 1)
    assert env.roi.rect == ROI_RECT and app.bg.clean_bg_valid  # ไม่ล้างเพราะไม่ได้ใช้ ROI ใหม่
