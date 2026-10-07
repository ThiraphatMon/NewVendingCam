"""fixtures ร่วม: นาฬิกาปลอม, กล้องปลอม, controller ปลอม, เฟรมสังเคราะห์ และตัวสร้าง App"""

import json
import time
import types

import numpy as np
import pytest

import core.tracker
from api.redis_controller import Command, SendResult
from core.frame_source import NO_NEW_FRAME
from core.roi import ROIManager
from utils.state_store import StateStore

FPS = 30.0
BG_GRAY = 60
OBJ_GRAY = 220
ROI_RECT = {"x": 100, "y": 100, "w": 400, "h": 300}


class FakeClock:
    """ใช้ทั้ง wall clock และ monotonic (เริ่มที่ 06:45:12 UTC = 13:45:12 ไทย 05/10/2026)"""

    def __init__(self, t=1_791_182_712.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, sec):
        self.t += sec


class FakeSource:
    """กล้องปลอม: คืนเฟรมที่ตั้งไว้ (None = กล้องหลุด/ค้าง, NO_NEW_FRAME = ยังไม่มีเฟรมใหม่) และนับการ open/release"""

    def __init__(self):
        self.frame = None
        self.open_count = 1  # เปิดครั้งเดียวตอนสร้าง (เหมือน FrameSource)
        self.release_count = 0
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.frame is None or self.frame is NO_NEW_FRAME:
            return self.frame
        return self.frame.copy()

    def release(self):
        self.release_count += 1


class FakeController:
    """แทน RedisController: test ใส่คำสั่งเอง และ S0 สำเร็จทันที (นับไว้ใน s0)"""

    enabled = True

    def __init__(self):
        self.inbox = []
        self.seq = 0
        self.s0 = []
        self.revoked = []

    def push(self, text):
        self.seq += 1
        self.inbox.append(Command(self.seq, text, 0.0))

    inject = push

    def drain(self):
        items, self.inbox = self.inbox, []
        return items

    def request_s0(self, cycle_id, after_seq):
        self.s0.append(cycle_id)
        self.inbox.append(SendResult(cycle_id, "ENQUEUED"))

    def revoke(self, cycle_id):
        self.revoked.append(cycle_id)


def empty_frame():
    return np.full((480, 640, 3), BG_GRAY, np.uint8)


def frame_with(*centers, size=60):
    """เฟรมที่มีวัตถุสี่เหลี่ยมสว่างที่ตำแหน่ง centers [(cx, cy), ...]"""
    f = empty_frame()
    half = size // 2
    for cx, cy in centers:
        f[cy - half:cy + half, cx - half:cx + half] = OBJ_GRAY
    return f


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    # tracker ใช้ time.time() ภายใน → ชี้ไปนาฬิกาเดียวกัน (ไม่แก้ logic ของ tracker)
    monkeypatch.setattr(core.tracker, "time", types.SimpleNamespace(time=c))
    return c


@pytest.fixture
def env(tmp_path, clock):
    """สภาพแวดล้อมของ App ใน tmp_path ทั้งหมด"""
    roi_path = tmp_path / "roi_config.json"
    roi_path.write_text(json.dumps({
        "frame": {"width": 640, "height": 480}, "roi_type": "rect", "rect": ROI_RECT,
    }))
    ns = types.SimpleNamespace(
        tmp=tmp_path,
        clock=clock,
        db_path=str(tmp_path / "data" / "vending_state.sqlite3"),
        evidence_dir=str(tmp_path / "evidence_images"),
        daily_dir=str(tmp_path / "logs" / "item_drops"),
        roi=ROIManager(640, 480, config_path=str(roi_path)),
        source=FakeSource(),
    )
    ns.open_store = lambda: StateStore(ns.db_path, "VENDING_01", "Asia/Bangkok", clock=clock)
    return ns


@pytest.fixture
def make_app(env):
    from main import App

    # send_s0=True: เทสต์เดิมทั้งหมดทดสอบพฤติกรรม SEND_S0=1 (default ของ config เป็น 0 = โหมดเก็บข้อมูล)
    def _make(controller=None, store=None, cloud=None, send_s0=True):
        app = App(
            "VENDING_01", env.source, env.roi, store or env.open_store(),
            controller or FakeController(),
            headless=True, evidence_dir=env.evidence_dir, daily_log_dir=env.daily_dir,
            clock=env.clock, mono=env.clock, cloud=cloud, send_s0=send_s0,
        )
        return app

    return _make


def run_frames(app, env, frame, n):
    """ป้อนเฟรมเดิม n ครั้ง เดินนาฬิกาตาม FPS"""
    env.source.frame = frame
    for _ in range(n):
        env.clock.advance(1 / FPS)
        app.step()


def settle(app, env, sec=1.0):
    """ถาดว่างนิ่ง ๆ ให้ bg + clean_bg พร้อม"""
    run_frames(app, env, empty_frame(), int(sec * FPS))


# วัตถุนิ่งจนผ่านเกณฑ์ยืนยัน: 4 เฟรมจน SHAPE_CONFIRMED + CAPTURE_HOLD_SEC (default 1.0s) + เผื่อ
FRAMES_TO_CONFIRM = int(2.0 * FPS)


# ── stub HTTP server ของ cloud (127.0.0.1 port สุ่ม — ห้ามยิง server จริง) ────────────
class CloudStub:
    """จำทุก request ที่ได้รับ; ตั้งผลตอบได้ต่อ path:
      roi        : dict ที่ GET .../roi คืน (None = {"status": "no_config"})
      fail_next  : list ของ status code ที่จะตอบก่อน (ใช้ทีละตัว) เช่น [500, 500] แล้วค่อย 200
      hang       : True = รับ request แล้วไม่ตอบ (จำลองเน็ตค้าง)"""

    def __init__(self):
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.requests = []
        self.roi = None
        self.fail_next = []
        self.hang = False
        self.lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _handle(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                with stub.lock:
                    stub.requests.append(types.SimpleNamespace(
                        method=self.command, path=self.path, headers=dict(self.headers), body=body,
                    ))
                    status = stub.fail_next.pop(0) if stub.fail_next else 200
                if stub.hang:
                    time.sleep(5)
                    return
                if self.command == "GET":
                    out = json.dumps(stub.roi or {"status": "no_config"}).encode()
                else:
                    out = b"ok"
                self.send_response(status)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            do_GET = do_POST = do_PUT = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def events_url(self):
        return f"http://127.0.0.1:{self.port}/api/events"

    def paths(self, method=None):
        with self.lock:
            return [r.path for r in self.requests if method is None or r.method == method]

    def wait_for(self, pred, timeout=3.0):
        """รอจนมี request ที่ pred(r) เป็นจริง คืน request นั้น (ไม่มี → None)"""
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                for r in self.requests:
                    if pred(r):
                        return r
            time.sleep(0.01)
        return None

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def multipart_fields(req):
    """แยก multipart/form-data → ({field: str}, {file field: bytes})"""
    ctype = req.headers.get("Content-Type", "")
    boundary = ctype.split("boundary=", 1)[1].encode()
    fields, files = {}, {}
    for part in req.body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        data = data[:-2] if data.endswith(b"\r\n") else data
        name = head.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
        if b"filename=" in head:
            files[name] = data
        else:
            fields[name] = data.decode()
    return fields, files


@pytest.fixture
def cloud_stub(monkeypatch):
    import api.client

    stub = CloudStub()
    monkeypatch.setattr(api.client, "CLOUD_API_URL", stub.events_url)
    monkeypatch.setattr(api.client, "API_KEY", "test-key")
    yield stub
    stub.close()
