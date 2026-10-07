"""tests S5: อ่านกล้องใน thread แยก (slot เฟรมล่าสุด), กล้องค้าง, กล้องหลุด, ไฟล์วิดีโอเล่นตามเวลาจริง"""

import threading
import time

import numpy as np
import pytest

import core.frame_source as fs
from conftest import FakeController, empty_frame, run_frames, settle
from core import cycle as cyc
from core.frame_source import NO_NEW_FRAME, FrameSource


class Camera:
    """พฤติกรรมของกล้องปลอมแต่ละครั้งที่เปิด: scripts[n] = รายการ action ของการเปิดครั้งที่ n
    action: int = คืนเฟรมค่าสีนั้น | "fail" = ret False | "block" = ค้างจนกว่า release_block"""

    def __init__(self, *scripts, fps=30.0, frame_delay=0.0):
        self.scripts = list(scripts)
        self.fps = fps
        self.frame_delay = frame_delay
        self.opened = 0
        self.unblock = threading.Event()

    def factory(self, source):
        script = self.scripts[min(self.opened, len(self.scripts) - 1)]
        self.opened += 1
        return FakeCap(self, list(script))


class FakeCap:
    def __init__(self, cam, actions):
        self.cam, self.actions = cam, actions
        self.released = False

    def set(self, *a):
        return True

    def get(self, prop):
        return self.cam.fps

    def read(self):
        if not self.actions:
            self.cam.unblock.wait()  # หมดสคริปต์ = ค้าง
            return False, None
        a = self.actions.pop(0)
        if a == "fail":
            time.sleep(self.cam.frame_delay)
            return False, None
        if a == "block":
            self.cam.unblock.wait()
            return False, None
        if self.cam.frame_delay:
            time.sleep(self.cam.frame_delay)
        return True, np.full((480, 640, 3), a, np.uint8)

    def release(self):
        self.released = True


@pytest.fixture
def camera(monkeypatch):
    holder = {}

    def make(*scripts, **kw):
        cam = Camera(*scripts, **kw)
        monkeypatch.setattr(fs.cv2, "VideoCapture", cam.factory)
        holder["cam"] = cam
        return cam

    yield make
    if "cam" in holder:
        holder["cam"].unblock.set()  # ปล่อย thread ที่ค้างอยู่


def read_until(src, pred, timeout=3.0):
    end = time.time() + timeout
    seen = []
    while time.time() < end:
        r = src.read()
        seen.append(r)
        if pred(r):
            return r, seen
    raise AssertionError(f"ไม่ได้ผลที่ต้องการภายใน {timeout}s: {[_kind(x) for x in seen][-10:]}")


def _kind(r):
    if r is None:
        return "None"
    if r is NO_NEW_FRAME:
        return "NO_NEW"
    return int(r[0, 0, 0])


def test_each_frame_returned_once_then_no_new_frame(camera):
    camera([10, 20, 30, "block"], frame_delay=0.02)
    src = FrameSource(0, stall_sec=5)
    got = []
    end = time.time() + 2
    while time.time() < end and len(got) < 3:
        r = src.read()
        if r is not NO_NEW_FRAME and r is not None:
            got.append(int(r[0, 0, 0]))
    assert got == [10, 20, 30]  # ทุกเฟรมตามลำดับ ไม่ซ้ำ (main อ่านเร็วกว่ากล้อง)
    assert len(got) == len(set(got))
    assert src.read() is NO_NEW_FRAME  # ไม่คืนเฟรมเดิมซ้ำ
    src.release()


def test_stall_reports_gap_and_reopens(camera, caplog):
    cam = camera([10, "block"], [40, 40, 40, "block"])
    src = FrameSource(0, stall_sec=0.3, reconnect_sec=0.01)
    read_until(src, lambda r: r is not None and r is not NO_NEW_FRAME)
    t0 = time.time()
    r, seen = read_until(src, lambda r: r is None)
    assert time.time() - t0 >= 0.25 and NO_NEW_FRAME in seen  # ก่อนครบ stall = NO_NEW_FRAME
    assert "camera stalled" in caplog.text
    r, _ = read_until(src, lambda r: r is not None and r is not NO_NEW_FRAME)
    assert int(r[0, 0, 0]) == 40 and cam.opened == 2
    src.release()


def test_disconnect_returns_none_then_recovers(camera):
    cam = camera([10, "fail"], [50, "block"], frame_delay=0.2)
    src = FrameSource(0, stall_sec=5, reconnect_sec=0.05)
    read_until(src, lambda r: r is not None and r is not NO_NEW_FRAME)
    read_until(src, lambda r: r is None)
    r, _ = read_until(src, lambda r: r is not None and r is not NO_NEW_FRAME)
    assert int(r[0, 0, 0]) == 50 and cam.opened == 2
    src.release()


def test_video_file_paced_to_real_time(camera):
    camera(list(range(1, 40)) + ["block"], fps=30.0)
    src = FrameSource("clip.mp4", stall_sec=5)
    t0 = time.time()
    n = 0
    while n < 15:
        r = src.read()
        if r is not None and r is not NO_NEW_FRAME:
            n += 1
    assert time.time() - t0 >= 14 / 30 - 0.05  # ไม่เร็วกว่า FPS ของคลิป
    src.release()


def test_read_does_not_block_when_camera_hangs(camera):
    camera(["block"])
    src = FrameSource(0, stall_sec=10)
    t0 = time.time()
    assert src.read() is NO_NEW_FRAME
    assert time.time() - t0 < fs.READ_WAIT_SEC + 0.1
    src.release()


# ── main loop ระหว่างไม่มีเฟรมใหม่ / กล้องค้าง ─────────────────────────────────

def test_commands_processed_without_new_frames(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    quiet = app.bg.quiet_frames
    run_frames(app, env, NO_NEW_FRAME, 20)  # กล้องยังไม่ส่งเฟรมใหม่
    assert app.bg.quiet_frames == quiet  # ไม่นับเฟรมเดิมซ้ำเป็นเฟรมนิ่ง
    assert app.cm.state == cyc.ACTIVE and app.camera_ok is True
    ctl.push("STOP")
    run_frames(app, env, NO_NEW_FRAME, 1)
    assert app.cm.state == cyc.WAIT_START


def test_stall_blocks_cycle_and_stop_still_closes(make_app, env):
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, empty_frame(), 3)
    cid = app.cm.cycle_id
    run_frames(app, env, None, 1)  # FrameSource รายงานกล้องค้าง/หลุด
    assert app.cm.state == cyc.BLOCKED_WAIT_STOP
    ctl.push("STOP")
    run_frames(app, env, None, 1)
    assert app.cm.state == cyc.WAIT_START
    row = app.store.conn.execute("SELECT outcome FROM cycles WHERE cycle_id=?", (cid,)).fetchone()
    assert row[0] == "UNCERTAIN"
