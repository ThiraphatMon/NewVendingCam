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
- รันได้ทั้งบน **PC (มีจอ debug)** และ **Raspberry Pi (ไม่มีจอ / headless)**

### สิ่งที่ระบบ *ไม่ได้* ทำ
- ไม่รู้ว่าสินค้าคือ "อะไร" (ไม่มี object classification / AI จำแนกชนิดสินค้า)
  มันจับแค่ "มีของเคลื่อนไหวแล้วมานิ่ง" = นับเป็น 1 ชิ้น
- ไม่ได้ตัดสินใจเรื่องเงิน/การจ่ายเงิน (นั่นเป็นหน้าที่ของระบบ order ฝั่ง server)

---

## 2. แนวคิดหลักที่ต้องเข้าใจก่อน

ก่อนอ่านโค้ด ต้องเข้าใจ 6 แนวคิดนี้ก่อน ไม่งั้นจะงงว่าทำไมโค้ดเขียนแบบนี้

### 2.1 Background Subtraction (การลบพื้นหลัง)
หัวใจของการจับ motion คือ **เปรียบเทียบเฟรมปัจจุบันกับ "ภาพพื้นหลัง" (background)**
- เก็บภาพพื้นหลังไว้ (ช่องรับของว่าง ๆ) เรียกว่า `bg_np`
- ทุกเฟรมใหม่ เอามาลบกับ background → `diff = |frame - bg|`
- ตรงไหน `diff` สูง = ตรงนั้นมีของเปลี่ยนไป = **motion**

Background ไม่ได้ fix ตายตัว แต่ค่อย ๆ อัปเดตตามสภาพแสง (running average ด้วย
`learning rate` = `LR`) เพื่อไม่ให้แสงเปลี่ยนกลายเป็น motion หลอก

### 2.2 ROI — Region of Interest (บริเวณที่สนใจ)
เราสนใจแค่ **ช่องรับสินค้า** ไม่ใช่ทั้งเฟรม (ข้างนอกอาจมีคนเดินผ่าน เงา ฯลฯ)
ROI คือรูปหลายเหลี่ยม (polygon/quad/rect) ที่วาดครอบเฉพาะช่องรับของ
motion ที่เกิดนอก ROI จะถูกตัดทิ้งทั้งหมด

### 2.3 "ของตก = เคลื่อนที่แล้วมานิ่ง"
กุญแจสำคัญของการนับ: **ของที่กำลังตกจะเคลื่อนที่ (centroid ขยับ) พอตกถึงที่จะนิ่ง**
- ของกำลังตก → state `MOVING` / `DETECTING`
- ของนิ่งครบ N เฟรม → state `SHAPE_CONFIRMED` = "ลงจอดแล้ว" = **จังหวะที่ capture**

เราไม่ได้รอ timer ยาว ๆ แต่จับทันทีที่ "นิ่ง" เพื่อให้พร้อมรับชิ้นถัดไปเร็ว

### 2.4 Re-baseline (ล้างพื้นหลังใหม่หลัง capture)
หลังจับของ 1 ชิ้นได้ เราเอา **เฟรมปัจจุบันทั้งภาพมาเป็น background ใหม่ทันที**
ผลคือ motion mask ว่างเปล่า (ของที่เพิ่งจับถูก "กลืน" เข้าพื้นหลัง)
→ ของชิ้นถัดไปที่ตกลงมา (แม้ตกทับที่เดิม) จะกลายเป็น motion ใหม่สด ๆ → นับเป็นชิ้นใหม่ได้

