"""S20: ทุกข้อความที่โปรแกรม log/print ตอนรันต้องเป็น ASCII ล้วน (ไม่มีอีโมจิ / อักษรไทย / ×)
คอมเมนต์และ docstring ยังเป็นภาษาไทยได้ (ไม่ถูกพิมพ์ตอนรัน)"""

import ast
import logging
import os
import subprocess

from conftest import FRAMES_TO_CONFIRM, FakeController, empty_frame, frame_with, run_frames, settle

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def runtime_modules():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=REPO, capture_output=True, text=True).stdout.split()
    return [p for p in out if not p.startswith(("tests/", "legacy_reference/"))]


def non_ascii_literals(path):
    """string literal ที่มีอักขระ > 0x7F (ไม่นับ docstring)"""
    src = open(os.path.join(REPO, path), encoding="utf-8").read()
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return [
        f"{path}:{n.lineno}: {n.value[:60]!r}"
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
        and any(ord(c) > 0x7F for c in n.value)
    ]


def test_no_non_ascii_string_literals_in_runtime_code():
    bad = [x for p in runtime_modules() for x in non_ascii_literals(p)]
    assert bad == [], "\n".join(bad)


def test_all_logs_of_a_full_cycle_are_ascii(make_app, env, caplog):
    caplog.set_level(logging.DEBUG, logger="vending")
    ctl = FakeController()
    app = make_app(ctl)
    settle(app, env)
    run_frames(app, env, frame_with((200, 180)), FRAMES_TO_CONFIRM)  # OUTSIDE_CYCLE
    run_frames(app, env, empty_frame(), 60)
    ctl.push("START")
    ctl.push("START")  # duplicate START
    run_frames(app, env, frame_with((300, 250)), FRAMES_TO_CONFIRM)
    run_frames(app, env, frame_with((300, 250), (420, 330)), FRAMES_TO_CONFIRM)  # EXTRA_AFTER_CONFIRM
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 5)
    ctl.push("START")
    run_frames(app, env, None, 3)  # camera disconnected during cycle
    ctl.push("STOP")
    run_frames(app, env, empty_frame(), 3)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("item confirmed" in m for m in msgs) and any("cycle closed" in m for m in msgs)
    bad = [m for m in msgs if not m.isascii()]
    assert bad == []
