# AUTORUN_REPORT — ความคืบหน้างานต่อเนื่อง (branch `auto/round1-finish`)

> คำสั่งหลัก: `docs/AUTORUN_TASK.md` | review: `git log main..auto/round1-finish`

## สถานะแต่ละขั้น

| ขั้น | สถานะ | commit | pytest | e2e (1–6, 8 / 7) | START→S0 ข้อ 1 / ข้อ 3 |
|---|---|---|---|---|---|
| S0 ตั้งต้น + D2 baseline freshness | ✅ เสร็จ | autorun S0 | 100 passed | ✅ / ❌ (คาดไว้) | 3.41s / 3.40s, 3.40s |
| S1 ปิดงาน D2 (ตั้งพื้นหลังใหม่หลัง env change สงบ) | ✅ เสร็จ | autorun S1 | 103 passed | ✅ (+8b, 8c) / ✅* | 3.41s / 3.41s, 3.42s |
| S2 ขั้น E (พร้อมลง Orange Pi) | ✅ เสร็จ | autorun S2 | 107 passed | ✅ (+8b, 8c) / ✅ | 3.40s / 3.43s, 3.39s |
| S3 แยกหยิบออก / ใส่เข้า (ข้อ 7) | ✅ เสร็จ | autorun S3 | 120 passed | ✅ (+7b, 8b, 8c) / ✅ (7b ผ่านด้วย S3 ล้วน) | 3.42s / 3.42s, 3.39s |
| S4 ความนิ่งของ tracker | ✅ เสร็จ (default เปิด) | autorun S4 | 126 passed (ทั้ง 2 โหมด) | ✅ ทั้ง 2 โหมด | ปิด 3.42s / 3.40s, 3.38s · เปิด 3.54s / 3.56s, 3.56s |
| S5 กล้องค้าง | ✅ เสร็จ | autorun S5 | 133 passed | ✅ / ✅ | 3.54s / 3.55s, 3.55s |
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

### S3
- ใหม่ `core/removal.py` (pure): `classify()` เทียบ candidate ในรอบ ACTIVE ก่อนยืนยัน
  - วัดเฉพาะพิกเซลที่เปลี่ยน (|ปัจจุบัน − พื้นหลังรอบ| > MOT_THRESH) ในกล่องของ tracker + ขอบ 8px
    (ครั้งแรกวัดทั้งกล่อง → ในคลิปจริงกล่อง tracker กว้าง 288px สัญญาณจาง: หยิบออก ×0.82 vs ใส่เข้า ×1.14 แยกไม่ได้ → เปลี่ยนเป็นเฉพาะพิกเซลที่เปลี่ยน)
  - สัญญาณ 1 ความคม (Sobel) ลด: คลิปจริงผ่าน App — ใส่เข้า ×1.52, หยิบออก ×0.40 (เกณฑ์ `REMOVAL_EDGE_RATIO` 0.6)
  - สัญญาณ 2 กลับไปเหมือนฉากนิ่งก่อนวัตถุนี้ปรากฏ (scene history): หยิบออก 11.9–13.1 vs พื้นหลังรอบ 77.6;
    ใส่เข้า 76.6 vs 76.8 (เกณฑ์ `REMOVAL_MATCH_RATIO` 0.5)
  - ADDITION = ขอบไม่ลด (แม้ฉากก่อนหน้าตรง — กรณีซื้อซ้ำที่ตำแหน่งเดิม ว่าง→ของ→ว่าง→ของ ซึ่งสัญญาณ 2 อย่างเดียวแยกไม่ได้)
    / REMOVAL = ขอบลด + ฉากก่อนหน้าตรง / UNCERTAIN = ขอบลดแต่ไม่มีฉากยืนยัน → default ไม่ส่ง S0
- `BackgroundModel`: scene history (ring buffer `SCENE_HISTORY_SIZE`=10 ฉาก uint8 ≈ 3MB) บันทึกฉากนิ่งทุกสถานะ
  ฉากใหม่ต่างจากฉากล่าสุด ≥ MIN_AREA px ใน ROI → เพิ่ม ไม่งั้นแทนที่ (ตามแสงทัน); กล้องหลุดล้างทิ้ง
