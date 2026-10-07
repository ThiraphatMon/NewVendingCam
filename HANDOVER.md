# Vending Camera — เอกสารส่งมอบโปรเจค (Handover Document)

> สำหรับ developer / ผู้ติดตั้งที่รับโปรเจคต่อ อ่านจากบนลงล่าง: ระบบทำอะไร → วงจร START/STOP →
> การตรวจจับ → ข้อมูลที่เก็บ → config → การลงบอร์ด / rollback → ข้อจำกัดที่รู้แล้ว
> ขั้นตอนติดตั้ง Docker บน Orange Pi แบบละเอียดอยู่ที่ `ORANGE_PI_DOCKER.md`

> **สถานะปัจจุบัน: โหมดเก็บข้อมูล (observe mode, `SEND_S0=0` = ค่าเริ่มต้น)** — ทดสอบที่ตู้จริงพบว่ามีออเดอร์แต่ของไม่ตก
> แล้วเงาลูกค้าเข้า ROI → กล้องส่ง S0 → controller จบออเดอร์ผิด จึง deploy เป็นโหมดที่ **ทำงานเหมือนเดิมทุกอย่าง
> (รอบ / ภาพ / DB / daily log / cloud) แต่ไม่เขียน `CAMERA` กลับ controller เลย** จนกว่าจะเก็บข้อมูลพอและเปิด `SEND_S0=1` เอง (ข้อ 2.1)

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

### 2.1 `SEND_S0` — โหมดเก็บข้อมูล (default 0)
| `SEND_S0` | พฤติกรรม |
|---|---|
| **0** (default) | observe mode: รับ `CTRL` ด้วย RPOP เหมือนเดิม, state machine / ยืนยัน / ภาพ / SQLite / daily log / ITEM_LANDED เหมือนเดิมทุกประการ **แต่ไม่เขียน `CAMERA` เลยไม่ว่ากรณีใด** (ยืนยันปกติ, S0 ค้างหลัง Redis กลับมา, หลัง restart) — controller จบออเดอร์ด้วย timeout ของตัวเอง |
| 1 | ส่ง S0 จริง (พฤติกรรมเดิม) |

- กันสองชั้น: main ไม่ขอส่ง + `RedisController(send_s0=False)` ไม่มีทาง LPUSH แม้ถูกเรียกผิด
- DB: แถว `responses` ของรอบที่ยืนยันเป็น `state='NOT_SENT'`, `updated_at` = เวลาที่ "จะได้ส่ง" (เวลายืนยัน)
  → เทียบกับเวลา STOP จริง: `SELECT r.updated_at, c.closed_at_utc, c.outcome FROM responses r JOIN cycles c USING (cycle_id) WHERE r.state='NOT_SENT'`
  (state ใหม่อย่างเดียว ไม่เปลี่ยน schema — image รุ่นก่อน rollback ได้)
- log startup 1 บรรทัด: `S0 response: DISABLED (observe mode, SEND_S0=0)` / `S0 response: ENABLED (SEND_S0=1)`
  และตอนยืนยัน: `[cycle xxxxxxxx] item confirmed, today's count N (saved in 25ms) -> S0 NOT SENT (observe mode)`
- ตรวจที่ตู้: `redis-cli MONITOR` ต้องเห็นแค่ `RPOP CTRL` ไม่มีคำสั่งใดที่แตะ `CAMERA`

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
  → นิ่งต่ออีก `CAPTURE_HOLD_SEC` (0.3s) → ยืนยัน (ในคลิปทดสอบ START→ยืนยัน ≈ 2.3s ที่ hold 0.3 / 3.03s ที่ hold 1.0 —
  ทุกการยืนยันมี log `timing:` แยกช่วงเวลา ดูตารางใน docs/AUTORUN_REPORT.md S18)
