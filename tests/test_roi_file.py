"""S15: data/roi_config.json ไม่อยู่ใน git → clone ใหม่ต้องเริ่มได้ (copy จาก example / default) และ ROI จากเว็บเขียนลงไฟล์ได้"""

import json
import os
import types

import api.client
import core.roi
from core.roi import ROIManager

EXAMPLE = {"frame": {"width": 640, "height": 480}, "roi_type": "quad",
           "points": [{"x": 104, "y": 200}, {"x": 414, "y": 192}, {"x": 409, "y": 314}, {"x": 109, "y": 299}]}
WEB_ROI = {"frame": {"width": 640, "height": 480}, "roi_type": "rect", "rect": {"x": 10, "y": 20, "w": 300, "h": 200}}


def test_repo_ships_example_roi():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "data", "roi_config.example.json"), encoding="utf-8") as f:
        assert "roi_type" in json.load(f)


def test_missing_roi_copied_from_example(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "roi_config.example.json").write_text(json.dumps(EXAMPLE))
    path = tmp_path / "data" / "roi_config.json"
    roi = ROIManager(640, 480, config_path=str(path))
    assert json.loads(path.read_text()) == EXAMPLE
    assert roi.roi_type == "quad" and len(roi.points) == 4


def test_missing_roi_and_example_creates_default(tmp_path):
    path = tmp_path / "data" / "roi_config.json"  # ไม่มีแม้แต่โฟลเดอร์ data/
    roi = ROIManager(640, 480, config_path=str(path))
    assert path.exists() and roi.roi_type == "rect"
    assert roi.rect == {"x": 320, "y": 0, "w": 320, "h": 480}


def test_broken_example_falls_back_to_default(tmp_path):
    (tmp_path / "roi_config.example.json").write_text("{broken")
    roi = ROIManager(640, 480, config_path=str(tmp_path / "roi_config.json"))
    assert roi.roi_type == "rect"


def test_web_roi_written_to_created_file_and_reloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(core.roi, "ROI_CHECK_INTERVAL", 0.0)
    path = tmp_path / "data" / "roi_config.json"
    roi = ROIManager(640, 480, config_path=str(path))
    resp = types.SimpleNamespace(status_code=200, json=lambda: WEB_ROI)
    monkeypatch.setattr(api.client.requests, "get", lambda *a, **k: resp)
    api.client.fetch_remote_roi("VENDING_01", str(path))
    assert json.loads(path.read_text()) == WEB_ROI
    t = roi.last_mtime + 10
    os.utime(path, (t, t))
    assert roi.reload_if_changed() and roi.rect == WEB_ROI["rect"]
