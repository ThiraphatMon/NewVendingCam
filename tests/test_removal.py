"""tests S3: แยก "ของหายไป" (ลูกค้าหยิบออก) กับ "ของใส่เข้า" (สินค้าตก) — core/removal.py + main"""

import logging

import numpy as np

import main
from conftest import FRAMES_TO_CONFIRM, FakeController, empty_frame, frame_with, run_frames, settle
from core import cycle as cyc
from core import removal

BOX = (270, 220, 60, 60)                 # ตำแหน่งของ
PATCH = (262, 212, 76, 76)               # patch ที่เทียบ = กล่องของ + BOX_PAD (8px)
EDGE, MATCH = 0.6, 0.5


def _mat(seed=0):
    """ถาดมีลายอ่อน ๆ (noise std ~3) — ไม่เรียบสนิทเหมือนภาพสังเคราะห์ทั่วไป"""
    rng = np.random.default_rng(seed)
    return (np.full((480, 640), 90.0) + rng.normal(0, 3, (480, 640))).astype(np.float32)


def _with_item(img, value=200, checker=0):
    """วางของในกล่อง BOX: สีเดียว (value) หรือลายตาราง ±checker รอบ value (สีใกล้พื้น)"""
    out = img.copy()
    x, y, w, h = BOX
    patch = np.full((h, w), float(value), np.float32)
    if checker:
        yy, xx = np.mgrid[0:h, 0:w]
        patch += np.where(((yy // 6) + (xx // 6)) % 2 == 0, checker, -checker)
    out[y:y + h, x:x + w] = patch
    return out


def _classify(cur, base, history):
    return removal.classify(cur, base, history, PATCH, EDGE, MATCH, 25)


# ── classify (pure) ───────────────────────────────────────────────────────────

def test_addition_on_empty_tray():
    mat = _mat()
    v = _classify(_with_item(mat), mat, [mat])
    assert v.kind == removal.ADDITION and v.edge_ratio > 1


def test_removal_returns_to_earlier_scene():
    mat = _mat()
    v = _classify(_mat(1), _with_item(mat), [_with_item(mat), mat])  # ถาดว่าง (noise ใหม่) เหมือนฉากก่อนหน้า
    assert v.kind == removal.REMOVAL
    assert v.diff_history < v.diff_base * MATCH


def test_removal_without_earlier_scene_is_uncertain():
    mat = _mat()
    v = _classify(mat, _with_item(mat), [_with_item(mat)])  # เปิดเครื่องตอนมีของในถาดอยู่แล้ว
    assert v.kind == removal.UNCERTAIN
    assert _classify(mat, _with_item(mat), []).kind == removal.UNCERTAIN


def test_rebuy_at_same_spot_is_addition():
    # ว่าง → ของชิ้นเก่า → (หยิบออก) ว่าง = พื้นหลังรอบ → ของชิ้นใหม่ตกที่เดิม: ฉากก่อนหน้า "ตรง" แต่ขอบเพิ่ม → ใส่เข้า
    mat = _mat()
    old, new = _with_item(mat, 200), _with_item(_mat(2), 205)
    v = _classify(new, mat, [mat, old])
    assert v.diff_history < v.diff_base * MATCH  # สัญญาณฉากก่อนหน้าอย่างเดียวแยกไม่ได้
    assert v.kind == removal.ADDITION


def test_close_colour_item_addition_and_removal():
    # ของสีใกล้พื้น (ค่าเฉลี่ย 95 vs พื้น 90) แต่มีลาย → ใส่เข้า = ADDITION, หยิบออก = REMOVAL
    mat = _mat()
    item = _with_item(mat, 95, checker=20)
    assert _classify(item, mat, [mat]).kind == removal.ADDITION
    assert _classify(_mat(3), item, [item, mat]).kind == removal.REMOVAL


def test_box_of_clips_to_frame():
    assert removal.box_of({"centroid": (300, 250), "shape": (60, 60)}, (480, 640)) == PATCH
    assert removal.box_of({"centroid": (5, 5), "shape": (40, 40)}, (480, 640)) == (0, 0, 33, 33)
    assert removal.box_of({"centroid": (0, 0), "shape": (2, 2)}, (480, 640), pad=0) is None


# ── main: ในรอบ ACTIVE ───────────────────────────────────────────────────────

ITEM_POS = (300, 250)


def _remove_item_by_hand():
    """มือเข้ามาบังของ แล้วของหายไปพร้อมมือ (ไม่ใช่ env change)"""
    seq = [frame_with(ITEM_POS, (180 + 20 * i, 330), size=50) for i in range(4)]
    seq += [frame_with((290 + 10 * i, 250 + 8 * i), size=80) for i in range(5)]
    seq += [frame_with((360 + 25 * i, 320), size=50) for i in range(4)]
    return seq


def _run_seq(app, env, frames):
    for f in frames:
        run_frames(app, env, f, 1)


def _anomaly_kinds(app):
    return [k for (k,) in app.store.conn.execute("SELECT kind FROM anomalies ORDER BY id")]


def _anomaly_rows(app):
    return [tuple(r) for r in app.store.conn.execute(
        "SELECT kind, cycle_id, evidence_path IS NOT NULL FROM anomalies ORDER BY id")]


def test_possible_removal_recorded_even_when_over_image_quota(make_app, env):
    # OUTSIDE_CYCLE ใช้โควตาภาพไปแล้ว (< 30s) → POSSIBLE_REMOVAL ยังต้องมีแถวใน DB (ไม่มีภาพ)
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_frames(app, env, frame_with(ITEM_POS), FRAMES_TO_CONFIRM * 2)
    ctl.push("START")
    run_frames(app, env, frame_with(ITEM_POS), 5)
    _run_seq(app, env, _remove_item_by_hand())
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    assert ctl.s0 == []
    assert _anomaly_rows(app) == [("OUTSIDE_CYCLE", None, 1), ("POSSIBLE_REMOVAL", app.cm.cycle_id, 0)]


def _item_resting_before_start(app, env, ctl):
    """ของตกนอกรอบ (OUTSIDE_CYCLE) แล้ววางนิ่งอยู่ → START (clean_bg มีของ)"""
    settle(app, env)
    run_frames(app, env, frame_with(ITEM_POS), FRAMES_TO_CONFIRM * 2)
    env.clock.advance(31)  # พ้นโควตาภาพ anomaly
    run_frames(app, env, frame_with(ITEM_POS), 30)
    ctl.push("START")
    run_frames(app, env, frame_with(ITEM_POS), 5)


def test_item_removed_during_cycle_is_not_confirmed(make_app, env, caplog):
    # redis_e2e ข้อ 7 แบบไม่มี env change: ของวางนิ่งก่อน START แล้วถูกหยิบออกระหว่างรอบ
    ctl = FakeController()
    app = make_app(ctl)
    _item_resting_before_start(app, env, ctl)
    _run_seq(app, env, _remove_item_by_hand())
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    assert ctl.s0 == [] and app.store.count_today() == 0
    assert "POSSIBLE_REMOVAL" in _anomaly_kinds(app)
    assert "ดูเหมือนหยิบออก" in caplog.text
    assert _anomaly_rows(app)[-1] == ("POSSIBLE_REMOVAL", app.cm.cycle_id, 1)
    assert app.cm.state == cyc.ACTIVE
    # รอบยังรับของจริงได้ต่อ
    run_frames(app, env, frame_with((200, 180)), FRAMES_TO_CONFIRM)
    assert len(ctl.s0) == 1 and app.cm.state == cyc.CONFIRMED_WAIT_STOP


def test_removal_without_history_is_uncertain_no_s0_by_default(make_app, env, caplog):
    # เปิดเครื่องตอนมีของในถาดอยู่แล้ว → ไม่มีฉากถาดว่างให้เทียบ → ไม่แน่ใจ → default ไม่ส่ง S0
    ctl = FakeController()
    app = make_app(ctl)
    run_frames(app, env, frame_with(ITEM_POS), 30)
    ctl.push("START")
    run_frames(app, env, frame_with(ITEM_POS), 5)
    _run_seq(app, env, _remove_item_by_hand())
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    assert ctl.s0 == [] and "ไม่แน่ใจว่าหยิบออก" in caplog.text
    assert _anomaly_kinds(app) == ["POSSIBLE_REMOVAL"]


def test_uncertain_policy_can_send_s0(make_app, env, monkeypatch):
    monkeypatch.setattr(main, "REMOVAL_UNCERTAIN_SEND_S0", True)
    ctl = FakeController()
    app = make_app(ctl)
    run_frames(app, env, frame_with(ITEM_POS), 30)
    ctl.push("START")
    run_frames(app, env, frame_with(ITEM_POS), 5)
    _run_seq(app, env, _remove_item_by_hand())
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    assert len(ctl.s0) == 1


def test_removal_check_can_be_disabled(make_app, env, monkeypatch):
    monkeypatch.setattr(main, "REMOVAL_CHECK", False)
    ctl = FakeController()
    app = make_app(ctl)
    _item_resting_before_start(app, env, ctl)
    _run_seq(app, env, _remove_item_by_hand())
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    assert len(ctl.s0) == 1  # พฤติกรรมเดิม (known limitation)


def test_addition_verdict_logged_at_info_with_threshold(make_app, env, caplog):
    # เก็บข้อมูลตอนทดสอบสินค้าจริง: ทุกการตัดสินของ S3 ต้องมี log INFO 1 บรรทัด (ค่าขอบ + เกณฑ์ + ผล)
    caplog.set_level(logging.INFO, logger="vending")
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, frame_with(ITEM_POS), FRAMES_TO_CONFIRM)
    assert len(ctl.s0) == 1
    lines = [r for r in caplog.records if "S3=ADDITION" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO
    msg = lines[0].getMessage()
    assert "ขอบ ×" in msg and f"ขอบ < {main.REMOVAL_EDGE_RATIO:.2f}" in msg and "→ ยืนยัน" in msg


def test_rebuy_same_spot_after_pickup_outside_cycle_is_confirmed(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, frame_with(ITEM_POS), FRAMES_TO_CONFIRM)
    ctl.push("STOP")
    run_frames(app, env, frame_with(ITEM_POS), 60)
    _run_seq(app, env, _remove_item_by_hand())          # ลูกค้าหยิบนอกรอบ
    run_frames(app, env, empty_frame(), FRAMES_TO_CONFIRM * 2)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 5)
    _run_seq(app, env, [frame_with((300, 130 + 15 * i)) for i in range(8)])  # ของชิ้นใหม่ตกที่เดิม
    run_frames(app, env, frame_with(ITEM_POS), FRAMES_TO_CONFIRM)
    assert len(ctl.s0) == 2 and app.cm.state == cyc.CONFIRMED_WAIT_STOP
    assert "POSSIBLE_REMOVAL" not in _anomaly_kinds(app)


def test_scene_history_records_distinct_still_scenes(make_app, env):
    app = make_app(FakeController())
    settle(app, env)
    run_frames(app, env, frame_with(ITEM_POS), 30)
    run_frames(app, env, empty_frame(), 30)
    assert len(app.bg.scenes) == 3  # ว่าง → มีของ → ว่าง (ฉากเดิมซ้ำ = แทนที่ ไม่เพิ่ม)
