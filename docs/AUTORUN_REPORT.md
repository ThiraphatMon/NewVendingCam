# AUTORUN_REPORT — ความคืบหน้างานต่อเนื่อง (branch `auto/round1-finish`)

> คำสั่งหลัก: `docs/AUTORUN_TASK.md` | review: `git log main..auto/round1-finish`
> **สถานะ: ครบทุกขั้น S0–S13 ไม่มีขั้นที่ถูกข้าม ไม่มี AUTORUN BLOCKED** — ไม่ได้ push / merge / แตะ main
> **รอบ OBSERVE (`docs/AUTORUN_TASK_OBSERVE.md`) S17–S21 ครบ ไม่มี AUTORUN BLOCKED** — สรุปอยู่ท้ายไฟล์ (หัวข้อ "รอบ OBSERVE")

## สรุปผลล่าสุด (S9–S13 — cloud/เว็บ)
- pytest: **166 passed** (+32 ใน `tests/test_cloud.py`, `tests/test_roi_sync.py` — cloud ทดสอบกับ stub HTTP ในเครื่อง ไม่ยิง server จริง)
- redis_e2e: **ผ่านทุกข้อ** 1, 2, 3, 4, 5, 6, 7, 7b, 8, 8b, 8c ทุกขั้น S9–S13 (e2e รันด้วย `CLOUD_ENABLED=0`)
- START→S0 (S13): ข้อ 1 = 3.05s, ข้อ 3 = 3.05s / 3.26s
  (ข้อ 3 รอบสอง 3.01–3.26s แกว่งตามรอบ — รันซ้ำที่ S13 ได้ 3.22s, 3.01s / ที่ S10 ได้ 3.04s, 3.05s: ไม่ใช่ช้าลงถาวร
  รอบสองของข้อ 3 START ใช้เฟรมปัจจุบันเป็นพื้นหลังจึงแกว่งได้)
- ทดสอบ main.py จริง + Redis ทดสอบ + stub HTTP (`CLOUD_ENABLED=1`, ROI_POLL/CHECK 0.5s, RETRY_INTERVAL 4s) 4 รอบ:
  ปกติ / เว็บเปลี่ยน ROI ระหว่าง ACTIVE / server ค้าง / server ปิด → S0 ทุกรอบ 3.03–3.05s, ยอด 4, CONFIRMED ×4;
  ITEM_LANDED ส่งหลัง S0 ทันที (field ครบ + landed_image ~106KB), 2 รายการที่ค้างตอน server ค้าง/ปิด ส่งครบ 1.5s หลัง server กลับ;
  ROI ใหม่ log "รอใช้" แล้วใช้ตอน STOP; ภาพ confirmed ในเครื่องครบ 4 ภาพ
- บูตตอน server ปิด 12s: register / push ROI ลองใหม่ 5s → 10s แล้วสำเร็จเอง 7.8s หลัง server เปิด
- Docker smoke: ไม่ได้รันซ้ำตั้งแต่ S6 (S9–S13 ไม่แตะ Dockerfile/compose)

## สถานะแต่ละขั้น

| ขั้น | สถานะ | commit | pytest | e2e (1–6, 8 / 7) | START→S0 ข้อ 1 / ข้อ 3 |
|---|---|---|---|---|---|
| S0 ตั้งต้น + D2 baseline freshness | ✅ เสร็จ | `1694b6f` | 100 passed | ✅ / ❌ (คาดไว้) | 3.41s / 3.40s, 3.40s |
| S1 ปิดงาน D2 (ตั้งพื้นหลังใหม่หลัง env change สงบ) | ✅ เสร็จ | `2645e87` | 103 passed | ✅ (+8b, 8c) / ✅* | 3.41s / 3.41s, 3.42s |
| S2 ขั้น E (พร้อมลง Orange Pi) | ✅ เสร็จ | `753a07f` | 107 passed | ✅ (+8b, 8c) / ✅ | 3.40s / 3.43s, 3.39s |
| S3 แยกหยิบออก / ใส่เข้า (ข้อ 7) | ✅ เสร็จ | `4ccca22` | 120 passed | ✅ (+7b, 8b, 8c) / ✅ (7b ผ่านด้วย S3 ล้วน) | 3.42s / 3.42s, 3.39s |
| S4 ความนิ่งของ tracker | ✅ เสร็จ (default เปิด) | `215105d` | 126 passed (ทั้ง 2 โหมด) | ✅ ทั้ง 2 โหมด | ปิด 3.42s / 3.40s, 3.38s · เปิด 3.54s / 3.56s, 3.56s |
| S5 กล้องค้าง | ✅ เสร็จ | `4665040` | 133 passed | ✅ / ✅ | 3.54s / 3.55s, 3.55s |
| S6 สรุป | ✅ เสร็จ | `552649e` | 133 passed | ✅ ทุกข้อ (1–7, 7b, 8, 8b, 8c) + Docker smoke PASS | 3.51s / 3.55s, 3.53s |
| S7 CAPTURE_HOLD_SEC 1.0 | ✅ เสร็จ | `b59c9bb` | 133 passed | ✅ ทุกข้อ (1–7, 7b, 8, 8b, 8c) | 3.03s / 3.03s, 3.04s |
| S8 log การตัดสิน S3 ระดับ INFO | ✅ เสร็จ | `d42d2fa` | 134 passed | (ไม่ได้รัน — เปลี่ยนแค่ log) | - |
| S9 สวิตช์ cloud ทีละฟีเจอร์ | ✅ เสร็จ | `3456861` | 144 passed | ✅ ทุกข้อ | 3.05s / 3.05s, 3.01s |
| S10 ภาพสด 60s q80 | ✅ เสร็จ | `cdb87d4` | 146 passed | ✅ ทุกข้อ | 3.06s / 3.04s, 3.02s |
| S11 ITEM_LANDED ผ่าน outbox | ✅ เสร็จ | `59d464d` | 157 passed | ✅ ทุกข้อ | 3.02s / 3.04s, 3.24s |
| S12 ROI จากเว็บรอใช้ตอนจบรอบ | ✅ เสร็จ | `81e3d04` | 161 passed | ✅ ทุกข้อ | 3.01s / 3.05s, 3.25s |
| S13 register / push ROI backoff | ✅ เสร็จ | `5a3d7d2` | 166 passed | ✅ ทุกข้อ | 3.05s / 3.05s, 3.26s |

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

### S8
- log 1 บรรทัดทุกครั้งที่ S3 ตัดสิน candidate: ADDITION ระดับ INFO (เดิม DEBUG), REMOVAL/UNCERTAIN ระดับ WARNING เหมือนเดิม
  ทุกบรรทัดมี `S3=<ผล>`, ขอบ ×, ความต่างจากพื้นหลังรอบ/ฉากก่อนหน้า, เกณฑ์ที่ใช้ (`REMOVAL_EDGE_RATIO`,
  `REMOVAL_MATCH_RATIO` × พื้นหลังรอบ) และผล (ยืนยัน / ไม่ยืนยัน)
  ตัวอย่าง: `🔍 รอบ 8e53bc04: S3=ADDITION candidate เป็นของใส่เข้า (ขอบ ×1.13, ต่างจากพื้นหลังรอบ 46.8, ต่างจากฉากก่อนหน้า 47.3 | เกณฑ์: ขอบ < 0.60 = ขอบลด, ฉากก่อนหน้า < 23.4 (พื้นหลังรอบ ×0.50) = ตรง) → ยืนยัน`
- pytest 134 passed (+1 `test_addition_verdict_logged_at_info_with_threshold`)