- ก้อนใหญ่เกิน `MAX_BLOB_ROI_RATIO` (30%) ของ ROI = **env change** (แสง/slat/มือบัง) ไม่ใช่ของ
- **ตัวกรองแสง/เงา (S22, `SHADOW_FILTER=texture` default)** — คนยืนหน้าตู้ทำให้แสง/เงาใน ROI เปลี่ยน → เคยยืนยันผิด
  - แสง/เงาเปลี่ยนแค่ความสว่าง ลวดลายพื้นเดิม: จุดที่ local NCC (หน้าต่าง `SHADOW_NCC_WIN` 7 px) ระหว่างภาพอ้างอิงกับเฟรม
    > `SHADOW_NCC_THR` 0.6 หรือไม่มีลายทั้งคู่ (variance < `SHADOW_FLAT_VAR` 4) = แค่แสง → ตัดออกจาก mask ก่อน OPEN/DILATE
    (ทำเฉพาะกล่อง ROI; นอกกล่องล้างเป็น 0 กันเงานอกกรอบถูก DILATE ล้นเข้าขอบ ROI)
  - ภาพอ้างอิงลวดลาย ≠ ภาพที่ใช้ diff: frozen snapshot (ถ้า freeze) → clean_bg ล่าสุด (แม้หมดอายุแล้ว) → bg ของ diff
    (bg ที่กำลังเรียนรู้ผสมวัตถุที่เพิ่งเข้ามา → NCC สูงผิด) · ROI ใหม่ → clean_bg เก่าถูกทิ้งทันที
  - ก้อนเล็กสุดในโหมด texture = `SHADOW_MIN_AREA` 400 px (แทน `MIN_AREA` 150 — เศษเงาที่เหลือ ~200 px) · `off` ใช้ MIN_AREA เดิม
  - ทุกการยืนยัน log `item size: blob …px, box WxH at (x,y)` → เก็บขนาดสินค้าจริงจากตู้ก่อนปรับ `SHADOW_MIN_AREA`
    (⚠ ของชิ้นเล็กมากที่ mask < 400 px จะไม่ถูกนับในโหมด texture)
  - ต้นทุน ~0.7 ms/เฟรมบน PC (ROI ~340x136) · ประมาณ 6–10 ms บน Orange Pi · `SHADOW_FILTER=off` = แบบเดิมทุกพิกเซล
  - ภาพตัวอย่าง mask: `docs/img/s22_*.jpg|png` · ผลทดสอบ: docs/AUTORUN_REPORT.md S22

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

### 4.3 แยก "หยิบออก" กับ "ใส่เข้า" (`core/removal.py`)
ก่อนยืนยันในรอบ ACTIVE เทียบ candidate (เฉพาะพิกเซลที่ต่างจากพื้นหลังรอบ ในกล่อง + ขอบ 8px):
- **ความคม (Sobel) ลดลง** เทียบพื้นหลังรอบ (< `REMOVAL_EDGE_RATIO` 0.6) = ดูเหมือนของหายไป
  (คลิปทดสอบ: สินค้าตก ×1.52, หยิบออก ×0.40)
- **กลับไปเหมือนฉากนิ่งก่อนหน้า** (scene history ที่บันทึกก่อนวัตถุนี้ปรากฏ, < `REMOVAL_MATCH_RATIO` 0.5 ของความต่างจากพื้นหลังรอบ)
- ขอบไม่ลด → ใส่เข้า (ยืนยัน) แม้ฉากก่อนหน้าตรง (ซื้อซ้ำที่ตำแหน่งเดิม) / ขอบลด + ฉากตรง → หยิบออก /
  ขอบลดแต่ไม่มีฉากยืนยัน → ไม่แน่ใจ → `REMOVAL_UNCERTAIN_SEND_S0` (default 0 = ไม่ส่ง S0)
- หยิบออก/ไม่แน่ใจ → anomaly `POSSIBLE_REMOVAL` (แถวใน DB เสมอ ภาพตามโควตา) + ตั้งพื้นหลังใหม่ รอบยัง ACTIVE รับของจริงต่อได้
- scene history: ฉากนิ่งย้อนหลัง `SCENE_HISTORY_SIZE` (10) ฉาก บันทึกทุกสถานะ (ฉากต่างกัน ≥ MIN_AREA px = ฉากใหม่)

### 4.4 ความนิ่งแบบเข้ม (`STRICT_STABILITY`=1, default)
- ขยับเกิน `CENTROID_STABLE_DIST` ระหว่างรอถ่าย (SHAPE_CONFIRMED) → ถอนสถานะ เริ่มนับนิ่งใหม่
- วัตถุที่หายไป (ghost) แล้วกลับมา ต้องนิ่งครบ `LANDING_STABLE_FRAMES` ใหม่ ไม่สะสมข้ามช่วงหาย
- ทำให้ START→S0 ช้าลง ~0.15s ในคลิปทดสอบ (3.4s → 3.55s)

