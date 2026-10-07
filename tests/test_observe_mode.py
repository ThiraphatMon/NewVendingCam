"""S17 โหมดเก็บข้อมูล (SEND_S0=0): ทำงานเหมือนเดิมทุกอย่าง แต่ไม่เขียน CAMERA เลยไม่ว่าทางไหน

ทุกเส้นทางที่เคยส่ง S0: ยืนยันปกติ / ส่งค้างหลัง Redis หลุดแล้วกลับมา / restart ที่มี S0 ค้างใน DB
ใช้ fakeredis + RedisController จริง (ห้ามต่อ Redis ของเครื่องจริง)
"""

import logging
import time

import fakeredis
import pytest

import config
from api.redis_controller import RedisController
from conftest import FRAMES_TO_CONFIRM, empty_frame, frame_with, run_frames, settle
from core import cycle as cyc
from utils.state_store import R_NOT_SENT

ITEM = frame_with((300, 250))


class SpyRedis(fakeredis.FakeRedis):
    """fakeredis ที่จดทุกคำสั่งที่แตะ key CAMERA (เทียบเท่า MONITOR)"""

    log = None

    def execute_command(self, *args, **options):
        if any(a in ("CAMERA", b"CAMERA") for a in args[1:]):
            SpyRedis.log.append(args)
        return super().execute_command(*args, **options)


@pytest.fixture
def observe(env, make_app):
    server = fakeredis.FakeServer()
    SpyRedis.log = []
    ctls = []

    def _make(send_s0=False, store=None):
        ctl = RedisController(
            lambda: SpyRedis(server=server), poll_interval=0.01, backoff_min=0.05, backoff_max=0.1,
            send_s0=send_s0,
        )
        ctl.start()
        ctls.append(ctl)
        app = make_app(ctl, store=store, send_s0=send_s0)
        settle(app, env)
        return app, ctl

    yield _make, server, fakeredis.FakeRedis(server=server)
    for c in ctls:
        c.stop()


def pump(app, env, frame, pred, timeout=3.0):
    env.source.frame = frame
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        env.clock.advance(1 / 30)
        app.step()
        if pred():
            return True
        time.sleep(0.005)
    return False


def send(app, env, producer, text, frame):
    before = app.last_cmd_seq
    producer.lpush("CTRL", text)
    assert pump(app, env, frame, lambda: app.last_cmd_seq > before)


def test_default_is_observe_mode():
    assert config.SEND_S0 is False


def test_confirm_in_observe_mode_writes_nothing_to_camera(observe, env, caplog):
    make, _, producer = observe
    app, _ = make(send_s0=False)
    send(app, env, producer, "START", empty_frame())
    cid = app.cm.cycle_id
    with caplog.at_level(logging.INFO):
        run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    # state machine / ยอด / ภาพ เหมือนเดิม
    assert app.cm.state == cyc.CONFIRMED_WAIT_STOP and app.store.count_today() == 1
    resp = app.store.get_response(cid)
    assert resp["state"] == R_NOT_SENT and "observe" in resp["last_error"]
    assert "S0 NOT SENT (observe mode)" in caplog.text
    pump(app, env, ITEM, lambda: False, timeout=0.3)  # ให้ worker มีเวลาทำงาน
    send(app, env, producer, "STOP", ITEM)
    assert app.store.get_cycle(cid)["outcome"] == "CONFIRMED"
    assert app.store.get_response(cid)["state"] == R_NOT_SENT  # ปิดรอบไม่เปลี่ยนเป็น EXPIRED
    assert producer.llen("CAMERA") == 0 and SpyRedis.log == []


def test_send_mode_still_writes_camera(observe, env):
    make, _, producer = observe
    app, _ = make(send_s0=True)
    send(app, env, producer, "START", empty_frame())
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert pump(app, env, ITEM, lambda: producer.llen("CAMERA") == 1)
    assert [a[0] for a in SpyRedis.log] == ["LPUSH"]


def test_redis_down_then_back_in_observe_mode_writes_nothing(observe, env):
    # เส้นทาง "S0 ค้างส่งหลัง Redis กลับมา": ยืนยันระหว่าง Redis ล่ม แล้ว Redis กลับมา
    make, server, producer = observe
    app, _ = make(send_s0=False)
    send(app, env, producer, "START", empty_frame())
    cid = app.cm.cycle_id
    server.connected = False
    assert pump(app, env, empty_frame(), lambda: app.redis_up is False)
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert app.store.count_today() == 1
    server.connected = True
    assert pump(app, env, ITEM, lambda: app.redis_up is True)
    pump(app, env, ITEM, lambda: False, timeout=0.3)
    assert app.store.get_response(cid)["state"] == R_NOT_SENT
    assert producer.llen("CAMERA") == 0 and SpyRedis.log == []


def test_restart_with_pending_s0_in_observe_mode_writes_nothing(observe, env):
    # เส้นทาง restart: DB มี S0 ค้าง (PENDING) จาก process ก่อนหน้าที่ SEND_S0=1
    make, _, producer = observe
    store = env.open_store()
    store.open_cycle("hanging")
    store.confirm("hanging", "old.jpg")  # PENDING
    app, _ = make(send_s0=False, store=store)
    assert app.store.get_response("hanging")["state"] == "EXPIRED"
    assert app.store.get_cycle("hanging")["outcome"] == "INTERRUPTED"
    send(app, env, producer, "START", empty_frame())
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    pump(app, env, ITEM, lambda: False, timeout=0.3)
    assert app.store.count_today() == 2
    assert producer.llen("CAMERA") == 0 and SpyRedis.log == []


def test_controller_with_send_s0_off_never_lpushes(observe):
    # กันซ้ำที่ controller: ต่อให้มีคนเรียก request_s0 ก็ไม่เขียน CAMERA
    _, server, producer = observe
    ctl = RedisController(lambda: SpyRedis(server=server), poll_interval=0.01, send_s0=False)
    ctl.start()
    try:
        ctl.request_s0("abc12345", 0)
        time.sleep(0.2)
        assert producer.llen("CAMERA") == 0 and SpyRedis.log == []
        producer.lpush("CTRL", "START")  # ยังรับคำสั่งด้วย RPOP เหมือนเดิม
        end = time.monotonic() + 2
        got = []
        while time.monotonic() < end and not got:
            got = [e for e in ctl.drain() if getattr(e, "text", None) == "START"]
            time.sleep(0.01)
        assert got and producer.llen("CTRL") == 0
    finally:
        ctl.stop()
