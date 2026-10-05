"""tests S4: ความนิ่งของ tracker (F03 ขยับระหว่าง hold / F04 หายแล้วกลับมา) — STRICT_STABILITY"""

import types

import pytest

import core.tracker as tr
from conftest import FakeClock

BOX = (300, 250, 60, 60)


@pytest.fixture
def tracker(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(tr, "time", types.SimpleNamespace(time=clock))
    t = tr.MemoryTracker()
    t.clock = clock
    return t


def feed(t, boxes, n=1):
    for _ in range(n):
        t.clock.advance(1 / 30)
        objs = t.update(boxes)
    return objs


def only(objs):
    assert len(objs) == 1
    return next(iter(objs.values()))


def landed(t):
    """วัตถุนิ่งครบ LANDING_STABLE_FRAMES → SHAPE_CONFIRMED"""
    feed(t, [BOX], tr.LANDING_STABLE_FRAMES + 1)
    obj = only(t.objects)
    assert obj["state"] == "SHAPE_CONFIRMED"
    return obj


@pytest.mark.parametrize("strict", [False, True])
def test_move_during_hold(tracker, monkeypatch, strict):
    # [F03] ขยับเกิน CENTROID_STABLE_DIST ระหว่าง hold
    monkeypatch.setattr(tr, "STRICT_STABILITY", strict)
    landed(tracker)
    moved = (BOX[0] + tr.CENTROID_STABLE_DIST + 5, BOX[1], BOX[2], BOX[3])
    obj = only(feed(tracker, [moved]))
    if strict:
        assert obj["state"] == "DETECTING" and obj["shape_confirmed_time"] is None
        assert obj["shape_stable_count"] == 0
        feed(tracker, [moved], tr.LANDING_STABLE_FRAMES)
        assert only(tracker.objects)["state"] == "SHAPE_CONFIRMED"  # นิ่งใหม่ครบ → ลงจอดใหม่
    else:
        assert obj["state"] == "SHAPE_CONFIRMED"  # แบบเดิม: ไม่ถอน


def test_small_jitter_during_hold_keeps_confirmed(tracker, monkeypatch):
    monkeypatch.setattr(tr, "STRICT_STABILITY", True)
    first = landed(tracker)["shape_confirmed_time"]
    obj = only(feed(tracker, [(BOX[0] + 3, BOX[1] + 2, BOX[2], BOX[3])], 5))
    assert obj["state"] == "SHAPE_CONFIRMED" and obj["shape_confirmed_time"] == first


@pytest.mark.parametrize("strict", [False, True])
def test_ghost_then_return_restarts_stability(tracker, monkeypatch, strict):
    # [F04] นิ่งได้ 3 เฟรม → หาย 1 เฟรม → กลับมา
    monkeypatch.setattr(tr, "STRICT_STABILITY", strict)
    feed(tracker, [BOX], 4)  # สร้าง + นิ่ง 3
    tracker.clock.advance(1)  # พ้น NEW_OBJ_GRACE_SEC (ไม่ถูกลบทันทีเป็นวัตถุใหม่)
    obj = only(feed(tracker, []))
    assert obj["state"] == "DETECTING" and obj["ghost_frames"] == 1
    obj = only(feed(tracker, [BOX]))
    if strict:
        assert obj["shape_stable_count"] == 1 and obj["state"] == "DETECTING"
    else:
        assert obj["shape_stable_count"] == 4 and obj["state"] == "SHAPE_CONFIRMED"  # สะสมข้ามช่วงหาย


def test_ghost_after_confirm_requires_full_stability_again_when_strict(tracker, monkeypatch):
    monkeypatch.setattr(tr, "STRICT_STABILITY", True)
    landed(tracker)
    feed(tracker, [])
    obj = only(feed(tracker, [BOX], tr.LANDING_STABLE_FRAMES - 1))
    assert obj["state"] == "DETECTING"
    obj = only(feed(tracker, [BOX]))
    assert obj["state"] == "SHAPE_CONFIRMED"
