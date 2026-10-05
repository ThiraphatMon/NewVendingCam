"""tests ของ api/redis_controller.py — ใช้ fakeredis เท่านั้น (ห้ามต่อ Redis ของเครื่องจริง)"""

import time

import fakeredis
import pytest
import redis

from api.redis_controller import Command, LinkStatus, RedisController, SendResult, make_client


def wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


class Collector:
    """เก็บเหตุการณ์จาก inbox ไว้ตรวจ"""

    def __init__(self, ctl):
        self.ctl = ctl
        self.events = []

    def pull(self):
        self.events += self.ctl.drain()
        return self.events

    def of(self, kind):
        self.pull()
        return [e for e in self.events if isinstance(e, kind)]

    def wait(self, kind, n=1, timeout=3.0):
        assert wait_for(lambda: len(self.of(kind)) >= n, timeout), f"ไม่ได้ {kind.__name__} ครบ {n}: {self.events}"
        return self.of(kind)


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def producer(server):
    return fakeredis.FakeRedis(server=server)


@pytest.fixture
def make_ctl(server):
    ctls = []

    def _make(factory=None, **kw):
        kw.setdefault("poll_interval", 0.02)
        kw.setdefault("backoff_min", 0.05)
        kw.setdefault("backoff_max", 0.2)
        ctl = RedisController(factory or (lambda: fakeredis.FakeRedis(server=server)), **kw)
        ctl.start()
        ctls.append(ctl)
        return ctl, Collector(ctl)

    yield _make
    for c in ctls:
        c.stop()


def test_commands_arrive_in_fifo_order(make_ctl, producer):
    # producer LPUSH + เรา RPOP = FIFO (เหมือนตัวเก่า)
    for t in ("START", "STOP", "START"):
        producer.lpush("CTRL", t)
    ctl, col = make_ctl()
    cmds = col.wait(Command, 3)
    assert [c.text for c in cmds] == ["START", "STOP", "START"]
    assert [c.seq for c in cmds] == [1, 2, 3]
    assert col.of(LinkStatus)[0].up is True


def test_unknown_and_undecodable_messages_ignored(make_ctl, producer):
    for raw in (b"\xff\xfe", "HELLO", "start", " START", "START\n", "S0"):
        producer.lpush("CTRL", raw)
    producer.lpush("CTRL", "STOP")
    ctl, col = make_ctl()
    cmds = col.wait(Command, 1)
    time.sleep(0.1)
    assert [c.text for c in col.of(Command)] == ["STOP"]
    assert producer.llen("CTRL") == 0
    assert ctl._thread.is_alive()


class CountingClient:
    """ห่อ fakeredis นับจำนวนครั้งที่เรียก (ตรวจว่าไม่ busy-loop)"""

    def __init__(self, inner, counts):
        self.inner = inner
        self.counts = counts

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        def wrapped(*a, **kw):
            self.counts[name] = self.counts.get(name, 0) + 1
            return attr(*a, **kw)

        return wrapped


def test_empty_queue_does_not_busy_loop(make_ctl, server):
    counts = {}
    make_ctl(lambda: CountingClient(fakeredis.FakeRedis(server=server), counts), poll_interval=0.05)
    time.sleep(0.5)
    # 0.5s / poll 0.05s ≈ 10 ครั้ง (ไม่ใช่หลายพันครั้งแบบ busy-loop)
    assert 3 <= counts.get("rpop", 0) <= 20


def test_redis_down_backs_off_then_recovers(make_ctl, server, producer):
    server.connected = False
    attempts = []

    def factory():
        attempts.append(time.monotonic())
        return fakeredis.FakeRedis(server=server)

    ctl, col = make_ctl(factory, backoff_min=0.1, backoff_max=0.4)
    down = col.wait(LinkStatus, 1)
    assert down[0].up is False
    time.sleep(1.0)
    # backoff 0.1, 0.2, 0.4, 0.4 ... → ไม่เกิน ~5 ครั้งใน 1 วินาที
    assert 2 <= len(attempts) <= 7
    assert col.of(Command) == []

    server.connected = True
    producer.lpush("CTRL", "START")
    cmds = col.wait(Command, 1)
    assert cmds[0].text == "START"
    assert [s.up for s in col.of(LinkStatus)] == [False, True]