### S9 — สวิตช์ cloud ทีละฟีเจอร์
- config: `CLOUD_ENABLED` เป็นสวิตช์หลัก (0 = ไม่มี HTTP เลย; 1 แต่ไม่มี `CLOUD_API_URL` = ปิดทั้งหมด),
  ใหม่ `CLOUD_ROI_SYNC`=1, `CLOUD_SEND_EVENTS`=1, `CLOUD_SEND_ANOMALY`=0 (เตรียมไว้ ยังไม่ส่ง), ภาพสดเปิด/ปิดด้วย `SEND_INTERVAL` (0 = ปิด)
  — `config.cloud_features()` / `cloud_summary()`; register ตู้ทำเสมอเมื่อเปิด cloud
- ใหม่ `api/cloud.py` `CloudServices`: เริ่มเฉพาะ thread ของฟีเจอร์ที่เปิด, ทุก thread หยุดได้ (`stop()` ตอนปิดโปรแกรม)
  ภาพสดย้ายจาก global ใน `client.py` มาเป็นของ CloudServices (main loop แค่ฝากเฟรม)
- startup log 1 บรรทัด: `☁️ Cloud: register=เปิด, ROI sync=เปิด (ทุก 10s), ภาพสด=เปิด (ทุก 60s q80), ITEM_LANDED=เปิด, anomaly=ปิด`
- `.envexample` / HANDOVER 7.1: ตารางสวิตช์ + โปรไฟล์ "ช่วงทดสอบ" (`CLOUD_SEND_EVENTS=1`, `SEND_INTERVAL=60`) /
  "ขายจริง" (`CLOUD_SEND_EVENTS=0`, `CLOUD_ROI_SYNC=1`, `SEND_INTERVAL=300`) + วิธีเปลี่ยนบนตู้
  (แก้ `.env` → `docker compose up -d --force-recreate` → `docker compose logs vending-cam | grep "Cloud:"`)
- tests: `tests/test_cloud.py` + fixture `cloud_stub` (stub HTTP 127.0.0.1 port สุ่ม) ใน conftest — ปิดแล้วไม่มี thread/HTTP,
  ปิดเฉพาะ ROI sync ไม่มี request `/roi`, stop แล้วไม่ยิงต่อ, ภาพสดเฟรมแรกทันทีแล้วตาม interval

### S10 — ภาพสด
- `SEND_INTERVAL` default 1 → **60**; ใหม่ `REALTIME_JPEG_QUALITY`=80 (1–100) ใช้เฉพาะ `send_frame()` — **ไม่ย่อขนาด** (640x480)
  ภาพหลักฐานยังบันทึกด้วย `cv2.imwrite` ค่าเดิม (มี test ยืนยัน)
- ขนาดจากคลิปทดสอบ: q95 เดิม ≈ 94KB/ภาพ → q80 ≈ 45KB → ทุก 60s ≈ 65MB/วัน, ทุก 300s ≈ 13MB/วัน (เดิมทุก 1s ≈ 8.3GB/วัน)
- test ที่เปลี่ยน: `test_summary_lists_each_feature` (เขียนใน S9) — ข้อความสรุปมี `q80` เพิ่ม (เปลี่ยนรูปแบบ log โดยตั้งใจ)

### S11 — ITEM_LANDED ผ่าน outbox
- ตาราง `cloud_outbox` (event_id UNIQUE, cycle_id, event, payload JSON, image_path, state PENDING/SENT, attempts, last_error,
  next_attempt_at, created/updated) สร้างด้วย `CREATE TABLE IF NOT EXISTS` ตอนเปิด DB **ไม่ bump user_version**
  → DB เดิมใช้ต่อได้ และ rollback image รุ่นก่อนยังเปิด DB ได้
- main: ยืนยัน → S0 → daily log → `_queue_item_landed()` เขียน outbox **transaction แยก** (ล้มเหลวแค่ log, ไม่ย้อนยอด/S0) → ปลุก worker
- worker `cloud-outbox` (connection ของตัวเอง, `mode=rw` ไม่สร้าง DB เอง): 2xx → SENT; ไม่สำเร็จ → PENDING + backoff 5s, 10s, 20s ...
  สูงสุด `RETRY_INTERVAL` (ใช้ wall clock เก็บใน DB → ข้าม restart ได้); ปิด `CLOUD_SEND_EVENTS` → ไม่เริ่ม worker รายการค้างหยุดส่ง ไม่ลบ
  (startup log จำนวนที่ค้าง)
- field ที่เว็บเดิมรับ: `machine_id`, `event=ITEM_LANDED`, `transaction_id=TXN-<YYYYMMDD-HHMMSS ไทย>-<cycle8>`, `item_no`=daily_sequence,
  `obj_id` (tracker id), `land_time` `%H:%M:%S` ไทย, `order_id=""` + ไฟล์ `landed_image` (ภาพ confirmed) — event_id = `ITEM_LANDED:<cycle_id>`
- `client.send_event()` ใหม่ (ไม่ลบภาพ); `retry_queue` ไม่ถูกเริ่มอีก (เหลือไฟล์ไว้พร้อมคำเตือนห้ามใช้กับภาพหลักฐาน)
- disk_cleanup: ภาพที่ยัง PENDING ใน outbox ไม่ลบแม้เก่าเกิน; อ่าน DB ไม่ได้ → ข้าม cleanup รอบนั้นทั้งรอบ
- tests: field ครบ + ภาพตรงไฟล์ + ภาพยังอยู่, retry 500/503 แล้ว SENT, backoff/last_error, ปิด events ไม่มีแถว/HTTP,
  ค้างข้าม restart + หยุดส่งตอนปิด, server ค้างไม่กระทบ S0/STOP และไม่มี HTTP บน main thread, DB เดิมได้ตารางใหม่โดย version ไม่เปลี่ยน,
  cleanup เก็บภาพ PENDING, worker ไม่สร้าง DB เอง

### S12 — ROI จากเว็บระหว่างรอบ
- `ROIManager.reload_if_changed(allow_apply)`: main ส่ง `allow_apply = (state == WAIT_START)` — ไฟล์ ROI เปลี่ยนระหว่างรอบ
  → log `🕒 พบ ROI ใหม่ระหว่างรอบ → รอใช้ตอนจบรอบ` ครั้งเดียว → ใช้ทันทีเมื่อกลับ WAIT_START (ไม่รอรอบเช็คถัดไป)
- ใช้ ROI ใหม่ → `_on_roi_changed()`: จบ watch (ถ้ามี), ล้าง tracker, `bg.forget_roi_history()` (clean_bg, นับความนิ่ง, scene history)
  — log `🗺️ ใช้ ROI ใหม่ (...) → ล้าง ...`; ไฟล์ ROI เสีย → ใช้ ROI เดิมต่อและไม่ล้างอะไร
- tests `tests/test_roi_sync.py`: ACTIVE รอใช้ (log ครั้งเดียว) แล้วใช้หลัง STOP / CONFIRMED_WAIT_STOP รอใช้และการยืนยันไม่กระทบ /
  WAIT_START ใช้ทันที + ล้าง watch/clean_bg/scene/tracker / ไฟล์เสียไม่ล้าง

### S13 — register / push ROI ตอนเริ่ม
- `register_machine()` / `push_default_roi()` คืนผลสำเร็จ; `CloudServices._retry_until_ok()` ลองใหม่ backoff 5s, 10s, ... สูงสุด
  `RETRY_INTERVAL` จนสำเร็จ (หยุดได้ด้วย stop)
- `push_default_roi` เดิมถาม ROI ไม่สำเร็จ (ไม่ใช่ 200) แล้ว PUT ROI ในเครื่องทับทันที → เปลี่ยนเป็นถือว่าล้มเหลวแล้วลองใหม่
  (กันทับ ROI ที่เว็บมีอยู่แล้วตอนเว็บ error ชั่วคราว)
- tests: register 500/502 แล้วสำเร็จ thread จบ / เว็บ 503 ต่อเนื่องไม่ busy-loop (2–8 ครั้งใน 0.6s ที่ backoff 0.05–0.2s) /
  push ไม่ PUT ตอนถามไม่สำเร็จ / เว็บมี ROI แล้วไม่ PUT / stop ตัดการรอ backoff

