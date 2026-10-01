# VendingCam — รายงานตรวจฟังก์ชัน และแผน Cleanup

วันที่: 1 ต.ค. 2026 · ฐานโค้ดที่ตรวจ: เวอร์ชันล่าสุดที่มี patch env-change rebaseline · `CAPTURE_HOLD_SEC=0.5`, `MAX_BLOB_ROI_RATIO=0.30`

เป้าหมาย: ให้ระบบ **คลีน จัดการง่าย และพร้อมลง Orange Pi** โดย **ไม่เปลี่ยนพฤติกรรมการนับของ** (ยืนยันด้วย regression test ทุกขั้น)

---

## 1. สรุปภาพรวม

| ไฟล์ | บรรทัด | สภาพ | ปัญหาหลัก |
|---|---|---|---|
| `main.py` | ~750 | 🔴 เละที่สุด | main loop ก้อนเดียวทำทุกอย่าง, ฟังก์ชันซ้อนสร้างใหม่ทุกเฟรม, ตรรกะ reset กระจาย 3 จุด, โค้ดวาดจอ ~200 บรรทัดปนอยู่ |
| `config.py` | ~100 | 🟡 | ค่าไม่เรียงตามความสำคัญ, ค่าสำคัญหลายตัว hardcode กระจายอยู่ไฟล์อื่น, 3 ค่าไม่มีผลจริง |
| `core/tracker.py` | ~170 | 🟢 | มีเลขลอย (0.75, 30, 0.95, 0.5s) ไม่มีชื่อ, `group_close_boxes` อยู่ผิดไฟล์ |
| `core/state_machine.py` | ~285 | 🟢 | attribute ที่ไม่ได้ใช้ 3 ตัว, emit 3 ฟังก์ชันซ้ำกัน |
| `core/roi.py` | ~215 | 🟢 | สร้าง mask ใหม่ทุกเฟรม (ไม่จำเป็น), อ่านไฟล์พังแล้วโปรแกรมตาย |
| `core/detect.py` | ~50 | 🟢 ดีอยู่แล้ว | — |
| `api/*` | ~4 ไฟล์ | 🟡 | `sent_frame.py` แยกไฟล์เล็กเกิน, base_url คำนวณซ้ำ 3 ที่ |
| `utils/*` | ~3 ไฟล์ | 🟢 | `disk_cleanup` อ่าน .env เองไม่ผ่าน config |

---

## 2. รายงานรายฟังก์ชัน

ความหมาย: **เก็บ** = ดีแล้ว · **แก้** = เก็บแต่ปรับ · **ย้าย** = ย้ายไฟล์ · **รวม** = รวมกับฟังก์ชันอื่น · **ตัด** = ลบ

### main.py

