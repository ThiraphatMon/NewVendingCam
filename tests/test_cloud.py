"""tests ฝั่ง cloud (CLOUD_ENABLED=1) กับ stub HTTP server ในเครื่อง (conftest.cloud_stub) — ห้ามยิง server จริง"""

import json
import threading
import time

import pytest

import api.cloud
import config
from api.cloud import CloudServices
from conftest import FPS, empty_frame, run_frames

LOCAL_ROI = {"frame": {"width": 640, "height": 480}, "roi_type": "rect",
             "rect": {"x": 100, "y": 100, "w": 400, "h": 300}}
ALL_OFF = {"register": False, "roi_sync": False, "realtime": False, "events": False, "anomaly": False}


def features(**on):
    return {**ALL_OFF, **on}


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

    def _make(feats):
        svc = CloudServices("VENDING_01", feats, roi_path=str(roi_path))
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
    assert "register=เปิด" in s and "ROI sync=เปิด" in s and "ภาพสด=เปิด (ทุก 300s)" in s
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
