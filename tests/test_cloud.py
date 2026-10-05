"""tests ฝั่ง cloud (CLOUD_ENABLED=1) กับ stub HTTP server ในเครื่อง (conftest.cloud_stub) — ห้ามยิง server จริง"""

import json
import os
import re
import threading
import time
from urllib.parse import parse_qsl

import cv2
import numpy as np
import pytest

import api.client
import api.cloud
import config
from api.cloud import CloudServices
from conftest import (
    FPS, FRAMES_TO_CONFIRM, FakeController, empty_frame, frame_with, multipart_fields, run_frames, settle,
)

LOCAL_ROI = {"frame": {"width": 640, "height": 480}, "roi_type": "rect",
             "rect": {"x": 100, "y": 100, "w": 400, "h": 300}}
ITEM = frame_with((300, 250))
ALL_OFF = {"register": False, "roi_sync": False, "realtime": False, "events": False, "anomaly": False}


def features(**on):
    return {**ALL_OFF, **on}


def _wait(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def cloud_cfg(monkeypatch):
    """ตั้งค่า cloud ใน config (cloud_features อ่านค่าตอนเรียก)"""

    def _set(**kv):
        for k, v in kv.items():
            monkeypatch.setattr(config, k, v)

    _set(CLOUD_ENABLED=True, CLOUD_API_URL="http://127.0.0.1:1/api/events", CLOUD_ROI_SYNC=True,
         CLOUD_SEND_EVENTS=True, CLOUD_SEND_ANOMALY=False, SEND_INTERVAL=60.0)
    return _set


@pytest.fixture
def services(monkeypatch, tmp_path):
    """สร้าง CloudServices แล้ว stop ให้ตอนจบ test (ไม่มี thread ค้างข้าม test)"""
    monkeypatch.setattr(api.cloud, "ROI_POLL_INTERVAL", 0.05)
    made = []

    roi_path = tmp_path / "roi.json"
    roi_path.write_text(json.dumps(LOCAL_ROI))

    def _make(feats, db_path=None):
        svc = CloudServices("VENDING_01", feats, roi_path=str(roi_path),
                            db_path=db_path or str(tmp_path / "state.sqlite3"))
        made.append(svc)
        return svc

    yield _make
    for svc in made:
        svc.stop()


# ── สวิตช์ ───────────────────────────────────────────────────────────────────
def test_master_switch_off_disables_everything(cloud_cfg):
    cloud_cfg(CLOUD_ENABLED=False)
    assert not any(config.cloud_features().values())
    assert "ปิดทั้งหมด" in config.cloud_summary()


def test_enabled_without_url_is_off(cloud_cfg):
    cloud_cfg(CLOUD_API_URL="")
    assert not any(config.cloud_features().values())
    assert "CLOUD_API_URL" in config.cloud_summary()


def test_feature_switches_map_to_features(cloud_cfg):
    f = config.cloud_features()
    assert f == {"register": True, "roi_sync": True, "realtime": True, "events": True, "anomaly": False}
    cloud_cfg(CLOUD_ROI_SYNC=False, SEND_INTERVAL=0.0, CLOUD_SEND_EVENTS=False, CLOUD_SEND_ANOMALY=True)
    f = config.cloud_features()
    assert f == {"register": True, "roi_sync": False, "realtime": False, "events": False, "anomaly": True}


def test_summary_lists_each_feature(cloud_cfg):
    cloud_cfg(CLOUD_SEND_EVENTS=False, SEND_INTERVAL=300.0)
    s = config.cloud_summary()
    assert "register=เปิด" in s and "ROI sync=เปิด" in s and "ภาพสด=เปิด (ทุก 300s q80)" in s
    assert "ITEM_LANDED=ปิด" in s and "anomaly=ปิด" in s


# ── thread / HTTP ตามสวิตช์ ──────────────────────────────────────────────────
def test_all_off_starts_no_thread_and_no_http(cloud_stub, services):
    before = threading.active_count()
    svc = services(ALL_OFF).start()
    time.sleep(0.2)
    assert svc.threads == [] and threading.active_count() == before
    assert cloud_stub.requests == []
    assert not svc.realtime_due(0.0)


def test_register_only_no_roi_requests(cloud_stub, services):
    svc = services(features(register=True)).start()
    assert cloud_stub.wait_for(lambda r: r.path == "/api/events")
    time.sleep(0.3)
    assert [t.name for t in svc.threads] == ["cloud-register"]
    assert all("/roi" not in p for p in cloud_stub.paths())


def test_roi_sync_pushes_then_polls(cloud_stub, services):
    svc = services(features(roi_sync=True)).start()
    put = cloud_stub.wait_for(lambda r: r.method == "PUT" and r.path == "/api/machines/VENDING_01/roi")
    assert put and json.loads(put.body) == LOCAL_ROI
    time.sleep(0.3)
    assert len(cloud_stub.paths("GET")) >= 3  # GET ตอน push + polling ทุก 0.05s
    assert all(r.headers.get("X-API-Key") == "test-key" for r in cloud_stub.requests)
    svc.stop()
    n = len(cloud_stub.requests)
    time.sleep(0.2)
    assert len(cloud_stub.requests) == n  # stop แล้วไม่ยิงต่อ
    assert not any(t.is_alive() for t in svc.threads)


def test_app_without_cloud_sends_no_frames(make_app, env, cloud_stub):
    app = make_app(cloud=None)
    run_frames(app, env, empty_frame(), int(FPS))
    assert cloud_stub.requests == []


def test_realtime_off_app_never_submits(make_app, env, cloud_stub, services):
    svc = services(features(register=False)).start()
    app = make_app(cloud=svc)
    run_frames(app, env, empty_frame(), int(FPS))
    time.sleep(0.2)
    assert cloud_stub.requests == [] and svc.last_send_time is None


def test_realtime_sends_first_frame_then_every_interval(make_app, env, cloud_stub, services, monkeypatch):
    monkeypatch.setattr(api.cloud, "SEND_INTERVAL", 1.0)
    svc = services(features(realtime=True)).start()
    app = make_app(cloud=svc)
    run_frames(app, env, empty_frame(), int(2.5 * FPS))  # 2.5 วิ → ภาพที่ 0, 1, 2 วิ
    assert cloud_stub.wait_for(lambda r: r.path.endswith("/realtime-image"))
    time.sleep(0.3)
    sent = [p for p in cloud_stub.paths("POST") if p == "/api/machines/VENDING_01/realtime-image"]
    assert 1 <= len(sent) <= 3  # sender ถือเฉพาะเฟรมล่าสุด (ส่งไม่ทันถูกทับ ไม่ต่อคิว)


# ── ภาพสด: คุณภาพ JPEG เฉพาะภาพสด ขนาดคง 640x480 ─────────────────────────────
def _textured_frame():
    rng = np.random.default_rng(0)
    f = np.full((480, 640, 3), 90, np.uint8)
    f[100:400, 100:500] = rng.integers(0, 255, (300, 400, 3), dtype=np.uint8)
    return f


def test_realtime_frame_full_size_at_realtime_quality(cloud_stub, monkeypatch):
    monkeypatch.setattr(api.client, "REALTIME_JPEG_QUALITY", 80)
    frame = _textured_frame()
    before = frame.copy()
    assert api.client.send_frame("VENDING_01", frame) is True
    req = cloud_stub.wait_for(lambda r: r.path == "/api/machines/VENDING_01/realtime-image")
    _, files = multipart_fields(req)
    jpg = files["image"]
    assert cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR).shape == (480, 640, 3)  # ไม่ย่อ
    assert len(jpg) == len(cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])[1])
    assert len(jpg) < len(cv2.imencode(".jpg", frame)[1])  # เล็กกว่า q95 เดิม
    assert np.array_equal(frame, before)


