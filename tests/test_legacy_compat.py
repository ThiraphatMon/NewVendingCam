"""ลำดับคำสั่งจริงผ่าน Redis (fakeredis) — ต้องตอบสนองเหมือน legacy_reference/main.py

ตัวเก่า: RPOP CTRL — "START" เปิดรอบ, ระหว่างรอบ "STOP" จบรอบ อย่างอื่น pop ทิ้ง
         detect ได้ → LPUSH CAMERA "S0" แล้วจบรอบทันที / ครบ 300s → จบรอบเงียบ ๆ
"""

import time

import fakeredis
import pytest

from api.redis_controller import RedisController
from conftest import FRAMES_TO_CONFIRM, empty_frame, frame_with, run_frames, settle
from core import cycle as cyc

POS = [(300, 250), (180, 170), (420, 330)]


@pytest.fixture
def redis_env(env, make_app):
    server = fakeredis.FakeServer()
    producer = fakeredis.FakeRedis(server=server)
    ctl = RedisController(
        lambda: fakeredis.FakeRedis(server=server), poll_interval=0.01, backoff_min=0.05,
    )
    ctl.start()
    app = make_app(ctl)
    settle(app, env)
    yield app, producer, server
    ctl.stop()


def pump(app, env, frame, pred, timeout=3.0):
    """เดิน main loop (เฟรมเดิม) จนเงื่อนไขเป็นจริง — worker ใช้เวลาจริง"""
    env.source.frame = frame
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        env.clock.advance(1 / 30)
        app.step()
        if pred():
            return
        time.sleep(0.005)
    raise AssertionError("รอนานเกิน")


def send(app, env, producer, text, frame):
    before = app.last_cmd_seq
    producer.lpush("CTRL", text)
    pump(app, env, frame, lambda: app.last_cmd_seq > before)


def s0_count(producer):
    return producer.llen("CAMERA")


def drop_item(app, env, producer, items):
    """ของตกในช่องแล้วนิ่ง → รอจน S0 ถึง CAMERA"""
    before = s0_count(producer)
    frame = frame_with(*items)
    run_frames(app, env, frame, FRAMES_TO_CONFIRM)
    pump(app, env, frame, lambda: s0_count(producer) > before)
    return frame


def test_start_s0_stop_start_s0_stop(redis_env, env):
    app, producer, _ = redis_env
    send(app, env, producer, "START", empty_frame())
    f = drop_item(app, env, producer, POS[:1])
    send(app, env, producer, "STOP", f)
    send(app, env, producer, "START", f)
    f = drop_item(app, env, producer, POS[:2])
    send(app, env, producer, "STOP", f)
    assert s0_count(producer) == 2 and app.store.count_today() == 2
    assert app.cm.state == cyc.WAIT_START


def test_start_s0_start_s0_single_stop(redis_env, env):
    app, producer, _ = redis_env
    send(app, env, producer, "START", empty_frame())
    f = drop_item(app, env, producer, POS[:1])
    first = app.cm.cycle_id
    send(app, env, producer, "START", f)  # ไม่มี STOP คั่น (ตัวเก่ารับ START ถัดไปได้ทันที)
    assert app.cm.cycle_id != first and app.cm.state == cyc.ACTIVE
    assert app.store.get_cycle(first)["outcome"] == "CONFIRMED"
    f = drop_item(app, env, producer, POS[:2])
    send(app, env, producer, "STOP", f)
    assert s0_count(producer) == 2 and app.store.count_today() == 2
    assert producer.lrange("CAMERA", 0, -1) == [b"S0", b"S0"]


def test_start_s0_stop_stop(redis_env, env):
    app, producer, _ = redis_env
    send(app, env, producer, "START", empty_frame())
    f = drop_item(app, env, producer, POS[:1])
    send(app, env, producer, "STOP", f)
    send(app, env, producer, "STOP", f)  # ไม่มีผล
    run_frames(app, env, f, 30)
    assert app.cm.state == cyc.WAIT_START
    assert s0_count(producer) == 1 and app.store.count_today() == 1
    n_cycles = app.store.conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
    assert n_cycles == 1


def test_start_no_item_start_is_ignored(redis_env, env):
    app, producer, _ = redis_env
    send(app, env, producer, "START", empty_frame())
    first = app.cm.cycle_id
    run_frames(app, env, empty_frame(), 30)
    send(app, env, producer, "START", empty_frame())  # ตัวเก่า pop ทิ้ง → รอบเดิมเดินต่อ
    assert app.cm.cycle_id == first and app.cm.state == cyc.ACTIVE
    drop_item(app, env, producer, POS[:1])
    assert s0_count(producer) == 1 and app.cm.cycle_id == first


def test_start_no_item_timeout_sends_nothing(redis_env, env):
    app, producer, _ = redis_env
    send(app, env, producer, "START", empty_frame())
    cid = app.cm.cycle_id
    env.clock.advance(300)
    run_frames(app, env, empty_frame(), 1)
    assert app.cm.state == cyc.WAIT_START
    assert app.store.get_cycle(cid)["outcome"] == "TIMEOUT"
    time.sleep(0.1)
    assert s0_count(producer) == 0


def test_garbage_messages_do_not_open_cycle(redis_env, env):
    app, producer, _ = redis_env
    for raw in ("hello", b"\x00\xff", "start", "S0", ""):
        producer.lpush("CTRL", raw)
    pump(app, env, empty_frame(), lambda: producer.llen("CTRL") == 0)
    run_frames(app, env, frame_with(POS[0]), FRAMES_TO_CONFIRM)
    assert app.cm.state == cyc.WAIT_START and app.last_cmd_seq == 0
    assert s0_count(producer) == 0


def test_redis_down_during_cycle_marks_uncertain_and_stop_after_recovery(redis_env, env):
    app, producer, server = redis_env
    send(app, env, producer, "START", empty_frame())
    cid = app.cm.cycle_id
    server.connected = False
    pump(app, env, empty_frame(), lambda: app.redis_up is False)
    assert app.cm.redis_gap
    server.connected = True
    pump(app, env, empty_frame(), lambda: app.redis_up is True)
    send(app, env, producer, "STOP", empty_frame())
    assert app.store.get_cycle(cid)["outcome"] == "UNCERTAIN"