### 4.5 กล้อง (`core/frame_source.py`)
- reader thread อ่านตลอด ถือเฉพาะเฟรมล่าสุด → main loop ไม่ติดใน `cap.read()` — START/STOP ประมวลผลได้แม้กล้องค้าง
- เฟรมเดิมไม่ถูกประมวลผลซ้ำ (`NO_NEW_FRAME`) — ไม่งั้นเฟรมซ้ำถูกนับว่า ROI นิ่ง
- ไม่มีเฟรมใหม่เกิน `CAMERA_STALL_SEC` (3s) = กล้องค้าง → เหมือนกล้องหลุด (ACTIVE → BLOCKED) + เปิดกล้องใหม่
- ไฟล์วิดีโอ: reader หน่วงตาม FPS จริง และวนเล่นเมื่อจบ (ทดสอบบน PC / e2e)

### 4.6 Watch mode (นอกรอบ)
WAIT_START แล้วมี motion ใน ROI → freeze bg (ฉากก่อนมีการเปลี่ยนแปลง) เพื่อให้ของที่วางนิ่งนอกรอบ
ไม่ถูกกลืนก่อนครบเกณฑ์ → ถ่ายภาพ anomaly `OUTSIDE_CYCLE` (ไม่นับยอด ไม่ส่ง S0) แล้ว rebaseline
จบเมื่อ ROI นิ่งครบ N เฟรม **และ** tracker ว่าง หรือเฝ้าครบ 25s → unfreeze + grace
START ระหว่าง watch → เลิกเฝ้า ใช้พื้นหลังตามข้อ 4.2 (ไม่ใช้ bg ที่ freeze ไว้ตอนเริ่มเฝ้า)

---

## 5. ข้อมูลที่เก็บ

| ที่เก็บ | เนื้อหา | หมายเหตุ |
|---|---|---|
| `data/vending_state.sqlite3` | ตาราง `cycles`, `confirmations`, `anomalies`, `responses`, `cloud_outbox` (event รอส่งขึ้นเว็บ) | **แหล่งจริงของยอด** ห้ามลบ / ห้ามแก้มือ — DB เสีย = โปรแกรมหยุด ไม่นับต่อ |
| `logs/item_drops/YYYY-MM-DD.log` | `05/10/2026 13:45:12 : item drop : 1` บรรทัดละการยืนยัน | ภาพสะท้อนของ DB, startup สร้างไฟล์ของวันนี้ใหม่จาก DB (ซ่อมหลัง crash) ห้ามใช้กู้ยอด |
| `logs/vending.log` | operational log (หมุนไฟล์ ~25MB) — **ภาษาอังกฤษ ASCII ล้วน** ข้อความเกี่ยวกับรอบขึ้นต้น `[cycle <id8>]` (ตาราง `docs/LOG_MESSAGES.md`) | ดูการเปิด/ปิดรอบ, พื้นหลังที่ใช้, S3, timing, Redis |
| `evidence_images/confirmed/` | ภาพตอนยืนยัน 1 ภาพต่อการยืนยัน | ลบอัตโนมัติเกิน `CLEANUP_KEEP_DAYS` — ยกเว้นภาพที่ยังรอส่งขึ้นเว็บ (outbox PENDING) |
| `evidence_images/anomaly/` | 1 ภาพต่อเหตุการณ์ (ไม่จำกัดความถี่ตั้งแต่ S19): `OUTSIDE_CYCLE`, `EXTRA_AFTER_CONFIRM`, `POSSIBLE_REMOVAL`, `NO_CONFIRM_AT_CLOSE` (ทุกรอบที่ไม่ยืนยัน), **`ENV_CHANGE`** (ใหม่: ตอนเริ่ม env change ทุก state — ไม่ถ่ายซ้ำจนถาดกลับมานิ่ง `CLEAN_BG_STABLE_FRAMES`) · เพดานรวม `ANOMALY_MAX_PER_DAY` (2000) ภาพ/วัน ถึงแล้วไม่เก็บภาพเพิ่ม (DB ยังบันทึก) + เตือนวันละครั้ง | ไม่นับยอด, ลบเกิน `ANOMALY_KEEP_DAYS`, ไม่ส่งขึ้นเว็บ |

ลำดับการยืนยัน (ล้มเหลวขั้นไหน = ไม่มียอด ไม่มี S0): บันทึกภาพ → DB (transaction เดียว) → latch รอบ → S0 → daily log
ยอดรายวันนับตาม `COUNT_TIMEZONE` (Asia/Bangkok) ไม่ขึ้นกับเวลาเครื่อง