> นี่คือดีไซน์หลักของระบบ — เข้าใจตรงนี้แล้วจะเข้าใจ 80% ของโค้ด main loop

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
vending-clean/
├── main.py                  ★ หัวใจ — main loop, ประสานทุกอย่าง
├── config.py                ★ ค่าตั้งทั้งหมด (อ่านจาก .env)
├── .env                     ค่าตั้งจริงของเครื่องนี้ (ไม่ commit ขึ้น git)
├── requirements.txt         library ที่ต้องลง
├── Dockerfile               สร้าง container
├── docker-compose.yml       รัน container + ผูกกล้อง + mount โฟลเดอร์
│
├── core/                    ★ ตรรกะหลักของการมองเห็น
│   ├── detect.py            สร้าง motion mask + หากล่อง (bounding box)
│   ├── tracker.py           จำวัตถุข้ามเฟรม + รวมกล่องที่แตก
│   ├── roi.py               จัดการบริเวณที่สนใจ (โหลด/วาด/สร้าง mask)
│   └── state_machine.py     ตรรกะสถานะ + นับของ + สรุปผล order + ส่ง event
│
├── api/                     ★ การสื่อสารกับ server
│   ├── client.py            ฟังก์ชันยิง HTTP ขึ้น cloud (post_event, ROI sync)
│   ├── sent_frame.py        ส่งภาพ realtime ขึ้น server (สำหรับ monitor)
│   ├── retry_queue.py       queue เก็บ event ที่ส่งไม่สำเร็จ + retry
│   └── order_listener.py    รับ order ใหม่ผ่าน WebSocket
│
├── utils/                   ★ เครื่องมือเสริม
│   ├── image_saver.py       บันทึกภาพหลักฐาน (แยกโฟลเดอร์ with/without order)
│   ├── disk_cleanup.py      ลบภาพเก่าอัตโนมัติ (กันดิสก์เต็ม)
│   └── logger.py            ตั้งค่า logging (เขียนไฟล์ + rotate)
│
└── data/
    └── roi_config.json      พิกัด ROI (แก้ได้จาก server หรือแก้ไฟล์ตรง ๆ)
