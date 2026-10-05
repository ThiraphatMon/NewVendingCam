"""tests ขั้น D: ภาพ anomaly (D6), daily log, disk_cleanup, เงื่อนไขเก็บ clean_bg ใน ROI"""

import os
import time

import numpy as np

from conftest import FRAMES_TO_CONFIRM, FakeController, empty_frame, frame_with, run_frames, settle
from core import cycle as cyc
from core.background import BackgroundModel
from utils import daily_log
from utils.disk_cleanup import _cleanup_once

ITEM = frame_with((300, 250))
ITEM_B = frame_with((200, 180))


def anomalies(app):
    return [tuple(r) for r in app.store.conn.execute(
        "SELECT kind, cycle_id, evidence_path IS NOT NULL FROM anomalies ORDER BY id"
    ).fetchall()]


def kinds(app):
    return [k for k, _, _ in anomalies(app)]


def anomaly_files(env):
    d = os.path.join(env.evidence_dir, "anomaly")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def read_daily(env, date):
    path = os.path.join(env.daily_dir, f"{date}.log")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


# ── a) OUTSIDE_CYCLE ──────────────────────────────────────────────────────────

def test_outside_cycle_object_gives_anomaly_not_count(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert kinds(app) == ["OUTSIDE_CYCLE"] and anomalies(app)[0][1] is None
    assert len(anomaly_files(env)) == 1 and "OUTSIDE_CYCLE_nocycle" in anomaly_files(env)[0]
    assert app.store.count_today() == 0 and ctl.s0 == []
    assert read_daily(env, "2026-10-05") is None  # ไม่มีบรรทัด item drop
    # หลังถ่าย: rebaseline + ล้าง tracker → ของเดิมนิ่งต่อไม่ถูกถ่ายซ้ำ และเลิกเฝ้า
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM * 2)
    assert kinds(app) == ["OUTSIDE_CYCLE"]
    assert app.watch_since is None and not app.bg.frozen


def test_outside_cycle_rate_limited(make_app, env):
    app = make_app(FakeController())
    settle(app, env)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)        # ภาพที่ 1
    run_frames(app, env, empty_frame(), 60)              # หยิบออก → รอยว่างนิ่ง (ภายใน 30s → ไม่ถ่าย)
    run_frames(app, env, ITEM_B, FRAMES_TO_CONFIRM)      # ของใหม่ภายใน 30s → ไม่ถ่าย
    assert kinds(app) == ["OUTSIDE_CYCLE"]
    run_frames(app, env, empty_frame(), 60)
    env.clock.advance(31)
    settle(app, env)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)        # พ้น 30s แล้ว → ถ่ายได้อีก
    assert kinds(app) == ["OUTSIDE_CYCLE", "OUTSIDE_CYCLE"]
    assert app.store.count_today() == 0


def test_start_during_watch_uses_pre_motion_background(make_app, env):
    # ของกำลังตกก่อน START เล็กน้อย (ยังไม่ถึงเกณฑ์นอกรอบ) → START → ต้องยืนยันได้ในรอบ
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_frames(app, env, ITEM, 10)
    assert app.watch_since is not None and app.bg.frozen
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and len(ctl.s0) == 1
    assert kinds(app) == []


# ── b) EXTRA_AFTER_CONFIRM ────────────────────────────────────────────────────

