"""
tests/integration/redis_e2e.py — integration test ระดับ 3: main.py จริง + Redis จริง (Docker) + คลิปวิดีโอ

ไม่ใช่ pytest test (pytest ปกติไม่รัน) — รันเอง:
    .venv\\Scripts\\python.exe tests\\integration\\redis_e2e.py --clip C:\\path\\big1_pickup_cutted.mp4
    .venv\\Scripts\\python.exe tests\\integration\\redis_e2e.py --clip ... --scenarios 1,3,7
    .venv\\Scripts\\python.exe tests\\integration\\redis_e2e.py --clip ... --send-s0 0   (เฉพาะโหมดเก็บข้อมูล)

โหมด SEND_S0 (--send-s0, ค่าเริ่ม "1,0" = รันทุกข้อทั้ง 2 โหมด):
  1 = ส่ง S0 จริง: ตรวจเหมือนเดิม (นับ S0 จาก list CAMERA)
  0 = โหมดเก็บข้อมูล: "S0" ในการตรวจนับจากแถว NOT_SENT ใน DB (= S0 ที่จะได้ส่ง) และวัด START→confirm
      จาก confirmed_at_utc แทน START→S0 + ทุกข้อต้องมี list CAMERA ยาว 0 และ MONITOR ไม่เห็นคำสั่งที่แตะ CAMERA
      + outcome ของทุกรอบใน DB ต้องเหมือนโหมด 1 (เมื่อรันทั้ง 2 โหมด)

ความปลอดภัย:
  - ใช้ Redis ใน container ทดสอบ vendingcam-redis-test พอร์ต 6380 เท่านั้น (สร้างเอง ลบเองตอนจบ)
    พอร์ตอื่นปฏิเสธ — ห้ามต่อ Redis ของเครื่องจริง / ของโปรเจกต์อื่น
  - main.py รันด้วย cwd = โฟลเดอร์ชั่วคราวใน .e2e_tmp/ → DB / evidence_images / logs ไม่ปนกับของจริง
  - docker: ใช้ `docker` ถ้ามีใน PATH ไม่งั้นใช้ `wsl -d Ubuntu -- docker` (ตั้งเองได้ด้วย E2E_DOCKER)

สมมติฐานของคลิป big1_pickup_cutted.mp4 (13 วินาที วนซ้ำเมื่อจบ):
  0–2s ถาดว่าง | 2s ของตก | 3s นิ่ง | ~7s เปิด slat หยิบของออก

[S22] ข้อ 9, 10 ใช้คลิปของตัวเอง (อยู่โฟลเดอร์เดียวกับ --clip หรือ --clip-dir) + ROI ใน fixtures/roi_shadow_clips.json
  person_shadow.mp4       (~24.2s) คนยืนหน้าตู้ มีแต่เงา/แสง ไม่มีของ
  small1pick_big1pick.mp4 (~38.1s) ขนมตก ~10.7s ถึงพื้น ~11.0s → ฝาเปิด 14.9–16.7s หยิบ
                                   → ขวดน้ำใสตก ~26.4s ถึงพื้น ~26.9s → ฝาเปิด 29.2–30.2s หยิบ → ว่าง 32.2s
โหมดตัวกรองแสง/เงา (--shadow, ค่าเริ่ม "texture"): ส่ง SHADOW_FILTER ให้ main.py ทุกข้อ ("texture,off" = รันทั้งสองโหมด)
  ข้อ 9 ที่ off: คาดว่ายืนยันผิด → รายงานอย่างเดียว ไม่นับ fail
  ข้อ 9 ที่ texture: ผ่านเมื่อไม่มีการยืนยัน — ถ้ายังมี ผ่านเมื่อ "ดีกว่า off" (ยืนยันน้อยกว่า หรือเท่ากันแต่ภาพ
    EXTRA_AFTER_CONFIRM น้อยกว่า) ในโหมด SEND_S0 เดียวกัน (ผู้ใช้ตัดสินใน S22) — ต้องรัน --shadow texture,off
  small1_big1_cutted.mp4  (~47s)   ขนมห่อม่วงตก ~4.1s → ขวดน้ำตกข้างขนม ~20s → ดันฝาหยิบขวด 32.8–34.8s (ขนมยังอยู่)
                                   → ดันฝาหยิบขนม 38.9s → ว่าง 41s (ข้อ 11)
เวลาคลิปนับจากบรรทัด FIRST_FRAME ใน logs/vending.log (FrameSource log ทุกครั้งที่เปิดคลิปใหม่)
"""

import argparse
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime

import redis

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYTHON = sys.executable
CONTAINER = "vendingcam-redis-test"
PORT = 6380
IMAGE = "redis:7-alpine"
# โฟลเดอร์ชั่วคราวอยู่ในโปรเจค (.e2e_tmp/ — อยู่ใน .gitignore) ไม่ใช้ Temp ของ Windows
TMP_BASE = os.path.join(REPO, ".e2e_tmp")
FIRST_FRAME_RE = re.compile(r"FIRST_FRAME t=(\d+\.\d+)")

# โหมดของรอบที่กำลังรัน (main() ตั้ง) — s0s / wait_s0 อ่านจากที่นี่
MODE = {"send_s0": True, "wd": None, "hold": None, "shadow": "texture"}
TIMING_RE = re.compile(
    r"START->motion (?P<motion>[\d.]+)s, START->item seen (?P<seen>[\d.]+)s, seen->still (?P<still>[\d.]+)s "
    r"\((?P<frames>\d+) frames, LANDING_STABLE_FRAMES=\d+, still resets (?P<resets>\d+)\), "
    r"still->hold done (?P<hold>[\d.]+)s .*?S3 (?P<s3>\d+)ms, save (?P<save>\d+)ms, "
    r"START->confirm (?P<total>[\d.]+)s t0=(?P<t0>[\d.]+)"
)