### S7
- ผู้ใช้ทดสอบกับของจริงแล้ว → default `CAPTURE_HOLD_SEC` 1.5 → **1.0** (`config.py`, `.envexample`, `HANDOVER.md`)
- pytest 133 passed โดยไม่ต้องแก้ test (ไม่มี test อิงค่า 1.5 ตรง ๆ ที่ fail; แก้แค่คอมเมนต์ใน `tests/conftest.py`)
- e2e ทุกข้อผ่าน — ข้อ 4 S0 1.10s หลัง Redis กลับ; ข้อ 7 ไม่มี S0; 7b จับได้ว่าหยิบออก (ขอบ ×0.36) → POSSIBLE_REMOVAL
- S3 กับของตกจริง: ทุกรอบที่ยืนยันใน e2e ถูกจัดเป็น "ใส่เข้า" ขอบ ×1.07–1.14 (เกณฑ์ 0.6)
  เทียบรันข้อ 1, 3 ด้วย hold 1.5s: ×1.11–1.14 → hold ที่สั้นลงไม่ทำให้ขอบของของตกจริงลดลง
  (ค่า ×1.52 ที่บันทึกใน S3 มาจากรอบที่พื้นหลังต่างกัน — ในรันเปรียบเทียบนี้ก็พบ ×1.52 ในรอบที่ 3 ของ hold 1.5s)

### S6
- `HANDOVER.md`: เพิ่มหัวข้อ 4.3 แยกหยิบออก/ใส่เข้า, 4.4 ความนิ่งแบบเข้ม, 4.5 กล้อง (reader thread), anomaly POSSIBLE_REMOVAL,
  ค่า config ใหม่, e2e 7b + docker_smoke, known limitations ปรับตามจริง (ข้อ 7 ลดเป็น MED + ข้อจำกัดใหม่ของ S3/S5),
  จุดระวังข้อ 8 (ห้ามประมวลผลเฟรมซ้ำ)
- Docker image build ใหม่จาก source ล่าสุด + smoke ผ่าน, รัน pytest + e2e ทั้งชุดรอบสุดท้าย (ตัวเลขด้านบน)

## ไฟล์ที่เปลี่ยน (สะสม)
- S0: `core/background.py`, `main.py` (D2), `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (ข้อ 8, `.e2e_tmp/`),
  `.gitignore`, `docs/AUTORUN_TASK.md`, `docs/AUTORUN_REPORT.md`
- S1: `main.py`, `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (8b, 8c)
- S2: `config.py`, `main.py`, `.envexample`, `requirements*.txt`, `docker-compose.yml`, `Dockerfile`, `.dockerignore`,
  `.gitattributes`, `HANDOVER.md`, `ORANGE_PI_DOCKER.md`, `tests/test_config.py`, `tests/integration/docker_smoke.py`, `redis_e2e.py`
- S3: `core/removal.py` (ใหม่), `core/background.py`, `main.py`, `config.py`, `.envexample`, `tests/test_removal.py` (ใหม่), `redis_e2e.py` (7b)
- S4: `core/tracker.py`, `config.py`, `.envexample`, `tests/test_tracker.py` (ใหม่)
- S5: `core/frame_source.py`, `main.py`, `config.py`, `.envexample`, `tests/conftest.py`, `tests/test_frame_source.py` (ใหม่)
- S6: `HANDOVER.md`, `docs/AUTORUN_REPORT.md`
- S7: `config.py`, `.envexample`, `HANDOVER.md`, `tests/conftest.py` (คอมเมนต์) / S8: `main.py`, `tests/test_removal.py`
- S9: `config.py`, `api/cloud.py` (ใหม่), `api/client.py`, `main.py`, `.envexample`, `HANDOVER.md`, `tests/conftest.py`, `tests/test_cloud.py` (ใหม่)
- S10: `config.py`, `api/client.py`, `.envexample`, `HANDOVER.md`, `tests/test_cloud.py`
- S11: `utils/state_store.py`, `utils/disk_cleanup.py`, `api/cloud.py`, `api/client.py`, `api/retry_queue.py` (คำเตือน), `main.py`,
  `config.py`, `.envexample`, `HANDOVER.md`, `tests/test_cloud.py`
- S12: `core/roi.py`, `core/background.py`, `main.py`, `HANDOVER.md`, `tests/test_roi_sync.py` (ใหม่)
- S13: `api/client.py`, `api/cloud.py`, `config.py`, `HANDOVER.md`, `tests/test_cloud.py`

รวม: `git diff --stat main..auto/round1-finish`

## ความหมายของ test ที่เปลี่ยน
- S0 (D2): `test_start_during_watch_uses_pre_motion_background` แยกเป็น
  `test_start_during_watch_while_item_falling_is_confirmed` (ของกำลังตกตอน START ยังนับได้) และ
  `test_start_during_watch_uses_latest_still_scene_not_watch_freeze` (ของนิ่งก่อน START ≥5 เฟรมไม่นับ — เหมือนตัวเก่า,
  ผู้ใช้อนุมัติแล้ว)
- S1–S13: ไม่มี test เดิมถูกลบหรือเปลี่ยนความหมาย — เพิ่มอย่างเดียว (100 → 166)
  (S10 แก้ข้อความที่คาดใน `test_summary_lists_each_feature` ซึ่งเพิ่งเขียนใน S9 เพราะ log สรุปมีคุณภาพ JPEG เพิ่ม)
  ข้อยกเว้นเล็ก: S5 ลบ `FakeSource.pace()` ใน conftest (main ไม่เรียกแล้ว) และให้ `FakeSource.read()` คืน `NO_NEW_FRAME` ได้

## คำถามรอผู้ใช้ (ประเภท A — ทำต่อไปแล้วด้วยทางที่ปลอดภัย)
- S11: เขียน outbox **หลัง** S0 ใน transaction แยก (ตามโจทย์ "ห้ามกระทบ S0") — ถ้าไฟดับในช่วงไม่กี่ ms ระหว่างยืนยันกับเขียน outbox
  event ของชิ้นนั้นจะไม่ถูกส่ง (ยอด/S0/ภาพอยู่ครบ) ทางอื่น: เขียนใน transaction เดียวกับการยืนยัน (ไม่หาย แต่ outbox error = ไม่มี S0)
- S11: `RETRY_INTERVAL` (60) เปลี่ยนความหมายเป็น "รอสูงสุดของ backoff" ใช้ร่วมกับ register/push ROI; BASE 5s เป็นค่าคงที่ใน `api/cloud.py`
- S11: ส่งไม่สำเร็จลองใหม่ไปเรื่อย ๆ ไม่มีจำนวนครั้งสูงสุด (เว็บตอบ 4xx ถาวรก็ลองทุก RETRY_INTERVAL) และภาพของรายการ PENDING ไม่ถูก cleanup
  → ถ้าเว็บปฏิเสธนาน ๆ ภาพสะสม (log `เก็บภาพเก่า ... รอส่งขึ้นเว็บ`) ทางอื่น: จำกัดอายุ/จำนวนครั้งแล้วเปลี่ยนเป็นสถานะ GAVE_UP