def test_realtime_quality_does_not_change_evidence_image(tmp_path, monkeypatch):
    """ภาพหลักฐานยังบันทึกแบบเดิม (cv2.imwrite ค่า default) ไม่ใช้ REALTIME_JPEG_QUALITY"""
    from utils import image_saver

    monkeypatch.setattr(api.client, "REALTIME_JPEG_QUALITY", 10)
    calls = []
    real = image_saver.cv2.imwrite
    monkeypatch.setattr(image_saver.cv2, "imwrite", lambda p, img, *a: calls.append(a) or real(p, img, *a))
    path = image_saver.save_evidence(_textured_frame(), image_saver.CONFIRMED, "CONFIRMED", "c" * 32,
                                     base_dir=str(tmp_path))
    assert path and calls == [()]


# ── ITEM_LANDED ผ่าน outbox (S11) ──────────────────────────────────────────────
@pytest.fixture
def events_svc(services, env, monkeypatch):
    """CloudServices ที่เปิดเฉพาะ event (worker อ่าน DB เดียวกับ App) + backoff เร็วสำหรับ test"""
    monkeypatch.setattr(api.cloud, "BACKOFF_BASE_SEC", 0.05)
    monkeypatch.setattr(api.cloud, "RETRY_INTERVAL", 0.2)

    env.open_store().close()  # main เปิด StateStore (สร้าง DB) ก่อนเริ่ม cloud เสมอ

    def _make(on=True):
        return services(features(events=on), db_path=env.db_path)

    return _make


