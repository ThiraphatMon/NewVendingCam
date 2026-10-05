# AUTORUN_REPORT — ความคืบหน้างานต่อเนื่อง (branch `auto/round1-finish`)

> คำสั่งหลัก: `docs/AUTORUN_TASK.md` | review: `git log main..auto/round1-finish`

## สถานะแต่ละขั้น

| ขั้น | สถานะ | commit | pytest | e2e (1–6, 8 / 7) | START→S0 ข้อ 1 / ข้อ 3 |
|---|---|---|---|---|---|
| S0 ตั้งต้น + D2 baseline freshness | ✅ เสร็จ | autorun S0 | 100 passed | ✅ / ❌ (คาดไว้) | 3.41s / 3.40s, 3.40s |
| S1 ปิดงาน D2 (ตั้งพื้นหลังใหม่หลัง env change สงบ) | ✅ เสร็จ | autorun S1 | 103 passed | ✅ (+8b, 8c) / ✅* | 3.41s / 3.41s, 3.42s |
| S2 ขั้น E (พร้อมลง Orange Pi) | ✅ เสร็จ | autorun S2 | 107 passed | ✅ (+8b, 8c) / ✅ | 3.40s / 3.43s, 3.39s |
| S3 แยกหยิบออก / ใส่เข้า (ข้อ 7) | รอ | | | | |
| S4 ความนิ่งของ tracker | รอ | | | | |
| S5 กล้องค้าง | รอ | | | | |
| S6 สรุป | รอ | | | | |

## รายละเอียดผลทดสอบ

### S0
- pytest: 100 passed
- e2e: ข้อ 1–6, 8 ผ่าน, ข้อ 7 ไม่ผ่าน (S0 ที่ clip 12.21s — หลุมจากของที่ถูกหยิบออกถูกยืนยันเป็นของ)
- พื้นหลังของ START: ข้อ 1–5 ใช้ clean_bg อายุ 0.2–0.4s; ข้อ 3 รอบสอง / ข้อ 8 รอบสอง ใช้เฟรมปัจจุบัน
- ข้อ 8 รอบสอง (START @9.0 slat ยังเปิด) ผ่านเพราะพื้นหลังต่างจากถาดหลัง slat ปิด 56% ของ ROI
  → env change ค้างทั้งรอบ (มองไม่เห็นอะไรเลย) — S1 แก้ด้วยการตั้งพื้นหลังใหม่หลัง env change สงบ

### S1
- เพิ่ม `App._rebaseline_settled_env()`: รอบ ACTIVE ที่ยังไม่ยืนยัน + env change **ยังค้างอยู่ในเฟรมนี้** + ROI นิ่งเฟรมต่อเฟรมครบ
  CLEAN_BG_STABLE_FRAMES (5) → ตั้งพื้นหลังของรอบเป็นเฟรมนี้ + ล้าง tracker + log 1 บรรทัด (ใช้ค่าเดิม ไม่เพิ่ม config ใหม่)
  - เงื่อนไข "env change ค้างอยู่ตอนนิ่ง" กันกรณีของตกที่ก้อน motion ใหญ่ชั่วขณะ: พอของตกถึงพื้นก้อนเล็กลง → ไม่เข้าเงื่อนไข → ไม่กลืนของ
- pytest 103 passed (+3: ตั้งใหม่หลัง slat ปิดแล้วของตกยังยืนยันได้ / ไม่ตั้งใหม่ขณะยังขยับ / ไม่ตั้งใหม่หลังยืนยันแล้ว)
- e2e ทั้งชุดผ่าน: 8b START @9.0 → เฟรมปัจจุบัน → ตั้งพื้นหลังใหม่ที่ clip 10.40s → UNCONFIRMED;
  8c START @11.0 → clean_bg อายุ 0.3s → UNCONFIRMED
- \* **ข้อ 7 ผ่านแล้ว (ผลข้างเคียงของ S1)**: log ข้อ 7 ตั้งพื้นหลังใหม่ 2 ครั้ง — ~8.0s (slat เปิดค้างนิ่ง 5 เฟรม)
  และ ~10.4s (slat ปิดแล้ว ถาดว่าง) → หลุมของที่หายไปถูกกลืนเข้าพื้นหลังก่อนครบ CAPTURE_HOLD_SEC
  ผ่านเพราะคลิปนี้การหยิบทำให้ slat บัง ROI เกิน 30% (env change) — ถ้าหยิบออกโดยไม่มี env change (มือเล็ก/slat ไม่บัง)
  ยังเกิด S0 ผิดได้ → S3 ยังจำเป็น

### S2
- config: `inactive_warnings()` — ค่าที่ตั้งใน .env แต่ไม่มีผล (ระบบ order เดิม / cloud ตอน CLOUD_ENABLED=0 /
  REDIS_* ตอน keyboard) → main log `⚠️ .env: ... ไม่มีผล` ตอน startup; คอมเมนต์ clean_bg อัปเดตตามความหมายใหม่
- `.envexample` เขียนใหม่: ครบทุกค่าใหม่ (CONTROL_MODE, REDIS_*, CLOUD_ENABLED, CYCLE_TIMEOUT_SEC, CLEAN_BG_*,
  STATE_DB_PATH, COUNT_TIMEZONE, DAILY_LOG_DIR, ANOMALY_*) ค่า cloud/order เดิมเป็นคอมเมนต์ (ไม่ให้เกิด warning)
