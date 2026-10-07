"""
tests/integration/docker_smoke.py — smoke test ของ Docker image: --network host + Redis ทดสอบ 6380 + คลิป mount เข้า

ต้อง build ก่อน (ใน WSL):  docker build -t vending-cam:autorun-test <repo>
รัน:  .venv\Scripts\python.exe tests\integration\docker_smoke.py [--send-s0 0,1]
รันทีละโหมด (ค่าเริ่ม "0,1"):
  SEND_S0=0 (ค่าเริ่มของ image): START @1.0s → ยืนยันใน DB (NOT_SENT) และ CAMERA ต้องว่าง + MONITOR ไม่เห็นคำสั่งที่แตะ CAMERA
  SEND_S0=1: START @1.0s → S0 1 รายการใน CAMERA
พิมพ์ RESULT PASS/FAIL ต่อโหมด · ไฟล์ชั่วคราวอยู่ .e2e_tmp/docker_s0<โหมด>
"""
import argparse, os, re, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import redis_e2e as e

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = e.REPO
wsl = lambda p: "/mnt/" + p[0].lower() + p[2:].replace("\\", "/")
NAME = "vendingcam-docker-smoke"
CLIP = os.path.abspath(os.environ.get(
    "E2E_CLIP", r"C:\Users\epicm\Desktop\VendingCameraProject\test_videos\big1_pickup_cutted.mp4"))


def run(r, mon, send):
    work = os.path.join(REPO, ".e2e_tmp", f"docker_s0{int(send)}")
    shutil.rmtree(work, ignore_errors=True)
    for d in ("data", "logs", "evidence_images"):
        os.makedirs(os.path.join(work, d))
    shutil.copy(os.path.join(REPO, "data", "roi_config.example.json"), os.path.join(work, "data", "roi_config.json"))
    e.MODE.update(send_s0=send, wd=work)
    e.reset_keys(r)
    time.sleep(0.2)
    mon.take()
    env = ["-e", f"SEND_S0={int(send)}"] if send else []  # โหมด 0 = ไม่ตั้ง (ใช้ค่าเริ่มของ image)
    e.docker("rm", "-f", NAME, check=False)
    e.docker("run", "-d", "--name", NAME, "--network", "host",
             "-e", "CONTROL_MODE=redis", "-e", "REDIS_HOST=127.0.0.1", "-e", f"REDIS_PORT={e.PORT}",
             "-e", "HEADLESS=1", "-e", "CLOUD_ENABLED=0", "-e", "TZ=Asia/Bangkok", *env,
             "-e", "CAMERA_INDEX=/clips/" + os.path.basename(CLIP),
             "-v", wsl(os.path.join(work, "data")) + ":/app/data",
             "-v", wsl(os.path.join(work, "logs")) + ":/app/logs",
             "-v", wsl(os.path.join(work, "evidence_images")) + ":/app/evidence_images",
             "-v", wsl(os.path.dirname(CLIP)) + ":/clips:ro",
             "vending-cam:autorun-test")
    try:
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
        t_s0 = e.wait_s0(r, 1, timeout=8)  # โหมด 0 = เวลายืนยันจาก DB
        time.sleep(2)
        e.push(r, "STOP")
        time.sleep(1)
        writes = mon.take()
        raw = open(log, "rb").read()
        text = raw.decode("utf-8", "replace")
        ascii_ok = all(b <= 0x7F for b in raw)
        cam = r.llen("CAMERA")
        print(f"=== SEND_S0={int(send)} ===")
        print("START ที่ clip", round(t - first, 2), "| START→" + ("S0" if send else "confirm") + ":",
              round(t_s0 - t, 2) if t_s0 else None)
        print("CAMERA:", r.lrange("CAMERA", 0, -1), "| MONITOR CAMERA:", writes, "| outcomes:", e.outcomes(work),
              "| log ASCII:", ascii_ok)
        for line in text.splitlines():
            if re.search(r"START|STOP|S0|item confirmed|cycle closed|Redis|\.env:", line):
                print("  ", line[11:190])
        if send:
            ok = t_s0 is not None and cam == 1
        else:
            ok = t_s0 is not None and cam == 0 and not writes and "S0 response: DISABLED" in text
        ok = ok and ascii_ok and e.outcomes(work) == ["CONFIRMED"]
        print(f"RESULT SEND_S0={int(send)}", "PASS" if ok else "FAIL")
        return ok
    finally:
        print(e.docker("logs", "--tail", "3", NAME, check=False))
        e.docker("rm", "-f", NAME, check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-s0", default="0,1")
    args = ap.parse_args()
    r = e.redis_up()
    mon = e.CameraMonitor()
    try:
        results = [run(r, mon, x.strip() == "1") for x in args.send_s0.split(",")]
    finally:
        mon.stop()
        e.redis_down()
    print("RESULT", "PASS" if all(results) else "FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