def _confirm_one(make_app, env, cloud):
    ctl = FakeController()
    app = make_app(ctl, cloud=cloud)
    settle(app, env)
    ctl.push("START")
    run_frames(app, env, ITEM, FRAMES_TO_CONFIRM)
    assert len(ctl.s0) == 1
    return app, ctl


def _event_posts(stub):
    return [r for r in stub.requests if r.method == "POST" and r.path == "/api/events"]


def test_item_landed_sent_after_s0_with_legacy_fields(make_app, env, cloud_stub, events_svc):
    svc = events_svc().start()
    app, ctl = _confirm_one(make_app, env, svc)
    req = cloud_stub.wait_for(lambda r: r.path == "/api/events")
    assert req is not None
    fields, files = multipart_fields(req)
    cycle = ctl.s0[0]
    assert set(fields) == {"machine_id", "event", "transaction_id", "item_no", "obj_id", "land_time", "order_id"}
    assert fields["machine_id"] == "VENDING_01" and fields["event"] == "ITEM_LANDED" and fields["order_id"] == ""
    # FakeClock เริ่ม 13:45:12 ไทย 05/10/2026 → ยืนยันหลัง settle 1s + ~2s
    assert re.fullmatch(rf"TXN-20261005-1345\d\d-{cycle[:8]}", fields["transaction_id"])
    assert re.fullmatch(r"13:45:\d\d", fields["land_time"])
    assert fields["item_no"] == "1" and fields["obj_id"].isdigit()
    conf_path = app.store.confirmations_for_date("2026-10-05")[0].evidence_path
    with open(conf_path, "rb") as f:
        assert files["landed_image"] == f.read()
    assert os.path.exists(conf_path)  # ห้ามลบภาพในเครื่องหลังส่งสำเร็จ
    _wait(lambda: app.store.cloud_events()[0]["state"] == "SENT")
    row = app.store.cloud_events()[0]
    assert row["event_id"] == f"ITEM_LANDED:{cycle}" and row["cycle_id"] == cycle and row["attempts"] == 1
    assert row["image_path"] == conf_path and row["last_error"] is None
    assert len(_event_posts(cloud_stub)) == 1


def test_outbox_retries_with_backoff_then_sends(make_app, env, cloud_stub, events_svc):
    cloud_stub.fail_next = [500, 503]
    svc = events_svc().start()
    app, _ = _confirm_one(make_app, env, svc)
    assert _wait(lambda: app.store.cloud_events()[0]["state"] == "SENT", timeout=5)
    row = app.store.cloud_events()[0]
    assert row["attempts"] == 3 and len(_event_posts(cloud_stub)) == 3


def test_outbox_failure_records_error_and_backoff(make_app, env, cloud_stub, events_svc, monkeypatch):
    monkeypatch.setattr(api.cloud, "BACKOFF_BASE_SEC", 30.0)
    monkeypatch.setattr(api.cloud, "RETRY_INTERVAL", 60)
    cloud_stub.fail_next = [500]
    svc = events_svc().start()
    app, _ = _confirm_one(make_app, env, svc)
    assert _wait(lambda: app.store.cloud_events()[0]["attempts"] == 1)
    row = app.store.cloud_events()[0]
    assert row["state"] == "PENDING" and row["last_error"].startswith("HTTP 500")
    assert 25 < row["next_attempt_at"] - time.time() <= 30  # รอ backoff ไม่ยิงซ้ำทันที
    time.sleep(0.3)
    assert len(_event_posts(cloud_stub)) == 1