- S11: ปิด `CLOUD_SEND_EVENTS` ภายหลัง → รายการค้างอยู่ใน DB ตลอด และภาพของรายการนั้นถูกกันไม่ให้ cleanup ด้วย (ตามโจทย์ "หยุดส่ง ไม่ลบ")
- S11: ภาพหลักฐานหายไปก่อนส่ง (เช่นลบมือ) → ส่ง event โดยไม่มี `landed_image` + log warning (ไม่รู้ว่าเว็บรับได้ไหม)
- S12: ใช้ ROI ใหม่แล้ว START ถัดไปต้องรอถาดนิ่งใน ROI ใหม่ 5 เฟรม (~0.2s) ก่อนมี clean_bg — ถ้า START มาทันทีจะใช้เฟรมปัจจุบัน
- S9: `CLOUD_SEND_ANOMALY=1` ตอนนี้แค่แสดงใน log สรุป ยังไม่ส่งอะไร (รอยืนยันว่าเว็บรับ event ชนิดใหม่ได้)
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
(ฉบับเต็มอยู่ใน `HANDOVER.md` ข้อ 10)
- ~~ข้อ 7~~ แก้แล้ว (S1 กรณีมี env change + S3 แยกหยิบออก/ใส่เข้า) — เหลือ: ของที่เรียบกว่าพื้นถาดมาก หรือไม่มีฉากก่อนหน้า
  (เพิ่งเปิดเครื่องตอนมีของในถาด) → UNCERTAIN → ไม่ส่ง S0
- สินค้าที่ขอบ/ลายน้อยกว่าพื้นถาด อาจถูกมองว่า "หยิบออก" → ไม่ส่ง S0 (ยังไม่พบในคลิป ต้องทดสอบสินค้าจริง)
- จ่ายเกิน (2 ชิ้นในรอบเดียว) นับเป็น 1 + ภาพ EXTRA_AFTER_CONFIRM (ตามดีไซน์ S0 ครั้งเดียวต่อรอบ)
- ของที่นิ่งอยู่ก่อน START ≥5 เฟรม ไม่ถูกนับในรอบนั้น (เหมือนตัวเก่า)
- START ขณะฉากยังไม่นิ่ง → พื้นหลังไม่แน่นอน; ของที่ตกพร้อม slat ปิดอาจถูกกลืนตอนตั้งพื้นหลังใหม่ (ไม่ส่ง S0)
- ของชิ้นใหญ่เกิน 30% ของ ROI = env change ไม่ถูกนับ
- กล้องค้างบน V4L2: reader เก่าที่ค้างอาจถือ /dev/video0 จนเปิดใหม่ไม่ได้ชั่วคราว (ยังไม่ได้ทดสอบกับกล้องจริง)
- LPUSH timeout → UNKNOWN ไม่ส่งซ้ำ (controller อาจไม่ได้ S0) — ตั้งใจ กัน S0 ซ้ำ
- ทดสอบด้วยคลิปเดียว (`big1_pickup_cutted.mp4`) — ค่าเกณฑ์ใหม่ (REMOVAL_*, CLEAN_BG_*) ยังไม่ได้ยืนยันกับหลายตู้/หลายสภาพแสง

## สิ่งที่ต้องทดสอบที่ตู้จริง (ทำไม่ได้บน PC)
1. **Build บน Orange Pi (arm64)** — ทดสอบแค่ amd64 ใน WSL; ตรวจว่า pip ได้ wheel aarch64 (opencv-headless, numpy, redis, tzdata)
2. **หยุดโปรแกรมตัวเก่าก่อน** แล้ว `redis-cli MONITOR` ต้องเห็น RPOP CTRL จาก client เดียว (HANDOVER ข้อ 9 / ORANGE_PI_DOCKER ข้อ 4–5)
3. **controlled test**: START → ปล่อยของ → S0 ครั้งเดียว → STOP; START → ไม่มีของ → STOP → ไม่มี S0; ตรวจ daily log / ภาพ
4. **ซื้อต่อกัน** (ข้อ 8): ลูกค้าหยิบของแล้วซื้อชิ้นถัดไปทันที — ต้องได้ S0 ของชิ้นใหม่ และไม่มี S0 จากรอยหยิบ
5. **หยิบของออกระหว่างรอบ** (ข้อ 7) ด้วยมือจริง ทั้งแบบ slat บัง (env change) และไม่บัง — ดู log `ดูเหมือนหยิบออก`
6. **สินค้าทุกแบบที่ขาย** โดยเฉพาะของสีเรียบ/ไม่มีลาย บนพื้นถาดที่มีลาย — ต้องไม่ถูกมองว่า "หยิบออก" (log `🔍 รอบ ...: S3=ADDITION ... (ขอบ ×...`
   ระดับ INFO ใน logs/vending.log ทุกการตัดสิน (S8): ถ้าค่าขอบของสินค้าจริงเข้าใกล้ 0.6 ต้องปรับ `REMOVAL_EDGE_RATIO`)
7. **ถอดสาย USB กล้อง / กล้องค้าง** ระหว่างรอบ → รอบเป็น BLOCKED → STOP ปิดเป็น UNCERTAIN, กล้องกลับมาแล้วรอบถัดไปปกติ
   (เช็คว่าเปิด /dev/video0 ใหม่ได้ขณะ reader เก่ายังค้าง)
8. **เวลา START→S0 จริง** (คลิป ~3.0s ที่ hold 1.0s) และ CPU/RAM (`docker stats`) — scene history ใช้ RAM เพิ่ม ~3MB
9. **แสงในตู้เปลี่ยนตามเวลา** (กลางวัน/กลางคืน) — log `baseline ไม่แน่นอน` ไม่ควรเกิดบ่อยตอนถาดนิ่ง

## วิธี review / merge
```bash
git log --oneline main..auto/round1-finish      # 15 commit: autorun S0–S13 + report
git diff --stat main..auto/round1-finish
git diff main..auto/round1-finish -- core/ main.py config.py   # โค้ดหลัก
# ทดสอบซ้ำ
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tests\integration\redis_e2e.py --clip <big1_pickup_cutted.mp4>
# merge เมื่อพอใจ (ผู้ใช้ทำเอง — autorun ไม่ merge / push)
git checkout main && git merge --no-ff auto/round1-finish
```
แนะนำ review ทีละ commit (แต่ละขั้นผ่านประตูทดสอบของตัวเองก่อน commit) — ถ้าไม่ต้องการขั้นไหน revert เฉพาะ commit นั้นได้
(S4 / S5 แยกจาก S3 ได้; S3 ใช้ scene history ใน background.py; S1 ปิดได้ด้วย `ENV_SETTLE_REBASELINE=0`,
S3 ด้วย `REMOVAL_CHECK=0`, S4 ด้วย `STRICT_STABILITY=0`, cloud ทั้งหมดด้วย `CLOUD_ENABLED=0` หรือทีละฟีเจอร์ (HANDOVER 7.1) โดยไม่ต้อง revert)

---

# รอบ OBSERVE (S17–S21) — `docs/AUTORUN_TASK_OBSERVE.md`

> เหตุผล: ที่ตู้จริงมีออเดอร์แต่ของไม่ตก แล้วเงาลูกค้าเข้า ROI → S0 ผิด → deploy กลับเป็นโหมดเก็บข้อมูล (ไม่ส่งสัญญาณกลับ controller)
> ทำต่อบน `auto/round1-finish` · ไม่ push / ไม่ merge / ไม่แตะ main

### S17 — สวิตช์ `SEND_S0` (default 0 = โหมดเก็บข้อมูล)
- `config.py` / `.envexample`: `SEND_S0` (0/1) **default 0**
- `main.py`: `App(send_s0=...)` (None = ตาม config) — โหมด 0 ยืนยันตามปกติทุกอย่าง (latch CONFIRMED_WAIT_STOP, ภาพ, SQLite,
  daily log, ITEM_LANDED ตาม `CLOUD_SEND_EVENTS`) แต่ **ไม่เรียก `request_s0`**;
  log ตอนยืนยัน `... item confirmed ... -> S0 NOT SENT (observe mode)`;
  log startup 1 บรรทัด `S0 response: DISABLED (observe mode, SEND_S0=0)` / `S0 response: ENABLED (SEND_S0=1)`
