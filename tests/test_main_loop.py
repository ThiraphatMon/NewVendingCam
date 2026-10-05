"""tests ของ main.App — กล้องปลอม + เฟรมสังเคราะห์ + controller ปลอม + SQLite ใน tmp_path"""

import os
import sqlite3

from conftest import FRAMES_TO_CONFIRM, FakeController, empty_frame, frame_with, run_frames, settle
from core import cycle as cyc
from utils import image_saver

ITEM = frame_with((300, 250))


def confirmed_files(env):
    d = os.path.join(env.evidence_dir, "confirmed")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def outcome(app, cycle_id):
    return app.store.get_cycle(cycle_id)["outcome"]


def test_object_outside_cycle_is_not_counted(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM * 2)
    assert app.cm.state == cyc.WAIT_START
    assert app.store.count_today() == 0 and ctl.s0 == [] and confirmed_files(env) == []


def test_start_item_confirm_s0_then_stop(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    cid = app.cm.cycle_id
    assert app.cm.state == cyc.ACTIVE and app.bg.frozen

    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP
    assert ctl.s0 == [cid] and app.today_count == 1 and app.store.count_today() == 1
    assert len(confirmed_files(env)) == 1 and cid in confirmed_files(env)[0]
    assert app.store.get_response(cid)["state"] == "ENQUEUED"

    ctl.push("STOP")
    run_frames(app, env, ITEM, 1)
    assert app.cm.state == cyc.WAIT_START and outcome(app, cid) == "CONFIRMED"
    assert cid in ctl.revoked


def test_more_motion_after_confirm_does_not_count(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.store.count_today() == 1
    # ของชิ้นใหม่ / มือ / ขยับของ หลายรอบ
    for pos in ((200, 200), (420, 330), (250, 330)):
        run_frames(app, env, frame_with((300, 250), pos), FRAMES_TO_CONFIRM)
        run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM)  # หยิบออกหมด
    assert app.store.count_today() == 1 and len(ctl.s0) == 1
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP


def test_start_stop_without_object_is_unconfirmed(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 30)
    cid = app.cm.cycle_id
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 1)
    assert outcome(app, cid) == "UNCONFIRMED" and ctl.s0 == []
    assert not app.bg.frozen  # ปลด freeze + grace


def test_no_stop_for_300s_times_out(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 1)
    cid = app.cm.cycle_id
    env.clock.advance(299.0)
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.is_open()
    env.clock.advance(1.0)
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.state == cyc.WAIT_START and outcome(app, cid) == "TIMEOUT" and ctl.s0 == []


def test_duplicate_start_and_stop_in_wait_start(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("STOP")  # no-op
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.state == cyc.WAIT_START
    ctl.push("START")
    run_frames(app, env, empty_frame(), 1)
    cid = app.cm.cycle_id
    ctl.push("START")  # ซ้ำขณะ ACTIVE
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.cycle_id == cid and app.cm.state == cyc.ACTIVE
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and app.store.count_today() == 1


def test_fast_start_stop_start_does_not_reuse_previous_object(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)

    # รอบ 1 ยืนยันของ → STOP → START ทันที (เฟรมเดียวกัน) ของยังค้างในถาด
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    first = app.cm.cycle_id
    ctl.push("STOP")
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM * 2)
    second = app.cm.cycle_id
    assert second != first and app.cm.state == cyc.ACTIVE
    assert app.store.count_today() == 1 and ctl.s0 == [first]


def test_unconfirmed_leftover_not_confirmed_in_next_cycle(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    # รอบ 1: ของเพิ่งตก แต่ STOP มาก่อนนิ่งครบเกณฑ์
    ctl.push("START")
    run_frames(app, env, ITEM, 10)
    first = app.cm.cycle_id
    ctl.push("STOP")
    run_frames(app, env, ITEM, 15)  # 0.5s ระหว่างรอบ (ยังอยู่ใน grace)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM * 2)
    assert app.cm.cycle_id != first and app.cm.state == cyc.ACTIVE
    assert outcome(app, first) == "UNCONFIRMED"
    assert app.store.count_today() == 0 and ctl.s0 == []


def test_camera_none_while_active_stop_still_closes(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    cid = app.cm.cycle_id
    run_frames(app, env, None, 5)  # กล้องหลุด
    assert app.cm.state == cyc.BLOCKED_WAIT_STOP and app.camera_ok is False
    ctl.push("STOP")
    run_frames(app, env, None, 1)  # ยังไม่มีเฟรม แต่ STOP ต้องมีผล
    assert app.cm.state == cyc.WAIT_START and outcome(app, cid) == "UNCERTAIN"
    assert ctl.s0 == []
    # คำสั่งไม่เปิด/ปิดกล้อง
    assert env.source.open_count == 1 and env.source.release_count == 0


def test_camera_back_during_blocked_does_not_confirm(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    run_frames(app, env, None, 3)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM * 2)
    assert app.cm.state == cyc.BLOCKED_WAIT_STOP and ctl.s0 == []
    assert app.store.count_today() == 0


def test_start_before_any_frame_is_blocked(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    ctl.push("START")  # ยังไม่มีพื้นหลังเลย
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM * 2)
    assert app.cm.state == cyc.BLOCKED_WAIT_STOP and ctl.s0 == []


def test_image_save_failure_no_s0_no_count_then_retry(make_app, env, monkeypatch):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    monkeypatch.setattr(image_saver.cv2, "imwrite", lambda *a, **k: False)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.ACTIVE and ctl.s0 == [] and app.store.count_today() == 0
    assert confirmed_files(env) == []  # ไม่มี .tmp ค้าง

    monkeypatch.undo()
    run_frames(app, env, ITEM, int(1.5 * 30))  # ของยังนิ่ง → ลองใหม่สำเร็จ
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and len(ctl.s0) == 1
    assert app.store.count_today() == 1


def test_db_failure_no_s0_no_count(make_app, env, monkeypatch):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")

    def broken(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(app.store, "confirm", broken)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.ACTIVE and ctl.s0 == [] and app.today_count == 0
    assert confirmed_files(env) == []  # ภาพที่ไม่มี confirmation ถูกลบ
    monkeypatch.undo()
    assert app.store.count_today() == 0


def test_restart_with_open_cycle_enters_recovery_until_stop(make_app, env):
    store = env.open_store()
    store.open_cycle("hanging")
    store.close()

    ctl = FakeController()
    app = make_app(ctl)
    assert app.cm.state == cyc.RECOVERY_BLOCKED
    assert app.store.get_cycle("hanging")["outcome"] == "INTERRUPTED"
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.RECOVERY_BLOCKED and ctl.s0 == []
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 60)
    assert app.cm.state == cyc.WAIT_START
    ctl.push("START")
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.state == cyc.ACTIVE


def test_restart_same_day_continues_count(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    for _ in range(3):
        ctl.push("START")
        run_frames(app, env, empty_frame(), 3)
        run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
        ctl.push("STOP")
        run_frames(app, env, empty_frame(), 60)
    assert app.today_count == 3
    app.store.close()

    app2 = make_app(FakeController())
    assert app2.cm.state == cyc.WAIT_START and app2.today_count == 3