- main: REMOVAL/UNCERTAIN → anomaly ใหม่ `POSSIBLE_REMOVAL` (ใช้โควตาภาพร่วม, **แถวใน DB บันทึกเสมอ** แม้เกินโควตา
  เพราะเป็นหลักฐานว่าทำไมรอบนี้ไม่ส่ง S0) + rebaseline + ล้าง tracker → รอบยัง ACTIVE รับของจริงต่อได้
- config ใหม่: `REMOVAL_CHECK`=1, `REMOVAL_EDGE_RATIO`=0.6, `REMOVAL_MATCH_RATIO`=0.5, `REMOVAL_UNCERTAIN_SEND_S0`=0,
  `SCENE_HISTORY_SIZE`=10, `ENV_SETTLE_REBASELINE`=1 (เปิด/ปิดของ S1 — เพิ่มเพื่อทดสอบ S3 แยกได้)
- B_empty calibration: **ไม่ทำ** (ดูคำถามรอผู้ใช้) — ระบบทำงานได้ด้วย scene history อยู่แล้ว
- tests: `tests/test_removal.py` 13 ข้อ — classify (ใส่เข้า / หยิบออก / ไม่มีฉากยืนยัน / ซื้อซ้ำที่เดิม /
  ของสีใกล้พื้นมีลายทั้งใส่และหยิบ / box) + App (หยิบออกระหว่างรอบไม่ยืนยันแล้วรับของจริงต่อได้ / UNCERTAIN default /
  นโยบายส่ง S0 / ปิด REMOVAL_CHECK = พฤติกรรมเดิม / ซื้อซ้ำที่เดิมยืนยัน / เกินโควตายังบันทึก / scene history)
- e2e ใหม่ **7b** = ข้อ 7 + `ENV_SETTLE_REBASELINE=0` → ผ่านด้วย S3 อย่างเดียว: log
  `วัตถุนิ่งดูเหมือนหยิบออก (ขอบ ×0.40, ต่างจากพื้นหลังรอบ 77.9, ต่างจากฉากก่อนหน้า 11.9)` + anomaly POSSIBLE_REMOVAL
- เวลา START→S0 ไม่เปลี่ยน (classify ทำเฉพาะตอนมี candidate ครั้งเดียว)

### S4
- `core/tracker.py` หลัง flag `STRICT_STABILITY`:
  - F03: ขยับเกิน CENTROID_STABLE_DIST ระหว่าง hold (SHAPE_CONFIRMED) → ถอนเป็น DETECTING, ล้าง stable count และเวลาลงจอด
    (เดิม: SHAPE_CONFIRMED แล้วไม่เช็คการขยับอีกเลย — ของที่ไถลระหว่าง 1.5s ยังถูกถ่าย)
  - F04: หาย (ghost) → ล้าง stable count + เวลาลงจอด → กลับมาต้องนิ่งครบ LANDING_STABLE_FRAMES ใหม่
    (เดิม: count สะสมข้ามช่วงหาย กลับมา 1 เฟรมก็ลงจอดทันที)
- วัด 2 แบบ (pytest 126 ผ่านทั้งคู่, e2e ทุกข้อผ่านทั้งคู่):

  | โหมด | ข้อ 1 START→S0 | ข้อ 3 | ข้อ 4 S0 หลัง Redis กลับ |
  |---|---|---|---|
  | STRICT_STABILITY=0 | 3.42s | 3.40s, 3.38s | 1.05s |
  | STRICT_STABILITY=1 | 3.54s | 3.56s, 3.56s | 1.64s |

  เปิดแล้วช้าลง +0.12 ถึง +0.18s (< 0.3s) ไม่ถอยหลัง → **default เปิด** ตามกติกา
  (ช้าลงเพราะในคลิปของมี mask กระพริบ/ขยับเล็กน้อยช่วงแรกหลังตก ทำให้เริ่มนับนิ่งใหม่ 3–5 เฟรม)
- tests: `tests/test_tracker.py` 6 ข้อ (ขยับระหว่าง hold ทั้ง 2 โหมด / สั่นเล็กน้อยไม่ถอน / ghost แล้วกลับมาทั้ง 2 โหมด /
  ghost หลังลงจอดต้องนิ่งใหม่ครบ)