def timing_rows(m):
    """บรรทัด timing: ของทุกการยืนยัน → dict เวลาเป็นวินาทีของคลิป (นับจาก FIRST_FRAME ของรอบคลิปนั้น)"""
    out = []
    for line in m.grep("timing:"):
        g = TIMING_RE.search(line)
        if not g:
            continue
        t0 = float(g["t0"])
        ff = max([f for f in m.first_frames if f <= t0], default=None)
        if ff is None:
            continue
        start = t0 - ff
        seen = start + float(g["seen"])
        still = seen + float(g["still"])
        hold_done = still + float(g["hold"])
        out.append({
            "start": start, "motion": start + float(g["motion"]), "seen": seen, "still": still,
            "hold_done": hold_done, "s3_ms": int(g["s3"]), "save_ms": int(g["save"]),
            "frames": int(g["frames"]), "resets": int(g["resets"]), "total": float(g["total"]),
        })
    return out


class CameraMonitor:
    """MONITOR ของ Redis ทดสอบ: จดทุกคำสั่งที่แตะ key CAMERA (ต่อใหม่เองเมื่อ Redis ดับ เช่นข้อ 4)
    ไม่นับคำสั่งอ่าน/ล้างของตัวทดสอบเอง (LLEN / DEL / LRANGE)"""

    OWN = ("LLEN", "DEL", "LRANGE")

    def __init__(self):
        self.seen = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                with test_redis().monitor() as mon:
                    for ev in mon.listen():
                        if self._stop.is_set():
                            return
                        parts = ev.get("command", "").split()
                        if parts and parts[0].upper() not in self.OWN and "CAMERA" in parts[1:]:
                            self.seen.append(ev["command"])
            except Exception:
                time.sleep(0.2)

    def take(self):
        out, self.seen = self.seen, []
        return out

    def stop(self):
        self._stop.set()


# ── docker ───────────────────────────────────────────────────────────────────
def docker_cmd():
    if os.environ.get("E2E_DOCKER"):
        return shlex.split(os.environ["E2E_DOCKER"])
    if shutil.which("docker"):
        return ["docker"]
    if shutil.which("wsl"):
        return ["wsl", "-d", "Ubuntu", "--", "docker"]
    raise SystemExit("❌ ไม่พบ docker (และไม่มี WSL) — หยุด ไม่ต่อ Redis ตัวอื่น")


def docker(*args, check=True):
    r = subprocess.run(docker_cmd() + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} ล้มเหลว: {r.stderr.strip()}")
    return r.stdout.strip()


_keepalive = None


