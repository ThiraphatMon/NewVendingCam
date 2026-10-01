# Vending Camera — เอกสารส่งมอบโปรเจค (Handover Document)

> เอกสารนี้เขียนสำหรับ developer ที่เพิ่งรับโปรเจคต่อ โดยไม่เคยเห็นโค้ดมาก่อน
> อ่านจากบนลงล่างจะเข้าใจตั้งแต่ "ระบบนี้ทำอะไร" ไปจนถึง "แต่ละ function ทำงานยังไง
> และส่งข้อมูลต่อกันอย่างไร"

---

## สารบัญ

1. [ระบบนี้คืออะไร (ภาพใหญ่)](#1-ระบบนี้คืออะไร)
2. [แนวคิดหลักที่ต้องเข้าใจก่อน](#2-แนวคิดหลักที่ต้องเข้าใจก่อน)
3. [โครงสร้างไฟล์ทั้งโปรเจค](#3-โครงสร้างไฟล์)
4. [Data Flow — ข้อมูลไหลจากไหนไปไหน](#4-data-flow)
5. [วงจรชีวิตของ "การตกของ 1 ชิ้น" แบบ step-by-step](#5-วงจรชีวิต)
6. [รายละเอียดรายไฟล์ + ทุก function](#6-รายละเอียดรายไฟล์)
7. [State Machine อธิบายละเอียด](#7-state-machine)
8. [การตั้งค่า (config / .env)](#8-การตั้งค่า)
9. [การ deploy และ run](#9-การ-deploy)
10. [จุดที่ต้องระวัง / เคยเป็น bug](#10-จุดที่ต้องระวัง)

---

## 1. ระบบนี้คืออะไร

ระบบกล้องตรวจจับสำหรับ **ตู้ขายสินค้าอัตโนมัติ (vending machine)** หน้าที่หลักคือ:

> **"เมื่อลูกค้าสั่งซื้อสินค้า ให้ยืนยันด้วยกล้องว่าสินค้าตกลงมาจริงกี่ชิ้น
> และเก็บภาพหลักฐานไว้"**

ปัญหาที่แก้: ตู้ขายของบางครั้งลูกค้าจ่ายเงินแล้วแต่ของไม่ตก (ค้าง/ขัดกลไก) หรือ
ตกไม่ครบจำนวน ระบบนี้ใช้กล้องจับ "การเคลื่อนไหวของของที่ตกลงมาในช่องรับสินค้า"
เพื่อพิสูจน์ว่าเกิดอะไรขึ้นจริง แล้วส่งผล + ภาพขึ้น server กลาง

### สิ่งที่ระบบทำได้
- ตรวจจับ **การเคลื่อนไหว (motion)** เฉพาะในบริเวณที่กำหนด (ROI = ช่องรับของ)
- นับจำนวนของที่ตก **ได้หลายชิ้น** ต่อ 1 คำสั่งซื้อ
- เก็บ **ภาพหลักฐาน** ตอนของตกถึงที่ (landed)
- เชื่อมกับ **ระบบ order** ผ่าน WebSocket — รู้ว่าลูกค้าสั่งกี่ชิ้น แล้วเทียบกับที่จับได้
- สรุปผลเป็น 3 สถานะ: `completed` (ครบ), `anomaly` (ไม่ครบ/เกิน), `no_drop` (ไม่ตกเลย)
- **ทนเน็ตหลุด** — ถ้าส่งขึ้น server ไม่ได้ จะเก็บ queue ไว้ retry อัตโนมัติ
- รันได้ทั้งบน **PC (มีจอ debug)** และ **Orange Pi ผ่าน Docker (ไม่มีจอ / headless)**

### สิ่งที่ระบบ *ไม่ได้* ทำ
- ไม่รู้ว่าสินค้าคือ "อะไร" (ไม่มี object classification / AI จำแนกชนิดสินค้า)
  มันจับแค่ "มีของเคลื่อนไหวแล้วมานิ่ง" = นับเป็น 1 ชิ้น
- ไม่ได้ตัดสินใจเรื่องเงิน/การจ่ายเงิน (นั่นเป็นหน้าที่ของระบบ order ฝั่ง server)

---

## 2. แนวคิดหลักที่ต้องเข้าใจก่อน

ก่อนอ่านโค้ด ต้องเข้าใจ 6 แนวคิดนี้ก่อน ไม่งั้นจะงงว่าทำไมโค้ดเขียนแบบนี้

### 2.1 Background Subtraction (การลบพื้นหลัง)
หัวใจของการจับ motion คือ **เปรียบเทียบเฟรมปัจจุบันกับ "ภาพพื้นหลัง" (background)**
- เก็บภาพพื้นหลังไว้ (ช่องรับของว่าง ๆ) ใน `BackgroundModel.bg` (`core/background.py`)
- ทุกเฟรมใหม่ เอามาลบกับ background → `diff = |frame - bg|`
- ตรงไหน `diff` สูง = ตรงนั้นมีของเปลี่ยนไป = **motion**

Background ไม่ได้ fix ตายตัว แต่ค่อย ๆ อัปเดตตามสภาพแสง (running average ด้วย
`BG_LEARNING_RATE`) เพื่อไม่ให้แสงเปลี่ยนช้า ๆ กลายเป็น motion หลอก
ตอนเจอของตก background จะถูก **freeze** (หยุดเรียนรู้) ไม่ให้ของถูกกลืนเข้าไป

### 2.2 ROI — Region of Interest (บริเวณที่สนใจ)
เราสนใจแค่ **ช่องรับสินค้า** ไม่ใช่ทั้งเฟรม (ข้างนอกอาจมีคนเดินผ่าน เงา ฯลฯ)
ROI คือรูปหลายเหลี่ยม (polygon/quad/rect) ที่วาดครอบเฉพาะช่องรับของ
motion ที่เกิดนอก ROI จะถูกตัดทิ้งทั้งหมด

### 2.3 "ของตก = เคลื่อนที่แล้วมานิ่ง"
กุญแจสำคัญของการนับ: **ของที่กำลังตกจะเคลื่อนที่ (centroid ขยับ) พอตกถึงที่จะนิ่ง**
- ของกำลังตก → state `MOVING` / `DETECTING`
- ของนิ่งครบ `LANDING_STABLE_FRAMES` เฟรม → state `SHAPE_CONFIRMED` = "ลงจอดแล้ว"
- นิ่งต่ออีก `CAPTURE_HOLD_SEC` → **capture** (นับ + ถ่ายภาพ)

### 2.4 Re-baseline (ล้างพื้นหลังใหม่หลัง capture)
หลังจับของ 1 ชิ้นได้ เราเอา **เฟรมปัจจุบันทั้งภาพมาเป็น background ใหม่ทันที**
(`BackgroundModel.rebaseline()`) ผลคือ motion mask ว่างเปล่า (ของที่เพิ่งจับถูก "กลืน" เข้าพื้นหลัง)
→ ของชิ้นถัดไปที่ตกลงมา (แม้ตกทับที่เดิม) จะกลายเป็น motion ใหม่สด ๆ → นับเป็นชิ้นใหม่ได้

> นี่คือดีไซน์หลักของระบบ (เปิดถาวร ไม่มี switch ปิด) — เข้าใจตรงนี้แล้วจะเข้าใจ 80% ของ main loop

### 2.5 Tracker (ตัวจำวัตถุข้ามเฟรม)
กล้องให้มาทีละเฟรม แต่ละเฟรมเจอ "กล่อง" (bounding box) ของ motion
Tracker ทำหน้าที่ **จับคู่กล่องในเฟรมนี้กับวัตถุเดิมในเฟรมก่อน** (ด้วยระยะทางที่ใกล้สุด)
เพื่อให้รู้ว่า "กล่องนี้คือวัตถุตัวเดิมที่ขยับมา" ไม่ใช่วัตถุใหม่ และติดตามได้ว่ามันนิ่งหรือยัง

### 2.6 State Machine (เครื่องจักรสถานะ)
ระบบมี 3 สถานะหลัก วนเป็นวงจร:
```
IDLE ──(เจอ motion)──> DROP_DETECTED ──(จับของได้)──> EVIDENCE_CAPTURED
  ^                                                          │
  └──────────────────(หมดเวลา / reset)───────────────────────┘
```

---

## 3. โครงสร้างไฟล์

```
MotionDetectionForVendingMachine/
├── main.py                  ★ main loop — อ่านจากบนลงล่างเห็นลำดับทั้งระบบ
├── config.py                ★ ค่าตั้งทั้งหมด (อ่านจาก .env) เรียงตามความสำคัญ 6 หมวด
├── .env                     ค่าตั้งจริงของเครื่องนี้ (ไม่ commit ขึ้น git)
├── .envexample              ตัวอย่าง .env (คัดลอกเป็น .env แล้วแก้)
├── requirements.txt         library สำหรับ Orange Pi / Docker (opencv แบบ headless)
├── requirements-pc.txt      library สำหรับ PC (opencv แบบมีหน้าต่าง)
├── Dockerfile               สร้าง container
├── docker-compose.yml       รัน container + ผูกกล้อง + mount โฟลเดอร์
│
├── core/                    ★ ตรรกะหลักของการมองเห็น
│   ├── frame_source.py      อ่านเฟรมจากกล้อง/วิดีโอ + resize + reconnect + pacing
│   ├── background.py        BackgroundModel (bg, freeze, grace, rebaseline, env change)
│   ├── detect.py            สร้าง motion mask + หากล่อง + รวมกล่องที่แตก
│   ├── tracker.py           จำวัตถุข้ามเฟรม + ตัดสินว่านิ่ง (ลงจอด) หรือยัง
│   ├── roi.py               จัดการบริเวณที่สนใจ (โหลด/วาด/สร้าง mask)
│   ├── state_machine.py     สถานะ + นับของ + สรุปผล order + ส่ง event
│   └── reset_policy.py      กติกาว่าเมื่อไหร่ต้อง reset กลับ IDLE (รวมไว้ที่เดียว)
│
├── api/                     ★ การสื่อสารกับ server
│   ├── client.py            HTTP: post_event, register, ROI sync, ภาพ realtime
│   ├── retry_queue.py       queue เก็บ event ที่ส่งไม่สำเร็จ + retry
│   └── order_listener.py    รับ order ใหม่ผ่าน WebSocket
│
├── ui/
│   └── overlay.py           วาดข้อมูล debug บนจอ (เฉพาะ PC / HEADLESS=0)
│
├── utils/                   ★ เครื่องมือเสริม
│   ├── image_saver.py       บันทึกภาพหลักฐาน (แยกโฟลเดอร์ with/without order)
│   ├── disk_cleanup.py      ลบภาพเก่าอัตโนมัติ (กัน eMMC เต็ม)
│   ├── json_file.py         อ่าน/เขียน JSON แบบ atomic (ไฟล์ ROI)
│   └── logger.py            logging (เขียนไฟล์ + rotate) + LogThrottle
│
├── data/
│   └── roi_config.json      พิกัด ROI (แก้ได้จาก server หรือแก้ไฟล์ตรง ๆ)
├── evidence_images/         ภาพหลักฐาน (runtime, mount ออกนอก container)
└── logs/                    log ไฟล์ (runtime, mount ออกนอก container)
```

**กฎการพึ่งพา (dependency):** `main.py` เรียกใช้ `core/*` + `api/*` + `ui/*` + `utils/*`
โมดูลใน `core/` แทบไม่พึ่งกัน (ยกเว้น state_machine เรียก image_saver + retry_queue,
reset_policy ใช้ helper จาก tracker) ทำให้ทดสอบแต่ละส่วนแยกกันได้
ทุกไฟล์อ่านค่าตั้งจาก `config.py` เท่านั้น (ไม่เรียก `os.getenv` เอง)

---

## 4. Data Flow

### 4.1 เส้นทางหลัก: จากกล้อง → นับของ → ขึ้น server

```
  [กล้อง/วิดีโอ]
        │
        ▼
  core/frame_source.py: FrameSource.read()   → เฟรม BGR 640x480 (หลุด → reconnect)
        │
        ▼
  core/background.py: BackgroundModel.update() → diff = |gray - bg| (+ เรียนรู้ bg ถ้าไม่ freeze)
        │
        ▼
  main.py: detect_objects()
        ├─ core/detect.py: build_fgmask(diff)      → binary motion mask
        ├─ core/roi.py: build_mask() → bitwise_and → เหลือ motion เฉพาะใน ROI
        ├─ core/background.py: find_env_change()  → ก้อนใหญ่เกิน = แสง/bg เปลี่ยน
        ├─ core/detect.py: contour_boxes()         → list ของกล่อง (x,y,w,h)
        ├─ core/detect.py: drop_large_boxes()      → (เฉพาะตอน env change) ตัดก้อนใหญ่
        └─ core/detect.py: group_close_boxes()     → รวมกล่องที่แตกของชิ้นเดียว
        │
        ▼
  core/tracker.py: MemoryTracker.update()    → จำวัตถุข้ามเฟรม + คำนวณ state
        │  (objects: {id: {centroid, shape, state, ...}})
        ▼
  main.py: capture_landed() — object SHAPE_CONFIRMED นิ่งครบ CAPTURE_HOLD_SEC ไหม
        │  ถ้าใช่ ▼
  core/state_machine.py: trigger("still_in_ROI")
        │  ├─► _capture_item() → บันทึกลง captured_items
        │  ├─► utils/image_saver.py: save_evidence_image()   [เขียนไฟล์ .jpg]
        │  └─► _emit("ITEM_LANDED") → api/retry_queue.py: send_or_queue()
        │                                    │
        ▼                                    ▼
  bg.rebaseline() + tracker.clear_all()  api/client.py: post_event() → ☁️ server
  (bg = เฟรมปัจจุบัน, พร้อมชิ้นถัดไป)       (ส่งไม่ได้ → เก็บ queue รอ retry)
        │
        ▼
  core/reset_policy.py: decide_reset()  → ถึงเวลา reset ไหม → main.apply_reset()
```

### 4.2 เส้นทาง order (ขนานกับเส้นทางหลัก)

```
  ☁️ server ──(WebSocket: new_order)──► api/order_listener.py
                                              │ เก็บใน _pending_order
                                              ▼
  main.py loop: get_pending_order() ──► sm.set_order()  [เริ่มนับ ORDER_WINDOW]
                                              │
                        (ของตกครบ / หมดเวลา)  ▼
  core/state_machine.py: finalize_order() → เทียบ got vs expected
                                              │
                                              ▼
                          _emit("ORDER_RESULT") → ☁️ server (completed/anomaly/no_drop)
```

### 4.3 เส้นทางเสริม (background threads — รันตลอดเวลา)

เริ่มทั้งหมดใน `main.start_services()`

| Thread | ไฟล์ | ทำอะไร | ทุกกี่นาน (config) |
|--------|------|--------|-----------|
| retry loop | retry_queue.py | ส่ง event ที่ค้างซ้ำ | `RETRY_INTERVAL` 60 วิ |
| order listener | order_listener.py | ฟัง WebSocket รอ order | ตลอด (reconnect `WS_RECONNECT_SEC` 5 วิ) |
| disk cleanup | disk_cleanup.py | ลบภาพเก่า | `CLEANUP_INTERVAL_HOURS` 1 ชม. |
| ROI polling | client.py: `start_roi_polling()` | ดึง ROI ใหม่จาก server | `ROI_POLL_INTERVAL` 10 วิ |
| register + push ROI | client.py | ลงทะเบียนตู้ตอนเปิด | ครั้งเดียว |

> ทุก thread เป็น `daemon=True` = ดับตามโปรแกรมหลักอัตโนมัติ

---

## 5. วงจรชีวิต

ตัวอย่างจริง: **ลูกค้าสั่งน้ำ 2 ขวด** ระบบทำงานยังไงตั้งแต่ต้นจนจบ

```
[0] server ส่ง new_order (qty=2) ผ่าน WebSocket
      → order_listener เก็บไว้ → main loop เรียก sm.set_order()
      → state ยัง IDLE, เริ่มนับ ORDER_WINDOW (30 วิ)

[1] ขวดที่ 1 เริ่มตกลงมาในช่องรับของ
      → เกิด motion ใน ROI (is_motion_in_roi)
      → bg.freeze() (แช่แข็ง background ไว้ ไม่ให้ขวดถูกดูดเข้า bg)
      → sm.trigger("motion_in_ROI") → state: IDLE → DROP_DETECTED

[2] ขวดที่ 1 ตกถึงก้นช่อง หยุดนิ่ง
      → tracker เห็น centroid นิ่งครบ 4 เฟรม → state = SHAPE_CONFIRMED
      → capture_landed(): นิ่งครบ CAPTURE_HOLD_SEC → sm.trigger("still_in_ROI")
      → _capture_item(): บันทึกภาพ LANDED_item1.jpg, นับเป็นชิ้นที่ 1
      → state: DROP_DETECTED → EVIDENCE_CAPTURED
      → ส่ง ITEM_LANDED event ขึ้น server
      → reset_order_window() (นับ 30 วิใหม่ รอชิ้นถัดไป)
      → bg.rebaseline() + tracker.clear_all()
         (bg = เฟรมนี้, ขวดที่ 1 กลืนเข้า bg, tracker ลืมขวดที่ 1)

[3] ขวดที่ 2 ตกลงมา (bg สะอาดแล้ว ขวด 2 = motion ใหม่)
      → tracker สร้าง object ใหม่ → MOVING → นิ่ง → SHAPE_CONFIRMED
      → _capture_item(): บันทึก LANDED_item2.jpg, นับเป็นชิ้นที่ 2
      → item_count() == order_qty() == 2

[4] หมด ORDER_WINDOW (ไม่มีของตกเพิ่มใน 30 วิ)
      → decide_reset() คืน "order_done"
      → sm.finalize_order(): got=2, expected=2 → status = "completed"
      → บันทึก ORDER_SUMMARY.jpg → ส่ง ORDER_RESULT + ภาพขึ้น server
      → reset_all(): state → IDLE, bg.unfreeze() + grace period พร้อมรับ order ถัดไป
```

**กรณีผิดปกติ:**
- ของตกแค่ 1 ขวด (ค้าง 1 ขวด) → `got=1, expected=2` → `anomaly`
- ไม่ตกเลย → หมด ORDER_WINDOW โดยไม่มี capture → `got=0` → `no_drop`
- ไม่มี order เลยแต่มี motion (คนเอามือล้วง/สิ่งแปลกปลอม) → จับได้ แต่ภาพไปลง
  โฟลเดอร์ `without_order/` แยกไว้ให้ตรวจสอบ

---

## 6. รายละเอียดรายไฟล์

### 6.1 `config.py` — ศูนย์รวมค่าตั้ง

โหลดค่าจาก `.env` (ผ่าน `python-dotenv`) แปลงเป็น Python constant ให้ไฟล์อื่น import
**ทุกค่าปรับผ่าน .env ได้โดยไม่ต้องแก้โค้ด** ยกเว้นหมวด 6 (`FRAME_W/FRAME_H`, `ROI_CONFIG_PATH`)

- ค่าเรียงเป็น 6 หมวดตามความสำคัญ (ดูตารางเต็มในหัวข้อ 8) แต่ละค่ามีคอมเมนต์บอกว่า ↑/↓ แล้วเกิดอะไร
- ใส่ค่าผิดรูปแบบใน .env (เช่น `MOT_THRESH=abc`) → โปรแกรมหยุดพร้อมบอกชื่อค่าที่ผิด
- `summary()` — คืนข้อความรายการค่าที่ใช้จริงทั้งหมด (ซ่อน `API_KEY`)
  main เรียกตอน startup → ดูได้จาก `docker compose logs`

---

### 6.2 `core/detect.py` — สร้าง motion mask + หากล่อง

โมดูลนี้ไม่มี state ใด ๆ (pure function) รับ input ออก output ตรง ๆ ทดสอบง่าย

#### `build_fgmask(diff, mot_thresh, open_ksize, dilate_ksize, dilate_iter)`
สร้าง **binary mask** (ภาพขาว-ดำ) จากภาพ diff
- **input:** `diff` = ภาพ absdiff (เฟรม - background), ค่ายิ่งสูง = เปลี่ยนยิ่งมาก
- **ขั้นตอน:**
  1. `threshold`: ตรงไหน diff > mot_thresh → ขาว (255), ที่เหลือ → ดำ (0)
  2. `MORPH_OPEN`: ลบจุด noise เล็ก ๆ (จุดขาวเดี่ยว ๆ จากสัญญาณกล้อง)
  3. `MORPH_DILATE`: ขยายมวลขาวให้ชิ้นส่วนที่ขาดของวัตถุเดียวเชื่อมเป็นก้อนตัน
- **ทำไม OPEN ก่อน DILATE:** ต้องลบ noise ก่อน ไม่งั้น dilate จะขยาย noise ตามไปด้วย
- **output:** mask ขาว-ดำ (numpy uint8)

#### `contour_boxes(fgmask, min_area)`
หา **กรอบสี่เหลี่ยม** ครอบแต่ละก้อนขาวใน mask
- ใช้ `cv2.findContours` หาเส้นขอบของแต่ละก้อน
- กรองก้อนที่พื้นที่ ≤ `min_area` ทิ้ง (เล็กเกิน = noise)
- **output:** list ของ `(x, y, w, h)`

#### `drop_large_boxes(boxes, roi_areas, max_ratio)`
ตัดกล่องที่ใหญ่เกิน `max_ratio` ของพื้นที่ ROI area ใดก็ได้ — ใช้เฉพาะเฟรมที่เจอ env change
(ก้อนใหญ่ = แสง/bg เปลี่ยน ไม่ส่งเข้า tracker แต่ก้อนเล็กที่เหลือยังส่งต่อ)

#### `group_close_boxes(boxes, max_dist, overlap_pad, mode)`
**รวมกล่องที่เป็นชิ้นส่วนของวัตถุเดียวกัน** กลับเป็นกล่องเดียว
- ปัญหา: วัตถุ 1 ชิ้นบางทีแตกเป็นหลาย contour (mask ขาดกลาง)
- `mode="distance"` (default): กล่องที่ขอบห่างกัน < `max_dist` → รวมเป็นก้อน
  ของ 2 ชิ้นที่ตกห่างกันเกิน max_dist จะ **ไม่** ถูกรวม → นับแยกได้
- `mode="overlap"`: รวมเฉพาะกล่องที่ซ้อนทับกันจริง
- ใช้ **union-find แบบง่าย** (วน group แล้ว merge กลุ่มที่เชื่อมกัน)
- **output:** list ของกล่องที่รวมแล้ว `(x, y, w, h)`

---

### 6.3 `core/tracker.py` — จำวัตถุข้ามเฟรม

#### `class MemoryTracker`
ตัวจำวัตถุ เก็บ `self.objects = {id: {...}}` แต่ละ object มี field:
| field | ความหมาย |
|-------|----------|
| `centroid` | จุดกึ่งกลาง (cx, cy) |
| `shape` | ขนาด (w, h) |
| `state` | MOVING / DETECTING / SHAPE_CONFIRMED |
| `first_seen` | เวลาที่เจอครั้งแรก (ใช้กัน noise แวบเดียว) |
| `shape_stable_count` | นับเฟรมที่ centroid นิ่งติดต่อกัน |
| `shape_confirmed_time` | เวลาที่ยืนยันว่านิ่ง (= ลงจอด) |
| `ghost_frames` | นับเฟรมที่หายไป (tolerance ก่อนลบ) |

**`update(detected_boxes)`** — เรียกทุกเฟรม เป็นหัวใจของ tracker:
1. **Matching:** สำหรับแต่ละกล่องที่เจอ หา object เดิมที่ centroid **ใกล้ที่สุด**
   (ระยะ < `TRACK_MATCH_DIST`) → ถือว่าเป็นตัวเดิมที่ขยับมา
   - ถ้าเจอคู่: อัปเดต centroid/shape, เช็คว่านิ่งไหม
     - กล่องหดเหลือ < `SHRINK_RATIO` (75%) และขยับ < `SHRINK_MAX_MOVE` (30px)
       → ถือเป็น noise กระพริบ คืนกล่องเดิม, ปกติหดได้ไม่เกินเฟรมละ 5% (`SHRINK_SMOOTH`)
     - centroid ขยับ ≤ `CENTROID_STABLE_DIST` → `shape_stable_count++`
     - นิ่งครบ `LANDING_STABLE_FRAMES` เฟรม → state = **SHAPE_CONFIRMED** (ลงจอด!)
     - ขยับเยอะ → รีเซ็ต count, state = DETECTING
   - ถ้าไม่เจอคู่: สร้าง object ใหม่ (state = MOVING, id ใหม่)
2. **Disappearance:** object เดิมที่ไม่ถูก match เฟรมนี้ = หายไป
   - เพิ่งเกิด < `NEW_OBJ_GRACE_SEC` (0.5 วิ) → ลบทันที (noise)
   - หายเกิน `GHOST_FRAME_TOLERANCE` เฟรม → ลบ (ของออกจาก ROI จริง)
   - ยังไม่เกิน → เก็บไว้ก่อน (เผื่อกระพริบ)
- **output:** `self.objects` (dict ล่าสุด) — main loop เอาไปตัดสินใจต่อ

**`clear_all()`** — ล้าง object ทั้งหมด (เรียกหลัง capture + re-baseline และตอน reset)
> หมายเหตุ: **ไม่ reset `next_id`** — เพราะถ้า id ซ้ำกับที่ state machine จำอยู่
> ของชิ้นใหม่อาจถูก skip โดยไม่ตั้งใจ

**helper ระดับโมดูล:**
- `is_motion_in_roi(tracked)` — มี object ที่ยังขยับไหม (IDLE ใช้ตัดสินว่าเริ่มมีของตก)
- `has_active_motion(tracked, captured_ids)` — มีมือ/ของใหม่ขยับ (ไม่นับของที่ capture แล้ว)
  ใช้ทั้งใน `reset_policy` (หยุด hold timer) และ `ui/overlay` (แสดง countdown)

---

### 6.4 `core/roi.py` — บริเวณที่สนใจ

#### `class ROIManager`
โหลด/จัดการพิกัด ROI จาก `data/roi_config.json` (`ROI_CONFIG_PATH`) รองรับ 4 แบบ:
`rect` (สี่เหลี่ยม), `polygon`/`quad` (หลายเหลี่ยม), `multi_polygon` (หลายพื้นที่)

| method | หน้าที่ |
|--------|---------|
| `load()` | อ่าน json → เก็บ points/rect/areas ตาม roi_type · ไฟล์พัง/ค่าผิด → log warning แล้ว**ใช้ ROI เดิมต่อ** (ไม่ตาย) · ไม่มีไฟล์ → สร้าง default |
| `reload_if_changed()` | เช็ค mtime ของไฟล์ทุก `ROI_CHECK_INTERVAL` (5 วิ) ถ้าเปลี่ยน → โหลดใหม่ (server แก้ ROI ได้สด) |
| `_scale_point()` | แปลงพิกัดจากขนาดที่ตั้งไว้ → ขนาดเฟรมจริง (เผื่อ config คนละ resolution) |
| `_scaled_rect()` | คืน (x1,y1,x2,y2) ของ rect หลัง scale |
| `build_mask(shape)` | สร้าง mask ขาว-ดำ: ใน ROI = ขาว, นอก = ดำ (ใช้ bitwise_and กับ fgmask) |
| `get_roi_areas(shape)` | คืนแต่ละพื้นที่ ROI แยกกัน + จำนวน pixel (ใช้ตรวจ env change) |
| `draw(frame)` | วาด ROI ลงเฟรม (โหมด DISPLAY เท่านั้น) |

**จุดสำคัญ:** `reload_if_changed()` เช็คไฟล์แค่ทุก 5 วิ (ไม่ใช่ทุกเฟรม) เพื่อลด I/O บน eMMC

---

### 6.5 `core/state_machine.py` — สมองของระบบ

#### `class VendingStateMachine(machine_id)`
เก็บสถานะ + ของที่จับได้ + context ของ order สื่อสารกับ server ผ่าน `_emit()`

**field สำคัญ:**
- `state` — IDLE / DROP_DETECTED / EVIDENCE_CAPTURED
- `captured_items` — dict ของที่จับได้ `{obj_id: {land_time, item_no, cx, cy, w, h, ...}}`
- `current_order` — order ปัจจุบัน `{id, machine_id, qty}` หรือ None
- `order_window_start` — เวลาเริ่มนับ ORDER_WINDOW
- `transaction_id` — รหัสธุรกรรม `TXN-YYYYMMDD-HHMMSS`

**method หลัก:**

| method | หน้าที่ |
|--------|---------|
| `set_order(order)` | รับ order → เริ่มนับ ORDER_WINDOW ทันที |
| `has_order()` / `order_qty()` | เช็ค/อ่านจำนวนที่สั่ง |
| `is_order_window_expired(now)` | ORDER_WINDOW หมดหรือยัง |
| `reset_order_window(now)` | รีเซ็ต timer (เรียกทุกครั้งที่ capture ได้) |
| `trigger(event, ...)` | **ตัวขับ state machine** (ดูหัวข้อ 7) |
| `can_capture_more()` | ถ้ามี order + CAP_COUNT_TO_ORDER_QTY → ห้ามนับเกิน qty |
| `_capture_item(...)` | บันทึกของ 1 ชิ้น: save ภาพ + เก็บ captured_items + emit |
| `finalize_order(frame)` | สรุปผล order → completed/anomaly/no_drop → emit |
| `new_transaction_id()` | สร้าง `TXN-YYYYMMDD-HHMMSS` (ใช้ที่เดียวทั้งระบบ) |
| `reset()` | ล้าง field กลับ IDLE |

**`_emit(event, transaction_id, image_path, **fields)`** — ส่ง event ขึ้น server ผ่าน thread แยก
| event | ส่งเมื่อ | transaction_id |
|-------|---------|----------------|
| `ITEM_LANDED` | ของตก 1 ชิ้น + ภาพ | `{txn}-item{n}` |
| `NO_DROP` | DROP_TIMEOUT หมดโดยไม่มีของ (กรณีไม่มี order) | `{txn}` |
| `ORDER_RESULT` | สรุปผล order + ภาพ summary | `{txn}-summary` |

> ทุก emit ยิงผ่าน `send_or_queue()` ใน thread แยก → ไม่ block main loop
> ถ้าเน็ตหลุด event จะไปนอนใน retry queue เอง

---

### 6.6 `core/background.py` — background model

#### `class BackgroundModel`
รวมสถานะ background ทั้งหมดไว้ที่เดียว (เดิมเป็นตัวแปรลอย 8 ตัวใน main loop)

| field | ความหมาย |
|-------|----------|
| `bg` | ภาพพื้นหลังปัจจุบัน (float32 grayscale) |
| `frozen` | True = หยุดเรียนรู้ (กำลังรับของ) |
| `snapshot` | bg ตอน freeze / หลัง rebaseline (ใช้ restore ตอน env change) |
| `clean_bg` | bg ที่ไม่มี motion เก็บไว้ทุก `CLEAN_BG_INTERVAL` ตอน IDLE |
| `grace_until` | เวลาสิ้นสุด grace period หลัง reset |

| method | เรียกเมื่อ | ทำอะไร |
|--------|-----------|--------|
| `update(gray, now, idle)` | ทุกเฟรม | คืน diff; ถ้าไม่ freeze → เรียนรู้ bg (`BG_LEARNING_RATE`, ระหว่าง grace ใช้ `BG_RELEARN_RATE`) + เก็บ clean_bg |
| `freeze()` | IDLE เจอ motion | หยุดเรียนรู้ + ดึง bg กลับไปที่ clean_bg |
| `rebaseline(gray)` | capture สำเร็จ | เฟรมนี้เป็น bg ใหม่ (mask ว่างทันที) |
| `restore_snapshot()` | env change ตอนไม่ IDLE | ดึง snapshot กลับมา |
| `unfreeze(now)` | reset กลับ IDLE | กลับมาเรียนรู้ + เข้า grace `RESET_GRACE_SEC` |
| `clear()` | กล้องหลุด / กดปุ่ม r | ล้างหมด เฟรมถัดไปเป็น bg ใหม่ |
| `in_grace(now)` | ก่อน trigger ของใหม่ | ยังอยู่ใน grace period ไหม |

#### `find_env_change(fgmask, roi_areas)`
มี ROI area ไหนที่ motion รวมเกิน `MAX_BLOB_ROI_RATIO` ไหม → True = env change (ดูหัวข้อ 10.3)

---

### 6.7 `core/frame_source.py` — แหล่งภาพ

#### `class FrameSource(source)`
- `read()` — คืนเฟรม 640x480 เสมอ (resize ให้ถ้าขนาดไม่ตรง) หรือ `None` ถ้ากล้องหลุด
  (ปิดแล้วเปิดใหม่หลัง `CAMERA_RECONNECT_SEC` — main จะ `bg.clear()`; ไฟล์วิดีโอจะวนเล่นซ้ำ)
- `pace()` — หน่วงให้ไฟล์วิดีโอเล่นตาม FPS จริง (กล้องจริงไม่ทำอะไร)

---

### 6.8 `core/reset_policy.py` — กติกา reset

#### `decide_reset(sm, tracked, now)` → `"order_done"` / `"hold_timeout"` / `"drop_timeout"` / `"empty_frame"` / `None`
รายละเอียดลำดับความสำคัญในหัวข้อ 7.3 — main เรียก `apply_reset()` ทำงานตามเหตุผลแล้ว `reset_all()`

---

### 6.9 `api/client.py` — ยิง HTTP ขึ้น cloud

| function | หน้าที่ |
|----------|---------|
| `_headers()` | สร้าง header ใส่ API key (ถ้ามี) — ใช้ร่วมกันทั้ง api/ |
| `post_event(payload, image_path)` | ★ ส่ง event + ภาพ (multipart) ขึ้น server → คืน True/False |
| `register_machine(id)` | ลงทะเบียนตู้ตอน startup (ส่ง SYSTEM_ONLINE, server auto-create machine) |
| `fetch_remote_roi(id)` | ดึง ROI จาก server → เขียนทับ local **เฉพาะเมื่อข้อมูลต่างจากเดิม** แบบ atomic (tmp → `os.replace`) |
| `start_roi_polling(id)` | thread เรียก `fetch_remote_roi` ทุก `ROI_POLL_INTERVAL` (10 วิ) |
| `push_default_roi(id, path)` | push ROI local ขึ้น server ถ้า server ยังไม่มี (ครั้งเดียว) |
| `submit_frame(id, frame)` | main loop ฝากเฟรมไว้แล้วไปต่อทันที — thread `frame-sender` ส่งเฉพาะเฟรมล่าสุด (ส่งไม่ทัน → เฟรมเก่าถูกทับทิ้ง) ทุก `SEND_INTERVAL` (0 = ปิด) |
| `send_frame(id, frame)` | ส่งภาพสด JPEG ขึ้น `realtime-image` (timeout 2 วิ) — ถูกเรียกจาก thread ไม่ใช่ main loop |

**`post_event` คืนค่า boolean** — สำคัญมาก เพราะ retry_queue ใช้ค่านี้ตัดสินว่า
จะลบภาพทิ้ง (สำเร็จ) หรือเก็บ queue (ล้มเหลว)

---

### 6.10 `api/retry_queue.py` — ทนเน็ตหลุด

หลักการ: **event ทุกตัวต้องส่งถึง server ให้ได้ ถ้าส่งไม่ได้ห้ามทิ้ง**

| function | หน้าที่ |
|----------|---------|
| `send_or_queue(payload, image_path)` | ★ ลองส่งทันที สำเร็จ→ลบภาพ, ล้มเหลว→เก็บ queue |
| `_retry_loop()` | thread วน retry queue ทุก `RETRY_INTERVAL` สำเร็จ→ลบภาพออกจาก queue |
| `start_retry_thread()` | เริ่ม thread (เรียกตอน startup) |
| `_delete_image(path)` | ลบภาพออกจากดิสก์ (หลังส่งสำเร็จ) |

**flow:** state_machine เรียก `send_or_queue` แทน `post_event` ตรง ๆ เสมอ
→ ได้ retry ฟรีโดยไม่ต้องคิดเรื่องเน็ตในโค้ดหลัก

> **ข้อควรรู้:** queue เก็บใน memory (list) — ถ้าโปรแกรมดับ queue หาย
> แต่ภาพยังอยู่บนดิสก์ (ไม่ถูกลบเพราะยังไม่สำเร็จ)

---

### 6.11 `api/order_listener.py` — รับ order ผ่าน WebSocket

เชื่อม WebSocket ไป server ฟัง message `new_order` แบบ real-time

| function | หน้าที่ |
|----------|---------|
| `start_order_listener()` | เริ่ม thread เชื่อม WS (เรียกตอน startup) |
| `_run_forever()` | loop เชื่อม WS + reconnect อัตโนมัติทุก `WS_RECONNECT_SEC` ถ้าหลุด |
| `_on_message(ws, msg)` | รับ message: ถ้าเป็น new_order ของตู้เรา → เก็บ _pending_order |
| `get_pending_order()` | main loop เรียกดู order ที่รออยู่ |
| `clear_pending_order()` | ล้าง order (เมื่อจบ order แล้ว) |

**จุดสำคัญ:**
- ใช้ `threading.Lock` เพราะ main loop กับ WS thread อ่าน/เขียน `_pending_order` พร้อมกัน
- กรอง `machine_id` — server broadcast ไปทุกตู้ แต่รับเฉพาะของตัวเอง
- ถ้ามี order ค้างอยู่แล้ว → reject order ใหม่ (ทำทีละ order)

---

### 6.12 `utils/image_saver.py` — บันทึกภาพหลักฐาน

#### `save_evidence_image(frame, event_name, transaction_id, has_order)`
- แยก 2 โฟลเดอร์: `with_order/` (มี order) และ `without_order/` (ไม่มี — สิ่งแปลกปลอม)
- ตั้งชื่อไฟล์: `{txn_id}_{event}_{timestamp}.jpg`
- เขียน label เวลา + ประเภทลงบนภาพก่อนบันทึก
- **คืน path ของไฟล์** — state_machine เอาไปแนบกับ event ตอน emit

---

### 6.13 `utils/disk_cleanup.py` — กันดิสก์เต็ม

#### `start_cleanup_thread()`
thread วนลบภาพเก่ากว่า `CLEANUP_KEEP_DAYS` (default 3 วัน) ทุก `CLEANUP_INTERVAL_HOURS` (1 ชม.)
> สำคัญบน Orange Pi ที่ eMMC เล็ก — ถ้าไม่ลบ ภาพหลักฐานสะสมจนเต็ม

---

### 6.14 `utils/logger.py` — logging

#### `get_logger(name)`
คืน logger `vending.<name>` — ทุกตัวส่งต่อไปที่ logger แม่ `vending` ซึ่งมี handler ชุดเดียว:
ไฟล์ `logs/vending.log` (rotate 5MB × 5 ไฟล์, ระดับ DEBUG) และ console (ระดับ INFO)
ทั้งระบบใช้ logger แทน `print` (ข้อความมี timestamp + ชื่อโมดูล)

#### `LogThrottle(interval)`
จำกัดความถี่ log ที่อาจเกิดทุกเฟรม — ผ่านได้ 1 ครั้งต่อ interval แล้วบอกจำนวนที่ข้ามไป
ใช้กับ: env change / BG restored (5 วิ), ส่งภาพสดไม่สำเร็จ (60 วิ)

---

### 6.15 `ui/overlay.py` — จอ debug (เฉพาะ PC)

- `render_overlay(...)` — วาด ROI, badge สถานะ, `BG FROZEN`, `Items: n`, countdown order /
  `RESET IN`, กรอบ object ใน tracker
- `draw_captured_items(frame, sm)` — วาดกรอบ `#n COUNTED` จากพิกัดที่จำไว้ (ดู 10.5)

ไม่มีผลต่อการนับ — บน Orange Pi (`HEADLESS=1`) ไม่ถูกเรียกเลย

---

## 7. State Machine

### 7.1 แผนภาพสถานะ

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
              ┌──────────┐                                    │
       ┌─────▶│   IDLE   │                                    │
       │      └──────────┘                                    │
       │           │ motion_in_ROI                            │
       │           │ (เจอการเคลื่อนไหวใน ROI)                 │
       │           ▼                                          │
       │   ┌────────────────┐                                 │
       │   │  DROP_DETECTED  │  ของกำลังตก                     │
       │   └────────────────┘                                 │
       │           │ still_in_ROI                             │
       │           │ (ของนิ่ง = ลงจอด → capture)              │
       │           ▼                                          │
       │   ┌────────────────────┐                             │
       │   │ EVIDENCE_CAPTURED   │ ◀──┐ still_in_ROI          │
       │   └────────────────────┘    │ (ชิ้นถัดไปตกมาอีก)     │
       │           │                 │                        │
       │           └─────────────────┘                        │
       │                                                      │
       │  reset เมื่อ: order window หมด / hold timeout /       │
       └──────────  drop timeout / frame ว่าง  ────────────────┘
```

### 7.2 `trigger(event, ...)` — ตารางเปลี่ยนสถานะ

| state ปัจจุบัน | event | ทำอะไร | state ใหม่ |
|----------------|-------|--------|-----------|
| IDLE | `motion_in_ROI` | ตั้ง drop_time, สร้าง transaction_id, log ของกำลังตก | DROP_DETECTED |
| DROP_DETECTED | `still_in_ROI` | `_capture_item()` (ถ้ายังนับได้) | EVIDENCE_CAPTURED |
| DROP_DETECTED | `timeout` | ถ้าไม่มีของ → `_emit("NO_DROP")`, reset | IDLE |
| EVIDENCE_CAPTURED | `still_in_ROI` | capture ชิ้นถัดไป (ถ้ายังนับได้) | คงเดิม |

### 7.3 การตัดสินใจ reset (`core/reset_policy.py: decide_reset()`)

main เรียกเฉพาะตอน state = DROP_DETECTED / EVIDENCE_CAPTURED (หลังพยายาม capture ในเฟรมนั้น)
ลำดับความสำคัญ:

1. **`order_done`** — มี order + order window หมด → `finalize_order()` + reset
2. **มีของที่นับแล้ว** → ห้าม DROP_TIMEOUT / frame ว่าง มาตัด
   - มี motion/ของใหม่ใน ROI → เลื่อน `land_time` เป็นตอนนี้ (เริ่มนับ hold ใหม่)
   - มี order → รอ order window หมด (ข้อ 1) อย่างเดียว
   - ไม่มี order → **`hold_timeout`** ครบ `CONFIRMED_HOLD_TIMEOUT` โดยไม่มี motion ใหม่ → reset
3. **`drop_timeout`** — ไม่มี order + ยังไม่ได้ของ + เกิน `DROP_TIMEOUT` → ส่ง NO_DROP + reset
4. **`empty_frame`** — ไม่มี order + ยังไม่ได้ของ + ROI ว่าง → reset (มี order → รอ window หมด)

ทุกกรณีจบด้วย `reset_all()` = `sm.reset()` + `tracker.clear_all()` + `bg.unfreeze()` (เข้า grace)

**กรณีพิเศษใน main.py:** IDLE + มี order + window หมดโดยไม่มีของตกเลย → `finalize_order()` (no_drop)
แล้ว `sm.reset()` อย่างเดียว (bg ยังไม่ถูก freeze จึงไม่ต้อง grace) — อยู่ใน main เพราะต้องเช็ค
ก่อนรับ motion ใหม่ในเฟรมเดียวกัน

> เหตุผลที่ logic reset ไม่อยู่ใน state_machine: มันต้องดูข้อมูลจาก tracker
> (มี motion ไหม, frame ว่างไหม) ซึ่ง state_machine ไม่รู้จัก

---

## 8. การตั้งค่า

### 8.1 ตัวแปร .env

ทุกค่าอยู่ใน `config.py` (มีคอมเมนต์อธิบาย) และตัวอย่างใน `.envexample`
ค่าที่ไม่ได้ใส่ใน .env ใช้ default ในตาราง · ตอนเริ่มโปรแกรมจะ log ค่าที่ใช้จริงทั้งหมด

**หมวด 1 — ตัวตนตู้และการเชื่อมต่อ (ต้องตั้งทุกตู้):**
| ตัวแปร | default | ความหมาย |
|--------|---------|----------|
| `MACHINE_ID_DEFAULT` | VENDING_01 | ชื่อตู้ (ห้ามซ้ำ) — `python main.py --machine X` ทับได้ |
| `CLOUD_API_URL` | (ว่าง) | endpoint ส่ง event เช่น `http://host:5100/api/events` |
| `WS_URL` | ws://localhost:5100/ws | WebSocket url รับ order |
| `API_KEY` | (ว่าง) | key ยืนยันตัวตนกับ server (ถ้ามี) |
| `CAMERA_INDEX` | 0 | เลขกล้อง หรือ path ไฟล์วิดีโอ |
| `HEADLESS` | 1 | 1 = ไม่มีจอ (Orange Pi / Docker), 0 = เปิดหน้าต่าง debug (PC) |

**หมวด 2 — ความไว / ความเร็วการจับ (จูนบ่อยที่สุด):**
| ตัวแปร | default | ความหมาย | ปรับเมื่อ |
|--------|---------|----------|-----------|
| `CAPTURE_HOLD_SEC` | 1.5 | นิ่งเพิ่มหลังลงจอดก่อน capture (วิ) | ลูกค้าหยิบเร็วแล้วพลาด → ลด |
| `MOT_THRESH` | 25 | ความไวจับ motion | ของจางหลุด → ลด / noise เยอะ → เพิ่ม |
| `MIN_AREA` | 150 | พื้นที่ขั้นต่ำของก้อน (px²) | ของเล็กหลุด → ลด |
| `MAX_BLOB_ROI_RATIO` | 0.30 | ก้อนใหญ่เกินสัดส่วนนี้ของ ROI = env change | ตู้ขายของชิ้นใหญ่ → เพิ่ม |
| `LANDING_STABLE_FRAMES` | 4 | เฟรมที่ต้องนิ่งจึงถือว่าลงจอด | |
| `CENTROID_STABLE_DIST` | 10 | ระยะ centroid ขยับได้แล้วยังถือว่านิ่ง (px) | |

**หมวด 3 — เวลา order / reset:**
| ตัวแปร | default | ความหมาย |
|--------|---------|----------|
| `ORDER_WINDOW` | 30 | เวลารอของตกหลังได้ order (วิ) — นับใหม่ทุกครั้งที่ capture |
| `CONFIRMED_HOLD_TIMEOUT` | 30 | ไม่มี order: รอว่าไม่มีของตกเพิ่มก่อน reset (วิ) |
| `DROP_TIMEOUT` | 25 | ไม่มี order: เห็น motion แต่ไม่มีของนิ่งนานเท่านี้ → NO_DROP (วิ) |
| `CAP_COUNT_TO_ORDER_QTY` | 1 | ห้ามนับเกิน qty ที่สั่ง (⚠ จะตรวจไม่พบตู้ปล่อยของเกิน) |

**หมวด 4 — ขั้นสูง (ไม่ควรแตะ):**
| ตัวแปร | default | ความหมาย |
|--------|---------|----------|
| `GROUP_MODE` / `GROUP_DIST` / `GROUP_OVERLAP_PAD` | distance / 60 / 4 | การรวมก้อนที่แตก |
| `MORPH_OPEN_KSIZE` / `MORPH_DILATE_KSIZE` / `MORPH_DILATE_ITER` | 5 / 5 / 2 | ทำความสะอาด mask |
| `TRACK_MATCH_DIST` | 150 | ระยะที่ tracker match วัตถุเดิม (px) |
| `GHOST_FRAME_TOLERANCE` | 2 | ก้อนหายได้กี่เฟรมก่อนลบ |
| `BG_LEARNING_RATE` | 0.1 | ความเร็วที่ bg ปรับตามแสง |
| `RESET_GRACE_SEC` / `BG_RELEARN_RATE` | 1.5 / 0.3 | grace period หลัง reset (ดู 10.1) |
| `CLEAN_BG_INTERVAL` | 0.5 | เก็บ clean_bg ทุกกี่วิ (ดู 10.2) |

**หมวด 5 — ระบบ / ดูแลเครื่อง:**
| ตัวแปร | default | ความหมาย |
|--------|---------|----------|
| `SEND_INTERVAL` | 1 | ส่งภาพสดทุกกี่วิ (0 = ปิด) |
| `ROI_POLL_INTERVAL` / `ROI_CHECK_INTERVAL` | 10 / 5 | ดึง ROI จาก server / เช็คไฟล์ ROI |
| `RETRY_INTERVAL` | 60 | retry event ที่ค้าง (วิ) |
| `CAMERA_RECONNECT_SEC` / `WS_RECONNECT_SEC` | 2 / 5 | รอก่อนต่อใหม่ |
| `CLEANUP_KEEP_DAYS` / `CLEANUP_INTERVAL_HOURS` | 3 / 1 | ลบภาพเก่า |

**หมวด 6 — ค่าคงที่ (แก้ในโค้ดเท่านั้น ห้ามแก้):** `FRAME_W=640`, `FRAME_H=480`, `ROI_CONFIG_PATH`

### 8.2 `data/roi_config.json` — พิกัด ROI

```json
{
  "frame": { "width": 640, "height": 480 },
  "roi_type": "quad",
  "points": [
    { "x": 247, "y": 166 }, { "x": 454, "y": 164 },
    { "x": 460, "y": 241 }, { "x": 246, "y": 239 }
  ]
}
```
- `frame` = ขนาดตอนตั้งพิกัด (ระบบ scale ให้เองถ้าเฟรมจริงต่างขนาด)
- แก้ได้ 2 ทาง: แก้ไฟล์ตรง ๆ (reload อัตโนมัติใน 5 วิ) หรือแก้จาก server (sync ทุก 10 วิ)

---

## 9. การ deploy

### 9.1 รันบน PC (ทดสอบ + debug)
```bash
pip install -r requirements-pc.txt     # ไม่ใช่ requirements.txt (ตัวนั้นเป็น opencv headless เปิดหน้าต่างไม่ได้)
# ตั้ง .env: HEADLESS=0, CAMERA_INDEX=0 (หรือ path วิดีโอ)
python main.py
# หรือระบุชื่อตู้: python main.py --machine VENDING_02
```
โหมดนี้จะเปิด 2 หน้าต่าง: "Vending System" (ภาพ + overlay) และ "Motion Mask"
กด `q` = ออก, `r` = reset ระบบ (ล้าง state + tracker + background ทั้งหมด)

### 9.2 รันบน Orange Pi (production, Docker)
```bash
cp .envexample .env      # แก้หมวด 1 ให้ตรงตู้, HEADLESS=1
docker compose up -d --build
docker compose logs -f --tail=100 vending-cam   # ดู "Active config" ว่าค่าถูก
```
`docker-compose.yml` ผูก `/dev/video0` (กล้อง) และ mount `evidence_images/`, `data/`, `logs/`
ออกมานอก container → ภาพ, ROI และ log ไม่หายเมื่อ rebuild/restart

**อัปเดตแบบ rollback ได้** (compose ตั้งชื่อ image เป็น `vending-cam:latest`):
```bash
docker tag vending-cam:latest vending-cam:prev    # เก็บ image ที่ใช้อยู่ไว้ก่อน
# copy source ใหม่ (ไม่เอา .venv / .env / evidence_images / logs) แล้ว
docker compose up -d --build
docker compose logs -f --tail=100 vending-cam     # ดู "Active config" ว่าค่าถูก

# มีปัญหา → กลับไป image เดิมทันทีโดยไม่ต้อง build:
docker tag vending-cam:prev vending-cam:latest
docker compose up -d --no-build
```
container ใช้เวลาไทย (`TZ=Asia/Bangkok` ใน Dockerfile) → เวลาใน log, ชื่อไฟล์ภาพ และ TXN ID เป็นเวลาไทย

### 9.3 requirements
```
numpy, requests, python-dotenv, websocket-client
+ opencv-python-headless (requirements.txt — Pi/Docker)  หรือ  opencv-python (requirements-pc.txt — PC)
```
ห้ามลง opencv 2 แบบพร้อมกันใน env เดียว (import cv2 ชนกัน)

---

## 10. จุดที่ต้องระวัง

จุดเหล่านี้เคยเป็น bug หรือเป็นดีไซน์ที่ไม่ชัดในตัวเอง — อ่านก่อนแก้โค้ด

### 10.1 มือถูก snapshot เป็น background ตอน reset
หลัง reset มือลูกค้าอาจยังอยู่ในเฟรม ถ้าล้าง bg ทันที เฟรมถัดไปจะจับมือเป็น background ใหม่
→ พอมือถอยออกกลายเป็น "blob หลอก"
**แก้แล้วด้วย:** `bg.unfreeze()` ไม่ล้าง bg แต่เข้า grace period (`RESET_GRACE_SEC` 1.5 วิ)
ช่วงนี้ re-learn เร็ว (`BG_RELEARN_RATE`) เพื่อดูดมือเข้า bg และห้าม trigger motion ใหม่

### 10.2 Clean BG snapshot
ตอน freeze background (เจอของชิ้นแรก) เราไม่ใช้ bg ปัจจุบัน (อาจดูดมือไปบางส่วนแล้ว)
แต่ใช้ `clean_bg` = snapshot ตอน IDLE + ไม่มี motion เก็บไว้ล่วงหน้าทุก `CLEAN_BG_INTERVAL`
→ ได้ background ที่สะอาดจริง

### 10.3 Large motion = env change
ถ้า motion รวมใน ROI area ใดเกิน `MAX_BLOB_ROI_RATIO` (30%) ของพื้นที่ → ถือว่าเป็น
"สภาพแวดล้อมเปลี่ยน" (แสง เงา คนบังกล้อง) ไม่ใช่ของตก:
- ก้อนที่ใหญ่เกิน threshold ถูกตัดออก ไม่ส่งเข้า tracker (ก้อนเล็กที่เหลือยังส่งต่อ)
- **IDLE:** ไม่ทำอะไรกับ bg — bg ยังเรียนรู้ปกติ (`BG_LEARNING_RATE`) จึงกลืนแสงใหม่ใน ~0.3 วิ
- **ไม่ IDLE (bg freeze อยู่):** `restore_snapshot()` ดึง bg ตอน freeze กลับมา + เลื่อน hold timer
  - ⚠ **known issue:** ถ้าแสงเปลี่ยน "ค้าง" หลังจับของได้แล้ว (ไม่มี order) bg ที่ freeze อยู่ไม่เรียนรู้แสงใหม่
    → env change เกิดทุกเฟรม → hold timer ถูกเลื่อนตลอด → ค้าง EVIDENCE_CAPTURED จนกว่าแสงจะกลับ
    (มี order → จบตาม ORDER_WINDOW ปกติ)
- ⚠ ของชิ้นใหญ่กว่า 30% ของ ROI จะถูกมองเป็น env change และไม่ถูกนับ

### 10.4 Re-baseline คือดีไซน์หลัก
`bg.rebaseline()` + `tracker.clear_all()` หลัง capture เป็นกลไกที่ทำให้ **นับของหลายชิ้นที่ตกทับที่เดิมได้**
(เดิมมี switch `REBASELINE_ON_CAPTURE` แต่ปิดแล้วระบบนับหลายชิ้นพัง จึงเปิดถาวร)

### 10.5 กรอบ COUNTED เป็นแค่ overlay
หลัง re-baseline ของถูกกลืนเข้า bg (มองไม่เห็นใน mask แล้ว) แต่เรายังวาดกรอบเขียว
"COUNTED" ได้ เพราะกรอบนั้นวาดจากพิกัดที่จำไว้ใน `captured_items` (cx/cy/w/h)
**ไม่เกี่ยวกับ motion mask** — อย่าไปหา object ใน tracker มาวาด (มันไม่มีแล้ว)

### 10.6 next_id ห้าม reset
`tracker.clear_all()` ล้าง objects แต่ **ไม่แตะ `next_id`** ถ้า reset id กลับเป็น 1
ของชิ้นใหม่อาจได้ id ซ้ำกับที่ `sm.captured_items` จำอยู่ → ถูก skip (`is_obj_captured` เป็น True)

### 10.7 retry queue อยู่ใน memory
ถ้าโปรแกรมดับ queue หาย แต่ภาพยังอยู่บนดิสก์ (ไม่ถูกลบเพราะ event ยังไม่สำเร็จ)
ถ้าต้องการ persist queue ข้าม restart ต้องเพิ่มการเขียน queue ลงไฟล์เอง (ยังไม่มี)

### 10.8 Video file pacing
ถ้า `CAMERA_INDEX` เป็น path วิดีโอ OpenCV จะอ่านเฟรมเร็วสุดเท่าที่ CPU ไหว
(ไม่ผูก FPS คลิป) ทำให้ timer เพี้ยน → `FrameSource.pace()` หน่วงให้เล่นตาม FPS จริง
กล้องจริงไม่ต้องหน่วง (ส่งเฟรมตามอัตราของมันเอง)

### 10.9 `tracked` คือ dict เดียวกับ `tracker.objects`
`tracker.clear_all()` ทำให้ตัวแปร `tracked` ใน main ว่างไปด้วย — reset_policy อาศัยพฤติกรรมนี้
(หลัง capture `tracked` ว่าง) ถ้าเปลี่ยน `update()` ให้คืน copy ต้องตรวจตรงนี้

---

## ภาคผนวก: คำถามที่มักถูกถาม

**Q: ระบบแยกแยะชนิดสินค้าได้ไหม?**
ไม่ได้ มันนับแค่ "จำนวนวัตถุที่ตกแล้วมานิ่ง" ถ้าต้องการจำแนกชนิด ต้องเพิ่มโมเดล
classification (เช่น YOLO) เข้าไปในขั้นตอนหลัง `contour_boxes`

**Q: ถ้าอยากเพิ่มความแม่นยำ ควรปรับอะไรก่อน?**
เริ่มจากหมวด 2 ใน config: `CAPTURE_HOLD_SEC`, `MOT_THRESH` (ความไว), `MIN_AREA` (กรองขนาด),
`MAX_BLOB_ROI_RATIO` แล้วค่อย `LANDING_STABLE_FRAMES` ปรับผ่าน .env ทดสอบกับวิดีโอจริงได้เลย

**Q: logic reset อยู่ที่ไหน?**
`core/reset_policy.py: decide_reset()` ที่เดียว (ยกเว้นกรณี IDLE + order หมด ดู 7.3)

**Q: 3 threads ส่งข้อมูลขึ้น server พร้อมกันจะชนกันไหม?**
ไม่ชน เพราะแต่ละ event เป็น HTTP request อิสระ retry queue มี lock กัน race
เฉพาะตอนแก้ list ส่วน order listener มี lock กัน `_pending_order`

**Q: ดู log ได้ที่ไหน?**
`docker compose logs vending-cam` (console) หรือไฟล์ `logs/vending.log` บน host (เก็บย้อนหลัง ~25MB)