def test_s0_success_enqueued_once(make_ctl, producer):
    ctl, col = make_ctl()
    col.wait(LinkStatus, 1)
    ctl.request_s0("c1", after_seq=0)
    res = col.wait(SendResult, 1)
    assert (res[0].cycle_id, res[0].state) == ("c1", "ENQUEUED")
    assert producer.lrange("CAMERA", 0, -1) == [b"S0"]


class LpushTimeoutClient(CountingClient):
    """LPUSH ถึง Redis จริง แต่คำตอบหาย (จำลอง socket timeout หลังส่ง)"""

    def lpush(self, *a, **kw):
        self.counts["lpush"] = self.counts.get("lpush", 0) + 1
        self.inner.lpush(*a, **kw)
        raise redis.TimeoutError("Timeout reading from socket")


def test_lpush_timeout_is_unknown_and_not_retried(make_ctl, server, producer):
    counts = {}
    ctl, col = make_ctl(lambda: LpushTimeoutClient(fakeredis.FakeRedis(server=server), counts))
    col.wait(LinkStatus, 1)
    ctl.request_s0("c1", after_seq=0)
    res = col.wait(SendResult, 1)
    assert res[0].state == "UNKNOWN" and "Timeout" in res[0].error
    time.sleep(0.5)  # ให้เวลา worker reconnect / ลองใหม่ ถ้ามันจะทำ
    assert counts["lpush"] == 1
    assert producer.lrange("CAMERA", 0, -1) == [b"S0"]
    assert [r.state for r in col.of(SendResult)] == ["UNKNOWN"]


def test_known_failure_retried_while_allowed(make_ctl, server, producer):
    ctl, col = make_ctl()
    col.wait(LinkStatus, 1)
    server.connected = False  # PING ก่อนส่งจะ ConnectionError = ยังไม่ได้ส่งแน่นอน
    ctl.request_s0("c1", after_seq=0)
    failed = col.wait(SendResult, 1)
    assert failed[0].state == "FAILED"
    server.connected = True
    res = col.wait(SendResult, 2)
    assert res[1].state == "ENQUEUED"
    assert producer.lrange("CAMERA", 0, -1) == [b"S0"]


def test_revoked_request_never_sent(make_ctl, server, producer):
    ctl, col = make_ctl()
    col.wait(LinkStatus, 1)
    server.connected = False
    ctl.request_s0("c1", after_seq=0)
    col.wait(SendResult, 1)  # FAILED
    ctl.revoke("c1")  # STOP → รอบปิดระหว่าง Redis ล่ม
    res = col.wait(SendResult, 2)
    assert res[1].state == "EXPIRED"
    server.connected = True
    time.sleep(0.4)
    assert producer.llen("CAMERA") == 0


def test_stop_popped_before_send_blocks_s0(make_ctl, producer):
    ctl, col = make_ctl()
    producer.lpush("CTRL", "STOP")
    col.wait(Command, 1)  # worker pop STOP แล้ว แต่ main ยังไม่ประมวลผล (after_seq=0)
    ctl.request_s0("c1", after_seq=0)
    res = col.wait(SendResult, 1)
    assert res[0].state == "EXPIRED"
    assert producer.llen("CAMERA") == 0


def test_make_client_disables_automatic_retry():
    c = make_client("127.0.0.1", 6379, 0, "", 1.0, 1.0)
    kw = c.connection_pool.connection_kwargs
    assert kw["retry"]._retries == 0
    assert kw["socket_timeout"] == 1.0 and kw["socket_connect_timeout"] == 1.0
    assert not kw.get("retry_on_timeout")


def test_keyboard_mode_injects_and_never_sends(server, producer):
    ctl = RedisController(lambda: fakeredis.FakeRedis(server=server), enabled=False)
    ctl.start()
    ctl.inject("START")
    ctl.request_s0("c1", after_seq=1)
    events = ctl.drain()
    assert isinstance(events[0], Command) and events[0].source == "keyboard"
    assert isinstance(events[1], SendResult) and events[1].state == "EXPIRED"
    assert producer.llen("CAMERA") == 0