def _wsl_keepalive(on):
    """docker ผ่าน WSL: WSL รุ่นใหม่ (2.7) ปิด distro ที่ไม่มี wsl.exe ค้าง ~15s → port 6380 จาก Windows ต่อใหม่ไม่ได้
    (connection เดิมยังอยู่ แต่สถานการณ์ถัดไปต่อไม่ติด) → ค้าง `wsl ... sleep infinity` ไว้ตลอดการทดสอบ"""
    global _keepalive
    if on and _keepalive is None and docker_cmd()[0] == "wsl":
        distro = docker_cmd()[:-2]  # ["wsl", "-d", "Ubuntu"]
        # stdin=DEVNULL สำคัญ: wsl.exe อ่าน stdin ค้าง (blocking read) — ถ้าใช้ stdin ร่วมกับ main.py
        # Windows จะ serialize I/O บน file object เดียวกัน → main.py ค้างตั้งแต่ init stdio (ไม่มี output เลย)
        _keepalive = subprocess.Popen(distro + ["--", "sleep", "infinity"], stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif not on and _keepalive is not None:
        _keepalive.kill()
        _keepalive = None


def redis_up():
    _wsl_keepalive(True)
    docker("rm", "-f", CONTAINER, check=False)
    docker("run", "-d", "--name", CONTAINER, "-p", f"{PORT}:6379", IMAGE)
    r = test_redis()
    end = time.time() + 15
    while time.time() < end:
        try:
            r.ping()
            return r
        except redis.RedisError:
            time.sleep(0.2)
    raise RuntimeError("Redis ทดสอบไม่พร้อมภายใน 15s")


def redis_down():
    docker("rm", "-f", CONTAINER, check=False)
    _wsl_keepalive(False)


def test_redis():
    return redis.Redis(host="127.0.0.1", port=PORT, db=0, socket_timeout=2, socket_connect_timeout=2)


def reset_keys(r):
    """ล้างเฉพาะ key ทดสอบใน container ทดสอบ (ไม่เกี่ยวกับ Redis จริง)"""
    r.delete("CTRL", "CAMERA")


# ── main.py เป็น subprocess ──────────────────────────────────────────────────
class MainProc:
    def __init__(self, workdir, clip, extra_env=None):
        self.workdir = workdir
        self.clip = clip
        self.extra_env = extra_env or {}
        self.proc = None
        self.log_path = os.path.join(workdir, "logs", "vending.log")
        self._log_pos = 0
        self.first_frames = []  # epoch ของเฟรมแรกแต่ละรอบคลิป (ทุก process ในโฟลเดอร์นี้)
        self.lines = []

    def start(self):
        env = dict(os.environ)
        env.update({
            "HEADLESS": "1",
            "CONTROL_MODE": "redis",
            "REDIS_HOST": "127.0.0.1",
            "REDIS_PORT": str(PORT),
            "REDIS_DB": "0",
            "REDIS_PASSWORD": "",
            "CAMERA_INDEX": self.clip,
            "CLOUD_ENABLED": "0",
            "STATE_DB_PATH": "data/vending_state.sqlite3",
            "DAILY_LOG_DIR": "logs/item_drops",
            "PYTHONIOENCODING": "utf-8",
            "SEND_S0": "1" if MODE["send_s0"] else "0",
            "SHADOW_FILTER": MODE["shadow"],
        })
        if MODE["hold"] is not None:
            env["CAPTURE_HOLD_SEC"] = str(MODE["hold"])
        env.update(self.extra_env)
        self.out = open(os.path.join(self.workdir, "stdout.txt"), "ab")
        self.proc = subprocess.Popen(
            [PYTHON, os.path.join(REPO, "main.py")],
            cwd=self.workdir, env=env, stdin=subprocess.DEVNULL, stdout=self.out, stderr=subprocess.STDOUT,
        )
        self.loops_at_start = len(self.first_frames)

    def kill(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(10)
        if self.proc:
            self.out.close()

    def alive(self):
        return self.proc.poll() is None

    def poll_log(self):
        if not os.path.exists(self.log_path):
            return
        with open(self.log_path, "rb") as f:
            f.seek(self._log_pos)
            data = f.read()
        cut = data.rfind(b"\n") + 1
        self._log_pos += cut
        for raw in data[:cut].splitlines():
            line = raw.decode("utf-8", "replace")
            self.lines.append(line)
            m = FIRST_FRAME_RE.search(line)
            if m:
                self.first_frames.append(float(m.group(1)))

    def loop_index(self):
        """รอบคลิปของ process ปัจจุบัน (1 = รอบแรก)"""
        self.poll_log()
        return len(self.first_frames) - self.loops_at_start

    def clip_time(self):
        self.poll_log()
        if len(self.first_frames) <= self.loops_at_start:
            return None
        return time.time() - self.first_frames[-1]

    def wait_clip(self, t, loop=None, timeout=40):
        """รอจนเวลาคลิปของรอบ loop (ค่าเริ่ม = รอบปัจจุบัน) ถึง t วินาที"""
        end = time.time() + timeout
        while time.time() < end:
            if not self.alive():
                raise RuntimeError("main.py ตาย")
            ct = self.clip_time()
            if ct is not None and (loop is None or self.loop_index() >= loop):
                if loop is not None and self.loop_index() > loop:
                    raise RuntimeError(f"เลยรอบคลิป {loop} ไปแล้ว")
                if ct >= t:
                    return ct
            time.sleep(0.005)
        raise RuntimeError(f"รอเวลาคลิป {t}s (รอบ {loop}) ไม่ทัน")

    def grep(self, text):
        self.poll_log()
        return [l for l in self.lines if text in l]


# ── ตัวช่วยตรวจผล ────────────────────────────────────────────────────────────
def db_query(workdir, sql):
    path = os.path.join(workdir, "data", "vending_state.sqlite3")
    if not os.path.exists(path):
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def count(workdir):
    return db_query(workdir, "SELECT COUNT(*) FROM confirmations")[0][0]


def cycles(workdir):
    return db_query(workdir, "SELECT cycle_id, outcome, reason FROM cycles ORDER BY started_at_utc")


def images(workdir):
    d = os.path.join(workdir, "evidence_images", "confirmed")
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def not_sent_times(workdir):
    """โหมดเก็บข้อมูล: epoch ของการยืนยันที่ S0 เป็น NOT_SENT (= S0 ที่จะได้ส่ง) เรียงตามลำดับ"""
    rows = db_query(workdir, "SELECT c.confirmed_at_utc FROM confirmations c JOIN responses r "
                             "ON r.cycle_id = c.cycle_id WHERE r.state = 'NOT_SENT' ORDER BY c.id")
    return [datetime.fromisoformat(t).timestamp() for (t,) in rows]


def s0s(r):
    """จำนวน S0: โหมด 1 = ความยาว list CAMERA | โหมด 0 = S0 ที่จะได้ส่ง (NOT_SENT ใน DB)"""
    if MODE["send_s0"]:
        return r.llen("CAMERA")
    return len(not_sent_times(MODE["wd"]))


def push(r, cmd):
    r.lpush("CTRL", cmd)
    return time.time()


def wait_s0(r, n, timeout):
    """รอจน CAMERA มี S0 ครบ n รายการ คืนเวลาที่เห็น หรือ None
    โหมด 0: รอจน DB มีการยืนยัน (NOT_SENT) ครบ n → คืนเวลายืนยันของรายการที่ n (วัด START→confirm)"""
    end = time.time() + timeout
    while time.time() < end:
        if MODE["send_s0"]:
            if s0s(r) >= n:
                return time.time()
        else:
            times = not_sent_times(MODE["wd"])
            if len(times) >= n:
                return times[n - 1]
        time.sleep(0.01)
    return None


def anomaly_images(workdir, kind=""):
    d = os.path.join(workdir, "evidence_images", "anomaly")
    return sorted(n for n in os.listdir(d) if kind in n) if os.path.isdir(d) else []


def env_clip_times(m, names):
    """ชื่อภาพ YYYYmmdd_HHMMSS_mmm_... → เวลาคลิป (วินาที) ของรอบคลิปที่ภาพนั้นอยู่"""
    out = []
    for n in names:
        try:
            t = datetime.strptime(n[:19], "%Y%m%d_%H%M%S_%f").timestamp()
        except ValueError:
            continue
        ff = max([f for f in m.first_frames if f <= t], default=None)
        if ff is not None:
            out.append(f"{t - ff:.1f}s")
    return out


def non_ascii_lines(workdir):
    """S20: ทุกบรรทัดที่ main.py พิมพ์ (stdout/stderr + logs/vending.log) ต้องเป็น ASCII — คืนบรรทัดที่ผิด"""
    bad = []
    for rel in ("stdout.txt", os.path.join("logs", "vending.log")):
        path = os.path.join(workdir, rel)
        if os.path.exists(path):
            with open(path, "rb") as f:
                bad += [l.decode("utf-8", "replace") for l in f.read().splitlines() if any(b > 0x7F for b in l)]
    return bad


def outcomes(workdir):
    return [o for _, o, _ in cycles(workdir)]


def anomaly_kinds(workdir):
    return [k for (k,) in db_query(workdir, "SELECT kind FROM anomalies ORDER BY id")]


# ── สถานการณ์ ────────────────────────────────────────────────────────────────
class Report:
    def __init__(self):
        self.rows = []
        self.notes = []

    def check(self, sc, item, expected, actual, ok):
        self.rows.append((sc, item, expected, actual, "✅" if ok else "❌"))

    def note(self, text):
        self.notes.append(text)
        print("   ·", text)


def sc1(r, m, wd, rep):
    m.wait_clip(1.0, loop=1)
    t_start = push(r, "START")
    t_s0 = wait_s0(r, 1, timeout=8)
    lat = (t_s0 - t_start) if t_s0 else None
    rep.note(f"[1] START ที่ clip {t_start - m.first_frames[-1]:.2f}s → " + (f"S0 หลัง {lat:.2f}s" if lat else "ไม่มี S0"))
    rep.check(1, "S0 หลัง START", "1 รายการ", f"{s0s(r)}" + (f" (START→S0 {lat:.2f}s)" if lat else ""), t_s0 is not None and s0s(r) == 1)
    rep.check(1, "ยอด + ภาพหลังยืนยัน", "ยอด 1, ภาพ 1", f"ยอด {count(wd)}, ภาพ {len(images(wd))}", count(wd) == 1 and len(images(wd)) == 1)
    m.wait_clip(12.0, loop=1)
    rep.check(1, "หลังลูกค้าหยิบ (7s) ถึง 12s", "ยอด 1, S0 1", f"ยอด {count(wd)}, S0 {s0s(r)}", count(wd) == 1 and s0s(r) == 1)
    push(r, "STOP")
    time.sleep(0.5)
    rep.check(1, "STOP @12s", "ปิดรอบ CONFIRMED", ",".join(outcomes(wd)), outcomes(wd) == ["CONFIRMED"])


def sc2(r, m, wd, rep):
    m.wait_clip(1.0, loop=1)
    push(r, "START")
    m.wait_clip(1.5, loop=1)
    push(r, "STOP")
    m.wait_clip(12.0, loop=1)
    rep.check(2, "START @1.0 → STOP @1.5 แล้วของตก", "S0 0, ยอด 0, UNCONFIRMED",
              f"S0 {s0s(r)}, ยอด {count(wd)}, {','.join(outcomes(wd))}",
              s0s(r) == 0 and count(wd) == 0 and outcomes(wd) == ["UNCONFIRMED"])


def sc3(r, m, wd, rep):
    lats = []
    for loop in (1, 2):
        m.wait_clip(1.0, loop=loop)
        t = push(r, "START")
        t_s0 = wait_s0(r, loop, timeout=8)
        lats.append(t_s0 - t if t_s0 else None)
    m.wait_clip(5.0, loop=2)
    push(r, "STOP")
    time.sleep(0.5)
    lat_txt = ", ".join(f"{x:.2f}s" if x else "-" for x in lats)
    rep.note(f"[3] START→S0 รอบคลิป 1/2: {lat_txt}; outcomes={outcomes(wd)}")
    rep.check(3, "START→S0 → (คลิปวน) START→S0 → STOP", "ยอด 2, S0 2",
              f"ยอด {count(wd)}, S0 {s0s(r)} ({lat_txt})", count(wd) == 2 and s0s(r) == 2)
    rep.check(3, "outcome ของ 2 รอบ", "CONFIRMED,CONFIRMED", ",".join(outcomes(wd)),
              outcomes(wd) == ["CONFIRMED", "CONFIRMED"])


def sc4(r, m, wd, rep):
    m.wait_clip(1.0, loop=1)
    t_start = push(r, "START")
    m.wait_clip(1.3, loop=1)
    t_down = time.time()
    docker("stop", "-t", "1", CONTAINER)
    time.sleep(3)
    docker("start", CONTAINER)
    rr = test_redis()
    end = time.time() + 15
    while time.time() < end:
        try:
            rr.ping()
            break
        except redis.RedisError:
            time.sleep(0.1)
    t_up = time.time()
    rep.note(f"[4] Redis ดับที่ clip {t_down - m.first_frames[-1]:.2f}s นาน {t_up - t_down:.1f}s")
    t_s0 = wait_s0(rr, 1, timeout=12)
    alive = m.alive()
    lat = f"{t_s0 - t_up:.2f}s หลัง Redis กลับ" if t_s0 else "ไม่มี"
    rep.note(f"[4] S0: {lat}")
    m.wait_clip(9.0, loop=None, timeout=40)
    push(rr, "STOP")
    time.sleep(1.0)
    states = db_query(wd, "SELECT state, last_error FROM responses")
    rep.check(4, "docker stop ~3s ระหว่างรอบ", "ไม่ crash, S0 1 (ส่งหลัง Redis กลับ), ยอด 1",
              f"alive={alive}, S0 {s0s(rr)} ({lat}), ยอด {count(wd)}, response={states}",
              alive and m.alive() and s0s(rr) == 1 and count(wd) == 1)
    rep.check(4, "outcome", "CONFIRMED", ",".join(outcomes(wd)), outcomes(wd) == ["CONFIRMED"])
    rep.check(4, "log เชื่อม Redis คืน", "มี", f"{len(m.grep('Redis connected'))} ครั้ง",
              len(m.grep("Redis connected")) >= 2)


def sc5(r, m, wd, rep):
    # รอบคลิป 1: รอบปกติ 1 ชิ้น (ให้มียอดเดิม)
    m.wait_clip(1.0, loop=1)
    push(r, "START")
    wait_s0(r, 1, timeout=8)
    m.wait_clip(6.0, loop=1)
    push(r, "STOP")
    # รอบคลิป 2: START แล้ว kill ก่อนยืนยัน
    m.wait_clip(1.0, loop=2)
    push(r, "START")
    m.wait_clip(2.5, loop=2)
    m.kill()
    before = count(wd)
    rep.note(f"[5] kill main.py ที่ clip 2.5s (ยอดก่อน kill = {before}, S0 = {s0s(r)})")
    m.start()
    # เหมือนตัวเก่า: restart แล้วรับ START ใหม่ได้ทันที (ไม่มี RECOVERY_BLOCKED)
    m.wait_clip(1.0, loop=1)
    push(r, "START")
    t_s0 = wait_s0(r, 2, timeout=8)
    m.wait_clip(6.0, loop=1)
    push(r, "STOP")
    time.sleep(0.5)
    rep.check(5, "หลัง restart", "ยอดเดิม 1 ไม่หาย, ไม่มี S0 ของรอบเก่า, รอบค้าง INTERRUPTED",
              f"ยอดก่อน kill {before}, {','.join(outcomes(wd)[:2])}, log={bool(m.grep('INTERRUPTED'))}",
              before == 1 and outcomes(wd)[:2] == ["CONFIRMED", "INTERRUPTED"] and bool(m.grep("INTERRUPTED")))
    rep.check(5, "START แรกหลัง restart เปิดรอบได้ทันที", "S0 รวม 2, ยอด 2, รอบใหม่ CONFIRMED",
              f"S0 {s0s(r)}, ยอด {count(wd)}, {','.join(outcomes(wd))}",
              t_s0 is not None and s0s(r) == 2 and count(wd) == 2
              and outcomes(wd) == ["CONFIRMED", "INTERRUPTED", "CONFIRMED"])


def sc6(r, m, wd, rep):
    m.wait_clip(12.5, loop=1)
    rep.check(6, "ไม่ส่ง START ทั้งคลิป", "S0 0, ยอด 0, ไม่มีรอบ",
              f"S0 {s0s(r)}, ยอด {count(wd)}, รอบ {len(cycles(wd))}",
              s0s(r) == 0 and count(wd) == 0 and not cycles(wd))


def sc7(r, m, wd, rep):
    m.wait_clip(5.0, loop=1)
    t = push(r, "START")
    t_s0 = wait_s0(r, 1, timeout=7.5)
    m.wait_clip(12.5, loop=1)
    when = f"S0 ที่ clip {t_s0 - m.first_frames[-1]:.2f}s" if t_s0 else "ไม่มี S0"
    rep.note(f"[7] START @5.0 → {when}")
    rep.check(7, "START ช้า @5s ของนิ่งอยู่แล้ว + หยิบ @7s", "(อุดมคติ) S0 0",
              f"S0 {s0s(r)}, ยอด {count(wd)} ({when})", s0s(r) == 0)


def sc8(r, m, wd, rep):
    # ซื้อต่อกัน: ลูกค้าหยิบของ (@7s) นอกรอบ แล้ว START ถัดไปมาทันที — รอบ 2 ไม่มีของตกใหม่
    m.wait_clip(1.0, loop=1)
    push(r, "START")
    wait_s0(r, 1, timeout=8)
    m.wait_clip(5.0, loop=1)
    push(r, "STOP")
    m.poll_log()
    mark = len(m.lines)
    m.wait_clip(9.0, loop=1)
    push(r, "START")
    m.wait_clip(12.0, loop=1)
    push(r, "STOP")
    time.sleep(0.5)
    m.poll_log()
    keys = ("frozen", "unfrozen", "watch", "cycle opened", "cycle closed", "anomaly image", "item confirmed")
    for line in m.lines[mark:]:
        if any(k in line for k in keys):
            rep.note(f"[8] {line.strip()}")
    rep.check(8, "START@1→S0→STOP@5 → หยิบ @7 นอกรอบ → START@9 → STOP@12", "S0 1, ยอด 1",
              f"S0 {s0s(r)}, ยอด {count(wd)}", s0s(r) == 1 and count(wd) == 1)
    rep.check(8, "outcome ของ 2 รอบ", "CONFIRMED,UNCONFIRMED", ",".join(outcomes(wd)),
              outcomes(wd) == ["CONFIRMED", "UNCONFIRMED"])


def _buy_again(r, m, wd, rep, sc, t_start2):
    """รอบ 1 ปกติ (START@1→S0→STOP@5) → ลูกค้าหยิบนอกรอบ (7.2–10.6s) → START @t_start2 → STOP @12.5
    คืน (บรรทัด log พื้นหลังของ START รอบ 2, เวลาคลิปที่เห็น log ตั้งพื้นหลังใหม่ครั้งแรก หรือ None)"""
    m.wait_clip(1.0, loop=1)
    push(r, "START")
    wait_s0(r, 1, timeout=8)
    m.wait_clip(5.0, loop=1)
    push(r, "STOP")
    m.wait_clip(t_start2, loop=1)
    push(r, "START")
    seen = None
    while True:
        ct = m.wait_clip(m.clip_time() + 0.02, loop=1)
        if seen is None and m.grep("env change settled"):
            seen = ct
        if ct >= 12.5:
            break
    push(r, "STOP")
    time.sleep(0.5)
    starts = m.grep("cycle opened (background:")
    bg2 = starts[1].split("background:", 1)[-1].strip() if len(starts) > 1 else "-"
    rep.note(f"[{sc}] START รอบ 2 @{t_start2}: {bg2[:60]}; ตั้งพื้นหลังใหม่ครั้งแรกที่ clip "
             + (f"{seen:.2f}s" if seen else "- (ไม่มี)"))
    rep.check(sc, f"ซื้อต่อ: START รอบ 2 @{t_start2} → STOP @12.5", "S0 1, ยอด 1, CONFIRMED,UNCONFIRMED",
              f"S0 {s0s(r)}, ยอด {count(wd)}, {','.join(outcomes(wd))}",
              s0s(r) == 1 and count(wd) == 1 and outcomes(wd) == ["CONFIRMED", "UNCONFIRMED"])
    return bg2, seen


def sc8b(r, m, wd, rep):
    # START ตอน slat ยังเปิด → พื้นหลัง = เฟรมปัจจุบัน → slat ปิด (~10.6s) → ตั้งพื้นหลังใหม่
    bg2, seen = _buy_again(r, m, wd, rep, "8b", 9.0)
    rep.check("8b", "พื้นหลังรอบ 2 + ตั้งพื้นหลังใหม่หลัง slat ปิด", "current frame, ตั้งใหม่ ≥10.0s",
              f"{'current frame' if 'current frame' in bg2 else bg2[:30]}, "
              + (f"ตั้งใหม่ที่ {seen:.2f}s" if seen else "ไม่ตั้งใหม่"),
              "current frame" in bg2 and seen is not None and seen >= 10.0)


def sc8c(r, m, wd, rep):
    # START หลังถาดนิ่งแล้ว → ใช้ clean_bg (ถาดว่าง)
    bg2, _ = _buy_again(r, m, wd, rep, "8c", 11.0)
    rep.check("8c", "พื้นหลังรอบ 2", "empty-tray (clean_bg)", bg2[:40], "empty-tray" in bg2)


def sc7b(r, m, wd, rep):
    # ข้อ 7 แบบปิดการตั้งพื้นหลังใหม่หลัง env change สงบ → ต้องผ่านด้วยการแยกหยิบออก/ใส่เข้า (core/removal.py) อย่างเดียว
    sc7(r, m, wd, rep)
    rep.rows[-1] = ("7b",) + rep.rows[-1][1:]
    lines = m.grep("-> item removed") + m.grep("-> uncertain")
    rep.note("[7b] " + (lines[0].split("vending.main: ", 1)[-1] if lines else "ไม่มี log หยิบออก"))
    rep.check("7b", "จับได้ว่าเป็นการหยิบออก", "POSSIBLE_REMOVAL", ",".join(anomaly_kinds(wd)),
              "POSSIBLE_REMOVAL" in anomaly_kinds(wd))


def confirm_clip_times(m, wd):
    """เวลาคลิป (วินาที) ของทุกการยืนยันใน DB (ทั้ง 2 โหมด SEND_S0) เรียงตามลำดับ"""
    out = []
    for (t,) in db_query(wd, "SELECT confirmed_at_utc FROM confirmations ORDER BY id"):
        ts = datetime.fromisoformat(t).timestamp()
        ff = max([f for f in m.first_frames if f <= ts], default=None)
        out.append(ts - ff if ff is not None else None)
    return out


ANOMALY_KINDS = ("OUTSIDE_CYCLE", "EXTRA_AFTER_CONFIRM", "NO_CONFIRM_AT_CLOSE", "POSSIBLE_REMOVAL", "ENV_CHANGE")


def anomaly_summary(wd):
    """จำนวนภาพ anomaly แยกชนิด เช่น {'ENV_CHANGE': 3, 'NO_CONFIRM_AT_CLOSE': 1}"""
    out = {}
    for name in anomaly_images(wd):
        for kind in ANOMALY_KINDS:
            if kind in name:
                out[kind] = out.get(kind, 0) + 1
    return out


def item_sizes(m):
    """บรรทัด log "item size:" ของทุกการยืนยัน (ตัด prefix เวลา/โมดูล)"""
    return [line.split("item size: ", 1)[-1] for line in m.grep("item size:")]


# ข้อ 9: (shadow, send_s0) → (ยอด, ภาพ EXTRA_AFTER_CONFIRM, index แถวตรวจ) — ตัดสิน "ดีกว่า off" ตอนจบ
SC9 = {}


def sc9(r, m, wd, rep):
    # [S22] คนยืนหน้าตู้: เงา/แสงเปลี่ยนใน ROI ทั้งคลิป ไม่มีของตก → ต้องไม่ยืนยัน
    m.wait_clip(2.0, loop=1)
    push(r, "START")
    m.wait_clip(23.8, loop=1)
    push(r, "STOP")
    time.sleep(0.5)
    times = [t for t in confirm_clip_times(m, wd) if t is not None]
    rep.note(f"[9] SHADOW_FILTER={MODE['shadow']}: ยืนยัน {count(wd)} ครั้ง "
             f"(clip {', '.join(f'{t:.2f}s' for t in times) or '-'}), "
             f"outcome={outcomes(wd)}, ภาพ anomaly={anomaly_summary(wd)}")
    ok = (s0s(r) == 0 and count(wd) == 0 and outcomes(wd) == ["UNCONFIRMED"]
          and "NO_CONFIRM_AT_CLOSE" in anomaly_kinds(wd))
    off = MODE["shadow"] == "off"
    SC9[(MODE["shadow"], MODE["send_s0"])] = (count(wd), anomaly_summary(wd).get("EXTRA_AFTER_CONFIRM", 0),
                                              len(rep.rows))
    rep.check(9, "เงาคน START@2.0 → STOP@23.8" + (" (off: รายงานอย่างเดียว)" if off else ""),
              "S0 0, ยอด 0, UNCONFIRMED + NO_CONFIRM_AT_CLOSE" + ("" if off else " (หรือดีกว่า off)"),
              f"S0 {s0s(r)}, ยอด {count(wd)}, {','.join(outcomes(wd))}, anomaly={anomaly_kinds(wd)}",
              ok or off)


def judge_sc9(rep):
    """ข้อ 9 texture ที่ยังมีการยืนยัน → ผ่านเมื่อดีกว่า off (ยอด, ภาพ EXTRA) ในโหมด SEND_S0 เดียวกัน"""
    for (shadow, send), (n, extra, idx) in SC9.items():
        if shadow != "texture" or n == 0:
            continue
        o = SC9.get(("off", send))
        row = list(rep.rows[idx])
        if o is None:
            row[3] += " | ไม่มีผล off ให้เทียบ"
        else:
            better = (n, extra) < (o[0], o[1])
            row[3] += f" | off: ยอด {o[0]}, EXTRA {o[1]} → texture {'ดีกว่า' if better else 'ไม่ดีกว่า'}"
            row[4] = "✅" if better else "❌"
        rep.rows[idx] = tuple(row)


def sc10(r, m, wd, rep):
    # [S22] ขนมตก ~10.7s (ฝาเปิด 14.9–16.7) → ขวดน้ำใสตก ~26.4s (ฝาเปิด 29.2–30.2): 2 รอบ รอบละ 1 ยืนยัน
    lats = []
    for t_start, t_stop, n in ((10.0, 18.6, 1), (25.5, 32.5, 2)):
        m.wait_clip(t_start, loop=1)
        t = push(r, "START")
        t_s0 = wait_s0(r, n, timeout=t_stop - t_start - 0.3)
        lats.append(t_s0 - t if t_s0 else None)
        m.wait_clip(t_stop, loop=1)
        push(r, "STOP")
    time.sleep(0.5)
    times = [t for t in confirm_clip_times(m, wd) if t is not None]
    lat_txt = ", ".join(f"{x:.2f}s" if x else "-" for x in lats)
    rep.note(f"[10] SHADOW_FILTER={MODE['shadow']}: ยืนยันที่ clip {', '.join(f'{t:.2f}s' for t in times) or '-'}, "
             f"START->confirm(S0) {lat_txt}, outcome={outcomes(wd)}, ภาพ anomaly={anomaly_summary(wd)}")
    rep.check(10, "ขนม START@10→STOP@18.6 · ขวด START@25.5→STOP@32.5", "S0 2, ยอด 2, CONFIRMED,CONFIRMED",
              f"S0 {s0s(r)}, ยอด {count(wd)}, {','.join(outcomes(wd))} ({lat_txt})",
              s0s(r) == 2 and count(wd) == 2 and outcomes(wd) == ["CONFIRMED", "CONFIRMED"])
    in_win = len(times) == 2 and 10.7 <= times[0] < 14.9 and 26.4 <= times[1] < 29.2
    rep.check(10, "เวลายืนยัน (ไม่มียืนยันช่วงฝาเปิด)", "[10.7,14.9) และ [26.4,29.2)",
              ", ".join(f"{t:.2f}s" for t in times) or "-", in_win)


def sc11(r, m, wd, rep):
    # [S22] ขนมตก ~4.1s → (ขนมยังอยู่) ขวดตกข้างขนม ~20s → หยิบขวด 32.8–34.8 → หยิบขนม 38.9 → ว่าง 41s
    lats = []
    for t_start, t_stop, n in ((3.0, 12.0, 1), (19.0, 31.0, 2)):
        m.wait_clip(t_start, loop=1)
        t = push(r, "START")
        t_s0 = wait_s0(r, n, timeout=t_stop - t_start - 0.3)
        lats.append(t_s0 - t if t_s0 else None)
        m.wait_clip(t_stop, loop=1)
        push(r, "STOP")
    time.sleep(0.5)
    n_at_stop = count(wd)
    m.wait_clip(45.5, loop=1)  # หลัง STOP รอบ 2: หยิบขวด / หยิบขนม นอกรอบ → ต้องไม่มีการยืนยัน
    times = [t for t in confirm_clip_times(m, wd) if t is not None]
    lat_txt = ", ".join(f"{x:.2f}s" if x else "-" for x in lats)
    rep.note(f"[11] SHADOW_FILTER={MODE['shadow']}: ยืนยันที่ clip {', '.join(f'{t:.2f}s' for t in times) or '-'}, "
             f"START->confirm(S0) {lat_txt}, outcome={outcomes(wd)}, ภาพ anomaly={anomaly_summary(wd)}")
    rep.check(11, "ขนม START@3→STOP@12 · ขวด START@19→STOP@31", "S0 2, ยอด 2, CONFIRMED,CONFIRMED",
              f"S0 {s0s(r)}, ยอด {count(wd)}, {','.join(outcomes(wd))} ({lat_txt})",
              s0s(r) == 2 and count(wd) == 2 and outcomes(wd) == ["CONFIRMED", "CONFIRMED"])
    rep.check(11, "รอบ 2 ยืนยันขวด (ไม่ใช่ขนมเดิม)", "ยืนยัน 1 ใน [4.1,12) · ยืนยัน 2 ใน [20.0,31)",
              ", ".join(f"{t:.2f}s" for t in times) or "-",
              len(times) == 2 and 4.1 <= times[0] < 12.0 and 20.0 <= times[1] < 31.0)
    rep.check(11, "หลัง STOP รอบ 2 (หยิบขวด/ขนม) ถึง 45.5s", "ไม่มีการยืนยันเพิ่ม",
              f"ยอดตอน STOP {n_at_stop} → 45.5s {count(wd)}", count(wd) == n_at_stop == 2)


# env เพิ่มเติมของบางสถานการณ์
SCENARIO_ENV = {"7b": {"ENV_SETTLE_REBASELINE": "0"}}
# [S22] คลิป + ROI เฉพาะของบางสถานการณ์ (คลิปอยู่โฟลเดอร์เดียวกับ --clip หรือ --clip-dir)
SCENARIO_CLIP = {"9": "person_shadow.mp4", "10": "small1pick_big1pick.mp4", "11": "small1_big1_cutted.mp4"}
SCENARIO_ROI = {"9": "roi_shadow_clips.json", "10": "roi_shadow_clips.json", "11": "roi_shadow_clips.json"}
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

SCENARIOS = {"1": sc1, "2": sc2, "3": sc3, "4": sc4, "5": sc5, "6": sc6, "7": sc7, "8": sc8,
             "8b": sc8b, "8c": sc8c, "7b": sc7b, "9": sc9, "10": sc10, "11": sc11}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console Windows (cp1252) พิมพ์ไทยไม่ได้
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default=os.environ.get("E2E_CLIP"), required=not os.environ.get("E2E_CLIP"))
    ap.add_argument("--scenarios", default="1,2,3,4,5,6,7,7b,8,8b,8c,9,10,11")
    ap.add_argument("--clip-dir", default=None, help="โฟลเดอร์คลิปของข้อ 9, 10 (ไม่ใส่ = โฟลเดอร์เดียวกับ --clip)")
    ap.add_argument("--shadow", default="texture", help="SHADOW_FILTER ของ main.py: texture, off หรือ texture,off")
    ap.add_argument("--keep", action="store_true", help="ไม่ลบโฟลเดอร์ชั่วคราว (ไว้ดู log)")
    ap.add_argument("--send-s0", default="1,0", help="โหมด SEND_S0 ที่จะรัน: 1, 0 หรือ 1,0")
    ap.add_argument("--hold", type=float, default=None, help="CAPTURE_HOLD_SEC ของ main.py (ไม่ใส่ = default ใน config)")
    args = ap.parse_args()
    if not os.path.isfile(args.clip):
        raise SystemExit(f"❌ ไม่พบคลิป {args.clip}")

    rep = Report()
    os.makedirs(TMP_BASE, exist_ok=True)
    root = tempfile.mkdtemp(prefix="vendingcam_e2e_", dir=TMP_BASE)
    print(f"📁 โฟลเดอร์ชั่วคราว: {root}")
    modes = [x.strip() == "1" for x in args.send_s0.split(",")]
    shadows = [x.strip() for x in args.shadow.split(",")]
    clip_dir = args.clip_dir or os.path.dirname(os.path.abspath(args.clip))
    MODE["hold"] = args.hold
    if args.hold is not None:
        rep.note(f"CAPTURE_HOLD_SEC={args.hold:g}")
    results = {}  # (shadow, send_s0, ข้อ) → outcomes ของทุกรอบ
    r = redis_up()
    mon = CameraMonitor()
    try:
      for shadow, send in [(sh, s0) for sh in shadows for s0 in modes]:
        MODE["send_s0"], MODE["shadow"] = send, shadow
        tag = ("" if send else "@S0=0") + ("" if len(shadows) == 1 else f"@{shadow}")
        rep.note(f"=== SEND_S0={int(send)} SHADOW_FILTER={shadow} ===")
        for sc in args.scenarios.split(","):
            wd = os.path.join(root, f"{shadow}_s0{int(send)}_sc{sc}")
            MODE["wd"] = wd
            os.makedirs(os.path.join(wd, "data"))
            roi_src = (os.path.join(FIXTURES, SCENARIO_ROI[sc]) if sc in SCENARIO_ROI
                       else os.path.join(REPO, "data", "roi_config.example.json"))
            shutil.copy(roi_src, os.path.join(wd, "data", "roi_config.json"))
            clip = os.path.join(clip_dir, SCENARIO_CLIP[sc]) if sc in SCENARIO_CLIP else args.clip
            if not os.path.isfile(clip):
                rep.check(f"{sc}{tag}", "คลิป", clip, "ไม่พบไฟล์", False)
                continue
            reset_keys(r)
            time.sleep(0.2)
            mon.take()
            m = MainProc(wd, clip, SCENARIO_ENV.get(sc))
            print(f"▶️ สถานการณ์ {sc}{tag}")
            m.start()
            first_row = len(rep.rows)
            try:
                SCENARIOS[sc](r, m, wd, rep)
                starts = []
                for line in m.grep("cycle opened (background:"):
                    age = re.search(r"age (\d+\.\d+)s", line)
                    starts.append(f"clean_bg {age.group(1)}s" if age else "current frame")
                rep.note(f"[{sc}] พื้นหลังของแต่ละ START: {starts or '-'}; anomaly={anomaly_kinds(wd)}")
                env_imgs = anomaly_images(wd, "ENV_CHANGE")
                rep.note(f"[{sc}] ENV_CHANGE: ภาพ {len(env_imgs)} ภาพ "
                         f"(clip {', '.join(env_clip_times(m, env_imgs)) or '-'}) · ภาพ anomaly ทั้งหมด {len(anomaly_images(wd))}")
                sizes = item_sizes(m)
                if sizes:
                    rep.note(f"[{sc}] ขนาดก้อนที่ยืนยัน: {sizes}")
                for t in timing_rows(m):
                    rep.note(
                        f"[{sc}] TIMING (วินาทีคลิป) START {t['start']:.2f} → motion {t['motion']:.2f} → "
                        f"เห็นของ {t['seen']:.2f} → นิ่ง(เริ่ม hold) {t['still']:.2f} [{t['frames']} เฟรม, "
                        f"reset {t['resets']}] → ครบ hold {t['hold_done']:.2f} → S3 {t['s3_ms']}ms → "
                        f"ยืนยัน (+save {t['save_ms']}ms) | START→confirm {t['total']:.2f}s"
                    )
                ff = m.first_frames
                if len(ff) >= 2:
                    rep.note(f"[{sc}] คาบการวนคลิปที่วัดได้ {ff[1] - ff[0]:.2f}s (ความยาวคลิป + reconnect)")
            except Exception as e:
                rep.check(sc, "รันสถานการณ์", "สำเร็จ", f"error: {e}", False)
                try:  # วินิจฉัย: บรรทัดท้ายของ stdout main.py + จำนวน FIRST_FRAME ที่เห็น
                    with open(os.path.join(wd, "stdout.txt"), "rb") as f:
                        tail = f.read().decode("utf-8", "replace").splitlines()[-4:]
                    rep.note(f"[{sc}] DIAG first_frames={len(m.first_frames)} alive={m.alive()} stdout: {tail}")
                except OSError as de:
                    rep.note(f"[{sc}] DIAG อ่าน stdout ไม่ได้: {de}")
            finally:
                m.kill()
                r = test_redis()
            results[(shadow, send, sc)] = outcomes(wd)
            bad = non_ascii_lines(wd)
            rep.check(sc, "log ASCII ล้วน (stdout + vending.log)", "0 บรรทัดที่มีอักขระ > 0x7F",
                      f"{len(bad)} บรรทัด" + (f" เช่น {bad[0][:80]!r}" if bad else ""), not bad)
            time.sleep(0.3)  # ให้ MONITOR อ่านคำสั่งสุดท้ายทัน
            writes = mon.take()
            if not send:
                try:
                    cam = r.llen("CAMERA")
                except redis.RedisError as e:
                    cam = f"error {e}"
                rep.check(sc, "โหมดเก็บข้อมูล: ไม่แตะ CAMERA", "llen 0, MONITOR 0 คำสั่ง",
                          f"llen {cam}, MONITOR {len(writes)} {writes[:3]}", cam == 0 and not writes)
                if (shadow, True, sc) in results:
                    a, b = (",".join(map(str, results[(shadow, k, sc)])) for k in (True, False))
                    rep.check(sc, "outcome ทุกรอบเหมือนโหมด SEND_S0=1", a, b, a == b)
            else:
                lp = [w for w in writes if w.split()[0].upper().strip('"') == "LPUSH"]
                rep.note(f"[{sc}] MONITOR: LPUSH CAMERA {len(lp)} ครั้ง")
            for i in range(first_row, len(rep.rows)):
                rep.rows[i] = (f"{rep.rows[i][0]}{tag}",) + rep.rows[i][1:]
    finally:
        mon.stop()
        redis_down()
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)

    judge_sc9(rep)
    print("\n| # | ตรวจ | คาดหวัง | ได้จริง | ผล |\n|---|---|---|---|---|")
    for row in rep.rows:
        print("| " + " | ".join(str(x) for x in row) + " |")
    print("\nหมายเหตุ:")
    for n in rep.notes:
        print(" -", n)
    return 0 if all(row[4] == "✅" for row in rep.rows) else 1


if __name__ == "__main__":
    sys.exit(main())