ตัวอย่าง `logs/vending.log` รอบปกติ (observe mode):
```
[INFO] vending.main: [cycle fd77e6ca] START received -> cycle opened (background: empty-tray, age 0.4s)
[INFO] vending.main: [cycle fd77e6ca] S3=ADDITION edge_ratio=1.09 (threshold 0.60), diff_bg=46.9, diff_prev=47.5, diff_prev match < 23.4 (diff_bg x0.50) -> item added -> confirm
[INFO] vending.main: [cycle fd77e6ca] timing: START->motion 1.27s, START->item seen 1.60s, seen->still 0.33s (9 frames, LANDING_STABLE_FRAMES=4, still resets 1), still->hold done 0.33s (CAPTURE_HOLD_SEC=0.3), S3 1ms, save 35ms, START->confirm 2.27s t0=...
[INFO] vending.main: [cycle fd77e6ca] item confirmed, today's count 1 (saved in 35ms) -> S0 NOT SENT (observe mode)
[WARNING] vending.main: [cycle fd77e6ca] anomaly image ENV_CHANGE (not counted): evidence_images/anomaly/..._ENV_CHANGE_fd77e6ca....jpg
[INFO] vending.main: [cycle fd77e6ca] STOP received -> cycle closed: CONFIRMED
```
รอบที่ไม่เห็นของ: `[cycle …] STOP received -> cycle closed: UNCONFIRMED` + `anomaly image NO_CONFIRM_AT_CLOSE` ·
หยิบออก: `S3=REMOVAL ... -> item removed -> not confirmed, no S0` · log `timing:` ทุกการยืนยัน ใช้วัดว่าช้าที่ขั้นไหน

---

## 6. โครงสร้างไฟล์

