"""[S22] ตัวกรองแสง/เงาแบบ texture (local NCC) ใน core/detect.py

แสง/เงาเปลี่ยนแค่ความสว่าง ลวดลายพื้นเดิม → ตัดออกจาก mask | ของที่ตกทับลวดลาย (มีลาย/ขาว/ดำ) → ยังอยู่
SHADOW_FILTER=off → mask เท่าเดิมทุกพิกเซล
"""

import cv2
import numpy as np

import main
from core.detect import build_fgmask, light_only_mask

MOT = 25
BOX = (100, 100, 400, 300)  # (x, y, w, h) ของ ROI


def textured_bg(seed=1):
    """พื้นมีลาย (เหมือนพรม): noise เบลอเล็กน้อย ค่าเฉลี่ย ~110"""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 25, (480, 640)).astype(np.float32)
    return np.clip(110 + cv2.GaussianBlur(noise, (3, 3), 0) * 1.5, 0, 255).astype(np.float32)


def mask_of(bg, cur, shadow=True, box=BOX):
    diff = cv2.absdiff(cur, bg)
    sh = None
    if shadow:
        x, y, w, h = box
        sh = (bg[y:y + h, x:x + w], cur[y:y + h, x:x + w], box, 7, 0.6, 4.0)
    return build_fgmask(diff, MOT, 5, 5, 2, shadow=sh)


def roi(m):
    x, y, w, h = BOX
    return m[y:y + h, x:x + w]


# ── แค่แสง/เงา → mask ว่าง ───────────────────────────────────────────────────

def test_whole_frame_brighter_on_textured_floor_is_removed():
    bg = textured_bg()
    cur = np.clip(bg * 1.3 + 10, 0, 255)  # กล้องปรับแสง / สว่างขึ้นทั้งกรอบ
    assert cv2.countNonZero(roi(mask_of(bg, cur, shadow=False))) > 10000  # ไม่กรอง = เกิด motion เต็ม ROI
    assert cv2.countNonZero(roi(mask_of(bg, cur))) == 0


def test_shadow_patch_on_textured_floor_is_removed():
    bg = textured_bg()
    cur = bg.copy()
    cur[150:350, 150:400] *= 0.5  # เงาคนทับครึ่ง ROI
    assert cv2.countNonZero(roi(mask_of(bg, cur, shadow=False))) > 10000
    # ขอบเงาตรงเส้นแบ่งยังอาจหลงได้บ้างเล็กน้อย แต่ไม่ถึงก้อนของ (MIN_AREA 150)
    assert cv2.countNonZero(roi(mask_of(bg, cur))) < 150


def test_flat_area_getting_brighter_is_removed():
    bg = np.full((480, 640), 80, np.float32)
    cur = np.full((480, 640), 140, np.float32)  # พื้นเรียบไม่มีลายทั้งคู่ สว่างขึ้น
    assert cv2.countNonZero(roi(mask_of(bg, cur))) == 0


# ── ของจริงทับลวดลาย → ยังอยู่ ───────────────────────────────────────────────

def _object_kept(patch_value):
    bg = textured_bg()
    cur = bg.copy()
    y0, x0, s = 220, 260, 60
    if patch_value is None:  # ของมีลายของตัวเอง (ลายไม่เกี่ยวกับพื้น)
        cur[y0:y0 + s, x0:x0 + s] = textured_bg(seed=7)[y0:y0 + s, x0:x0 + s] + 60
    else:
        cur[y0:y0 + s, x0:x0 + s] = patch_value
    m = mask_of(bg, cur)
    inside = m[y0:y0 + s, x0:x0 + s]
    return cv2.countNonZero(inside) / (s * s)


def test_textured_object_on_textured_floor_kept():
    assert _object_kept(None) > 0.9


def test_white_flat_object_on_textured_floor_kept():
    assert _object_kept(255) > 0.9


def test_black_flat_object_on_textured_floor_kept():
    assert _object_kept(0) > 0.9