def test_backoff_delay_doubles_up_to_retry_interval(monkeypatch):
    monkeypatch.setattr(api.cloud, "BACKOFF_BASE_SEC", 5.0)
    monkeypatch.setattr(api.cloud, "RETRY_INTERVAL", 60)
    assert [api.cloud.backoff_delay(n) for n in range(1, 7)] == [5, 10, 20, 40, 60, 60]


def test_events_off_no_outbox_and_no_http(make_app, env, cloud_stub, events_svc):
    svc = events_svc(on=False).start()
    app, _ = _confirm_one(make_app, env, svc)
    time.sleep(0.2)
    assert app.store.cloud_events() == [] and cloud_stub.requests == []
    app2, _ = _confirm_one(make_app, env, None)  # cloud ปิดทั้งหมด
    assert app2.store.cloud_events() == []


def test_pending_survives_restart_and_stops_while_events_off(env, cloud_stub, events_svc):
    store = env.open_store()
    store.enqueue_cloud_event("ITEM_LANDED:abc", "abc", "ITEM_LANDED", {"event": "ITEM_LANDED"}, None)
    store.close()
    # ปิด CLOUD_SEND_EVENTS ภายหลัง → ไม่ส่ง ไม่ลบ
    events_svc(on=False).start()
    time.sleep(0.3)
    store = env.open_store()
    assert cloud_stub.requests == [] and store.cloud_events()[0]["state"] == "PENDING"
    # เปิดใหม่ (เหมือน restart) → ส่งรายการที่ค้าง
    events_svc().start()
    assert _wait(lambda: store.cloud_events()[0]["state"] == "SENT")
    assert store.count_pending_cloud_events() == 0


def test_cloud_hang_does_not_block_s0_or_main_thread(make_app, env, cloud_stub, events_svc, monkeypatch):
    import requests

    cloud_stub.hang = True
    threads = []
    real_post = requests.post
    monkeypatch.setattr(requests, "post", lambda *a, **k: threads.append(threading.current_thread().name)
                        or real_post(*a, **k))
    svc = events_svc().start()
    t0 = time.perf_counter()
    app, ctl = _confirm_one(make_app, env, svc)
    ctl.push("STOP")
    run_frames(app, env, ITEM, 3)
    assert app.store.get_cycle(ctl.s0[0])["outcome"] == "CONFIRMED"
    assert time.perf_counter() - t0 < 5
    assert cloud_stub.wait_for(lambda r: r.path == "/api/events")
    assert threads and "MainThread" not in threads


def test_outbox_table_added_to_existing_db_without_version_bump(env):
    store = env.open_store()
    store.conn.execute("DROP TABLE cloud_outbox")  # เหมือน DB ที่สร้างจากโปรแกรมรุ่นก่อน
    store.close()
    store = env.open_store()
    assert store.cloud_events() == []
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_cleanup_keeps_images_pending_in_outbox(env):
    from utils.disk_cleanup import _cleanup_once
    from utils.state_store import pending_image_paths

    d = os.path.join(env.evidence_dir, "confirmed")
    os.makedirs(d)
    paths = [os.path.join(d, n) for n in ("pending.jpg", "sent.jpg", "plain.jpg")]
    for p in paths:
        open(p, "wb").close()
        os.utime(p, (1, 1))  # เก่ามาก
    store = env.open_store()
    store.enqueue_cloud_event("e1", "c1", "ITEM_LANDED", {}, paths[0])
    store.enqueue_cloud_event("e2", "c2", "ITEM_LANDED", {}, paths[1])
    store.conn.execute("UPDATE cloud_outbox SET state='SENT' WHERE event_id='e2'")
    assert _cleanup_once(env.evidence_dir, protected=pending_image_paths(env.db_path)) == 2
    assert [os.path.exists(p) for p in paths] == [True, False, False]