```
main.py                 App: main loop (อ่านเฟรม → คำสั่ง → ตรวจจับ → ยืนยัน/anomaly), startup, จอ debug
config.py               ค่าตั้งทั้งหมดจาก .env + เตือนค่าที่ไม่มีผล (inactive_warnings)
core/cycle.py           state machine ของรอบ START–STOP
core/background.py      background model, clean_bg, freeze/rebaseline, env change
core/detect.py          mask → กล่อง (morphology, contour, group)
core/tracker.py         จำวัตถุข้ามเฟรม + ความนิ่ง (STRICT_STABILITY)
core/removal.py         แยกหยิบออก / ใส่เข้า ก่อนยืนยัน
core/roi.py             ROI จาก data/roi_config.json (reload อัตโนมัติ)
core/frame_source.py    กล้อง / ไฟล์วิดีโอ ใน reader thread (เฟรมล่าสุด, ตรวจกล้องค้าง, เล่นวิดีโอตามเวลาจริง)
api/redis_controller.py RPOP CTRL / LPUSH CAMERA (worker thread)
api/cloud.py            เริ่ม/หยุด thread ฝั่ง cloud ตามสวิตช์ (ROI sync, ภาพสด, ...) — ดูข้อ 7.1
api/client.py           HTTP ไปเว็บ (register, ROI, ภาพสด, event)
api/retry_queue.py      เลิกใช้ (ลบภาพหลังส่ง + คิวใน memory) — ห้ามนำกลับมาใช้กับภาพหลักฐาน
api/order_listener.py   ของระบบ order เดิม (ไม่ถูกเริ่ม)
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
ตอนเริ่มโปรแกรม log `active config:` ทั้งหมด และเตือน `.env: ... has no effect` ถ้าตั้งค่าที่ไม่มีผลกับโหมดที่รัน
(รวมค่าที่ยกเลิกแล้ว `ANOMALY_MIN_INTERVAL_SEC` / `ANOMALY_MAX_PER_HOUR`)

| หมวด | ค่าที่สำคัญ |
|---|---|
| 1 ตู้/การเชื่อมต่อ | `MACHINE_ID_DEFAULT`, `CAMERA_INDEX`, `HEADLESS`, `CONTROL_MODE` (redis/keyboard), `REDIS_*`, **`SEND_S0` 0** (ข้อ 2.1), `CLOUD_*` (ข้อ 7.1) |
| 2 ความไว | `CAPTURE_HOLD_SEC` 0.3, `MOT_THRESH` 25, `MIN_AREA` 150, `MAX_BLOB_ROI_RATIO` 0.30, **`SHADOW_FILTER` texture**, `SHADOW_NCC_WIN` 7, `SHADOW_NCC_THR` 0.6, `SHADOW_FLAT_VAR` 4.0, **`SHADOW_MIN_AREA` 400** (ข้อ 4.1), `LANDING_STABLE_FRAMES` 4, `CENTROID_STABLE_DIST` 10, `STRICT_STABILITY` 1 |
| 3 รอบ | `CYCLE_TIMEOUT_SEC` 300 |
| 4 ขั้นสูง | `GROUP_*`, `MORPH_*`, `BG_*`, `RESET_GRACE_SEC`, `CLEAN_BG_INTERVAL` 0.5, `CLEAN_BG_MAX_MOTION_RATIO` 0.002, `CLEAN_BG_STABLE_FRAMES` 5, `ENV_SETTLE_REBASELINE` 1, `REMOVAL_CHECK` 1, `REMOVAL_EDGE_RATIO` 0.6, `REMOVAL_MATCH_RATIO` 0.5, `REMOVAL_UNCERTAIN_SEND_S0` 0, `SCENE_HISTORY_SIZE` 10 |
| 5 ระบบ | `CAMERA_RECONNECT_SEC` 2, `CAMERA_STALL_SEC` 3, `STATE_DB_PATH`, `COUNT_TIMEZONE`, `DAILY_LOG_DIR`, `ANOMALY_MAX_PER_DAY` 2000, `ANOMALY_KEEP_DAYS` 3, `CLEANUP_*` |

ค่าระบบ order เดิม (`WS_URL`, `ORDER_WINDOW`, `DROP_TIMEOUT`, ...) ไม่มีผลในโหมด START–STOP
ROI: `data/roi_config.json` (rect / quad / polygon / multi_polygon บนภาพ 640x480) แก้แล้ว reload เองภายใน `ROI_CHECK_INTERVAL`
- ไฟล์นี้ **ไม่อยู่ใน git** (`.gitignore`) — เป็นของแต่ละตู้; ใน repo มีแค่ตัวอย่าง `data/roi_config.example.json`
- เริ่มโปรแกรมแล้วไม่มีไฟล์ → copy จาก `roi_config.example.json` (ไม่มี/อ่านไม่ได้ → สร้าง rect ครึ่งขวา) log `... not found -> copy from ...`
  จากนั้น ROI จากเว็บ (`CLOUD_ROI_SYNC`) เขียนทับไฟล์นี้ หรือแก้ไฟล์บนบอร์ดเอง — `git pull` ไม่แตะไฟล์นี้
- ROI ใหม่ (จากเว็บหรือแก้ไฟล์) ระหว่างรอบ (ACTIVE / CONFIRMED_WAIT_STOP / BLOCKED) → **ยังไม่ใช้** log `new ROI found during cycle -> will apply when cycle ends`
  แล้วใช้ทันทีที่กลับ WAIT_START (log `new ROI applied`) พร้อมล้าง tracker / clean_bg / scene history / watch ที่ผูกกับ ROI เดิม
  → START ถัดไปต้องรอถาดนิ่งใน ROI ใหม่ครบ `CLEAN_BG_STABLE_FRAMES` ก่อนจึงใช้ clean_bg ได้

### 7.1 Cloud / เว็บ (เปิด-ปิดทีละฟีเจอร์)

cloud เป็นส่วนเสริม — START/STOP/S0 ไม่รอและไม่พึ่ง cloud (เน็ตหลุด/เว็บค้างไม่กระทบ)
ฟีเจอร์ที่ปิด **ไม่เริ่ม thread และไม่ส่ง HTTP เลย**; ตอนเริ่มโปรแกรม log 1 บรรทัด `☁️ Cloud: register=..., ROI sync=..., ภาพสด=..., ITEM_LANDED=..., anomaly=...`

| ค่า | default | ผล |
|---|---|---|
| `CLOUD_ENABLED` | 0 | สวิตช์หลัก: 0 = ไม่มี HTTP เลย; 1 = เปิดตามสวิตช์ย่อย + register ตู้ (ต้องตั้ง `CLOUD_API_URL` ไม่งั้นถือว่าปิด) — เน็ตยังไม่มาตอนบูต: register / push ROI ลองใหม่แบบ backoff (5s, 10s, ... สูงสุด `RETRY_INTERVAL`) จนสำเร็จ |
| `CLOUD_ROI_SYNC` | 1 | ดึง ROI จากเว็บทุก `ROI_POLL_INTERVAL` + ส่ง ROI ในเครื่องขึ้นเว็บตอนเริ่มถ้าเว็บยังไม่มี (ROI ใหม่ระหว่างรอบรอใช้ตอนจบรอบ — ข้อ 7) |
| `SEND_INTERVAL` | 60 | ภาพสดขึ้น dashboard ทุกกี่วินาที (0 = ปิด) |
| `REALTIME_JPEG_QUALITY` | 80 | คุณภาพ JPEG ของภาพสดเท่านั้น — ขนาดคง 640x480 (เว็บใช้วาด ROI), ภาพหลักฐานไม่เกี่ยว; q80 ≈ 45KB/ภาพ (q95 เดิม ≈ 94KB) → ทุก 60s ≈ 65MB/วัน |
| `CLOUD_SEND_EVENTS` | 1 | ส่ง event `ITEM_LANDED` + ภาพตอนยืนยันสินค้า |
| `CLOUD_SEND_ANOMALY` | 0 | เตรียมไว้ ยังไม่ส่งจริง (ยังไม่รู้ว่าเว็บรับ event ชนิดใหม่ได้ไหม) |

ตัวอย่างโปรไฟล์ (ใส่ใน `.env` พร้อม `CLOUD_API_URL` / `API_KEY`):

| โปรไฟล์ | ค่า | ใช้เมื่อ |
|---|---|---|
| ช่วงทดสอบ | `CLOUD_ENABLED=1` `CLOUD_SEND_EVENTS=1` `CLOUD_ROI_SYNC=1` `SEND_INTERVAL=60` | อยากเห็นทุกชิ้นบนเว็บ + ภาพสดทุก 1 นาที |
| ขายจริง | `CLOUD_ENABLED=1` `CLOUD_SEND_EVENTS=0` `CLOUD_ROI_SYNC=1` `SEND_INTERVAL=300` | ประหยัดเน็ต: ROI จากเว็บยังใช้ได้ ภาพสดทุก 5 นาที |
| ไม่มีเน็ต | `CLOUD_ENABLED=0` | ทำงาน local อย่างเดียว |

**event `ITEM_LANDED`** (เว็บเดิมรับได้ — field เดียวกับโปรแกรมรุ่น order เดิม): multipart ไปที่ `CLOUD_API_URL`
`machine_id`, `event=ITEM_LANDED`, `transaction_id=TXN-<YYYYMMDD-HHMMSS เวลาไทยตอนยืนยัน>-<cycle_id 8 ตัวแรก>`,
`item_no` (= ลำดับยอดของวัน), `obj_id` (id วัตถุใน tracker), `land_time` (`%H:%M:%S` เวลาไทย), `order_id=""` + ไฟล์ `landed_image`
- main loop ยืนยัน → S0 → daily log → เขียนแถวลง `cloud_outbox` (transaction แยก ล้มเหลวแค่ log ไม่กระทบยอด/S0)
  → worker thread `cloud-outbox` ส่ง: 2xx = `SENT`, ไม่สำเร็จ = `PENDING` + `attempts`/`last_error` + backoff 5s, 10s, ... สูงสุด `RETRY_INTERVAL`
- คงอยู่ข้าม restart (อยู่ใน DB); ปิด `CLOUD_SEND_EVENTS` ภายหลัง → รายการค้างหยุดส่ง ไม่ลบ (startup log จำนวนที่ค้าง)
- **ไม่ลบภาพในเครื่องหลังส่ง** และ disk_cleanup ไม่ลบภาพที่ยัง PENDING (ถ้าค้างนานภาพจะสะสม — ดู log `เก็บภาพเก่า ... รอส่งขึ้นเว็บ`)
- ดูคิว: `sqlite3 data/vending_state.sqlite3 "SELECT event_id,state,attempts,last_error FROM cloud_outbox ORDER BY id DESC LIMIT 20"`
- ตาราง `cloud_outbox` สร้างอัตโนมัติตอนเปิด DB (`CREATE TABLE IF NOT EXISTS`, ไม่เปลี่ยน schema version) → rollback image รุ่นก่อนยังเปิด DB ได้

**เปลี่ยนโปรไฟล์บนตู้** (ไม่ต้อง build ใหม่ ยอด/DB ไม่หาย):
```bash
nano .env                                   # แก้ค่าตามตาราง
docker compose up -d --force-recreate       # .env อ่านตอนสร้าง container เท่านั้น → ต้อง recreate
docker compose logs vending-cam | grep "Cloud:"   # ตรวจว่าฟีเจอร์ที่ต้องการเปิด/ปิดจริง
```

---

## 8. การทดสอบ

```bash
pip install -r requirements-pc.txt -r requirements-dev.txt
python -m pytest -q                                            # unit tests (fake clock / กล้องปลอม / fakeredis)
python tests/integration/redis_e2e.py --clip <big1_pickup_cutted.mp4>   # main.py จริง + Redis จริง (Docker พอร์ต 6380)
#   ค่าเริ่ม --send-s0 1,0 = รันทุกข้อทั้ง 2 โหมด (โหมด 0 ตรวจว่าไม่แตะ CAMERA ด้วย MONITOR + outcome เหมือนโหมด 1)
#   --hold 0.1 = ลอง CAPTURE_HOLD_SEC อื่น · ทุกข้อตรวจว่า log เป็น ASCII ล้วน · หมายเหตุ TIMING / ENV_CHANGE ต่อข้อ
python tests/integration/docker_smoke.py                       # image จริง ทั้ง SEND_S0=0 (CAMERA ต้องว่าง) และ 1
```
- PC แบบมีจอ: `HEADLESS=0`, `CONTROL_MODE=keyboard` → กด `s` = START, `x` = STOP
- e2e ใช้ container `vendingcam-redis-test` พอร์ต 6380 เท่านั้น (สร้าง/ลบเอง) ไฟล์ชั่วคราวอยู่ `.e2e_tmp/`
- สถานการณ์ e2e: 1 ปกติ, 2 STOP ก่อนของตก, 3 สองรอบ, 4 Redis ดับระหว่างรอบ, 5 kill กลางรอบ, 6 ไม่มี START,
  7 ของนิ่งก่อน START แล้วถูกหยิบ, 7b = ข้อ 7 โดยปิด ENV_SETTLE_REBASELINE (ต้องผ่านด้วยการแยกหยิบออก),
  8/8b/8c ซื้อต่อกันหลังลูกค้าหยิบนอกรอบ — **ห้ามลบสถานการณ์ใด**
- Docker: `tests/integration/docker_smoke.py` (image `vending-cam:autorun-test` + `--network host` + Redis ทดสอบ 6380)
- Windows + WSL 2.7: ตัวทดสอบค้าง `wsl ... sleep infinity` (stdin=DEVNULL) ไว้ตลอด ไม่งั้น WSL ปิด distro ~15s แล้วต่อพอร์ต 6380 ไม่ได้

---

## 9. การลงบอร์ด / อัปเดต / rollback

รายละเอียดคำสั่งติดตั้ง Docker อยู่ที่ `ORANGE_PI_DOCKER.md` ลำดับที่ต้องทำทุกครั้ง:

1. **หยุดโปรแกรมกล้องตัวเก่าก่อนเสมอ** (ตัวที่ `RPOP CTRL`) — สองตัวพร้อมกันจะแย่งคำสั่งกัน
   ตรวจ: `redis-cli MONITOR` ต้องเห็น `RPOP CTRL` จาก client เดียว
2. ลง source ด้วย git (ครั้งแรก `git clone https://github.com/ThiraphatMon/NewVendingCam.git ~/MotionDetectionForVendingMachine`) แล้วเตรียม `.env` (หมวด 1)
   และ `data/roi_config.json` ของตู้นี้ (ไม่มี → โปรแกรม copy จาก `roi_config.example.json` ให้ แล้วรอ ROI จากเว็บ / แก้เอง)
   `.env`, `data/roi_config.json`, `data/*.sqlite3`, `evidence_images/`, `logs/` อยู่ใน `.gitignore` — git ไม่แตะ