### S5
- `core/frame_source.py` เขียนใหม่: reader thread อ่านกล้อง/ไฟล์ตลอด ถือเฉพาะเฟรมล่าสุด + เวลา (slot ขนาด 1)
  - `read()` รอเฟรมใหม่ได้ไม่เกิน 0.1s แล้วคืน: เฟรมใหม่ | `None` (กล้องหลุด / วิดีโอจบกำลังเปิดใหม่ / ไม่มีเฟรมใหม่เกิน
    `CAMERA_STALL_SEC`=3s) | `NO_NEW_FRAME` (ยังไม่มีเฟรมใหม่แต่ไม่ถือว่าค้าง)
  - เฟรมเดิมไม่ถูกคืนซ้ำ — สำคัญกับ S0/D2: เฟรมซ้ำจะถูกนับว่า ROI นิ่ง (clean_bg / watch / ตั้งพื้นหลังใหม่) ผิด
  - กล้องค้าง → log `📷 กล้องค้าง` + reader รุ่นใหม่เปิดกล้องใหม่; thread เก่าที่ค้างใน cap.read() เลิกเองเมื่อคืน
    (ไม่ release cap ข้าม thread เพราะ OpenCV ไม่ปลอดภัย) — บน V4L2 ถ้าตัวเก่ายังถือ /dev/video0 การเปิดใหม่อาจล้มเหลว
    แล้ววนลองใหม่ทุก CAMERA_RECONNECT_SEC จนตัวเก่าคืน (ต้องทดสอบที่ตู้จริง)
  - ไฟล์วิดีโอ: reader หน่วงตาม FPS เอง (`pace()` ใน main ถูกลบ) — e2e วัดคาบวนคลิปได้ 15.07s เท่าเดิม
- main: `NO_NEW_FRAME` → ประมวลผลคำสั่ง/timeout ตามปกติแต่ไม่ตรวจจับ (ไม่แตะ self.frame) ; `None` → camera gap
  ตามกติกาเดิม (ACTIVE → BLOCKED, ล้าง bg) — START/STOP ไม่ติดอยู่หลัง cap.read() อีกต่อไป
- config ใหม่ `CAMERA_STALL_SEC`=3.0
- tests: `tests/test_frame_source.py` 7 ข้อ (กล้องปลอมที่ค้าง/หลุด): ทุกเฟรมคืนครั้งเดียว / ค้าง → NO_NEW_FRAME ก่อนครบ
  แล้ว None + เปิดใหม่ได้เฟรม / หลุดแล้วกลับมา / ไฟล์วิดีโอเล่นตาม FPS / read() ไม่ block / main ประมวลผล STOP ระหว่าง
  ไม่มีเฟรมใหม่และไม่นับเฟรมซ้ำว่านิ่ง / กล้องค้างระหว่างรอบ → BLOCKED → STOP ปิด UNCERTAIN; รันซ้ำ 5 รอบไม่ flaky

## ไฟล์ที่เปลี่ยน (สะสม)
- S0: `core/background.py`, `main.py` (D2), `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (ข้อ 8, `.e2e_tmp/`),
  `.gitignore`, `docs/AUTORUN_TASK.md`, `docs/AUTORUN_REPORT.md`
- S1: `main.py`, `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (8b, 8c)
- S2: `config.py`, `main.py`, `.envexample`, `requirements*.txt`, `docker-compose.yml`, `Dockerfile`, `.dockerignore`,
  `.gitattributes`, `HANDOVER.md`, `ORANGE_PI_DOCKER.md`, `tests/test_config.py`, `tests/integration/docker_smoke.py`, `redis_e2e.py`
- S3: `core/removal.py` (ใหม่), `core/background.py`, `main.py`, `config.py`, `.envexample`, `tests/test_removal.py` (ใหม่), `redis_e2e.py` (7b)
- S4: `core/tracker.py`, `config.py`, `.envexample`, `tests/test_tracker.py` (ใหม่)
- S5: `core/frame_source.py`, `main.py`, `config.py`, `.envexample`, `tests/conftest.py`, `tests/test_frame_source.py` (ใหม่)

## ความหมายของ test ที่เปลี่ยน
- S0 (D2): `test_start_during_watch_uses_pre_motion_background` แยกเป็น
  `test_start_during_watch_while_item_falling_is_confirmed` (ของกำลังตกตอน START ยังนับได้) และ
  `test_start_during_watch_uses_latest_still_scene_not_watch_freeze` (ของนิ่งก่อน START ≥5 เฟรมไม่นับ — เหมือนตัวเก่า,
  ผู้ใช้อนุมัติแล้ว)

