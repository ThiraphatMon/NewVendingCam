"""tests ของ core/cycle.py — state machine แบบ pure ใช้ fake clock (ตัวเลข now ส่งเข้าไปเอง)"""

import itertools

import pytest

from core.cycle import (
    ACTIVE, BLOCKED_WAIT_STOP, CONFIRMED_WAIT_STOP, RECOVERY_BLOCKED, WAIT_START, CycleMachine,
)


@pytest.fixture
def cm():
    ids = (f"c{i}" for i in itertools.count(1))
    return CycleMachine(timeout_sec=300, new_id=lambda: next(ids))


def test_start_opens_active_and_can_confirm(cm):
    r = cm.on_start(now=0)
    assert r.opened == "c1" and r.closed is None and r.anomaly is None
    assert cm.state == ACTIVE and cm.can_confirm()


def test_wait_start_cannot_confirm(cm):
    assert cm.state == WAIT_START and not cm.can_confirm()


def test_stop_during_wait_start_is_noop(cm):
    r = cm.on_stop(now=0)
    assert r.closed is None and r.opened is None
    assert cm.state == WAIT_START


def test_start_stop_without_object_is_unconfirmed(cm):
    cm.on_start(0)
    r = cm.on_stop(5)
    assert r.closed.cycle_id == "c1"
    assert r.closed.outcome == "UNCONFIRMED" and not r.closed.confirmed
    assert cm.state == WAIT_START and cm.cycle_id is None


def test_confirm_latch_then_stop(cm):
    cm.on_start(0)
    cm.mark_confirmed()
    assert cm.state == CONFIRMED_WAIT_STOP and not cm.can_confirm()
    r = cm.on_stop(10)
    assert r.closed.outcome == "CONFIRMED" and r.closed.confirmed


def test_mark_confirmed_outside_active_raises(cm):
    with pytest.raises(RuntimeError):
        cm.mark_confirmed()
    cm.on_start(0)
    cm.mark_confirmed()
    with pytest.raises(RuntimeError):
        cm.mark_confirmed()


def test_duplicate_start_while_active_is_anomaly(cm):
    cm.on_start(0)
    r = cm.on_start(1)
    assert r.anomaly == "DUPLICATE_START" and r.opened is None and r.closed is None
    assert cm.state == ACTIVE and cm.cycle_id == "c1" and cm.started_at == 0


def test_start_after_confirm_closes_and_opens_new(cm):
    # Q1(b): เหมือนตัวเก่า — controller อาจไม่ส่ง STOP หลัง S0
    cm.on_start(0)
    cm.mark_confirmed()
    r = cm.on_start(3)
    assert r.closed.cycle_id == "c1" and r.closed.outcome == "CONFIRMED"
    assert r.closed.reason == "next_start"
    assert r.opened == "c2" and cm.state == ACTIVE and cm.started_at == 3


def test_start_stop_start_gives_separate_ids(cm):
    a = cm.on_start(0).opened
    cm.on_stop(0.01)
    b = cm.on_start(0.02).opened
    assert a != b and cm.cycle_id == b
    assert not cm.is_current_open(a) and cm.is_current_open(b)


def test_timeout_closes_cycle(cm):
    cm.on_start(100)
    assert cm.tick(399.9) is None
    r = cm.tick(400)
    assert r.closed.outcome == "TIMEOUT" and r.closed.reason == "timeout"
    assert cm.state == WAIT_START


def test_timeout_after_confirm_keeps_confirmed_outcome(cm):
    cm.on_start(0)
    cm.mark_confirmed()
    r = cm.tick(300)
    assert r.closed.outcome == "CONFIRMED" and r.closed.reason == "timeout"


def test_tick_in_wait_start_does_nothing(cm):
    assert cm.tick(10_000) is None


def test_camera_lost_blocks_confirmation_and_stop_is_uncertain(cm):
    cm.on_start(0)
    assert cm.on_camera_lost() is True
    assert cm.state == BLOCKED_WAIT_STOP and not cm.can_confirm()
    assert cm.on_start(1).anomaly == "DUPLICATE_START"
    r = cm.on_stop(2)
    assert r.closed.outcome == "UNCERTAIN" and "camera_gap" in r.closed.reason


def test_camera_lost_after_confirm_keeps_confirmed(cm):
    cm.on_start(0)
    cm.mark_confirmed()
    assert cm.on_camera_lost() is False
    assert cm.state == CONFIRMED_WAIT_STOP
    assert cm.on_stop(1).closed.outcome == "CONFIRMED"