3. `docker compose up -d --build` → `docker compose logs -f vending-cam` ดู `active config:`, `S0 response: DISABLED (observe mode, SEND_S0=0)`,
   `Redis connected` และไม่มี `.env: ... has no effect` ที่ไม่ได้ตั้งใจ
4. **controlled test** (ตู้ไม่ขายจริง): `redis-cli MONITOR` ในอีกหน้าต่าง
   - observe mode (`SEND_S0=0`): `redis-cli LPUSH CTRL START` → ปล่อยของ 1 ชิ้น → log `item confirmed ... -> S0 NOT SENT (observe mode)`
     และ MONITOR **ไม่มี** คำสั่งที่แตะ `CAMERA` → `redis-cli LPUSH CTRL STOP`
   - เมื่อเปิด `SEND_S0=1`: START → ปล่อยของ → เห็น `LPUSH CAMERA S0` ครั้งเดียว → STOP
   - `START` → ไม่ปล่อยของ → `STOP` → ต้องไม่มี S0 (ทั้ง 2 โหมด)
   - ตรวจ `logs/item_drops/<วันนี้>.log` และ `evidence_images/confirmed/`
5. เปิดขายจริง เฝ้า log ช่วงแรก

**อัปเดตแบบ rollback ได้:**
```bash
cd ~/MotionDetectionForVendingMachine
git status --short                               # ต้องว่าง (ห้ามแก้ไฟล์ที่อยู่ใน git บนบอร์ด)
docker tag vending-cam:latest vending-cam:prev   # เก็บ image ที่ใช้อยู่
git rev-parse --short HEAD                       # จด commit ที่ใช้อยู่ (ไว้ rollback source)
git pull --ff-only
docker compose up -d --build
# มีปัญหา → กลับ image เดิมทันที (ไม่ต้อง build):
docker tag vending-cam:prev vending-cam:latest && docker compose up -d --no-build
# (ถ้าต้อง rebuild ภายหลัง ให้ git checkout <commit ที่จดไว้> ก่อน)
# กลับไปโปรแกรมตัวเก่า: docker compose down แล้วเปิดโปรแกรมเดิม (อย่าเปิดพร้อมกัน)
```
`data/` อยู่นอก container → rollback image ไม่ทำให้ยอดหาย (schema DB เปลี่ยนเมื่อไรต้องระบุใน release)