| ฟังก์ชัน / ส่วน | คำตัดสิน | เหตุผล |
|---|---|---|
| `draw_captured_items()` | **ย้าย** → `ui/overlay.py` + **ตัด** branch แรก | branch "item_visible" ไม่มีทางเกิด เพราะหลัง capture tracker ถูกล้างทุกครั้ง (rebaseline เปิดตลอด) · ตัวแปร `all_gone` ไม่ได้ใช้ |
| `render_overlay()` | **ย้าย** → `ui/overlay.py` | ใช้เฉพาะ PC (HEADLESS=0) ไม่ควรปนกับตรรกะหลัก |
| `main()` startup (thread ต่าง ๆ, register, push ROI) | **แก้** → แยกเป็น `start_services()` | อ่านง่ายขึ้น |
| `roi_polling_task()` (ฟังก์ชันซ้อน) | **ย้าย** → `api/client.py: start_roi_polling()` | เป็นเรื่อง API ไม่ใช่ main loop |
| อ่านกล้อง + reconnect + pacing วิดีโอ | **แยก** → `core/frame_source.py` | โค้ด reconnect ซ้ำกับตอนเปิดกล้องครั้งแรก |
| background (`bg_np`, freeze, `clean_bg`, grace, rebaseline, env change) | **แยก** → `core/background.py: BackgroundModel` | ตอนนี้เป็นตัวแปรลอย 8 ตัวใน loop ที่ต้องแก้พร้อมกันหลายจุด (เคยเป็นต้นเหตุ bug) |
| `do_reset()`, `reset_motion_baseline()` (ซ้อนใน loop) | **รวม** → method ของ `BackgroundModel` | ตอนนี้ถูกนิยามใหม่ทุกเฟรม (~30 ครั้ง/วิ) |
| large-motion / env change block | **ย้าย** → `BackgroundModel` | |
| ตรรกะ reset 3 จุด (order หมด, drop timeout, frame ว่าง, hold timeout) | **รวม** → ฟังก์ชันเดียว `decide_reset()` | ตอนนี้ต้องอ่าน 3 block ถึงจะรู้ว่าระบบ reset เมื่อไหร่ |
| `has_active_motion` (คำนวณซ้ำใน overlay และใน loop) | **รวม** | |
| `import datetime` ใน loop, สร้าง `transaction_id` 3 ที่ | **แก้** → `sm.new_transaction_id()` | |
| ปุ่ม `r` | **แก้** → เรียก reset ตัวเดียวกับระบบ | ตอนนี้ล้างไม่ครบ (`clean_bg`, snapshot ค้าง) |
| `else: pass` ท้าย loop | **ตัด** | |

### core/

| ฟังก์ชัน | คำตัดสิน | เหตุผล |
|---|---|---|
| `detect.build_fgmask()`, `detect.contour_boxes()` | **เก็บ** | pure function ดีอยู่แล้ว |
| `tracker.group_close_boxes()` | **ย้าย** → `detect.py` | เป็นขั้น detection (รวมก้อน) ไม่ใช่ tracking |
| `MemoryTracker.update()` | **แก้** | ตั้งชื่อเลขลอย: `SHRINK_RATIO=0.75`, `SHRINK_MAX_MOVE=30`, `SHRINK_SMOOTH=0.95`, `NEW_OBJ_GRACE_SEC=0.5`; ใช้ `GHOST_FRAME_TOLERANCE` จาก config |
| `MemoryTracker.clear_all()` | **เก็บ** | |
| alias `SHAPE_STABLE_FRAMES`, `CENTROID_STABLE_DIST as CFG_...` | **ตัด** | ใช้ชื่อจาก config ตรง ๆ |
| `ROIManager.load()` | **แก้** | ครอบ try — ไฟล์พัง/เขียนไม่เสร็จให้ใช้ ROI เดิมต่อ (ตอนนี้โปรแกรมตาย) |
| `ROIManager.build_mask()`, `get_roi_areas()` | **แก้** | คำนวณครั้งเดียวตอน load แล้ว cache (ตอนนี้ fillPoly ใหม่ทุกเฟรม) |
| `ROIManager.reload_if_changed()`, `_scale_point()`, `_valid_points()`, `_scaled_rect()`, `draw()` | **เก็บ** | |
| `VendingStateMachine` (ทั้ง class) | **เก็บ** | |
| attribute `land_obj_id`, `capture_time`, `land_img_path` | **ตัด** | เขียนแต่ไม่มีใครอ่าน |
| `_emit_item_landed()`, `_emit_no_drop()`, `_emit_order_result()` | **รวม** → `_emit(event, txn, image, **fields)` | โค้ดเหมือนกัน 80% |
| parameter `default_machine` | **ตัด** | main ตั้ง `machine_id` ทับทุกครั้ง |

### api/ และ utils/