def test_extra_after_confirm_anomaly_rate_limited(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    cid = app.cm.cycle_id
    for pos in ((200, 180), (420, 330)):  # ของใหม่ 2 ชิ้นภายใน 30s
        run_frames(app, env, frame_with((300, 250), pos), FRAMES_TO_CONFIRM)
    assert anomalies(app) == [("EXTRA_AFTER_CONFIRM", cid, 1)]
    assert "EXTRA_AFTER_CONFIRM" in anomaly_files(env)[0]
    assert app.store.count_today() == 1 and len(ctl.s0) == 1


# ── c) NO_CONFIRM_AT_CLOSE ────────────────────────────────────────────────────

def test_no_confirm_at_stop_and_timeout(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    a = app.cm.cycle_id
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 60)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    b = app.cm.cycle_id
    env.clock.advance(300)
    run_frames(app, env, empty_frame(), 1)
    assert anomalies(app) == [("NO_CONFIRM_AT_CLOSE", a, 1), ("NO_CONFIRM_AT_CLOSE", b, 1)]
    assert ctl.s0 == [] and app.store.count_today() == 0


def test_no_confirm_at_close_without_frame(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    run_frames(app, env, None, 2)
    ctl.push("STOP")
    run_frames(app, env, None, 1)
    assert anomalies(app) == [("NO_CONFIRM_AT_CLOSE", anomalies(app)[0][1], 0)]  # ไม่มีภาพ (ไม่มีเฟรม)


def test_confirmed_close_has_no_anomaly(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    ctl.push("STOP")
    run_frames(app, env, ITEM, 1)
    assert kinds(app) == []


# ── daily log ─────────────────────────────────────────────────────────────────

def one_cycle(app, env, ctl, item=ITEM):
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    run_frames(app, env, item, FRAMES_TO_CONFIRM)
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 60)  # หยิบออก + ถาดว่างนิ่ง


def test_daily_log_lines_restart_and_thai_midnight(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    for _ in range(3):
        one_cycle(app, env, ctl)
    lines = read_daily(env, "2026-10-05")
    assert [l.rsplit(" : ", 1)[1] for l in lines] == ["1", "2", "3"]
    assert lines[0].startswith("05/10/2026 13:45:") and " : item drop : " in lines[0]
    app.store.close()

    # restart วันเดิม → ต่อเป็น 4
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    one_cycle(app, env, ctl)
    assert read_daily(env, "2026-10-05")[-1].endswith(" : item drop : 4")

    # ข้ามเที่ยงคืนไทย (16:59:59 UTC → 17:00 UTC = 00:00 ไทย) → วันใหม่เริ่ม 1
    env.clock.t = 1_791_219_600.0 - 1.5  # 23:59:58.5 ไทย → ยืนยันได้หลังเที่ยงคืน
    settle(app, env)
    one_cycle(app, env, ctl)
    new_day = read_daily(env, "2026-10-06")
    assert new_day == [new_day[0]] and new_day[0].startswith("06/10/2026 00:00:")
    assert new_day[0].endswith(" : item drop : 1")
    assert len(read_daily(env, "2026-10-05")) == 4  # วันเก่าไม่ถูกแตะ
    assert app.view()["today_count"] == 1


def test_daily_log_rebuilt_from_db_at_startup(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    for _ in range(2):
        one_cycle(app, env, ctl)
    app.store.close()
    # crash: บรรทัดซ้ำ + บรรทัดขาด
    path = os.path.join(env.daily_dir, "2026-10-05.log")
    with open(path, "w", encoding="utf-8") as f:
        f.write("05/10/2026 13:45:13 : item drop : 1\n05/10/2026 13:45:13 : item drop : 1\n")
    app = make_app(FakeController())
    assert [l.rsplit(" : ", 1)[1] for l in read_daily(env, "2026-10-05")] == ["1", "2"]


def test_daily_log_not_created_without_confirmation(make_app, env):
    make_app(FakeController())
    assert not os.path.exists(env.daily_dir) or os.listdir(env.daily_dir) == []


def test_daily_log_format():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from utils.state_store import Confirmation

    c = Confirmation("c", datetime(2026, 10, 5, 13, 45, 12, tzinfo=ZoneInfo("Asia/Bangkok")), "2026-10-05", 1, "p")
    assert daily_log.format_line(c) == "05/10/2026 13:45:12 : item drop : 1\n"


# ── disk_cleanup ──────────────────────────────────────────────────────────────

def test_cleanup_by_age_per_folder(tmp_path, monkeypatch):
    import utils.disk_cleanup as dc

    monkeypatch.setattr(dc, "CLEANUP_KEEP_DAYS", 3)
    monkeypatch.setattr(dc, "ANOMALY_KEEP_DAYS", 1)
    root = tmp_path / "evidence_images"
    now = time.time()
    files = {
        "confirmed/old.jpg": 4, "confirmed/new.jpg": 2,
        "anomaly/old.jpg": 2, "anomaly/new.jpg": 0.5,
        "without_order/old.jpg": 4,
    }
    for rel, days in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        os.utime(p, (now - days * 86400, now - days * 86400))
    # ไฟล์นอก evidence_images ต้องไม่ถูกแตะแม้เก่ามาก
    db = tmp_path / "data" / "vending_state.sqlite3"
    log = tmp_path / "logs" / "item_drops" / "2026-01-01.log"
    for p in (db, log):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x")
        os.utime(p, (now - 400 * 86400, now - 400 * 86400))

    assert _cleanup_once(str(root), now) == 3
    left = sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in root.rglob("*.jpg"))
    assert left == ["anomaly/new.jpg", "confirmed/new.jpg"]
    assert db.exists() and log.exists()


# ── clean_bg: นิ่งเฉพาะใน ROI + ยอม noise เล็กน้อย ─────────────────────────────

def _roi_mask():
    m = np.zeros((480, 640), np.uint8)
    m[100:400, 100:500] = 255  # 120,000 px
    return m


def _noisy(rng, n_in_roi, outside_noise=True):
    f = np.full((480, 640), 60, np.float32)
    if outside_noise:  # แสงสะท้อน / noise นอก ROI จำนวนมาก
        f[0:80, :] += rng.integers(0, 2, (80, 640)) * 80
    ys = rng.integers(100, 400, n_in_roi)
    xs = rng.integers(100, 500, n_in_roi)
    f[ys, xs] += 80
    return f


def test_clean_bg_captured_when_roi_quiet_despite_noise_outside():
    rng = np.random.default_rng(0)
    bg = BackgroundModel()
    mask = _roi_mask()
    t = 1000.0
    for i in range(10):
        bg.update(_noisy(rng, 30), t, idle=True, roi_mask=mask)  # 30/120000 = 0.025% < 0.2%
        t += 1 / 30
    assert bg.clean_bg is not None


def test_clean_bg_not_captured_when_roi_noisy():
    rng = np.random.default_rng(0)
    bg = BackgroundModel()
    mask = _roi_mask()
    t = 1000.0
    for i in range(30):
        bg.update(_noisy(rng, 1000), t, idle=True, roi_mask=mask)  # 0.8% > 0.2%
        t += 1 / 30
    assert bg.clean_bg is None


def test_clean_bg_needs_consecutive_quiet_frames():
    rng = np.random.default_rng(0)
    bg = BackgroundModel()
    mask = _roi_mask()
    t = 1000.0
    for i in range(40):
        n = 2000 if i % 4 == 3 else 0  # นิ่งได้แค่ 3 เฟรมติดกัน (< CLEAN_BG_STABLE_FRAMES=5)
        bg.update(_noisy(rng, n, outside_noise=False), t, idle=True, roi_mask=mask)
        t += 1 / 30
    assert bg.clean_bg is None


def test_clean_bg_not_captured_outside_idle():
    rng = np.random.default_rng(0)
    bg = BackgroundModel()
    t = 1000.0
    for i in range(10):
        bg.update(_noisy(rng, 0), t, idle=False, roi_mask=_roi_mask())
        t += 1 / 30
    assert bg.clean_bg is None


def test_freeze_reports_source(caplog):
    bg = BackgroundModel()
    f = np.full((480, 640), 60, np.float32)
    bg.update(f, 0.0, idle=True)
    assert bg.freeze(0.0, reason="START") is False  # ไม่มี clean_bg → fallback
    assert "fallback" in caplog.text