- `api/redis_controller.py`: `send_s0=False` กันซ้ำอีกชั้น — `request_s0` ถูกทิ้ง + worker return ก่อน LPUSH เสมอ
  (ไม่มีทางเขียน `REDIS_RESPONSE_KEY` แม้มีคนเรียกผิด) · ยัง RPOP `CTRL` เหมือนเดิม · log worker แสดง `CAMERA disabled (SEND_S0=0)`
- `utils/state_store.py`: `confirm(..., send_s0=False)` บันทึกแถว `responses` เป็น state ใหม่ **`NOT_SENT`**
  (`last_error='observe mode (SEND_S0=0)'`, `updated_at` = เวลาที่จะได้ส่ง = เวลายืนยัน) → เทียบกับ `cycles.closed_at_utc` (STOP จริง) ได้
  - additive: เป็นแค่ค่า state ใหม่ ไม่เปลี่ยน schema / user_version → image เก่า rollback ได้
    (รุ่นเก่า expire เฉพาะ PENDING/FAILED จึงไม่แตะแถว NOT_SENT)
- เส้นทางที่เคยเขียน CAMERA ทั้งหมดในโหมด 0: ยืนยันปกติ (ไม่ขอส่ง), ส่งค้างหลัง Redis กลับ (ไม่มีคำขอค้าง + guard ใน worker),
  restart (S0 ค้างจาก process เก่าถูก EXPIRED ใน DB อย่างเดียว ไม่มีการส่ง — เหมือนเดิม) → ไม่มีทางเขียน
- pytest: **177 passed** (+6 ใน `tests/test_observe_mode.py`: default=0, ยืนยันปกติ, ส่งจริงเมื่อ =1, Redis หลุดแล้วกลับ,
  restart ที่มี PENDING ค้าง, controller send_s0=False ไม่ LPUSH แม้ถูกเรียก + ยัง RPOP — ใช้ fakeredis ที่จดทุกคำสั่งที่แตะ CAMERA)
- redis_e2e (`--send-s0 1,0` = ค่าเริ่มใหม่ รันทุกข้อ 2 โหมด): **ผ่านทุกข้อทั้ง 2 โหมด**
  - SEND_S0=1: ผลเหมือนเดิมทุกข้อ, MONITOR เห็น `LPUSH CAMERA` ตรงกับจำนวน S0 (ข้อ 1:1, 3:2, 4:1, 5:2, 8/8b/8c:1, อื่น 0)
  - SEND_S0=0: ทุกข้อ `llen CAMERA = 0` และ MONITOR ไม่เห็นคำสั่งใดที่แตะ CAMERA (นอกจาก LLEN/DEL ของตัวทดสอบ) ·
    outcome ทุกรอบใน DB เหมือนโหมด 1 ทุกข้อ · ข้อ 4 response=`NOT_SENT`
  - START→S0 (โหมด 1) ข้อ 1 = 3.05s, ข้อ 3 = 3.02s / 3.05s · START→confirm (โหมด 0, จาก `confirmed_at_utc`) ข้อ 1 = 3.03s, ข้อ 3 = 3.03s / 3.23s
- **จุดที่แก้เทสต์**: `tests/conftest.py` `make_app(send_s0=True)` — เทสต์เดิมทั้งหมดทดสอบพฤติกรรม SEND_S0=1
  (default ของ config เปลี่ยนเป็น 0) ไม่มีเทสต์เดิมถูกแก้เงื่อนไข
- e2e: ในโหมด 0 "S0" ของการตรวจเดิมนับจากแถว `NOT_SENT` ใน DB (= S0 ที่จะได้ส่ง) และเวลาวัดเป็น START→confirm
  (ข้อความในตารางยังเขียนว่า "START→S0" ตามเดิม) · เพิ่มการตรวจ 2 แถวต่อข้อในโหมด 0 (ไม่แตะ CAMERA / outcome เหมือนโหมด 1)
- **พบระหว่างทำ (สภาพแวดล้อม ไม่ใช่โค้ด)**: WSL 2.7.12 ปิด distro ที่ไม่มี `wsl.exe` ค้าง ~15s หลังคำสั่ง docker สุดท้าย →
  ต่อ port 6380 จาก Windows ใหม่ไม่ได้ (connection เดิมยังอยู่ ข้อแรกผ่าน ข้อถัดไปต่อไม่ติด) → `redis_e2e.redis_up()` ค้าง
  `wsl -d Ubuntu -- sleep infinity` ไว้ตลอดการทดสอบ (`redis_down()` ปิด) — docker_smoke ใช้ร่วมด้วย

### S18 — `CAPTURE_HOLD_SEC` default 0.3 + วัดเวลาละเอียด
- `config.py` / `.envexample` / `HANDOVER.md`: default `CAPTURE_HOLD_SEC` 1.0 → **0.3**
- ทุกการยืนยัน log 1 บรรทัด (ASCII) `[cycle xxxxxxxx] timing: START->motion …s, START->item seen …s, seen->still …s
  (N frames, LANDING_STABLE_FRAMES=4, still resets R), still->hold done …s (CAPTURE_HOLD_SEC=0.3), S3 …ms, save …ms,
  START->confirm …s t0=<epoch>` — ใช้ทั้งที่ตู้จริงและ e2e (แปลงเป็นวินาทีคลิป)
  - `core/tracker.py` เพิ่มตัวนับสำหรับ log เท่านั้น (`frames`, `still_frame`, `still_resets`) **ไม่เปลี่ยนเกณฑ์ใด ๆ**
  - `main.py` จำเวลาเปิดรอบ / เฟรมแรกที่ tracker เห็นวัตถุในรอบ ACTIVE + จับเวลา S3
- e2e: `--hold X` (ส่ง `CAPTURE_HOLD_SEC` ให้ main.py) + หมายเหตุ `TIMING (วินาทีคลิป)` ของทุกการยืนยัน
- pytest **178 passed** (+1 `test_confirm_logs_timing_breakdown`: ช่วงเวลารวมกันได้ START→confirm, ≥ hold, ASCII)

**ตาราง S18 — แยกช่วงเวลา (วินาทีของคลิป, e2e ข้อ 1 รอบแรก, SEND_S0=1)**

| hold | START | เห็น motion แรก | เห็นของ (tracker obj ที่ยืนยัน) | นิ่ง = เริ่มนับ hold | ครบ hold | S3 | บันทึก (ภาพ+DB) | START→confirm | START→S0 (Redis) |
|---|---|---|---|---|---|---|---|---|---|
| 0.1 | 1.05 | 2.32 | 2.66 | 2.99 (9 เฟรม, reset 1) | 3.12 | 1ms | 39ms | 2.07s | 2.16s |
| **0.3** | 1.05 | 2.32 | 2.65 | 2.99 (9 เฟรม, reset 1) | 3.33 | 1ms | 37ms | 2.27s | 2.33–2.36s |
| 0.5 | 1.05 | 2.32 | 2.66 | 2.99 (9 เฟรม, reset 1) | 3.52 | 1ms | 30ms | 2.47s | - |
| 1.0 | 1.04 | 2.31 | 2.64 | 2.98 (9 เฟรม, reset 1) | 4.00 | 1ms | 23ms | 2.97s | (S7: 3.03s) |

ข้อ 3 (2 รอบคลิป) ได้ค่าเดียวกัน ±0.02s ทุก hold (เช่น hold 0.3: นิ่ง 2.98 → ครบ hold 3.28–3.31, START→confirm 2.24–2.27s)
ยกเว้นรอบที่ START ใช้เฟรมปัจจุบันเป็นพื้นหลัง: hold 1.0 ข้อ 3 รอบสอง เห็นของ 2.48 → นิ่ง 3.19 (21 เฟรม, reset 4)