| ฟังก์ชัน | คำตัดสิน | เหตุผล |
|---|---|---|
| `client.post_event()`, `register_machine()`, `push_default_roi()` | **เก็บ** | |
| `client.fetch_remote_roi()` | **แก้** | เขียนไฟล์เฉพาะเมื่อข้อมูลเปลี่ยน + เขียนแบบ atomic (tmp → `os.replace`) — ตอนนี้เขียน eMMC ทุก 10 วิ |
| base_url (คำนวณ 3 ที่) | **รวม** → `_base_url()` | |
| `sent_frame.send_frame()` | **ย้าย** → `client.py` + รันใน thread | ตอนนี้ block main loop ได้ถึง 2 วิเมื่อเน็ตช้า |
| `retry_queue.*` | **เก็บ** (แก้ race ภายหลัง) | |
| `order_listener.*` | **เก็บ** | |
| `disk_cleanup` | **แก้** | อ่านค่าจาก config แทน `os.getenv` เอง |
| `image_saver`, `logger` | **เก็บ** | ใช้ `logger` ทั้งระบบแทน `print` |

---

## 3. ค่าตั้ง (config) — ตัด / เก็บ / ดึงเข้ามา

**ตัด 3 ค่า (ไม่มีผลหรือห้ามปิดอยู่แล้ว)**

| ค่า | เหตุผล |
|---|---|
| `MIN_PRESENCE_SEC` | ไม่มีผลจริง: ของต้องนิ่งครบ `CAPTURE_HOLD_SEC` (0.5) หลังเจอครั้งแรก จึงอยู่ใน ROI ≥ 0.5 วิเสมอ มากกว่า 0.2 วิ |
| `REBASELINE_ON_CAPTURE` | ถ้าปิด ระบบนับหลายชิ้นพัง (HANDOVER 10.4 เขียนไว้ว่าห้ามปิด) → ให้เปิดถาวร |
| `ENV_SETTLE_FRAMES` | ทดสอบแล้ว 0 ดีที่สุด (5 ทำให้นับเกิน) → ใช้ค่า 0 ถาวร |

**ดึงค่าที่ hardcode อยู่ในไฟล์อื่นเข้ามา config (default = ค่าเดิมเป๊ะ)**
`BG_LEARNING_RATE` (0.1), `BG_RELEARN_RATE` (0.3), `RESET_GRACE_SEC` (1.5), `CLEAN_BG_INTERVAL` (0.5), `GHOST_FRAME_TOLERANCE` (2), `DROP_TIMEOUT` (25), `SEND_INTERVAL` (1), `ROI_POLL_INTERVAL` (10), `ROI_CHECK_INTERVAL` (5), `RETRY_INTERVAL` (60), `CAMERA_RECONNECT_SEC` (2), `WS_RECONNECT_SEC` (5), `CLEANUP_KEEP_DAYS`, `CLEANUP_INTERVAL_HOURS`

**ค่าที่ควรทบทวนภายหลัง (ยังไม่แตะใน cleanup)**
- `CAP_COUNT_TO_ORDER_QTY=1` ซ่อนกรณีตู้ปล่อยของเกิน order
- `ENV_CHANGE_REBASELINE` ถ้าทดสอบภาคสนามแล้วโอเค ให้ตัด switch ทิ้ง พร้อม path เก่า (restore snapshot) และตัวแปร `bg_frozen_snapshot`

**ลำดับหมวดใน config.py ใหม่** (ร่างอยู่ที่ `proposed/config.py`)
1. ตัวตนตู้และการเชื่อมต่อ — ต้องตั้งทุกตู้
2. ความไว / ความเร็วการจับ — จูนบ่อย (`CAPTURE_HOLD_SEC`, `MOT_THRESH`, `MIN_AREA`, `MAX_BLOB_ROI_RATIO`, ...)
3. เวลา order / reset
4. ขั้นสูง — ไม่ควรแตะ
5. ระบบ / ดูแลเครื่อง
6. ค่าคงที่ — ห้ามแก้

แต่ละค่ามีคอมเมนต์ภาษาไทยบอกว่า ↑/↓ แล้วเกิดอะไร · ใส่ค่าผิดรูปแบบใน .env จะแจ้ง error ชัด ๆ · ตอนเริ่มโปรแกรม print ค่าที่ใช้จริงทั้งหมด (`config.summary()`) ดูผ่าน `docker compose logs` ได้

---