## คำถามรอผู้ใช้ (ประเภท A — ทำต่อไปแล้วด้วยทางที่ปลอดภัย)
- S1: ตั้งพื้นหลังใหม่หลัง env change สงบ ใช้ CLEAN_BG_STABLE_FRAMES (5 เฟรม ≈ 0.17s) ร่วมกัน ไม่แยกค่า
  ทางอื่น: แยกค่า ENV_SETTLE_FRAMES ให้นานกว่า (เช่น 15) → กันการตั้งใหม่ตอน slat ค้างกลางทางได้ดีขึ้น แต่ถาดต้องนิ่งนานขึ้นก่อนเห็นของ
- S5: `CAMERA_STALL_SEC`=3s (กล้อง USB สะดุดสั้น ๆ ไม่ถือว่าค้าง) — ทางอื่น: 1–2s จับกล้องค้างไวขึ้น
  แต่เสี่ยงทำรอบเป็น BLOCKED/UNCERTAIN จากการสะดุดชั่วคราว
- S4: STRICT_STABILITY default เปิด (ผ่านเกณฑ์ ≤ +0.3s) — ทางอื่น: ปิดไว้ก่อนจนทดสอบที่ตู้จริง (เร็วกว่า ~0.15s
  แต่ของที่ไถลระหว่างรอถ่ายยังถูกถ่ายได้) ปรับได้ด้วย `STRICT_STABILITY=0`
- S3: เมื่อ "ไม่แน่ใจว่าหยิบออก" (ขอบลดแต่ไม่มีฉากก่อนหน้ายืนยัน เช่นเปิดเครื่องตอนมีของในถาด หรือของเรียบกว่าพื้นถาด)
  เลือก **ไม่ส่ง S0** + anomaly POSSIBLE_REMOVAL (`REMOVAL_UNCERTAIN_SEND_S0=0`)
  ทางอื่น: `=1` → ยืนยันตามปกติ — ได้ S0 ของจริงที่เรียบกว่าพื้นถาด แต่กลับไปเสี่ยง S0 ผิดแบบข้อ 7 ตอนไม่มีประวัติฉาก
- S3: ไม่ทำ B_empty calibration (ภาพถาดว่างที่ผู้ติดตั้งเก็บ) — เหตุผล: แสงในตู้เปลี่ยนตามเวลา ภาพตายตัวจะเก่าเร็ว
  และ scene history ให้ข้อมูลเดียวกันแบบสดอยู่แล้ว; จะช่วยเฉพาะกรณี UNCERTAIN หลังเปิดเครื่อง
  ทางอื่น: ทำเป็น optional (`data/empty_tray.png` + ปุ่ม/คำสั่งเก็บภาพ) ใช้เป็นฉากก่อนหน้าเพิ่มอีก 1 ฉาก
- S3: ระบบตรวจหยิบออกใช้เฉพาะรอบ ACTIVE; ในช่วง CONFIRMED_WAIT_STOP / นอกรอบ รอยหยิบยังถูกบันทึกเป็น
  EXTRA_AFTER_CONFIRM / OUTSIDE_CYCLE เหมือนเดิม (ไม่กระทบยอด) — ถ้าต้องการให้ติดป้าย POSSIBLE_REMOVAL ด้วยทำเพิ่มได้
- S2: HANDOVER/ORANGE_PI ระบุ "หยุดโปรแกรมตัวเก่า" แบบทั่วไป (systemctl / kill) เพราะไม่รู้ว่าบอร์ดจริงรันตัวเก่าอย่างไร
  → ควรเติมคำสั่งจริงของตู้
- S2: ยังไม่ได้ build บน Orange Pi (arm64) จริง — ทดสอบเฉพาะ amd64 ใน WSL
- S1: ของที่ตก "พร้อมกับ" ตอน env change (เช่นตกขณะ slat ปิด) จะถูกกลืนเข้าพื้นหลังใหม่ → ไม่ยืนยัน (ไม่ส่ง S0) — เลือกทางกัน S0 ผิด

## Known limitations
- ~~ข้อ 7~~ แก้แล้วใน S3 (+S1 ในกรณีมี env change) — เหลือ: ของที่เรียบกว่าพื้นถาดมาก หรือไม่มีฉากก่อนหน้า → UNCERTAIN → ไม่ส่ง S0
- ของที่นิ่งอยู่ก่อน START ≥5 เฟรม ไม่ถูกนับในรอบนั้น (เหมือนตัวเก่า)