def test_object_kept_even_under_shadow():
    bg = textured_bg()
    cur = bg * 0.6  # เงาทั้งกรอบ
    cur[220:280, 260:320] = 250  # ของสีขาวตกระหว่างมีเงา
    m = mask_of(bg, cur)
    assert cv2.countNonZero(m[220:280, 260:320]) / 3600 > 0.9
    assert cv2.countNonZero(roi(m)) - cv2.countNonZero(m[205:295, 245:335]) == 0  # นอกบริเวณของ = ว่าง


# ── off = mask เท่าเดิมทุกพิกเซล ──────────────────────────────────────────────

def _legacy_fgmask(diff):
    """pipeline ก่อน S22 (threshold → OPEN → DILATE) เขียนซ้ำไว้เทียบ"""
    m = np.where(diff > MOT, np.uint8(255), np.uint8(0))
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k)
    return cv2.morphologyEx(m, cv2.MORPH_DILATE, k, iterations=2)


def test_off_is_identical_to_legacy_pipeline():
    bg = textured_bg()
    cur = bg * 0.6
    cur[220:280, 260:320] = 250
    diff = cv2.absdiff(cur, bg)
    assert np.array_equal(build_fgmask(diff, MOT, 5, 5, 2, shadow=None), _legacy_fgmask(diff))
    assert np.array_equal(mask_of(bg, cur, shadow=False), _legacy_fgmask(diff))


def test_detect_objects_off_matches_legacy(env):
    bg = textured_bg()
    cur = bg * 0.6
    diff = cv2.absdiff(cur, bg)
    roi_mask = env.roi.build_mask(diff.shape)
    m_off, _, _ = main.detect_objects(diff, env.roi, roi_mask)  # ไม่ส่ง shadow_ref = off
    assert np.array_equal(m_off, cv2.bitwise_and(_legacy_fgmask(diff), roi_mask))
    box = cv2.boundingRect(roi_mask)
    x, y, w, h = box
    m_on, _, env_change = main.detect_objects(diff, env.roi, roi_mask, bg[y:y + h, x:x + w].copy(), cur, box)
    assert cv2.countNonZero(m_on) == 0 and not env_change


def test_motion_outside_box_does_not_leak_into_roi_edge():
    # เงานอกกล่อง ROI (ไม่ได้กรอง) ต้องไม่ถูก DILATE ล้นเข้าขอบ ROI
    bg = textured_bg()
    cur = np.clip(bg * 1.3 + 10, 0, 255)
    assert cv2.countNonZero(mask_of(bg, cur)) == 0
    cur[50:470, 520:600] = 250  # ของจริงนอก ROI ก็ไม่เข้า mask (ROI ตัดทิ้งอยู่แล้ว)
    assert cv2.countNonZero(mask_of(bg, cur)) == 0


def test_light_only_mask_shape_and_type():
    bg = textured_bg()[:50, :70]
    lo = light_only_mask(bg, bg * 0.7)
    assert lo.shape == (50, 70) and lo.dtype == bool and lo.all()


def test_startup_summary(monkeypatch):
    monkeypatch.setattr(main, "SHADOW_FILTER", "texture")
    monkeypatch.setattr(main, "SHADOW_MIN_AREA", 400)
    monkeypatch.setattr(main, "MIN_AREA", 150)
    assert main.shadow_summary() == (
        "Shadow filter: texture (win=7, ncc>0.6, flat_var<4, min blob 400px instead of MIN_AREA 150px)"
    )
    monkeypatch.setattr(main, "SHADOW_FILTER", "off")
    assert main.shadow_summary() == "Shadow filter: off"


# ── ภาพอ้างอิงลวดลาย (NCC reference) ───────────────────────────────────────────

