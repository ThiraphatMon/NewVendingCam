# Vending Camera — เอกสารส่งมอบโปรเจค (Handover Document)

> สำหรับ developer / ผู้ติดตั้งที่รับโปรเจคต่อ อ่านจากบนลงล่าง: ระบบทำอะไร → วงจร START/STOP →
> การตรวจจับ → ข้อมูลที่เก็บ → config → การลงบอร์ด / rollback → ข้อจำกัดที่รู้แล้ว
> ขั้นตอนติดตั้ง Docker บน Orange Pi แบบละเอียดอยู่ที่ `ORANGE_PI_DOCKER.md`

---

## สารบัญ

1. [ระบบนี้คืออะไร](#1-ระบบนี้คืออะไร)
2. [Protocol กับ controller (Redis)](#2-protocol-กับ-controller-redis)
3. [วงจร START–STOP และ state diagram](#3-วงจร-startstop-และ-state-diagram)
4. [การตรวจจับสินค้า](#4-การตรวจจับสินค้า)
5. [ข้อมูลที่เก็บ: DB, daily log, ภาพหลักฐาน](#5-ข้อมูลที่เก็บ)
6. [โครงสร้างไฟล์](#6-โครงสร้างไฟล์)
7. [การตั้งค่า (.env)](#7-การตั้งค่า)
8. [การทดสอบ](#8-การทดสอบ)
9. [การลงบอร์ด / อัปเดต / rollback](#9-การลงบอร์ด--อัปเดต--rollback)
10. [Known limitations](#10-known-limitations)
11. [จุดที่ต้องระวังก่อนแก้โค้ด](#11-จุดที่ต้องระวังก่อนแก้โค้ด)

---

## 1. ระบบนี้คืออะไร

กล้องในช่องรับสินค้าของตู้ขายของอัตโนมัติ ทำหน้าที่ **ยืนยันว่ามีสินค้าตกลงมาจริง 1 ชิ้นต่อรอบการขาย**
แทนโปรแกรมเดิม `legacy_reference/main.py` โดยคุยกับ controller ของตู้ผ่าน Redis protocol เดิมทุกประการ

- controller ส่ง `START` เมื่อเริ่มปล่อยสินค้า และ `STOP` เมื่อจบรอบ
- กล้องเห็นของตกแล้วนิ่ง → บันทึกยอด + ภาพหลักฐาน → ส่ง `S0` กลับ **ครั้งเดียวต่อรอบ**
- ไม่เห็นของ → ไม่ส่งอะไรกลับ (เหมือนตัวเก่า) แต่บันทึกผลรอบไว้ใน DB
- ยอดรายวันเก็บใน SQLite (แหล่งจริง) และเขียน log รายวันให้อ่านง่าย

สิ่งที่ระบบ **ไม่** ทำ: จำแนกชนิดสินค้า, นับหลายชิ้นต่อรอบ (จ่ายเกินนับเป็น 1), ตัดสินเรื่องเงิน

---

## 2. Protocol กับ controller (Redis)

| ทิศทาง | คำสั่ง Redis | ค่า |
|---|---|---|
| controller → กล้อง | กล้อง `RPOP CTRL` (DB 0) | `START` / `STOP` (ตรงตัว อย่างอื่นทิ้ง + log) |
| กล้อง → controller | กล้อง `LPUSH CAMERA` | `S0` (ยืนยันสินค้า 1 ครั้งต่อรอบ) |

- **ห้ามเปลี่ยน** key / payload / RPOP-LPUSH — controller เดิมพึ่งพาสิ่งนี้ ไม่มีข้อความใหม่บน wire
- `api/redis_controller.py`: worker thread ตัวเดียวคุย Redis → ส่งเหตุการณ์ให้ main loop ทางคิว
  Redis ล่ม/ช้า → backoff เอง กล้องและการประมวลผล STOP ไม่ค้าง
- S0 ส่งไม่เกิน 1 ครั้ง: ปิด retry ของ client, LPUSH error/timeout = สถานะ UNKNOWN ห้ามส่งซ้ำ
  (อาจได้ S0 สองรายการ), ปิดรอบแล้วเพิกถอน S0 ที่ยังไม่ได้ส่ง (EXPIRED)
- **ห้ามมีโปรแกรม RPOP CTRL สองตัวพร้อมกัน** (ตัวเก่า + ตัวใหม่ จะแย่งคำสั่งกัน) — ดูขั้นตอนลงบอร์ดข้อ 9

---

## 3. วงจร START–STOP และ state diagram

`core/cycle.py` (`CycleMachine`) — pure logic ไม่แตะ I/O, main loop เป็นเจ้าของตัวเดียว

```
  WAIT_START ──START──▶ ACTIVE ──ยืนยันสำเร็จ (ส่ง S0)──▶ CONFIRMED_WAIT_STOP
       ▲                  │ กล้องหลุด / ไม่มีพื้นหลังก่อน START
       │                  ▼
       │           BLOCKED_WAIT_STOP  (ห้ามยืนยันจนปิดรอบ)
       └── STOP / ครบ CYCLE_TIMEOUT_SEC (ทุก state ที่มีรอบเปิด)
```

ตอบสนองต่อลำดับคำสั่งเหมือนตัวเก่า:

| สถานะ | START | STOP |
|---|---|---|
| WAIT_START | เปิดรอบใหม่ | ไม่มีผล |
| ACTIVE | ไม่มีผล (anomaly ใน log, รอบเดินต่อ ไม่รีเซ็ตเวลา) | ปิดรอบ (UNCONFIRMED / UNCERTAIN) |
| CONFIRMED_WAIT_STOP | ปิดรอบ (CONFIRMED) + เปิดรอบใหม่ทันที | ปิดรอบ (CONFIRMED) |
| BLOCKED_WAIT_STOP | ปิดรอบ (UNCERTAIN) + เปิดรอบใหม่ทันที | ปิดรอบ (UNCERTAIN) |

outcome ของรอบ (เก็บใน DB เท่านั้น):

| outcome | ความหมาย |
|---|---|
| CONFIRMED | ยืนยันแล้ว ส่ง S0 แล้ว |
| UNCONFIRMED | ไม่เห็นสินค้า ภาพและ Redis ต่อเนื่องตลอดรอบ |
| UNCERTAIN | ไม่เห็นสินค้า แต่ระหว่างรอบกล้องหลุดหรือ Redis ขาด → บอกไม่ได้ว่าไม่มีของจริง |
| TIMEOUT | ไม่เห็นสินค้า และไม่มี STOP ภายใน `CYCLE_TIMEOUT_SEC` (300s) |
| INTERRUPTED | process ตายกลางรอบ — restart แล้วปิดรอบค้างเป็นค่านี้ + S0 ที่ค้างหมดอายุ แล้วรับ START ใหม่ได้ทันที |

---

## 4. การตรวจจับสินค้า

### 4.1 หลักการ: background subtraction ใน ROI
- `diff = |frame − bg|` เฉพาะใน ROI (`data/roi_config.json`) → mask → กล่อง → tracker
- **ของตก = เคลื่อนที่แล้วมานิ่ง:** centroid นิ่งครบ `LANDING_STABLE_FRAMES` (4) เฟรม → SHAPE_CONFIRMED
  → นิ่งต่ออีก `CAPTURE_HOLD_SEC` (1.5s) → ยืนยัน (ในคลิปทดสอบ START→S0 ≈ 3.4s)
- ก้อนใหญ่เกิน `MAX_BLOB_ROI_RATIO` (30%) ของ ROI = **env change** (แสง/slat/มือบัง) ไม่ใช่ของ

### 4.2 พื้นหลังของรอบ (สำคัญที่สุด)
`core/background.py` (`BackgroundModel`):

- **clean_bg** = เฟรมล่าสุดที่ ROI นิ่ง **เฟรมต่อเฟรม** (เปลี่ยน ≤ `CLEAN_BG_MAX_MOTION_RATIO` ติดกัน
  `CLEAN_BG_STABLE_FRAMES` เฟรม) เก็บเฉพาะตอน WAIT_START (รวมระหว่าง watch / grace)
- ROI เปลี่ยนเกินเกณฑ์ หรือ env change ระหว่าง WAIT_START → clean_bg **หมดสภาพทันที**
  ต้องนิ่งใหม่ครบ N เฟรมจึงใช้ได้ → clean_bg ที่ใช้ตอน START เก็บหลังการเปลี่ยนแปลงล่าสุดเสมอ
- **START:** ใช้ clean_bg ที่ valid → ไม่มี (ฉากยังไม่นิ่ง) ใช้เฟรมปัจจุบัน + log `baseline ไม่แน่นอน`
  (เหมือนตัวเก่าที่ใช้เฟรมแรกหลัง START) แล้ว freeze ทั้งรอบ
- **env change สงบ (รอบ ACTIVE):** env change ยังค้างแต่ ROI นิ่งครบ N เฟรม → ตั้งพื้นหลังของรอบเป็นเฟรมนั้น
  + ล้าง tracker (log `env change สงบแล้ว`) — เช่น START ตอน slat ยังเปิด แล้ว slat ปิด
- **หลังยืนยัน:** `rebaseline()` เฟรมปัจจุบันเป็นพื้นหลังใหม่ → ของชิ้นถัดไปเป็น motion ใหม่ (→ anomaly)
- **ปิดรอบ:** unfreeze + grace `RESET_GRACE_SEC` (re-learn เร็ว ดูดมือที่ค้างเข้า bg) + ทิ้ง clean_bg

### 4.3 Watch mode (นอกรอบ)
WAIT_START แล้วมี motion ใน ROI → freeze bg (ฉากก่อนมีการเปลี่ยนแปลง) เพื่อให้ของที่วางนิ่งนอกรอบ
ไม่ถูกกลืนก่อนครบเกณฑ์ → ถ่ายภาพ anomaly `OUTSIDE_CYCLE` (ไม่นับยอด ไม่ส่ง S0) แล้ว rebaseline
จบเมื่อ ROI นิ่งครบ N เฟรม **และ** tracker ว่าง หรือเฝ้าครบ 25s → unfreeze + grace
START ระหว่าง watch → เลิกเฝ้า ใช้พื้นหลังตามข้อ 4.2 (ไม่ใช้ bg ที่ freeze ไว้ตอนเริ่มเฝ้า)

---

## 5. ข้อมูลที่เก็บ

| ที่เก็บ | เนื้อหา | หมายเหตุ |
|---|---|---|
| `data/vending_state.sqlite3` | ตาราง `cycles`, `confirmations`, `anomalies`, `responses` | **แหล่งจริงของยอด** ห้ามลบ / ห้ามแก้มือ — DB เสีย = โปรแกรมหยุด ไม่นับต่อ |
| `logs/item_drops/YYYY-MM-DD.log` | `05/10/2026 13:45:12 : item drop : 1` บรรทัดละการยืนยัน | ภาพสะท้อนของ DB, startup สร้างไฟล์ของวันนี้ใหม่จาก DB (ซ่อมหลัง crash) ห้ามใช้กู้ยอด |
| `logs/vending.log` | operational log (หมุนไฟล์ ~25MB) | ดูการเปิด/ปิดรอบ, พื้นหลังที่ใช้, Redis |
| `evidence_images/confirmed/` | ภาพตอนยืนยัน 1 ภาพต่อการยืนยัน | ลบอัตโนมัติเกิน `CLEANUP_KEEP_DAYS` |
| `evidence_images/anomaly/` | `OUTSIDE_CYCLE`, `EXTRA_AFTER_CONFIRM` (จำกัดความถี่), `NO_CONFIRM_AT_CLOSE` (ทุกรอบที่ไม่ยืนยัน) | ไม่นับยอด, ลบเกิน `ANOMALY_KEEP_DAYS` |

ลำดับการยืนยัน (ล้มเหลวขั้นไหน = ไม่มียอด ไม่มี S0): บันทึกภาพ → DB (transaction เดียว) → latch รอบ → S0 → daily log
ยอดรายวันนับตาม `COUNT_TIMEZONE` (Asia/Bangkok) ไม่ขึ้นกับเวลาเครื่อง

---

## 6. โครงสร้างไฟล์

```
main.py                 App: main loop (อ่านเฟรม → คำสั่ง → ตรวจจับ → ยืนยัน/anomaly), startup, จอ debug
config.py               ค่าตั้งทั้งหมดจาก .env + เตือนค่าที่ไม่มีผล (inactive_warnings)
core/cycle.py           state machine ของรอบ START–STOP
core/background.py      background model, clean_bg, freeze/rebaseline, env change
core/detect.py          mask → กล่อง (morphology, contour, group)
core/tracker.py         จำวัตถุข้ามเฟรม + ความนิ่ง
core/roi.py             ROI จาก data/roi_config.json (reload อัตโนมัติ)
core/frame_source.py    กล้อง / ไฟล์วิดีโอ (เล่นตามเวลาจริง วนซ้ำ)
api/redis_controller.py RPOP CTRL / LPUSH CAMERA (worker thread)
api/client.py, retry_queue.py, order_listener.py   ฝั่ง cloud/order เดิม (ใช้เฉพาะ CLOUD_ENABLED=1; order listener ไม่ถูกเริ่ม)
utils/state_store.py    SQLite (รอบ / ยืนยัน / anomaly / สถานะ S0)
utils/daily_log.py      log ยอดรายวัน
utils/image_saver.py    บันทึกภาพหลักฐาน
utils/disk_cleanup.py   ลบภาพเก่า
ui/overlay.py           วาดจอ debug (HEADLESS=0)
legacy_reference/main.py  โปรแกรมเดิม (อ้างอิงพฤติกรรม ห้ามลบ)
tests/                  pytest (unit) + tests/integration/redis_e2e.py (Redis จริงใน Docker + คลิป)
```

---

## 7. การตั้งค่า

แก้ที่ `.env` เท่านั้น (คัดลอกจาก `.envexample`) — คำอธิบายทุกค่าอยู่ใน `config.py`
ตอนเริ่มโปรแกรม log `Active config` ทั้งหมด และเตือน `⚠️ .env: ... ไม่มีผล` ถ้าตั้งค่าที่ไม่มีผลกับโหมดที่รัน

| หมวด | ค่าที่สำคัญ |
|---|---|
| 1 ตู้/การเชื่อมต่อ | `MACHINE_ID_DEFAULT`, `CAMERA_INDEX`, `HEADLESS`, `CONTROL_MODE` (redis/keyboard), `REDIS_*`, `CLOUD_ENABLED` |
| 2 ความไว | `CAPTURE_HOLD_SEC` 1.5, `MOT_THRESH` 25, `MIN_AREA` 150, `MAX_BLOB_ROI_RATIO` 0.30, `LANDING_STABLE_FRAMES` 4, `CENTROID_STABLE_DIST` 10 |
| 3 รอบ | `CYCLE_TIMEOUT_SEC` 300 |
| 4 ขั้นสูง | `GROUP_*`, `MORPH_*`, `BG_*`, `RESET_GRACE_SEC`, `CLEAN_BG_INTERVAL` 0.5, `CLEAN_BG_MAX_MOTION_RATIO` 0.002, `CLEAN_BG_STABLE_FRAMES` 5 |
| 5 ระบบ | `STATE_DB_PATH`, `COUNT_TIMEZONE`, `DAILY_LOG_DIR`, `ANOMALY_*`, `CLEANUP_*` |

ค่าระบบ order เดิม (`WS_URL`, `ORDER_WINDOW`, `DROP_TIMEOUT`, ...) ไม่มีผลในโหมด START–STOP
ROI: `data/roi_config.json` (rect / quad / polygon / multi_polygon บนภาพ 640x480) แก้แล้ว reload เองภายใน `ROI_CHECK_INTERVAL`

---

## 8. การทดสอบ

```bash
pip install -r requirements-pc.txt -r requirements-dev.txt
python -m pytest -q                                            # unit tests (fake clock / กล้องปลอม / fakeredis)
python tests/integration/redis_e2e.py --clip <big1_pickup_cutted.mp4>   # main.py จริง + Redis จริง (Docker พอร์ต 6380)
```
- PC แบบมีจอ: `HEADLESS=0`, `CONTROL_MODE=keyboard` → กด `s` = START, `x` = STOP
- e2e ใช้ container `vendingcam-redis-test` พอร์ต 6380 เท่านั้น (สร้าง/ลบเอง) ไฟล์ชั่วคราวอยู่ `.e2e_tmp/`
- สถานการณ์ e2e: 1 ปกติ, 2 STOP ก่อนของตก, 3 สองรอบ, 4 Redis ดับระหว่างรอบ, 5 kill กลางรอบ, 6 ไม่มี START,
  7 ของนิ่งก่อน START แล้วถูกหยิบ, 8/8b/8c ซื้อต่อกันหลังลูกค้าหยิบนอกรอบ — **ห้ามลบสถานการณ์ใด**

---

## 9. การลงบอร์ด / อัปเดต / rollback

รายละเอียดคำสั่งติดตั้ง Docker อยู่ที่ `ORANGE_PI_DOCKER.md` ลำดับที่ต้องทำทุกครั้ง:

1. **หยุดโปรแกรมกล้องตัวเก่าก่อนเสมอ** (ตัวที่ `RPOP CTRL`) — สองตัวพร้อมกันจะแย่งคำสั่งกัน
   ตรวจ: `redis-cli MONITOR` ต้องเห็น `RPOP CTRL` จาก client เดียว
2. เตรียม `.env` (หมวด 1), `data/roi_config.json`, โฟลเดอร์ `data/ evidence_images/ logs/`
3. `docker compose up -d --build` → `docker compose logs -f vending-cam` ดู `Active config`, `เชื่อม Redis สำเร็จ`
   และไม่มี `⚠️ .env: ... ไม่มีผล` ที่ไม่ได้ตั้งใจ
4. **controlled test** (ตู้ไม่ขายจริง): `redis-cli MONITOR` ในอีกหน้าต่าง
   - `redis-cli LPUSH CTRL START` → ปล่อยของ 1 ชิ้น → เห็น `LPUSH CAMERA S0` ครั้งเดียว → `redis-cli LPUSH CTRL STOP`
   - `START` → ไม่ปล่อยของ → `STOP` → ต้องไม่มี S0
   - ตรวจ `logs/item_drops/<วันนี้>.log` และ `evidence_images/confirmed/`
5. เปิดขายจริง เฝ้า log ช่วงแรก

**อัปเดตแบบ rollback ได้:**
```bash
docker tag vending-cam:latest vending-cam:prev   # เก็บ image ที่ใช้อยู่
docker compose up -d --build                     # หลังได้ source ใหม่
# มีปัญหา → กลับ image เดิมทันที (ไม่ต้อง build):
docker tag vending-cam:prev vending-cam:latest && docker compose up -d --no-build
# กลับไปโปรแกรมตัวเก่า: docker compose down แล้วเปิดโปรแกรมเดิม (อย่าเปิดพร้อมกัน)
```
`data/` อยู่นอก container → rollback image ไม่ทำให้ยอดหาย (schema DB เปลี่ยนเมื่อไรต้องระบุใน release)

---

## 10. Known limitations

| ระดับ | ข้อจำกัด | สถานะ |
|---|---|---|
| HIGH | ของวางนิ่งก่อน START แล้วถูกหยิบออกระหว่างรอบ → หลุมที่ของเคยอยู่ถูกยืนยันเป็นสินค้า → S0 ผิด (e2e ข้อ 7) | ข้อ 7 ในคลิปผ่านแล้วเพราะการหยิบมี env change (slat) → ตั้งพื้นหลังใหม่หลังสงบ; การหยิบที่ไม่มี env change ยังเสี่ยง (Round 2) |
| MED | จ่ายเกิน (ของตก 2 ชิ้นในรอบเดียว) นับเป็น 1 + ภาพ anomaly `EXTRA_AFTER_CONFIRM` | ตามดีไซน์ (S0 1 ครั้งต่อรอบ) |
| MED | ของที่นิ่งอยู่แล้วก่อน START ≥ 5 เฟรม ถูกนับเป็นพื้นหลัง ไม่ยืนยันในรอบนั้น | เหมือนตัวเก่า |
| MED | START ขณะฉากยังไม่นิ่ง (มือ/slat) → พื้นหลังไม่แน่นอน; ของที่ตกพร้อม slat ปิดอาจถูกกลืนตอนตั้งพื้นหลังใหม่ (ไม่ส่ง S0) | เลือกทางกัน S0 ผิด |
| MED | ของชิ้นใหญ่กว่า 30% ของ ROI = env change ไม่ถูกนับ | ปรับ `MAX_BLOB_ROI_RATIO` / ROI |
| LOW | LPUSH timeout → สถานะ UNKNOWN ไม่ส่งซ้ำ (controller อาจไม่ได้ S0) | ตั้งใจ กัน S0 ซ้ำ |

---

## 11. จุดที่ต้องระวังก่อนแก้โค้ด

1. **คำสั่งก่อนผลตรวจจับเสมอ** ใน `App.step()` — STOP ที่มาระหว่างอ่านเฟรมต้องมีผลก่อนการยืนยัน
2. **ปิดรอบก่อนเปิดรอบใหม่** (`_apply`) — START ใน CONFIRMED_WAIT_STOP ต้องบันทึก CONFIRMED ก่อน
3. **rebaseline หลังยืนยัน/anomaly** + `tracker.clear_all()` — ไม่งั้นของเดิมถูกจับซ้ำทุกเฟรม
4. **grace หลัง unfreeze** — กันมือที่ค้างในเฟรมกลายเป็น blob หลอก
5. **ห้ามใช้ daily log กู้ยอด** — DB คือแหล่งจริง
6. `tracker.clear_all()` ไม่ reset `next_id` (กัน id ซ้ำ)
7. ไฟล์วิดีโอเล่นตาม FPS จริง (`FrameSource.pace()`) — timer ทั้งหมดอิงเวลาจริง
8. คอมเมนต์และ log เป็นภาษาไทย; ไฟล์ข้อความเป็น LF (`.gitattributes`) เพราะรันบน Linux