สรุปว่านอกจาก hold กินเวลาที่ไหน (คลิปนี้):
- START → motion แรก **1.27s** = เนื้อหาคลิป (ของเริ่มตกที่ ~2.3s ของคลิป) ไม่ใช่เวลาประมวลผล
- motion แรก → เห็นของ **0.33s**: ช่วงของกำลังตก tracker เห็นเป็นก้อนอื่น/ก้อนแตก — object ที่ถูกยืนยันเกิดตอนของใกล้ถึงพื้น
- เห็นของ → นิ่ง **0.33s = 9 เฟรม**: `LANDING_STABLE_FRAMES=4` ต้องนิ่ง 4 เฟรมติดกัน + ของเด้ง 1 ครั้ง (still resets 1 —
  STRICT_STABILITY นับใหม่) → ถ้าไม่เด้งจะเหลือ ~5 เฟรม (0.17s)
- นิ่ง → ครบ hold = hold + ≤1 เฟรม (0.00–0.03s เพราะตรวจทีละเฟรม 30fps)
- S3 ~1ms, บันทึกภาพ+DB 20–40ms, S0 ผ่าน Redis +~0.06–0.09s (poll 50ms ของ worker / ฝั่งตัวทดสอบ)
- ⇒ เวลาคงที่หลังของถึงถาด ≈ 0.67s + hold (0.3) ≈ **1.0s** จากของแตะถาดถึงยืนยัน

**รัน e2e ครบทุกข้อที่ hold 0.1 และ 0.3 (ไม่แก้ตามโจทย์)**
- hold **0.3** (default ใหม่): ทุกข้อผ่าน **ทั้ง SEND_S0=1 และ 0** (66/66 การตรวจ) — ผลเหมือน hold 1.0 ทุกข้อ
- hold **0.1**: 21/22 ผ่าน — **ข้อ 7 เปลี่ยน**: START @5.0 (ของนิ่งอยู่ก่อน) → หยิบ @7s → **ยืนยันผิด S0 ที่ clip 9.23s** (ยอด 1)
  (hold 0.3 ข้อ 7 / 7b ยังไม่ยืนยัน — hold 0.1 สั้นกว่าช่วงที่ ENV_SETTLE_REBASELINE/S3 ใช้กันรอยหยิบ) → **ไม่ควรตั้งต่ำกว่า 0.3**
- หมายเหตุ: ข้อ 3 รอบสองของโหมด 1 ที่ hold 0.3 วัดได้ START→S0 3.33s (START ที่ clip 0.05 ของรอบคลิปที่ 2 — ช่วงรอยต่อการวนคลิป
  ของตัวทดสอบ ไม่ใช่โปรแกรมช้า; โหมด 0 รันเดียวกันได้ 2.33s)
- **พบระหว่างทำ (ตัวทดสอบ)**: keepalive ของ S17 (`wsl … sleep infinity`) ใช้ stdin ร่วมกับ main.py → Windows serialize I/O บน
  file object เดียวกัน → main.py ค้างตั้งแต่ init stdio แบบสุ่ม (ไม่มี output, "รอเวลาคลิป 1.0s ไม่ทัน") → แก้: `stdin=DEVNULL`
  ทั้ง keepalive และ main.py + e2e บันทึก DIAG (stdout ท้าย ๆ ของ main.py) เมื่อสถานการณ์ error · ผล e2e ของ S17 ด้านบนเป็นรันที่ไม่โดน
- จุดที่แก้เทสต์: `tests/conftest.py` คอมเมนต์ default hold เท่านั้น

### S19 — ภาพ anomaly
1. **ยกเลิก rate limit เดิม** (30 วิ/ภาพ, 20 ภาพ/ชม.): `config.py` ลบ `ANOMALY_MIN_INTERVAL_SEC` / `ANOMALY_MAX_PER_HOUR`
   (ถ้ายังตั้งใน .env → log เตือน "ยกเลิกแล้ว" ผ่าน `inactive_warnings`) · main ไม่ใช้ `AnomalyLimiter` แล้ว
   (class ยังอยู่ใน `core/cycle.py` พร้อมเทสต์เดิม เผื่อเปิดกลับ — ไม่ถูกเรียก)
   - ตรวจทุกชนิดว่าเกิด 1 ครั้งต่อเหตุการณ์ ไม่ใช่ทุกเฟรม: `OUTSIDE_CYCLE` / `EXTRA_AFTER_CONFIRM` / `POSSIBLE_REMOVAL` →
     rebaseline + ล้าง tracker ทุกครั้ง (ทำอยู่แล้วแม้ตอนเกินโควตา) ของเดิมจึงไม่ถูกจับซ้ำ · `NO_CONFIRM_AT_CLOSE` เกิดตอนปิดรอบครั้งเดียว
     → **ไม่มีชนิดเดิมที่ยิงซ้ำทุกเฟรม** ไม่ต้องเพิ่มกันซ้ำ (มีแค่ ENV_CHANGE ใหม่ที่ต้องมีกันซ้ำของตัวเอง)
2. **เพดาน `ANOMALY_MAX_PER_DAY=2000`** (ทุกชนิดรวม วันตาม `COUNT_TIMEZONE`): นับจาก DB ตอนเริ่มวัน/เริ่มโปรแกรม
   (`StateStore.count_anomaly_images` — ต่อข้าม restart) · ถึงเพดาน → ไม่เก็บภาพ (แถว DB ยังบันทึก evidence_path NULL)
   + log เตือน 1 ครั้งต่อวัน `anomaly image limit reached ...`
3. **anomaly ใหม่ `ENV_CHANGE`**: 1 ภาพตอนเริ่ม env change ทุก state (ผูก cycle_id ถ้าอยู่ในรอบ, นอกรอบ = nocycle)
   - ถ่ายแล้ว "disarm" จน ROI นิ่งครบ `CLEAN_BG_STABLE_FRAMES` (ใช้ `bg.roi_still()` ตัวเดียวกับ clean_bg) แล้ว env change ถัดไปจึงถ่ายใหม่
   - ถ่ายเฉพาะตอนฉากกำลังเปลี่ยน (ROI ไม่นิ่ง) — env change ที่ค้างตอนฉากนิ่ง (slat เปิดค้าง / bg แกว่งรอบเกณฑ์ 30%) ไม่นับเป็นเหตุการณ์ใหม่
   - หมายเหตุ: ช่วง WAIT_START env change เรียก `mark_scene_changed()` ทุกเฟรม (ของเดิม — เกณฑ์ clean_bg) → env change ค้าง = ยังไม่สงบ
     จนกว่า env change หายและถาดนิ่ง 5 เฟรม · ในรอบ (ACTIVE/CONFIRMED) ความนิ่งนับตามเฟรมต่อเฟรมล้วน
   - **ไม่เปลี่ยนตรรกะการตรวจจับ** (แค่อ่าน `env_change` / `roi_still()` แล้วบันทึกภาพ)
4. ภาพ anomaly ยังลบเมื่อเก่ากว่า 3 วัน (`ANOMALY_KEEP_DAYS`) เหมือนเดิม · ไม่ส่งขึ้นเว็บ
- pytest **183 passed** (+5 `tests/test_anomaly.py`: ไม่มี rate limit ทุกชนิด, เพดานต่อวัน + เตือนครั้งเดียว + นับต่อหลัง restart +
  ข้ามวันเก็บได้อีก, ENV_CHANGE ค้าง 40 เฟรม = 1 ภาพ, เปลี่ยน-สงบ-เปลี่ยน = 2 ภาพ, ENV_CHANGE ในรอบผูก cycle_id และของตกจริงยังยืนยันได้)
- redis_e2e: **ผ่านทุกข้อทั้ง SEND_S0=1 และ 0** (66/66) · ภาพ ENV_CHANGE ตามจริงในคลิป (หยิบ/slat 7.2–10.6s):