- `requirements.txt` / `requirements-pc.txt`: + redis==5.2.1, tzdata==2025.2 (เวอร์ชันที่ใช้ทดสอบ);
  ใหม่ `requirements-dev.txt`: pytest==8.3.4, fakeredis==2.26.2
- `docker-compose.yml`: `network_mode: host`, `TZ=Asia/Bangkok`, volumes data/ evidence_images/ logs/, /dev/video0 (ไม่มี Redis service)
- `Dockerfile`: เลิก `COPY data` (ไม่ bake ROI/DB — เดิม data/vending_state.sqlite3 ในเครื่อง build จะหลุดเข้า image ได้);
  `.dockerignore` + data, .e2e_tmp, tests, docs, legacy_reference
- `.gitignore`: data/*.sqlite3*, .e2e_tmp/ (ทำใน S0) / `.gitattributes`: `* text=auto eol=lf` + binary (jpg/png/mp4/avi/sqlite3)
  index เป็น LF อยู่แล้วทุกไฟล์ (renormalize ไม่มีอะไรเปลี่ยน)
- **Docker บน WSL**: `docker build` ผ่าน (python:3.11-slim-bookworm, amd64) และ smoke test
  `tests/integration/docker_smoke.py` (container `--network host` → Redis ทดสอบ 6380, คลิป mount `/clips`)
  → START @1.0s → S0 1 รายการ หลัง 3.41s, log เวลาไทย, ไม่มี warning ค่า .env → **PASS**
  (network host ใน WSL ใช้ได้ — ไม่ต้องใช้วิธีอื่น; ยังไม่ได้ทดสอบ build บน arm64 จริง)
- `HANDOVER.md` เขียนใหม่ทั้งไฟล์ (ของเดิมอธิบายระบบ order/state_machine.py/reset_policy.py ที่ไม่มีแล้ว):
  protocol, วงจร START/STOP + state diagram + ตาราง START/STOP ทุก state, outcome, พื้นหลังของรอบ, watch mode,
  DB/daily log/ภาพ, config, การทดสอบ, ขั้นตอนลงบอร์ด (หยุดตัวเก่าก่อน, `redis-cli MONITOR`, controlled test), rollback,
  known limitations; `ORANGE_PI_DOCKER.md` อัปเดตตามกัน
- e2e: `redis_e2e.docker()` อ่าน output เป็น UTF-8 (เดิม cp1252 ทำ thread error ตอนอ่าน `docker logs` ภาษาไทย)

## ไฟล์ที่เปลี่ยน (สะสม)
- S0: `core/background.py`, `main.py` (D2), `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (ข้อ 8, `.e2e_tmp/`),
  `.gitignore`, `docs/AUTORUN_TASK.md`, `docs/AUTORUN_REPORT.md`
- S1: `main.py`, `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (8b, 8c)
- S2: `config.py`, `main.py`, `.envexample`, `requirements*.txt`, `docker-compose.yml`, `Dockerfile`, `.dockerignore`,
  `.gitattributes`, `HANDOVER.md`, `ORANGE_PI_DOCKER.md`, `tests/test_config.py`, `tests/integration/docker_smoke.py`, `redis_e2e.py`

## ความหมายของ test ที่เปลี่ยน
- S0 (D2): `test_start_during_watch_uses_pre_motion_background` แยกเป็น
  `test_start_during_watch_while_item_falling_is_confirmed` (ของกำลังตกตอน START ยังนับได้) และ
  `test_start_during_watch_uses_latest_still_scene_not_watch_freeze` (ของนิ่งก่อน START ≥5 เฟรมไม่นับ — เหมือนตัวเก่า,
  ผู้ใช้อนุมัติแล้ว)

## คำถามรอผู้ใช้ (ประเภท A — ทำต่อไปแล้วด้วยทางที่ปลอดภัย)
- S1: ตั้งพื้นหลังใหม่หลัง env change สงบ ใช้ CLEAN_BG_STABLE_FRAMES (5 เฟรม ≈ 0.17s) ร่วมกัน ไม่แยกค่า
  ทางอื่น: แยกค่า ENV_SETTLE_FRAMES ให้นานกว่า (เช่น 15) → กันการตั้งใหม่ตอน slat ค้างกลางทางได้ดีขึ้น แต่ถาดต้องนิ่งนานขึ้นก่อนเห็นของ
- S2: HANDOVER/ORANGE_PI ระบุ "หยุดโปรแกรมตัวเก่า" แบบทั่วไป (systemctl / kill) เพราะไม่รู้ว่าบอร์ดจริงรันตัวเก่าอย่างไร
  → ควรเติมคำสั่งจริงของตู้
- S2: ยังไม่ได้ build บน Orange Pi (arm64) จริง — ทดสอบเฉพาะ amd64 ใน WSL
- S1: ของที่ตก "พร้อมกับ" ตอน env change (เช่นตกขณะ slat ปิด) จะถูกกลืนเข้าพื้นหลังใหม่ → ไม่ยืนยัน (ไม่ส่ง S0) — เลือกทางกัน S0 ผิด

## Known limitations
- ข้อ 7: ของวางนิ่งก่อน START แล้วถูกหยิบออกระหว่างรอบ → หลุมถูกยืนยันเป็นของ → S0 ผิด (S3 จะแก้)
- ของที่นิ่งอยู่ก่อน START ≥5 เฟรม ไม่ถูกนับในรอบนั้น (เหมือนตัวเก่า)
