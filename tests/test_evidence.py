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


def falling(n, x=300, y0=130, step=8):
    """ของกำลังตก: ตำแหน่งเปลี่ยนทุกเฟรม (ROI ไม่นิ่งเฟรมต่อเฟรม)"""
    return [frame_with((x, y0 + step * i)) for i in range(n)]


def run_seq(app, env, frames):
    for f in frames:
        run_frames(app, env, f, 1)


def test_start_during_watch_while_item_falling_is_confirmed(make_app, env):
    # ของกำลังตกตอน START (ROI ยังไม่นิ่ง → ไม่มี clean_bg ที่ valid → เฟรมปัจจุบัน) → ตกถึงพื้น → ยืนยันได้
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    seq = falling(15)
    run_seq(app, env, seq[:8])
    assert app.watch_since is not None and app.bg.frozen
    ctl.push("START")
    run_seq(app, env, seq[8:])
    run_frames(app, env, seq[-1], FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and len(ctl.s0) == 1
    assert kinds(app) == []


def test_start_during_watch_uses_latest_still_scene_not_watch_freeze(make_app, env):
    # [ข้อ 4] watch freeze ไว้ที่ถาดว่าง แต่ของนิ่งครบ 5 เฟรมแล้ว → START ใช้ clean_bg ล่าสุด (มีของ)
    # → ของที่นิ่งอยู่ก่อน START ไม่ถูกนับ (เหมือนตัวเก่าที่ใช้เฟรมแรกหลัง START) — tradeoff ที่ยอมรับ
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_frames(app, env, ITEM, 10)
    assert app.watch_since is not None
    ctl.push("START")
    run_frames(app, env, ITEM, 1)
    assert app.watch_since is None
    assert np.array_equal(app.bg.bg, ITEM[:, :, 0].astype(np.float32))
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.ACTIVE and ctl.s0 == []


def test_pickup_outside_cycle_then_start_has_no_false_s0(make_app, env):
    # [redis_e2e ข้อ 8] ซื้อต่อกัน: ยืนยัน → STOP → ลูกค้าหยิบของนอกรอบ (มือ + env change) → ถาดว่างนิ่ง → START
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    ctl.push("STOP")
    run_frames(app, env, ITEM, 60)
    bright = empty_frame()
    bright[100:400, 100:500] = 200          # slat เปิด → env change ทั้ง ROI
    run_frames(app, env, bright, 3)
    run_seq(app, env, [frame_with((250 + 20 * i, 300), size=80) for i in range(6)])  # มือ
    run_frames(app, env, empty_frame(), 8)  # ของหายแล้ว ถาดนิ่ง
    assert app.bg.clean_bg_valid
    ctl.push("START")
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    assert len(ctl.s0) == 1 and app.store.count_today() == 1
    assert app.cm.state == cyc.ACTIVE


def test_env_change_in_wait_start_invalidates_clean_bg(make_app, env):
    # [ข้อ 2] env change (bg ต่างจากเฟรมเกินเกณฑ์) แม้เฟรมต่อเฟรมนิ่ง → clean_bg ห้ามใช้ ต้องนิ่งใหม่ครบ 5 เฟรม
    app = make_app(FakeController())
    settle(app, env)
    assert app.bg.clean_bg_valid
    app.bg.bg[:] = 200
    run_frames(app, env, empty_frame(), 1)
    assert not app.bg.clean_bg_valid and app.bg.quiet_frames == 0


def test_watch_not_ended_by_single_empty_tracker_frame(make_app, env):
    # [ข้อ 4] เฟรม env change ทำให้ tracker ว่าง แต่ ROI ยังไม่นิ่ง → ยังเฝ้าอยู่ จบเมื่อนิ่งครบ 5 เฟรม
    app = make_app(FakeController())
    settle(app, env)
    run_seq(app, env, falling(4))
    assert app.watch_since is not None
    bright = empty_frame()
    bright[100:400, 100:500] = 200
    run_frames(app, env, bright, 1)
    run_frames(app, env, empty_frame(), 1)
    assert app.watch_since is not None
    run_frames(app, env, empty_frame(), 10)
    assert app.watch_since is None and not app.bg.frozen


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


def _feed(bg, frames, t, idle=True, mask=None):
    for f in frames:
        bg.update(f, t, idle=idle, roi_mask=_roi_mask() if mask is None else mask)
        t += 1 / 30
    return t


def _gray(v=60):
    return np.full((480, 640), v, np.float32)


def _with_item(v=60):
    f = _gray(v)
    f[200:260, 250:310] = 220
    return f


def test_clean_bg_is_current_frame_when_still_frame_to_frame():
    # [ข้อ 1] bg (เรียนรู้ช้า) ยังต่างจากเฟรม แต่เฟรมต่อเฟรมนิ่ง → clean_bg = เฟรมปัจจุบัน (มีของ)
    bg = BackgroundModel()
    t = _feed(bg, [_gray()] * 10, 1000.0)
    t = _feed(bg, [_with_item()] * 6, t + 1)
    assert bg.clean_bg_valid and np.array_equal(bg.clean_bg, _with_item())
    assert not np.array_equal(bg.bg, _with_item())


def test_clean_bg_captured_while_frozen_and_in_grace():
    bg = BackgroundModel()
    t = _feed(bg, [_gray()], 1000.0)
    bg.freeze(t)
    t = _feed(bg, [_with_item()] * 7, t)
    assert bg.frozen and bg.clean_bg_valid and np.array_equal(bg.clean_bg, _with_item())
    bg.unfreeze(t)
    t = _feed(bg, [_gray()] * 7, t)
    assert bg.in_grace(t) and bg.clean_bg_valid and np.array_equal(bg.clean_bg, _gray())


def test_camera_gap_frames_not_counted_as_still():
    bg = BackgroundModel()
    t = _feed(bg, [_gray()] * 4, 1000.0)  # นิ่ง 3 เฟรม
    bg.clear()                            # กล้องหลุด
    t = _feed(bg, [_gray()] * 5, t + 1)   # เฟรมแรกตั้ง bg + นิ่ง 4 เฟรม → ยังไม่ครบ
    assert bg.clean_bg is None
    _feed(bg, [_gray()], t)
    assert bg.clean_bg_valid


def test_roi_change_invalidates_then_recaptures_without_interval_wait():
    # [ข้อ 2] เปลี่ยนเกินเกณฑ์ → ไม่ valid ทันที (ภาพเดิมยังเก็บไว้ให้ watch) → นิ่งครบ 5 เฟรม → เก็บใหม่ทันที
    bg = BackgroundModel()
    t = _feed(bg, [_gray()] * 8, 1000.0)
    assert bg.clean_bg_valid
    t = _feed(bg, [_with_item()], t)
    assert not bg.clean_bg_valid and np.array_equal(bg.clean_bg, _gray())
    t = _feed(bg, [_with_item()] * 5, t)  # < CLEAN_BG_INTERVAL หลังเก็บครั้งก่อน
    assert bg.clean_bg_valid and np.array_equal(bg.clean_bg, _with_item())


def test_start_cycle_uses_valid_clean_bg(caplog):
    bg = BackgroundModel()
    t = _feed(bg, [_gray()] * 8, 1000.0)
    assert bg.start_cycle(_with_item(), t, reason="START x") is True
    assert np.array_equal(bg.bg, _gray()) and bg.frozen
    assert "ใช้ clean_bg (อายุ" in caplog.text


def test_start_cycle_without_valid_clean_bg_uses_current_frame(caplog):
    # [ข้อ 3] ฉากยังไม่นิ่ง → เฟรมปัจจุบันเป็นพื้นหลังของรอบ + log baseline ไม่แน่นอน
    bg = BackgroundModel()
    t = _feed(bg, [_gray()] * 8, 1000.0)
    t = _feed(bg, [_with_item()], t)
    assert bg.start_cycle(_with_item(), t, reason="START x") is False
    assert np.array_equal(bg.bg, _with_item()) and np.array_equal(bg.snapshot, _with_item())
    assert "baseline ไม่แน่นอน" in caplog.text


def test_freeze_reports_source(caplog):
    bg = BackgroundModel()
    f = np.full((480, 640), 60, np.float32)
    bg.update(f, 0.0, idle=True)
    assert bg.freeze(0.0, reason="START") is False  # ไม่มี clean_bg → fallback
    assert "fallback" in caplog.text


# ── S1: ตั้งพื้นหลังของรอบใหม่หลัง env change สงบ ─────────────────────────────

def _slat(i):
    """slat กำลังเปิด/ปิด: ROI สว่างทั้งแผ่น และเปลี่ยนทุกเฟรม (ไม่นิ่ง)"""
    f = empty_frame()
    f[100:400, 100:500] = 150 + 40 * (i % 2)
    return f


def test_start_while_slat_open_rebaselines_after_settle_then_confirms(make_app, env, caplog):
    # START ตอน slat ยังเปิด (เฟรมปัจจุบันเป็นพื้นหลัง) → slat ปิด ถาดนิ่ง → env change ค้าง
    # → นิ่งครบ 5 เฟรม → ตั้งพื้นหลังใหม่ → ของตกหลังจากนั้นยังยืนยันได้
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_seq(app, env, [_slat(i) for i in range(6)])
    ctl.push("START")
    run_seq(app, env, [_slat(i) for i in range(6, 9)])
    assert "baseline ไม่แน่นอน" in caplog.text
    run_frames(app, env, empty_frame(), 10)
    assert "env change สงบแล้ว" in caplog.text
    assert np.array_equal(app.bg.bg, empty_frame()[:, :, 0].astype(np.float32))
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM)
    assert ctl.s0 == []                     # ถาดว่างหลัง slat ปิด ไม่ใช่ของ
    run_seq(app, env, falling(6))
    run_frames(app, env, falling(6)[-1], FRAMES_TO_CONFIRM)
    assert len(ctl.s0) == 1 and app.cm.state == cyc.CONFIRMED_WAIT_STOP


def test_no_rebaseline_while_env_change_still_moving(make_app, env, caplog):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 2)
    base = app.bg.bg.copy()
    run_seq(app, env, [_slat(i) for i in range(30)])
    assert "env change สงบแล้ว" not in caplog.text
    assert np.array_equal(app.bg.bg, base)


def test_no_rebaseline_after_confirm(make_app, env, caplog):
    # ยืนยันแล้ว (CONFIRMED_WAIT_STOP) ไม่ตั้งพื้นหลังรอบใหม่จาก env change
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    bright = empty_frame()
    bright[100:400, 100:500] = 200
    run_frames(app, env, bright, 20)
    assert "env change สงบแล้ว" not in caplog.text
