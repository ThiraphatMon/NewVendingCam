"""S19 ภาพ anomaly: ไม่มี rate limit (1 ภาพต่อเหตุการณ์), เพดานต่อวัน ANOMALY_MAX_PER_DAY, ENV_CHANGE"""

import logging
import os

import numpy as np

import main
from conftest import (
    BG_GRAY, FRAMES_TO_CONFIRM, OBJ_GRAY, ROI_RECT, FakeController, empty_frame, frame_with, run_frames, settle,
)
from core import cycle as cyc


def rows(app):
    return [tuple(r) for r in app.store.conn.execute(
        "SELECT kind, cycle_id, evidence_path IS NOT NULL FROM anomalies ORDER BY id")]


def files(env, kind=None):
    d = os.path.join(env.evidence_dir, "anomaly")
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    return [n for n in names if kind is None or kind in n]


def big_blob(dx=0, gray=OBJ_GRAY):
    """ก้อนใหญ่ ~55% ของ ROI (เกิน MAX_BLOB_ROI_RATIO 0.30) = env change (เช่น slat / แสง)"""
    f = empty_frame()
    x, y = ROI_RECT["x"] + 20 + dx, ROI_RECT["y"] + 20
    f[y:y + 220, x:x + 300] = gray
    return f


def moving_blob(n, gray=OBJ_GRAY):
    """env change ที่ฉากเปลี่ยนต่อเนื่อง n เฟรม (ก้อนใหญ่ขยับทุกเฟรม — ROI ไม่นิ่งเลย)"""
    return [big_blob(dx=(i % 2) * 40, gray=gray) for i in range(n)]


def run_seq(app, env, frames):
    for f in frames:
        run_frames(app, env, f, 1)


# ── ไม่มี rate limit: OUTSIDE_CYCLE / EXTRA_AFTER_CONFIRM / NO_CONFIRM_AT_CLOSE ─────────

def test_every_event_gets_one_image_without_rate_limit(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    # 3 รอบติดกันภายใน 30s ที่ไม่มีของ → NO_CONFIRM_AT_CLOSE ทุกรอบ (ภาพครบ)
    for _ in range(3):
        ctl.push("START")
        run_frames(app, env, empty_frame(), 10)
        ctl.push("STOP")
        run_frames(app, env, empty_frame(), 10)
    assert [r[0] for r in rows(app)] == ["NO_CONFIRM_AT_CLOSE"] * 3 and all(r[2] for r in rows(app))
    # ของนิ่งนอกรอบหลายชิ้นติดกัน → ภาพทุกชิ้น ชิ้นละ 1 ภาพ (ไม่ใช่ทุกเฟรม)
    for pos in ((200, 180), (420, 330)):
        run_frames(app, env, frame_with(pos), FRAMES_TO_CONFIRM * 3)
        run_frames(app, env, empty_frame(), 60)  # หยิบออก (รอยว่าง = อีกเหตุการณ์) + พ้น grace หลัง rebaseline
    outside = [r for r in rows(app) if r[0] == "OUTSIDE_CYCLE"]
    assert len(outside) >= 2 and all(r[2] for r in outside)  # ทุกเหตุการณ์มีภาพ (เดิมภายใน 30s ได้ภาพเดียว)
    assert len(files(env, "OUTSIDE_CYCLE")) == len(outside)
    n = len(rows(app))
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 3)  # ถาดว่างนิ่ง → ไม่มีภาพเพิ่ม
    assert len(rows(app)) == n


# ── เพดานต่อวัน ─────────────────────────────────────────────────────────────────

def test_daily_cap_stops_images_but_keeps_db_rows_and_warns_once(make_app, env, monkeypatch, caplog):
    monkeypatch.setattr(main, "ANOMALY_MAX_PER_DAY", 2)
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            ctl.push("START")
            run_frames(app, env, empty_frame(), 5)
            ctl.push("STOP")
            run_frames(app, env, empty_frame(), 5)
    assert [r[2] for r in rows(app)] == [1, 1, 0, 0]  # 4 แถวใน DB ภาพแค่ 2
    assert len(files(env)) == 2
    assert caplog.text.count("anomaly image limit reached") == 1  # เตือน 1 ครั้งต่อวัน

    # restart วันเดิม: นับต่อจาก DB (ยังเต็ม)
    app2 = make_app(ctl, store=app.store)
    ctl.push("START")
    run_frames(app2, env, empty_frame(), 5)
    ctl.push("STOP")
    run_frames(app2, env, empty_frame(), 5)
    assert rows(app2)[-1][2] == 0

    # ข้ามวัน (ตามเวลาไทย) → เก็บภาพได้อีก
    env.clock.advance(24 * 3600)
    ctl.push("START")
    run_frames(app2, env, empty_frame(), 5)
    ctl.push("STOP")
    run_frames(app2, env, empty_frame(), 5)
    assert rows(app2)[-1][2] == 1


# ── ENV_CHANGE ─────────────────────────────────────────────────────────────────

def test_env_change_lasting_many_frames_is_one_image(make_app, env):
    app = make_app(FakeController())
    settle(app, env)
    run_seq(app, env, moving_blob(40))  # env change ค้าง 40 เฟรม (ฉากไม่เคยนิ่ง)
    assert [r for r in rows(app) if r[0] == "ENV_CHANGE"] == [("ENV_CHANGE", None, 1)]
    assert len(files(env, "ENV_CHANGE")) == 1


def test_env_change_still_then_change_again_is_two_images(make_app, env):
    app = make_app(FakeController())
    settle(app, env)
    run_seq(app, env, moving_blob(10))              # เปลี่ยน → ภาพ 1
    run_frames(app, env, big_blob(), 20)            # ก้อนค้างนิ่ง แต่ยังเป็น env change (ยังไม่สงบตามเกณฑ์ clean_bg) → ไม่ถ่ายซ้ำ
    assert len(files(env, "ENV_CHANGE")) == 1
    run_frames(app, env, empty_frame(), 20)         # ถาดกลับมานิ่ง ครบ CLEAN_BG_STABLE_FRAMES → พร้อมถ่ายใหม่
    assert len(files(env, "ENV_CHANGE")) == 1
    run_seq(app, env, moving_blob(10, gray=0))      # เปลี่ยนอีก (ก้อนมืด เช่นเงา) → ภาพ 2
    assert len(files(env, "ENV_CHANGE")) == 2
    assert [r[0] for r in rows(app)].count("ENV_CHANGE") == 2


def test_env_change_during_cycle_is_linked_and_does_not_change_detection(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    cid = app.cm.cycle_id
    run_seq(app, env, moving_blob(8))       # slat / มือใหญ่ระหว่างรอบ
    run_frames(app, env, empty_frame(), 20)
    run_frames(app, env, frame_with((300, 250)), FRAMES_TO_CONFIRM)  # ของตกจริงยังยืนยันได้
    assert ("ENV_CHANGE", cid, 1) in rows(app)
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and len(ctl.s0) == 1