| ข้อ | ภาพ ENV_CHANGE | เวลาคลิป | หมายเหตุ |
|---|---|---|---|
| 7 | 2 | 7.3s, 9.1s | รอบ ACTIVE: slat เปิดค้างนิ่ง (~8.0s) → arm ใหม่ → slat ปิด = เหตุการณ์ที่ 2 |
| 7b | 2 | 7.3s, 8.1s | + POSSIBLE_REMOVAL |
| 8 | 1 | 7.3s | นอกรอบ (WAIT_START) — ทั้งช่วงหยิบเป็นเหตุการณ์เดียว |
| 8b | 1 | 7.3s | เหมือนข้อ 8 |
| ข้ออื่น | 1–2 | 7.3s (+8.1s) | ทุกข้อเห็นการหยิบที่ 7.3s; รอบที่ยังเปิดอยู่ (1, 3, 4) ได้ภาพที่ 2 ตอน slat ปิด |

- e2e: หมายเหตุใหม่ต่อข้อ `ENV_CHANGE: ภาพ N ภาพ (clip ...)` จากชื่อไฟล์ภาพ
- **จุดที่แก้เทสต์ (เงื่อนไขเปลี่ยนเพราะโจทย์ S19 ยกเลิก rate limit — ไม่ใช่เพราะ S0)**:
  - `test_evidence.py::test_outside_cycle_rate_limited` → `test_outside_cycle_one_image_per_event_no_rate_limit`
    (ลำดับเฟรมเดิม: เดิมคาด 1 ภาพภายใน 30s → ตอนนี้ 3 เหตุการณ์ = 3 ภาพ + ของนิ่งต่อไม่ถ่ายซ้ำ)
  - `test_evidence.py::test_extra_after_confirm_anomaly_rate_limited` → `..._one_image_per_item_no_rate_limit` (เดิม 1 แถว → 2 แถว 2 ภาพ)
  - `test_removal.py::test_possible_removal_recorded_even_when_over_image_quota`: ความหมายเดิม (เกินโควตา → แถว POSSIBLE_REMOVAL ไม่มีภาพ)
    คงไว้ แต่โควตามาจาก `ANOMALY_MAX_PER_DAY=1` (monkeypatch) แทน 30s