def test_ncc_reference_order():
    from core.background import BackgroundModel

    b = BackgroundModel()
    assert b.ncc_reference() is None
    b.bg = np.full((4, 4), 1, np.float32)
    assert b.ncc_reference() is b.bg  # ยังไม่มี clean_bg → bg ของ diff
    b.clean_bg, b.clean_bg_valid = np.full((4, 4), 2, np.float32), True
    assert b.ncc_reference() is b.clean_bg
    b.clean_bg_valid = False  # หมดอายุแล้ว (ฉากเปลี่ยน) ก็ยังใช้ภาพนิ่งล่าสุด
    assert b.ncc_reference() is b.clean_bg
    b.frozen, b.snapshot = True, np.full((4, 4), 3, np.float32)
    assert b.ncc_reference() is b.snapshot


def test_item_arriving_while_bg_learns_is_not_swallowed(make_app, env):
    # ของเข้ามาตอน bg ยังเรียนรู้ (ไม่ freeze): เฟรม 2 bg ผสมของไปแล้ว → อ้างอิง clean_bg (ถาดว่าง) ไม่ใช่ bg
    from conftest import FakeController, empty_frame, frame_with, run_frames, settle

    app = make_app(FakeController())
    app.shadow_filter = True
    settle(app, env)
    app.bg.grace_until = env.clock() + 0.05  # ยัง grace: watch ไม่ freeze, bg เรียนรู้เร็ว (0.3)
    run_frames(app, env, frame_with((200, 180)), 3)
    assert cv2.countNonZero(app.fgmask) > 3000 and app.tracker.objects


def test_roi_change_drops_old_clean_bg_reference(make_app, env):
    # ใช้ ROI ใหม่ (App._on_roi_changed — เรียกใน step ก่อนเลือกภาพอ้างอิง) → clean_bg ของ ROI เดิมถูกทิ้งทันที
    from conftest import FakeController, settle

    app = make_app(FakeController())
    settle(app, env, sec=2.0)
    old = app.bg.clean_bg
    assert old is not None and app.bg.ncc_reference() is old
    app._on_roi_changed(env.clock())
    assert app.bg.clean_bg is None and app.bg.ncc_reference() is app.bg.bg


# ── SHADOW_MIN_AREA (texture) / MIN_AREA (off) + log ขนาดก้อน ──────────────────

def _blob_frame(env, size):
    bg = textured_bg()
    cur = bg.copy()
    cur[200:200 + size, 250:250 + size] = 250
    diff = cv2.absdiff(cur, bg)
    roi_mask = env.roi.build_mask(diff.shape)
    box = cv2.boundingRect(roi_mask)
    x, y, w, h = box
    return diff, roi_mask, bg[y:y + h, x:x + w].copy(), cur, box


def test_min_area_texture_uses_shadow_min_area(env, monkeypatch):
    monkeypatch.setattr(main, "MIN_AREA", 150)
    monkeypatch.setattr(main, "SHADOW_MIN_AREA", 400)
    # ก้อน ~14x14 (หลัง DILATE ~ 18x18 ≈ 250-330 px): off นับ (> 150), texture ไม่นับ (< 400)
    diff, roi_mask, ref, cur, box = _blob_frame(env, 10)
    _, det_off, _ = main.detect_objects(diff, env.roi, roi_mask)
    _, det_tex, _ = main.detect_objects(diff, env.roi, roi_mask, ref, cur, box)
    assert len(det_off) == 1 and det_tex == []
    # ก้อนใหญ่ (ของจริง) นับทั้งสองโหมด
    diff, roi_mask, ref, cur, box = _blob_frame(env, 40)
    assert len(main.detect_objects(diff, env.roi, roi_mask)[1]) == 1
    assert len(main.detect_objects(diff, env.roi, roi_mask, ref, cur, box)[1]) == 1


def test_confirm_logs_item_size(make_app, env, caplog):
    import logging

    from conftest import FRAMES_TO_CONFIRM, FakeController, frame_with, run_frames, settle

    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    with caplog.at_level(logging.INFO, logger="vending.main"):
        run_frames(app, env, frame_with((300, 250)), FRAMES_TO_CONFIRM)
    lines = [r.getMessage() for r in caplog.records if "item size:" in r.getMessage()]
    assert app.store.count_today() == 1 and len(lines) == 1
    assert "blob " in lines[0] and "box " in lines[0] and lines[0].isascii()
