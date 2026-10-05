"""
tests/integration/docker_smoke.py — smoke test ของ Docker image: --network host + Redis ทดสอบ 6380 + คลิป mount เข้า

ต้อง build ก่อน (ใน WSL):  docker build -t vending-cam:autorun-test <repo>
รัน:  .venv\Scripts\python.exe tests\integration\docker_smoke.py
ผ่าน = START @1.0s ของคลิป → S0 1 รายการ (พิมพ์ RESULT PASS) ไฟล์ชั่วคราวอยู่ .e2e_tmp/docker
"""
import os, re, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redis_e2e as e

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = e.REPO
work = os.path.join(REPO, ".e2e_tmp", "docker")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(os.path.join(work, "data")); os.makedirs(os.path.join(work, "logs")); os.makedirs(os.path.join(work, "evidence_images"))
shutil.copy(os.path.join(REPO, "data", "roi_config.json"), os.path.join(work, "data"))
wsl = lambda p: "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
NAME = "vendingcam-docker-smoke"
CLIP = os.path.abspath(os.environ.get(
    "E2E_CLIP", r"C:\Users\epicm\Desktop\VendingCameraProject\test_videos\big1_pickup_cutted.mp4"))
r = e.redis_up()
try:
    e.docker("rm", "-f", NAME, check=False)
    e.docker("run", "-d", "--name", NAME, "--network", "host",
             "-e", "CONTROL_MODE=redis", "-e", "REDIS_HOST=127.0.0.1", "-e", f"REDIS_PORT={e.PORT}",
             "-e", "HEADLESS=1", "-e", "CLOUD_ENABLED=0", "-e", "TZ=Asia/Bangkok",
             "-e", "CAMERA_INDEX=/clips/" + os.path.basename(CLIP),
             "-v", wsl(os.path.join(work, "data")) + ":/app/data",
             "-v", wsl(os.path.join(work, "logs")) + ":/app/logs",
             "-v", wsl(os.path.join(work, "evidence_images")) + ":/app/evidence_images",
             "-v", wsl(os.path.dirname(CLIP)) + ":/clips:ro",
             "vending-cam:autorun-test")
    log = os.path.join(work, "logs", "vending.log")
    first = None
    end = time.time() + 40
    while time.time() < end and first is None:
        if os.path.exists(log):
            m = e.FIRST_FRAME_RE.search(open(log, encoding="utf-8", errors="replace").read())
            if m:
                first = float(m.group(1))
        time.sleep(0.05)
    assert first, "ไม่เห็น FIRST_FRAME ใน 40s"
    while time.time() - first < 1.0:
        time.sleep(0.01)
    t = e.push(r, "START")
    t_s0 = e.wait_s0(r, 1, timeout=8)
    time.sleep(2)
    e.push(r, "STOP")
    time.sleep(1)
    text = open(log, encoding="utf-8", errors="replace").read()
    print("START ที่ clip", round(t - first, 2))
    print("S0 list:", r.lrange("CAMERA", 0, -1), "START→S0:", round(t_s0 - t, 2) if t_s0 else None)
    for line in text.splitlines():
        if re.search(r"START|STOP|S0|FROZEN|ยืนยัน|ปิดรอบ|Redis|⚠️ \.env", line):
            print("  ", line[11:170])
    print("RESULT", "PASS" if (t_s0 and r.llen("CAMERA") == 1) else "FAIL")
finally:
    print(e.docker("logs", "--tail", "3", NAME, check=False))
    e.docker("rm", "-f", NAME, check=False)
    e.redis_down()