> ⚠ บอร์ดที่ clone ไว้ **ก่อน S15** (ตอนที่ `data/roi_config.json` ยังอยู่ใน git): `git pull` ข้าม S15 จะ**ลบ**ไฟล์ ROI
> (หรือ pull ไม่ผ่านถ้าไฟล์ถูกเว็บแก้ไว้) — สำรองก่อน แล้วคืนหลัง pull:
> `cp data/roi_config.json ~/roi_backup.json && git checkout -- data/roi_config.json && git pull --ff-only && cp ~/roi_backup.json data/roi_config.json`

---

## 10. Known limitations

- `CAPTURE_HOLD_SEC` default 0.3 (S18): START→ยืนยัน ≈ 2.3s ในคลิป (เดิม 3.0s ที่ 1.0) — ที่ 0.1 e2e ข้อ 7 กลับมายืนยันผิด → **อย่าตั้งต่ำกว่า 0.3**
- ภาพ anomaly ไม่จำกัดความถี่แล้ว → ตู้ที่มีเงา/แสงเปลี่ยนบ่อยจะมีภาพ `ENV_CHANGE` มาก (เพดาน 2000/วัน, ลบหลัง 3 วัน)

| ระดับ | ข้อจำกัด | สถานะ |
|---|---|---|
| MED | ของวางนิ่งก่อน START แล้วถูกหยิบออกระหว่างรอบ (e2e ข้อ 7) | แก้แล้ว: ตั้งพื้นหลังใหม่หลัง env change สงบ + แยกหยิบออก/ใส่เข้า (7b) — เหลือ: ของที่เรียบกว่าพื้นถาดมาก หรือไม่มีฉากก่อนหน้า (เพิ่งเปิดเครื่อง) → ไม่แน่ใจ → ไม่ส่ง S0 (ปรับ `REMOVAL_UNCERTAIN_SEND_S0`) |
| MED | สินค้าที่ "เรียบ" กว่าพื้นถาด (ขอบน้อยกว่าลายพื้น) อาจถูกมองว่าเป็นการหยิบออก → ไม่ส่ง S0 | ยังไม่พบในคลิปทดสอบ ต้องทดสอบกับสินค้าจริงทุกแบบ |
| LOW | กล้องค้างบน V4L2: reader เก่ายังถือ `/dev/video0` อาจทำให้เปิดใหม่ไม่ได้จนกว่าจะคืน | ต้องทดสอบที่ตู้จริง |
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
7. ไฟล์วิดีโอเล่นตาม FPS จริง (reader thread ของ `FrameSource`) — timer ทั้งหมดอิงเวลาจริง
8. ห้ามประมวลผลเฟรมเดิมซ้ำ — ความนิ่ง (clean_bg / watch / env settle) นับเฟรมต่อเฟรม
9. คอมเมนต์และ log เป็นภาษาไทย; ไฟล์ข้อความเป็น LF (`.gitattributes`) เพราะรันบน Linux