## 4. แผน cleanup ทีละเฟส

กติกาทุกเฟส: **พฤติกรรมเดิม** — `run_regression.py` ต้องผ่านเหมือน baseline · **ไม่ commit** — หยุดให้ตรวจและ commit เองทีละเฟส

| เฟส | งาน | ความเสี่ยง |
|---|---|---|
| 0 | วาง `tools/regression/`, สร้างคลิป, บันทึก baseline จากโค้ดปัจจุบัน | ไม่มี |
| 1 | config.py + .envexample ใหม่, ต่อค่าที่ดึงเข้ามา, ตัด 3 ค่า + dead code | ต่ำ |
| 2 | ย้าย: overlay → `ui/overlay.py`, roi polling → client, `group_close_boxes` → detect, send_frame → client | ต่ำ |
| 3 | แยก `FrameSource`, `BackgroundModel`, `decide_reset()` · main.py เหลือ < 250 บรรทัด | กลาง — เฟสนี้ต้องดู regression ละเอียดที่สุด |
| 4 | `print` → logger, `config.summary()` ตอน startup, ตั้งชื่อเลขลอยใน tracker | ต่ำ |
| 5 | **พร้อมลง Pi** (แก้พฤติกรรมเล็กน้อย แยกจากเฟสอื่น): send_frame ใน thread, ROI เขียน atomic + load ไม่ทำให้ตาย, `opencv-python-headless`, `TZ=Asia/Bangkok` ใน Dockerfile, image tag สำหรับ rollback | ต่ำ-กลาง |

---

## 5. การนำลง Orange Pi (มีเวอร์ชันเก่ารันอยู่)

**ความเข้ากันได้ของ .env:** ชื่อค่าเดิมทุกตัวยังใช้ได้ (`MACHINE_ID_DEFAULT`, `CLOUD_API_URL`, ...) ค่าใหม่มี default เท่าค่าเดิม ยกเว้น 2 ค่าที่ default เปลี่ยน:

| ค่า | เวอร์ชันบน Pi ตอนนี้ | เวอร์ชันใหม่ |
|---|---|---|
| `CAPTURE_HOLD_SEC` | 2 | **0.5** |
| `MAX_BLOB_ROI_RATIO` | 0.40 (hardcode) | **0.30** |

ถ้า `.env` บน Pi ไม่ได้ระบุ 2 ค่านี้ พฤติกรรมจะเปลี่ยนตามค่าใหม่ — ซึ่งเป็นค่าที่ต้องการอยู่แล้ว แต่ควรรู้ไว้

**ขั้นตอนอัปเดตแบบ rollback ได้**
```bash
# บน Pi — เก็บ image เก่าไว้ก่อน
docker tag $(docker compose images -q vending-cam) vending-cam:prev
# copy source ใหม่ (ไม่เอา .venv / .env / evidence_images / logs) แล้ว
docker compose up -d --build
docker compose logs -f --tail=100 vending-cam     # ดู "Active config" ว่าค่าถูก
# ถ้ามีปัญหา: กลับไป source เก่า แล้ว docker compose up -d --build อีกครั้ง
#            (หรือตั้ง image: vending-cam:prev ใน docker-compose.yml ชั่วคราว)
```
`data/roi_config.json`, `evidence_images/`, `logs/` อยู่ใน volume ของ host จึงไม่หายตอนอัปเดต

---

## 6. Known issues ที่ regression แสดง (ไม่แก้ใน cleanup นี้)

| คลิป | จริง | ระบบได้ | สาเหตุ |
|---|---|---|---|
| `item_then_removed` | 1 | 2 | หยิบของออก = จุดว่างถูกนับเป็นชิ้นใหม่ |
| `quick_grab` | 1 | 2 | เหตุเดียวกัน (hold 0.5 จับทันแล้ว แต่ตอนหยิบออกถูกนับเพิ่ม) |
| `large_item` | 1 | 0 | ของใหญ่เกิน 30% ของ ROI ถูกมองเป็น env change |