```

**กฎการพึ่งพา (dependency):** `main.py` เรียกใช้ `core/*` + `api/*` + `utils/*`
โมดูลใน `core/` แทบไม่พึ่งกัน (ยกเว้น state_machine เรียก image_saver + retry_queue)
ทำให้ทดสอบแต่ละส่วนแยกกันได้

---

## 4. Data Flow

### 4.1 เส้นทางหลัก: จากกล้อง → นับของ → ขึ้น server

```
  [กล้อง/วิดีโอ]
        │ frame (numpy BGR)
        ▼
  main.py: cvtColor เป็น grayscale
        │
        ▼
  bg_np (background) ──► diff = |frame - bg|
        │
        ▼
  core/detect.py: build_fgmask(diff)         → binary motion mask
        │
        ▼
  core/roi.py: build_mask() → bitwise_and     → เหลือ motion เฉพาะใน ROI
        │
        ▼
  core/detect.py: contour_boxes()            → list ของกล่อง (x,y,w,h)
        │
        ▼
  core/tracker.py: group_close_boxes()       → รวมกล่องที่แตกของชิ้นเดียว
        │
        ▼
  core/tracker.py: MemoryTracker.update()    → จำวัตถุข้ามเฟรม + คำนวณ state
        │  (objects: {id: {centroid, shape, state, ...}})
        ▼
  main.py: ตรวจว่ามี object state=SHAPE_CONFIRMED นิ่งครบไหม
        │  ถ้าใช่ ▼
  core/state_machine.py: trigger("still_in_ROI")
        │  ├─► _capture_item() → บันทึกลง captured_items
        │  ├─► utils/image_saver.py: save_evidence_image()   [เขียนไฟล์ .jpg]
        │  └─► _emit_item_landed() → api/retry_queue.py: send_or_queue()
        │                                    │
        ▼                                    ▼
  main.py: reset_motion_baseline()    api/client.py: post_event() → ☁️ server
        (bg = เฟรมปัจจุบัน, พร้อมชิ้นถัดไป)   (ส่งไม่ได้ → เก็บ queue รอ retry)
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
                          _emit_order_result() → ☁️ server (completed/anomaly/no_drop)
```

### 4.3 เส้นทางเสริม (background threads — รันตลอดเวลา)

| Thread | ไฟล์ | ทำอะไร | ทุกกี่นาน |
|--------|------|--------|-----------|
| retry loop | retry_queue.py | ส่ง event ที่ค้างซ้ำ | 60 วิ |
| order listener | order_listener.py | ฟัง WebSocket รอ order | ตลอด (reconnect 5 วิ) |
| disk cleanup | disk_cleanup.py | ลบภาพเก่า | ทุก 1 ชม. |
| ROI polling | main.py → client.py | ดึง ROI ใหม่จาก server | 10 วิ |
| register + push ROI | main.py → client.py | ลงทะเบียนตู้ตอนเปิด | ครั้งเดียว |

> ทุก thread เป็น `daemon=True` = ดับตามโปรแกรมหลักอัตโนมัติ

---

## 5. วงจรชีวิต

ตัวอย่างจริง: **ลูกค้าสั่งน้ำ 2 ขวด** ระบบทำงานยังไงตั้งแต่ต้นจนจบ

```
[0] server ส่ง new_order (qty=2) ผ่าน WebSocket
      → order_listener เก็บไว้ → main loop เรียก sm.set_order()
      → state ยัง IDLE, เริ่มนับ ORDER_WINDOW (30 วิ)

[1] ขวดที่ 1 เริ่มตกลงมาในช่องรับของ
      → เกิด motion ใน ROI
      → main loop: bg_frozen = True (แช่แข็ง background ไว้ ไม่ให้ขวดถูกดูดเข้า bg)
      → sm.trigger("motion_in_ROI") → state: IDLE → DROP_DETECTED

[2] ขวดที่ 1 ตกถึงก้นช่อง หยุดนิ่ง
      → tracker เห็น centroid นิ่งครบ 4 เฟรม → state = SHAPE_CONFIRMED
      → main loop: นิ่งครบ CAPTURE_HOLD_SEC → sm.trigger("still_in_ROI")
      → _capture_item(): บันทึกภาพ LANDED_item1.jpg, นับเป็นชิ้นที่ 1
      → state: DROP_DETECTED → EVIDENCE_CAPTURED
      → ส่ง ITEM_LANDED event ขึ้น server
      → reset_order_window() (นับ 30 วิใหม่ รอชิ้นถัดไป)
      → reset_motion_baseline() + tracker.clear_all()
         (bg = เฟรมนี้, ขวดที่ 1 กลืนเข้า bg, tracker ลืมขวดที่ 1)

[3] ขวดที่ 2 ตกลงมา (bg สะอาดแล้ว ขวด 2 = motion ใหม่)
      → tracker สร้าง object ใหม่ → MOVING → นิ่ง → SHAPE_CONFIRMED
      → _capture_item(): บันทึก LANDED_item2.jpg, นับเป็นชิ้นที่ 2
      → item_count() == order_qty() == 2

[4] หมด ORDER_WINDOW (ไม่มีของตกเพิ่มใน 30 วิ)
      → sm.finalize_order(): got=2, expected=2 → status = "completed"
      → บันทึก ORDER_SUMMARY.jpg
      → _emit_order_result() → ส่ง completed + ภาพขึ้น server
      → do_reset(): state → IDLE, พร้อมรับ order ถัดไป
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
**ทุกค่าปรับผ่าน .env ได้โดยไม่ต้องแก้โค้ด** ยกเว้น `FRAME_W/FRAME_H` (fix 640×480)

ค่าที่สำคัญ (รายละเอียดเต็มในหัวข้อ 8):
- `CAMERA_INDEX` — เลขกล้อง (0,1,..) หรือ path ไฟล์วิดีโอ (auto-detect)
- `MOT_THRESH` — ความไวจับ motion
- `MIN_AREA`, `GROUP_DIST` — กรอง/รวมกล่อง
- `LANDING_STABLE_FRAMES`, `CAPTURE_HOLD_SEC` — เงื่อนไข "นิ่ง = ลงจอด"
- `ORDER_WINDOW`, `CONFIRMED_HOLD_TIMEOUT` — timer ต่าง ๆ
- `HEADLESS` — 0 = มีจอ debug, 1 = ไม่มีจอ (Pi)

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

---

### 6.3 `core/tracker.py` — จำวัตถุข้ามเฟรม

#### `group_close_boxes(boxes, max_dist, overlap_pad, mode)`
**รวมกล่องที่เป็นชิ้นส่วนของวัตถุเดียวกัน** กลับเป็นกล่องเดียว
- ปัญหา: วัตถุ 1 ชิ้นบางทีแตกเป็นหลาย contour (mask ขาดกลาง)
- `mode="distance"` (default): กล่องที่ขอบห่างกัน < `max_dist` → รวมเป็นก้อน
  ของ 2 ชิ้นที่ตกห่างกันเกิน max_dist จะ **ไม่** ถูกรวม → นับแยกได้
- `mode="overlap"`: รวมเฉพาะกล่องที่ซ้อนทับกันจริง
- ใช้ **union-find แบบง่าย** (วน group แล้ว merge กลุ่มที่เชื่อมกัน)
- **output:** list ของกล่องที่รวมแล้ว `(x, y, w, h)`

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
     - centroid ขยับ ≤ `CENTROID_STABLE_DIST` → `shape_stable_count++`
     - นิ่งครบ `SHAPE_STABLE_FRAMES` เฟรม → state = **SHAPE_CONFIRMED** (ลงจอด!)
     - ขยับเยอะ → รีเซ็ต count, state = DETECTING
   - ถ้าไม่เจอคู่: สร้าง object ใหม่ (state = MOVING, id ใหม่)
2. **Disappearance:** object เดิมที่ไม่ถูก match เฟรมนี้ = หายไป
   - เพิ่งเกิด < 0.5 วิ → ลบทันที (noise)
   - หายเกิน `GHOST_FRAME_TOLERANCE` เฟรม → ลบ (ของออกจาก ROI จริง)
   - ยังไม่เกิน → เก็บไว้ก่อน (เผื่อกระพริบ)
- **output:** `self.objects` (dict ล่าสุด) — main loop เอาไปตัดสินใจต่อ

**`clear_all()`** — ล้าง object ทั้งหมด (เรียกหลัง capture + re-baseline)
> หมายเหตุ: **ไม่ reset `next_id`** — เพราะถ้า id ซ้ำกับที่ state machine จำอยู่
> ของชิ้นใหม่อาจถูก skip โดยไม่ตั้งใจ

---

### 6.4 `core/roi.py` — บริเวณที่สนใจ

#### `class ROIManager`
โหลด/จัดการพิกัด ROI จาก `data/roi_config.json` รองรับ 4 แบบ:
`rect` (สี่เหลี่ยม), `polygon`/`quad` (หลายเหลี่ยม), `multi_polygon` (หลายพื้นที่)

| method | หน้าที่ |
|--------|---------|
| `load()` | อ่าน json → เก็บ points/rect/areas ตาม roi_type |
| `reload_if_changed()` | เช็ค mtime ของไฟล์ทุก 5 วิ ถ้าเปลี่ยน → โหลดใหม่ (server แก้ ROI ได้สด) |
| `_scale_point()` | แปลงพิกัดจากขนาดที่ตั้งไว้ → ขนาดเฟรมจริง (เผื่อ config คนละ resolution) |
| `_scaled_rect()` | คืน (x1,y1,x2,y2) ของ rect หลัง scale (helper รวมโค้ดที่เคยซ้ำ 3 ที่) |
| `build_mask(shape)` | สร้าง mask ขาว-ดำ: ใน ROI = ขาว, นอก = ดำ (ใช้ bitwise_and กับ fgmask) |
| `get_roi_areas(shape)` | คืนแต่ละพื้นที่ ROI แยกกัน + จำนวน pixel (ใช้ large-motion check) |
| `draw(frame)` | วาด ROI ลงเฟรม (โหมด DISPLAY เท่านั้น) |

**จุดสำคัญ:** `reload_if_changed()` เช็คไฟล์แค่ทุก 5 วิ (ไม่ใช่ทุกเฟรม)
เพื่อลด I/O บน SD card ของ Pi

---

### 6.5 `core/state_machine.py` — สมองของระบบ

#### `class VendingStateMachine`
เก็บสถานะ + ของที่จับได้ + context ของ order สื่อสารกับ server ผ่าน emit helpers

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
| `finalize_order(frame)` | สรุปผล order → completed/anomaly/no_drop → emit + reset |
| `reset()` | ล้าง field กลับ IDLE |

**emit helpers** (ส่ง event ขึ้น server ผ่าน thread แยก):
- `_emit_item_landed()` → event `ITEM_LANDED` (ของตก 1 ชิ้น + ภาพ)
- `_emit_no_drop()` → event `NO_DROP` (ไม่มีของตกเลย กรณีไม่มี order)
- `_emit_order_result()` → event `ORDER_RESULT` (สรุปผล order + ภาพ summary)

> ทุก emit ยิงผ่าน `send_or_queue()` ใน thread แยก → ไม่ block main loop
> ถ้าเน็ตหลุด event จะไปนอนใน retry queue เอง

---

### 6.6 `api/client.py` — ยิง HTTP ขึ้น cloud

| function | หน้าที่ |
|----------|---------|
| `_headers()` | สร้าง header ใส่ API key (ถ้ามี) — ใช้ร่วมกันทั้ง api/ |
| `post_event(payload, image_path)` | ★ ส่ง event + ภาพ (multipart) ขึ้น server → คืน True/False |
| `register_machine(id)` | ลงทะเบียนตู้ตอน startup (ส่ง SYSTEM_ONLINE, server auto-create machine) |
| `fetch_remote_roi(id)` | ดึง ROI จาก server มาเขียนทับ local (เรียกทุก 10 วิ) |
| `push_default_roi(id, path)` | push ROI local ขึ้น server ถ้า server ยังไม่มี (ครั้งเดียว) |

**`post_event` คืนค่า boolean** — สำคัญมาก เพราะ retry_queue ใช้ค่านี้ตัดสินว่า
จะลบภาพทิ้ง (สำเร็จ) หรือเก็บ queue (ล้มเหลว)

---

### 6.7 `api/sent_frame.py` — ส่งภาพ realtime

#### `send_frame(machine_id, frame)`
encode เฟรมเป็น JPEG แล้ว POST ขึ้น endpoint `realtime-image`
main loop เรียกทุก `SEND_INTERVAL` (1 วิ) เพื่อให้ dashboard ฝั่ง server เห็นภาพสด
- timeout สั้น (2 วิ) — ถ้าส่งไม่ทันก็ข้าม ไม่ค้าง main loop
- ใช้ `_headers()` จาก client.py (ไม่เขียนซ้ำ)

---

### 6.8 `api/retry_queue.py` — ทนเน็ตหลุด

หลักการ: **event ทุกตัวต้องส่งถึง server ให้ได้ ถ้าส่งไม่ได้ห้ามทิ้ง**

| function | หน้าที่ |
|----------|---------|
| `send_or_queue(payload, image_path)` | ★ ลองส่งทันที สำเร็จ→ลบภาพ, ล้มเหลว→เก็บ queue |
| `_retry_loop()` | thread วน retry queue ทุก 60 วิ สำเร็จ→ลบภาพออกจาก queue |
| `start_retry_thread()` | เริ่ม thread (เรียกตอน startup) |
| `_delete_image(path)` | ลบภาพออกจากดิสก์ (หลังส่งสำเร็จ) |

**flow:** state_machine เรียก `send_or_queue` แทน `post_event` ตรง ๆ เสมอ
→ ได้ retry ฟรีโดยไม่ต้องคิดเรื่องเน็ตในโค้ดหลัก

> **ข้อควรรู้:** queue เก็บใน memory (list) — ถ้าโปรแกรมดับ queue หาย
> แต่ภาพยังอยู่บนดิสก์ (ไม่ถูกลบเพราะยังไม่สำเร็จ)

---

### 6.9 `api/order_listener.py` — รับ order ผ่าน WebSocket

เชื่อม WebSocket ไป server ฟัง message `new_order` แบบ real-time

| function | หน้าที่ |
|----------|---------|
| `start_order_listener()` | เริ่ม thread เชื่อม WS (เรียกตอน startup) |
| `_run_forever()` | loop เชื่อม WS + reconnect อัตโนมัติทุก 5 วิ ถ้าหลุด |
| `_on_message(ws, msg)` | รับ message: ถ้าเป็น new_order ของตู้เรา → เก็บ _pending_order |
| `get_pending_order()` | main loop เรียกดู order ที่รออยู่ |
| `clear_pending_order()` | ล้าง order (เมื่อจบ order แล้ว) |

**จุดสำคัญ:**
- ใช้ `threading.Lock` เพราะ main loop กับ WS thread อ่าน/เขียน `_pending_order` พร้อมกัน
- กรอง `machine_id` — server broadcast ไปทุกตู้ แต่รับเฉพาะของตัวเอง
- ถ้ามี order ค้างอยู่แล้ว → reject order ใหม่ (ทำทีละ order)

---

### 6.10 `utils/image_saver.py` — บันทึกภาพหลักฐาน

#### `save_evidence_image(frame, event_name, transaction_id, has_order)`
- แยก 2 โฟลเดอร์: `with_order/` (มี order) และ `without_order/` (ไม่มี — สิ่งแปลกปลอม)
- ตั้งชื่อไฟล์: `{txn_id}_{event}_{timestamp}.jpg`
- เขียน label เวลา + ประเภทลงบนภาพก่อนบันทึก
- **คืน path ของไฟล์** — state_machine เอาไปแนบกับ event ตอน emit

---

### 6.11 `utils/disk_cleanup.py` — กันดิสก์เต็ม

#### `start_cleanup_thread()`
thread วนลบภาพเก่ากว่า `CLEANUP_KEEP_DAYS` (default 3 วัน) ทุก `CLEANUP_INTERVAL_HOURS` (1 ชม.)
> สำคัญบน Pi ที่ดิสก์เล็ก — ถ้าไม่ลบ ภาพหลักฐานสะสมจนเต็ม

---

### 6.12 `utils/logger.py` — logging

#### `get_logger(name)`
คืน logger ที่เขียนทั้งไฟล์ (`logs/vending.log`, rotate 5MB × 5 ไฟล์) และ console
เรียกซ้ำได้ ได้ object เดิม (กัน handler ซ้ำ)


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
| IDLE | `motion_in_ROI` | ตั้ง drop_time, สร้าง transaction_id, print ของกำลังตก | DROP_DETECTED |
| DROP_DETECTED | `still_in_ROI` | `_capture_item()` (ถ้ายังนับได้) | EVIDENCE_CAPTURED |
| DROP_DETECTED | `timeout` | ถ้าไม่มีของ → `_emit_no_drop()`, reset | IDLE |
| EVIDENCE_CAPTURED | `still_in_ROI` | capture ชิ้นถัดไป (ถ้ายังนับได้) | คงเดิม |

### 7.3 การตัดสินใจ reset (อยู่ใน main.py ไม่ใช่ใน state_machine)

main loop เป็นคนตัดสินว่าเมื่อไหร่ควร reset กลับ IDLE โดยลำดับความสำคัญ:

1. **มี order + order window หมด** → `finalize_order()` + reset (สรุปผลก่อน)
2. **มี confirmed item ค้าง** → ไม่ reset ที่นี่ ปล่อยให้ block EVIDENCE_CAPTURED จัดการ
   ด้วย `CONFIRMED_HOLD_TIMEOUT` (นับใหม่ทุกครั้งที่มี motion → รอว่าไม่มีของตกเพิ่มจริง)
3. **ไม่มี order + ไม่มี item + เกิน DROP_TIMEOUT** → reset
4. **frame ว่าง (ไม่มีอะไรใน ROI)** → reset

> เหตุผลที่ logic reset อยู่ใน main.py ไม่ใช่ state_machine: มันต้องดูข้อมูลจาก
> tracker (มี motion ไหม, frame ว่างไหม) ซึ่ง state_machine ไม่รู้จัก

---

## 8. การตั้งค่า

### 8.1 ตัวแปร .env ที่สำคัญ

**การมองเห็น (detection):**
| ตัวแปร | default | ความหมาย | ปรับเมื่อ |
|--------|---------|----------|-----------|
| `MOT_THRESH` | 25 | ความไวจับ motion | ต่ำลง = จับของจาง ๆ ได้แต่ noise เยอะ |
| `MIN_AREA` | 150 | พื้นที่ขั้นต่ำของกล่อง (px) | ของเล็กหลุด → ลดค่า |
| `GROUP_DIST` | 60 | ระยะรวมกล่อง (px) | ของ 2 ชิ้นถูกรวม → ลดค่า |
| `GROUP_MODE` | distance | วิธีรวมกล่อง | ของบินใกล้กัน → "overlap" |
| `MORPH_OPEN_KSIZE` | 5 | ลบ noise | noise เยอะ → เพิ่ม |
| `MORPH_DILATE_KSIZE` | 5 | เชื่อม mask ที่ขาด | กรอบขาด → เพิ่ม |
| `MORPH_DILATE_ITER` | 2 | จำนวนรอบ dilate | " |

**จังหวะการจับ (timing):**
| ตัวแปร | default | ความหมาย |
|--------|---------|----------|
| `LANDING_STABLE_FRAMES` | 4 | เฟรมที่ต้องนิ่งจึงถือว่าลงจอด |
| `CAPTURE_HOLD_SEC` | 2 | นิ่งเพิ่มหลังลงจอดก่อน capture (0=ทันที) |
| `MIN_PRESENCE_SEC` | 0.2 | เวลาขั้นต่ำใน ROI ก่อน capture (กัน noise) |
| `CENTROID_STABLE_DIST` | 10 | ระยะ centroid ขยับได้แล้วยังถือว่านิ่ง (px) |
| `TRACK_MATCH_DIST` | 150 | ระยะที่ tracker match วัตถุเดิม (px) |

**timer / order:**
| ตัวแปร | default | ความหมาย |
|--------|---------|----------|
| `ORDER_WINDOW` | 30 | เวลารอของตกหลังได้ order (วิ) — reset ทุกครั้งที่ capture |
| `CONFIRMED_HOLD_TIMEOUT` | 20 | รอว่าไม่มีของตกเพิ่มก่อน reset (วิ, กรณีไม่มี order) |
| `CAP_COUNT_TO_ORDER_QTY` | 1 | ห้ามนับเกิน qty ที่สั่ง (1=เปิด) |
| `REBASELINE_ON_CAPTURE` | 1 | ล้าง bg หลัง capture (1=เปิด, ดีไซน์หลัก) |

**การเชื่อมต่อ / โหมด:**
| ตัวแปร | ความหมาย |
|--------|----------|
| `CAMERA_INDEX` | เลขกล้อง (0) หรือ path วิดีโอ |
| `HEADLESS` | 0=มีจอ debug, 1=ไม่มีจอ (Pi) |
| `MACHINE_ID_DEFAULT` | ชื่อตู้ |
| `CLOUD_API_URL` | endpoint ส่ง event เช่น http://host/api/events |
| `WS_URL` | WebSocket url รับ order |
| `API_KEY` | key ยืนยันตัวตนกับ server (ถ้ามี) |
| `CLEANUP_KEEP_DAYS` | เก็บภาพกี่วัน (default 3) |

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
pip install -r requirements.txt
# ตั้ง .env: HEADLESS=0, CAMERA_INDEX=0 (หรือ path วิดีโอ)
python main.py
# หรือระบุชื่อตู้: python main.py --machine VENDING_02
```
โหมดนี้จะเปิด 2 หน้าต่าง: "Vending System" (ภาพ + overlay) และ "Motion Mask"
กด `q` = ออก, `r` = reset ระบบ

### 9.2 รันบน Raspberry Pi (production)
```bash
# ตั้ง .env: HEADLESS=1
docker compose up -d
```
`docker-compose.yml` ผูก `/dev/video0` (กล้อง) และ mount `evidence_images/` + `data/`
ออกมานอก container เพื่อให้ภาพ + config ไม่หายเมื่อ container restart

### 9.3 requirements
```
opencv-python, numpy, requests, python-dotenv, websocket-client
```

---

## 10. จุดที่ต้องระวัง

จุดเหล่านี้เคยเป็น bug หรือเป็นดีไซน์ที่ไม่ชัดในตัวเอง — อ่านก่อนแก้โค้ด

### 10.1 มือถูก snapshot เป็น background ตอน reset
หลัง `do_reset()` มือลูกค้าอาจยังอยู่ในเฟรม ถ้าล้าง `bg_np = None` ทันที เฟรมถัดไป
จะจับมือเป็น background ใหม่ → พอมือถอยออกกลายเป็น "blob หลอก"
**แก้แล้วด้วย:** grace period (`RESET_GRACE_PERIOD` 1.5 วิ) — ช่วงนี้ re-learn เร็ว
(`LR_RELEARN`) เพื่อดูดมือเข้า bg และห้าม trigger motion ใหม่

### 10.2 Clean BG snapshot
ตอน freeze background (เจอของชิ้นแรก) เราไม่ใช้ `bg_np` ปัจจุบัน (อาจดูดมือไปบางส่วนแล้ว)
แต่ใช้ `clean_bg` = snapshot ตอน IDLE + ไม่มี motion เก็บไว้ล่วงหน้าทุก 0.5 วิ
→ ได้ background ที่สะอาดจริง

### 10.3 Large motion = env change
ถ้า motion blob ใหญ่เกิน `MAX_BLOB_ROI_RATIO` (60%) ของพื้นที่ ROI → ถือว่าเป็น
"สภาพแวดล้อมเปลี่ยน" (แสง เงา คนบังกล้อง) ไม่ใช่ของตก → restore bg + ไม่ trigger
กัน false positive จากแสงกระพริบ

### 10.4 Re-baseline คือดีไซน์หลัก (อย่าเผลอปิด)
`REBASELINE_ON_CAPTURE=1` เป็นกลไกที่ทำให้ **นับของหลายชิ้นที่ตกทับที่เดิมได้**
ถ้าปิด (0) ของที่นับแล้วจะค้างเป็น motion → ชิ้นถัดไปที่ตกทับจะไม่ถูกนับเป็นชิ้นใหม่
มีโค้ดที่พึ่งดีไซน์นี้: หลัง capture จะ `reset_motion_baseline()` + `tracker.clear_all()`

### 10.5 กรอบ CONFIRMED เป็นแค่ overlay
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
(ไม่ผูก FPS คลิป) ทำให้ timer เพี้ยน → main loop มี pacing หน่วงให้เล่นตาม FPS จริง
กล้องจริงไม่ต้องหน่วง (ส่งเฟรมตามอัตราของมันเอง)

---

## ภาคผนวก: คำถามที่มักถูกถาม

**Q: ระบบแยกแยะชนิดสินค้าได้ไหม?**
ไม่ได้ มันนับแค่ "จำนวนวัตถุที่ตกแล้วมานิ่ง" ถ้าต้องการจำแนกชนิด ต้องเพิ่มโมเดล
classification (เช่น YOLO) เข้าไปในขั้นตอนหลัง `contour_boxes`

**Q: ถ้าอยากเพิ่มความแม่นยำ ควรปรับอะไรก่อน?**
เริ่มจาก `MOT_THRESH` (ความไว), `MIN_AREA` (กรองขนาด), แล้ว `LANDING_STABLE_FRAMES`
(ความไวการจับตอนนิ่ง) ปรับผ่าน .env ทดสอบกับวิดีโอจริงได้เลย

**Q: ทำไม logic reset อยู่ใน main.py ไม่ใช่ state_machine?**
เพราะการตัดสิน reset ต้องดูข้อมูลจาก tracker (มี motion ไหม, frame ว่างไหม) ซึ่ง
state_machine ไม่รู้จัก tracker — มันดูแค่ order + captured_items

**Q: 3 threads ส่งข้อมูลขึ้น server พร้อมกันจะชนกันไหม?**
ไม่ชน เพราะแต่ละ event เป็น HTTP request อิสระ retry queue มี lock กัน race
เฉพาะตอนแก้ list ส่วน order listener มี lock กัน `_pending_order`