def test_camera_lost_outside_cycle_is_ignored(cm):
    assert cm.on_camera_lost() is False and cm.state == WAIT_START
    # gap ก่อนรอบไม่ติดไปกับรอบใหม่
    cm.on_start(0)
    assert cm.on_stop(1).closed.outcome == "UNCONFIRMED"


def test_redis_gap_makes_unconfirmed_close_uncertain(cm):
    cm.on_start(0)
    cm.on_redis_gap()
    assert cm.can_confirm()  # Redis ขาดไม่ block การยืนยัน (ยอดรายวันยังต้องครบ)
    r = cm.on_stop(1)
    assert r.closed.outcome == "UNCERTAIN" and "redis_gap" in r.closed.reason


def test_recovery_blocked_ignores_start_until_stop(cm):
    cm.enter_recovery(now=0)
    assert cm.state == RECOVERY_BLOCKED and not cm.is_open() and not cm.can_confirm()
    r = cm.on_start(0)
    assert r.anomaly == "START_DURING_RECOVERY" and r.opened is None
    assert cm.tick(299) is None
    r = cm.on_stop(1)
    assert r.closed is None and cm.state == WAIT_START
    assert cm.on_start(2).opened == "c1"


def test_recovery_blocked_expires_after_cycle_timeout(cm):
    cm.enter_recovery(now=1000)
    assert cm.tick(1299.9) is None and cm.state == RECOVERY_BLOCKED
    r = cm.tick(1300)
    assert r.closed is None and "RECOVERY_BLOCKED" in r.note
    assert cm.state == WAIT_START and cm.recovery_since is None
    assert cm.on_start(1301).opened == "c1"


# ── ลำดับคำสั่งเทียบกับ legacy_reference/main.py ────────────────────────────────
# ตัวเก่า: วงนอก RPOP ทุก 0.5s — เปิดรอบเฉพาะ "START" อย่างอื่น pop ทิ้ง
#          วงใน (≤300s) — "STOP" = จบรอบ อย่างอื่น (รวม START) pop ทิ้ง
#          detect ได้ → LPUSH S0 แล้วจบรอบทันที (ไม่รอ STOP)

def run(cm, script):
    """script: list ของ (เวลา, "START" | "STOP" | "ITEM" | "TICK") → คืนจำนวน S0"""
    s0 = 0
    for t, ev in script:
        if ev == "START":
            cm.on_start(t)
        elif ev == "STOP":
            cm.on_stop(t)
        elif ev == "TICK":
            cm.tick(t)
        elif ev == "ITEM" and cm.can_confirm():
            cm.mark_confirmed()
            s0 += 1
    return s0


def test_legacy_start_s0_stop_twice(cm):
    s0 = run(cm, [(0, "START"), (1, "ITEM"), (2, "STOP"), (3, "START"), (4, "ITEM"), (5, "STOP")])
    assert s0 == 2 and cm.state == WAIT_START


def test_legacy_start_s0_start_s0_single_stop(cm):
    s0 = run(cm, [(0, "START"), (1, "ITEM"), (2, "START"), (3, "ITEM"), (4, "STOP")])
    assert s0 == 2 and cm.state == WAIT_START


def test_legacy_second_stop_has_no_effect(cm):
    run(cm, [(0, "START"), (1, "ITEM"), (2, "STOP")])
    r = cm.on_stop(3)
    assert r.closed is None and r.opened is None and cm.state == WAIT_START


def test_legacy_start_without_item_then_start_is_ignored(cm):
    cm.on_start(0)
    first = cm.cycle_id
    r = cm.on_start(10)
    assert r.anomaly == "DUPLICATE_START"
    assert cm.cycle_id == first and cm.started_at == 0  # รอบเดิมเดินต่อ ไม่รีเซ็ตเวลา
    # ของตกหลัง START ที่สอง ยังยืนยันในรอบเดิมได้
    assert run(cm, [(11, "ITEM")]) == 1
    # timeout นับจาก START แรก (เหมือนตัวเก่า)
    assert cm.tick(300).closed.cycle_id == first


def test_legacy_no_item_timeout_closes_silently(cm):
    s0 = run(cm, [(0, "START"), (299, "TICK")])
    assert cm.is_open()
    r = cm.tick(300)
    assert s0 == 0 and r.closed.outcome == "TIMEOUT" and cm.state == WAIT_START


def test_is_current_open_rejects_none_and_closed(cm):
    assert not cm.is_current_open(None)
    cid = cm.on_start(0).opened
    assert cm.is_current_open(cid)
    cm.mark_confirmed()
    assert cm.is_current_open(cid)  # ยืนยันแล้วยังส่ง S0 ได้จนกว่าจะปิดรอบ
    cm.on_stop(1)
    assert not cm.is_current_open(cid)