### S20 — log ภาษาอังกฤษ ASCII ล้วน
- ทุกข้อความที่ออก log/print ตอนรัน (main, core/*, utils/*, api/*, config startup summary / `.env` warnings / SystemExit)
  → ภาษาอังกฤษง่าย ๆ ASCII ล้วน ไม่มีอีโมจิ/อักษรไทย/× · ข้อความเกี่ยวกับรอบขึ้นต้น `[cycle <id8>]` · ใช้คำตามตารางในโจทย์
  (cycle opened/closed, item confirmed, item removed/uncertain/added, edge_ratio=, background / empty-tray background,
  env change, still, duplicate START (ignored), cycle timeout, interrupted (program restarted), camera disconnected / stalled / reconnecting,
  anomaly image, upload / outbox) · คอมเมนต์ / docstring / เอกสาร ยังเป็นไทย
  - `api/order_listener.py` / `api/retry_queue.py` (ระบบเดิม ไม่ถูกเรียกในโหมด START–STOP) แปลด้วยให้ครบ
- โครงที่เปลี่ยนเล็กน้อย (ข้อความเท่านั้น ไม่เปลี่ยนพฤติกรรม):
  - เปิดรอบ = 1 บรรทัด `[cycle x] START received -> cycle opened (background: empty-tray, age 0.3s)`
    (`BackgroundModel.start_cycle` เก็บคำอธิบายไว้ใน `start_desc`; บรรทัด background ของ START กรณีปกติลดเป็น DEBUG,
    กรณีไม่แน่นอนยังเป็น WARNING ของตัวเอง)
  - ปิดรอบ = `[cycle x] STOP received / next START received / cycle timeout -> cycle closed: <OUTCOME> (gap)`;
    note ของ CycleMachine ที่ซ้ำกับบรรทัดเปิด/ปิดรอบลดเป็น DEBUG (note ที่ไม่มีรอบเปิด/ปิด เช่น STOP ขณะ WAIT_START ยัง INFO)
  - `Verdict.describe(edge_threshold)` → `edge_ratio=1.12 (threshold 0.60), diff_bg=.., diff_prev=..`
  - คงไว้: รหัส anomaly, `S3=...`, daily log `dd/mm/yyyy HH:MM:SS : item drop : N`, ชื่อไฟล์ภาพ, ข้อความบนภาพ
- `docs/LOG_MESSAGES.md`: ตารางเทียบข้อความเดิม → ใหม่ ของรอบ, ยืนยัน, S3, S0, anomaly, พื้นหลัง/ROI, กล้อง, Redis, cloud, startup
- เทสต์ใหม่ `tests/test_log_ascii.py` (+2): ไม่มี string literal non-ASCII (ยกเว้น docstring) ในโค้ดที่รันทุกไฟล์ +
  log ทั้งรอบ (นอกรอบ, START ซ้ำ, ยืนยัน, ของเพิ่ม, STOP, กล้องหลุด) เป็น ASCII
- e2e: ทุกสถานการณ์ตรวจ "log ASCII ล้วน" ทุกบรรทัดของ stdout + `logs/vending.log` (fail ถ้ามีไบต์ > 0x7F)
- pytest **185 passed** · redis_e2e **ผ่านทุกข้อทั้ง 2 โหมด (88/88)** — log ASCII 22/22 รัน, START→S0 2.31–2.35s
- **จุดที่แก้เทสต์ (เฉพาะข้อความที่ค้นหา — ความหมายเดิม)**:
  - `test_evidence.py`: `ใช้ clean_bg (อายุ` → `empty-tray background (age`, `baseline ไม่แน่นอน` → `background uncertain`,
    `env change สงบแล้ว` → `env change settled` (3 จุด)
  - `test_removal.py`: `ดูเหมือนหยิบออก` → `-> item removed`, `ไม่แน่ใจว่าหยิบออก` → `-> uncertain`,
    ข้อความ S3 ADDITION: `ขอบ ×` / `ขอบ < 0.60` / `→ ยืนยัน` → `edge_ratio=` / `(threshold 0.60)` / `-> item added -> confirm`
  - `test_frame_source.py`: `กล้องค้าง` → `camera stalled` · `test_roi_sync.py`: `พบ ROI ใหม่ระหว่างรอบ` → `new ROI found during cycle`,
    `ใช้ ROI ใหม่ (rect)` → `new ROI applied (rect)` · `test_state_store.py`: `เปิด state DB ไม่ได้` → `cannot open state DB`
  - `test_cloud.py`: `ปิดทั้งหมด` → `all off`, `register=เปิด` / `ภาพสด=เปิด (ทุก 300s q80)` / `=ปิด` → `register=on` / `live image=on (every 300s q80)` / `=off`
  - `redis_e2e.py`: `เชื่อม Redis สำเร็จ` → `Redis connected` (ข้อ 4), `FROZEN [START` + `อายุ` → `cycle opened (background:` + `age`,
    `เฟรมปัจจุบัน` → `current frame` (8b), `ใช้ clean_bg` → `empty-tray` (8c), `env change สงบแล้ว` → `env change settled` (8b),
    7b `ดูเหมือนหยิบออก`/`ไม่แน่ใจว่าหยิบออก` → `-> item removed`/`-> uncertain`, คำค้น log ของข้อ 8 เป็นอังกฤษ

### S21 — สรุปรอบ OBSERVE
- `HANDOVER.md`: สถานะ observe mode ต้นไฟล์, ข้อ 2.1 `SEND_S0` (ตาราง 0/1, NOT_SENT ใน DB + SQL เทียบเวลา STOP, MONITOR ที่ตู้),
  ภาพ anomaly ใหม่ (ไม่จำกัดความถี่, ENV_CHANGE, เพดาน 2000/วัน), ตัวอย่าง log อังกฤษ, config (`SEND_S0`, hold 0.3, `ANOMALY_MAX_PER_DAY`),
  การทดสอบ (`--send-s0`, `--hold`, docker_smoke 2 โหมด, WSL keepalive), ขั้นตอนลงบอร์ด/controlled test ตาม observe mode, known limitations (hold < 0.3, ภาพ ENV_CHANGE มาก)
- `.envexample` / `ORANGE_PI_DOCKER.md`: ข้อความ log ที่อ้างถึงเป็นอังกฤษ + controlled test แยก SEND_S0=0/1
- `tests/integration/docker_smoke.py`: รัน image ทั้ง SEND_S0=0 (ไม่ตั้ง env = ค่าเริ่มของ image → ยืนยันใน DB, CAMERA ว่าง, MONITOR 0 คำสั่ง,
  log ASCII) และ SEND_S0=1 (S0 1 รายการ) — image build ใหม่จาก source ล่าสุด (`docker build -t vending-cam:autorun-test`, WSL amd64)

**ผลรันครบรอบสุดท้าย (S21)**
- pytest: **185 passed**
- redis_e2e ทุกข้อ (1, 2, 3, 4, 5, 6, 7, 7b, 8, 8b, 8c) **ทั้ง SEND_S0=1 และ 0: 88/88 ผ่าน**
  — SEND_S0=0 ไม่แตะ CAMERA 11/11 ข้อ (llen 0 + MONITOR 0 คำสั่ง), outcome ทุกรอบเหมือนโหมด 1 11/11, log ASCII 22/22 รัน
  — START→S0 (โหมด 1) ข้อ 1 = 2.33s, ข้อ 3 = 2.35s / 2.33s · START→confirm (โหมด 0) ข้อ 1 = 2.34s, ข้อ 3 = 2.32s / 2.34s
  — ภาพ ENV_CHANGE: ข้อ 7 = 2 (clip 7.3s, 9.1s), ข้อ 8 = 1 (7.3s), ข้อ 8b = 1 (7.3s)
- docker_smoke: **PASS ทั้ง 2 โหมด** — SEND_S0=0: START→confirm 2.34s, CAMERA `[]`, MONITOR `[]`, CONFIRMED, log ASCII ·
  SEND_S0=1: START→S0 2.32s, CAMERA `[b'S0']`, MONITOR `['LPUSH CAMERA S0']`

**ตารางขั้น S17–S21**

| ขั้น | commit | pytest | redis_e2e (ทุกข้อ) | หมายเหตุ |
|---|---|---|---|---|
| S17 สวิตช์ `SEND_S0` (default 0) | `2e43e05` | 177 passed | ✅ ทั้ง SEND_S0=1 และ 0 (CAMERA 0, outcome เท่ากัน) | START→S0 3.05s / START→confirm 3.03s (hold 1.0) |
| S18 hold 0.3 + timing | `e524d6c` | 178 passed | ✅ ทั้ง 2 โหมดที่ hold 0.3 (66/66) · hold 0.1: ข้อ 7 ยืนยันผิด (รายงาน ไม่แก้) | START→S0 2.33s |
| S19 ภาพ anomaly | `4ce3297` | 183 passed | ✅ ทั้ง 2 โหมด (66/66) | ENV_CHANGE ข้อ 7: 2, ข้อ 8/8b: 1 |
| S20 log อังกฤษ ASCII | `fe0785b` | 185 passed | ✅ ทั้ง 2 โหมด (88/88 รวม ASCII 22/22) | `docs/LOG_MESSAGES.md` |
| S21 สรุป | (commit นี้) | 185 passed | ✅ ทั้ง 2 โหมด (88/88) + docker_smoke PASS 2 โหมด | HANDOVER / .envexample / ORANGE_PI_DOCKER |

**ตารางเวลา S18** (วินาทีคลิป, e2e ข้อ 1) — รายละเอียดอยู่ในหัวข้อ S18

| hold | START | motion แรก | เห็นของ | นิ่ง (เริ่ม hold) | ครบ hold | S3 | บันทึก | START→confirm |
|---|---|---|---|---|---|---|---|---|
| 0.1 | 1.05 | 2.32 | 2.66 | 2.99 (9 เฟรม) | 3.12 | 1ms | 39ms | 2.07s |
| **0.3** | 1.05 | 2.32 | 2.65 | 2.99 (9 เฟรม) | 3.33 | 1ms | 37ms | 2.27s |
| 0.5 | 1.05 | 2.32 | 2.66 | 2.99 (9 เฟรม) | 3.52 | 1ms | 30ms | 2.47s |
| 1.0 | 1.04 | 2.31 | 2.64 | 2.98 (9 เฟรม) | 4.00 | 1ms | 23ms | 2.97s |

**จุดที่แก้เทสต์ทั้งหมด (S17–S21)** — ไม่มีเทสต์ถูกลบ
- S17 (S0 ถูกปิดเป็นค่าเริ่ม): `tests/conftest.py` `make_app(send_s0=True)` — เทสต์เดิมทั้งหมดทดสอบโหมด SEND_S0=1 ตามเดิม;
  e2e โหมด 0 นับ "S0" จากแถว NOT_SENT ใน DB และวัด START→confirm แทน START→S0
- S18: `tests/conftest.py` คอมเมนต์ default hold (0.3) เท่านั้น
- S19 (โจทย์ยกเลิก rate limit): `test_outside_cycle_rate_limited` → `test_outside_cycle_one_image_per_event_no_rate_limit`,
  `test_extra_after_confirm_anomaly_rate_limited` → `test_extra_after_confirm_one_image_per_item_no_rate_limit` (คาดภาพทุกเหตุการณ์แทนภาพเดียว),
  `test_possible_removal_recorded_even_when_over_image_quota` (ความหมายเดิม โควตาจาก `ANOMALY_MAX_PER_DAY=1` แทน 30s);
  เทสต์ `AnomalyLimiter` ใน `test_cycle.py` คงเดิม (class ยังอยู่ ไม่ถูกเรียก)
- S20 (log เปลี่ยนภาษา — แก้เฉพาะข้อความที่ค้นหา): `test_evidence.py` (5 จุด), `test_removal.py` (3), `test_frame_source.py` (1),
  `test_roi_sync.py` (2), `test_state_store.py` (1), `test_cloud.py` (3), `redis_e2e.py` (ข้อ 4, 7b, 8, 8b, 8c + การนับพื้นหลังของ START),
  `docker_smoke.py` (คำค้น log)
- ตัวทดสอบ (ไม่ใช่เงื่อนไข): `redis_e2e.py` keepalive WSL + `stdin=DEVNULL`, DIAG เมื่อสถานการณ์ error, `--send-s0`, `--hold`, MONITOR,
  หมายเหตุ TIMING / ENV_CHANGE, ตรวจ log ASCII

**ข้อสังเกต / คำถามรอผู้ใช้ (ประเภท A — ทำต่อด้วยทางที่ปลอดภัยแล้ว)**
- hold 0.1 ทำให้ข้อ 7 ยืนยันผิด → default 0.3 ตามโจทย์ผ่านทุกข้อ แต่ไม่ควรลดต่ำกว่านี้โดยไม่มีข้อมูลตู้จริง
- `AnomalyLimiter` เก็บไว้ (ไม่ถูกเรียก) เพื่อไม่แตะเทสต์เดิม — ลบได้ถ้าไม่ต้องการเปิดกลับ
- ENV_CHANGE ในคลิปนี้: ทุกการหยิบ (slat) ได้ 1–2 ภาพ — ตู้ที่มีเงาลูกค้าเข้า ROI บ่อยจะมีภาพมาก (เพดาน 2000/วัน) ซึ่งตรงกับจุดประสงค์เก็บข้อมูลเงา
- ก่อนเปิด `SEND_S0=1` ที่ตู้จริง: ใช้ SQL ใน HANDOVER 2.1 เทียบเวลา NOT_SENT กับ STOP จริง + ดูภาพ confirmed / ENV_CHANGE ของรอบที่ของไม่ตก