def test_pending_image_paths_without_db_or_table(tmp_path):
    from utils.state_store import pending_image_paths
    import sqlite3

    assert pending_image_paths(str(tmp_path / "none.sqlite3")) == set()
    db = tmp_path / "old.sqlite3"
    sqlite3.connect(db).close()
    assert pending_image_paths(str(db)) == set()


def test_outbox_worker_does_not_create_db(services, tmp_path):
    path = tmp_path / "missing" / "state.sqlite3"
    services(features(events=True), db_path=str(path)).start()
    time.sleep(0.2)
    assert not path.exists()


# ── register / push ROI: ลองใหม่แบบ backoff จนสำเร็จ (S13) ─────────────────────
@pytest.fixture
def fast_backoff(monkeypatch):
    monkeypatch.setattr(api.cloud, "BACKOFF_BASE_SEC", 0.05)
    monkeypatch.setattr(api.cloud, "RETRY_INTERVAL", 0.2)


def test_register_retries_until_success(cloud_stub, services, fast_backoff):
    cloud_stub.fail_next = [500, 502]
    svc = services(features(register=True)).start()
    assert _wait(lambda: not svc.threads[0].is_alive(), timeout=3)  # สำเร็จแล้วจบ thread
    posts = [r for r in cloud_stub.requests if r.path == "/api/events"]
    assert len(posts) == 3 and dict(parse_qsl(posts[-1].body.decode()))["event"] == "SYSTEM_ONLINE"


def test_register_while_server_failing_backs_off_not_busy_loop(cloud_stub, services, fast_backoff):
    cloud_stub.fail_next = [503] * 1000  # เว็บยังไม่พร้อม
    svc = services(features(register=True)).start()
    time.sleep(0.6)
    with cloud_stub.lock:
        times = [r for r in cloud_stub.requests]
    assert 2 <= len(times) <= 8  # backoff 0.05, 0.1, 0.2, 0.2, ... ไม่ใช่ busy-loop
    # เว็บกลับมา → สำเร็จแล้ว thread จบ ไม่ยิงซ้ำอีก
    cloud_stub.fail_next = []
    assert _wait(lambda: not svc.threads[0].is_alive(), timeout=3)
    n = len(cloud_stub.requests)
    time.sleep(0.3)
    assert len(cloud_stub.requests) == n


def test_push_roi_retries_and_does_not_overwrite_when_server_errors(cloud_stub, services, fast_backoff):
    """ถาม ROI จากเว็บไม่สำเร็จ → ห้าม PUT ทับ (เว็บอาจมี ROI อยู่แล้ว) → ลองใหม่จนถามได้ แล้วค่อย push"""
    cloud_stub.fail_next = [500, 500]
    svc = services(features())  # ไม่เริ่ม polling (ไม่ให้ GET ของ polling ปน)
    ok = svc._retry_until_ok(lambda: api.client.push_default_roi("VENDING_01", svc.roi_path), "push ROI")
    assert ok
    assert [r.method for r in cloud_stub.requests] == ["GET", "GET", "GET", "PUT"]
    assert json.loads(cloud_stub.requests[-1].body) == LOCAL_ROI


def test_push_roi_done_when_server_has_roi(cloud_stub, services, fast_backoff):
    cloud_stub.roi = {"frame": {"width": 640, "height": 480}, "roi_type": "rect",
                      "rect": {"x": 1, "y": 1, "w": 10, "h": 10}}
    svc = services(features(roi_sync=True)).start()
    push_thread = [t for t in svc.threads if t.name == "cloud-roi-push"][0]
    assert _wait(lambda: not push_thread.is_alive())
    assert "PUT" not in [r.method for r in cloud_stub.requests]


def test_stop_interrupts_backoff_wait(services, monkeypatch, cloud_stub):
    monkeypatch.setattr(api.cloud, "BACKOFF_BASE_SEC", 30.0)
    monkeypatch.setattr(api.cloud, "RETRY_INTERVAL", 60)
    cloud_stub.fail_next = [500]
    svc = services(features(register=True)).start()
    assert cloud_stub.wait_for(lambda r: r.path == "/api/events")
    t0 = time.time()
    svc.stop()
    assert time.time() - t0 < 1.0 and not svc.threads[0].is_alive()
