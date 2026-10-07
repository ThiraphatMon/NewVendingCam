# LOG_MESSAGES — ตารางเทียบข้อความ log เดิม (ไทย) → ใหม่ (อังกฤษ ASCII)

> S20 (`docs/AUTORUN_TASK_OBSERVE.md`): ทุกข้อความที่ออก `docker compose logs` / `logs/vending.log` / startup summary
> เป็นภาษาอังกฤษง่าย ๆ ASCII ล้วน (ไม่มีอีโมจิ / อักษรไทย / ×) · คอมเมนต์ / docstring / เอกสาร ยังเป็นภาษาไทย
> ข้อความที่เกี่ยวกับรอบขึ้นต้นด้วย `[cycle <id8>]` · คงไว้: รหัส anomaly, `S3=...`, daily log `dd/mm/yyyy HH:MM:SS : item drop : N`, ชื่อไฟล์ภาพ
> ตรวจอัตโนมัติ: `tests/test_log_ascii.py` (ไม่มี string literal non-ASCII ในโค้ดที่รัน + log ทั้งรอบเป็น ASCII)
> และ `redis_e2e.py` (ทุกบรรทัดของ stdout + vending.log ทุกสถานการณ์ต้องเป็น ASCII)

## ตัวอย่างรอบปกติ (e2e ข้อ 1, SEND_S0=0)
```
[INFO] vending.main: S0 response: DISABLED (observe mode, SEND_S0=0)
[INFO] vending.redis: Redis worker started (RPOP CTRL / CAMERA disabled (SEND_S0=0))
[INFO] vending.main: START received (#1 from redis)
[INFO] vending.main: [cycle fd77e6ca] START received -> cycle opened (background: empty-tray, age 0.4s)
[INFO] vending.main: [cycle fd77e6ca] S3=ADDITION edge_ratio=1.09 (threshold 0.60), diff_bg=46.9, diff_prev=47.5, diff_prev match < 23.4 (diff_bg x0.50) -> item added -> confirm
[INFO] vending.main: [cycle fd77e6ca] timing: START->motion 1.27s, START->item seen 1.60s, seen->still 0.33s (9 frames, LANDING_STABLE_FRAMES=4, still resets 1), still->hold done 0.33s (CAPTURE_HOLD_SEC=0.3), S3 1ms, save 35ms, START->confirm 2.27s t0=...
[INFO] vending.main: [cycle fd77e6ca] item confirmed, today's count 1 (saved in 35ms) -> S0 NOT SENT (observe mode)
[WARNING] vending.main: [cycle fd77e6ca] anomaly image ENV_CHANGE (not counted): evidence_images/anomaly/..._ENV_CHANGE_<cycle>.jpg
[INFO] vending.main: STOP received (#2 from redis)
[INFO] vending.main: [cycle fd77e6ca] STOP received -> cycle closed: CONFIRMED
```

## รอบ (main.py / core/cycle.py)
| เดิม | ใหม่ |
|---|---|
| `📥 START (#1 จาก redis)` | `START received (#1 from redis)` |
| `▶️ เปิดรอบ a1b2c3d4 (state=ACTIVE)` + `🧊 Background FROZEN [START a1b2c3d4] — ใช้ clean_bg (อายุ 0.3s)` | `[cycle a1b2c3d4] START received -> cycle opened (background: empty-tray, age 0.3s)` (รวมเป็นบรรทัดเดียว; บรรทัด background ของ START ลดเป็น DEBUG) |
| `🧊 Background FROZEN [START …] — ไม่มี clean_bg ที่นิ่งหลังการเปลี่ยนแปลงล่าสุด → ใช้เฟรมปัจจุบัน (baseline ไม่แน่นอน: …)` | `background frozen [START …]: no still empty-tray background since last change -> using current frame (background uncertain: hand/item in this frame becomes background)` + open line `(background: current frame, uncertain)` |
| `⛔ รอบ …: ไม่มีพื้นหลังก่อน START → BLOCKED_WAIT_STOP` | `[cycle …] START received -> cycle opened (background: none - no background before START -> BLOCKED_WAIT_STOP)` (WARNING) |
| `⏹️ ปิดรอบ … → CONFIRMED (stop)` | `[cycle …] STOP received -> cycle closed: CONFIRMED` |
| `⏹️ ปิดรอบ … → CONFIRMED (next_start)` | `[cycle …] next START received -> cycle closed: CONFIRMED` |
| `⏹️ ปิดรอบ … → TIMEOUT (timeout)` | `[cycle …] cycle timeout -> cycle closed: TIMEOUT` |
| `⏹️ ปิดรอบ … → UNCERTAIN (stop;camera_gap)` | `[cycle …] STOP received -> cycle closed: UNCERTAIN (camera_gap)` |
| `🔁 เปิดรอบใหม่` / `🔁 STOP → ปิดรอบ` / `🔁 START ขณะ … → ปิดรอบเดิม … และเปิดรอบใหม่` / `🔁 ไม่มี STOP ภายใน 300s → ปิดรอบเอง` | `START -> cycle opened` / `STOP -> cycle closed` / `START while … -> previous cycle closed (…) and new cycle opened` / `cycle timeout: no STOP within 300s -> cycle closed` (DEBUG — บรรทัดเปิด/ปิดรอบด้านบนแทน) |
| `🔁 STOP ขณะ WAIT_START → no-op` | `STOP while WAIT_START (no open cycle) -> ignored` |
| `⚠️ [DUPLICATE_START] START ซ้ำขณะ ACTIVE → ไม่เปิดรอบใหม่ รอบเดิมเดินต่อ` | `[cycle …] [DUPLICATE_START] duplicate START (ignored) while ACTIVE -> current cycle continues` |
| `♻️ พบรอบค้างจากก่อน restart (…) → บันทึกเป็น INTERRUPTED (ไม่ส่ง S0 ของรอบเก่า) แล้วเริ่มที่ WAIT_START` | `interrupted (program restarted): open cycle(s) … closed as INTERRUPTED (no S0 for old cycles) -> WAIT_START` |
| `⚠️ Redis ขาดระหว่างรอบ … (…)` | `[cycle …] Redis disconnected during cycle (…)` |
| `📊 ยอดวันนี้ (2026-10-07) = 3 (daily log 3 บรรทัด)` | `today's count (2026-10-07) = 3 (daily log 3 lines)` |

## ยืนยัน / S3 / S0
| เดิม | ใหม่ |
|---|---|
| `📸 ยืนยันสินค้า รอบ … — ยอดวันนี้ 3 (บันทึก 25ms) → ส่ง S0` | `[cycle …] item confirmed, today's count 3 (saved in 25ms) -> S0 requested` (SEND_S0=1) |
| (ใหม่ S17) | `[cycle …] item confirmed, today's count 3 (saved in 25ms) -> S0 NOT SENT (observe mode)` (SEND_S0=0) |
| (ใหม่ S22) | `[cycle …] item size: blob 1447px, box 52x40 at (180,215)` (ทุกการยืนยัน: px ของ mask ในกล่อง) |
| (ใหม่ S18) | `[cycle …] timing: START->motion …s, START->item seen …s, seen->still …s (N frames, …), still->hold done …s (CAPTURE_HOLD_SEC=0.3), S3 …ms, save …ms, START->confirm …s t0=…` |
| `🔍 รอบ …: S3=ADDITION candidate เป็นของใส่เข้า (ขอบ ×1.12, ต่างจากพื้นหลังรอบ 46.9, ต่างจากฉากก่อนหน้า 47.5 \| เกณฑ์: ขอบ < 0.60 = ขอบลด, ฉากก่อนหน้า < 23.4 (พื้นหลังรอบ ×0.50) = ตรง) → ยืนยัน` | `[cycle …] S3=ADDITION edge_ratio=1.12 (threshold 0.60), diff_bg=46.9, diff_prev=47.5, diff_prev match < 23.4 (diff_bg x0.50) -> item added -> confirm` |
| `🔍 รอบ …: S3=REMOVAL วัตถุนิ่งดูเหมือนหยิบออก (…) → ไม่ยืนยัน ไม่ส่ง S0` | `[cycle …] S3=REMOVAL edge_ratio=0.40 (threshold 0.60), … -> item removed -> not confirmed, no S0` |
| `🔍 รอบ …: S3=UNCERTAIN วัตถุนิ่งดูเหมือนไม่แน่ใจว่าหยิบออก (ไม่มีฉากก่อนหน้ายืนยัน) (…) → ไม่ยืนยัน ไม่ส่ง S0` | `[cycle …] S3=UNCERTAIN … -> uncertain (no previous scene to compare) -> not confirmed, no S0` |
| `🔍 รอบ …: S3=UNCERTAIN ดูเหมือนหยิบออกแต่ไม่แน่ใจ (…) → ยืนยันตาม REMOVAL_UNCERTAIN_SEND_S0=1` | `[cycle …] S3=UNCERTAIN … -> uncertain -> confirm anyway (REMOVAL_UNCERTAIN_SEND_S0=1)` |
| `❌ [EVIDENCE FAULT] รอบ …: บันทึกภาพไม่ได้ → ไม่ยืนยัน (ลองใหม่ถ้าของยังนิ่ง)` | `[cycle …] [EVIDENCE FAULT] cannot save image -> not confirmed (retry if item still)` |
| `❌ [STORAGE FAULT] รอบ …: บันทึก DB ไม่ได้ (…) → ไม่ยืนยัน` | `[cycle …] [STORAGE FAULT] cannot save to DB (…) -> not confirmed` |
| `🔄 รอบ …: env change สงบแล้ว (ROI นิ่ง 5 เฟรม) → ตั้งพื้นหลังของรอบใหม่เป็นเฟรมนี้` | `[cycle …] env change settled (ROI still 5 frames) -> background reset to this frame` |
| `📤 LPUSH CAMERA S0 สำเร็จ (cycle=…)` | `[cycle …] LPUSH CAMERA S0 OK` |
| `⏭️ ไม่ส่ง S0 (cycle=…) — รับ START/STOP ใหม่มาก่อนส่ง` | `[cycle …] S0 not sent - newer START/STOP received before sending` |
| `❓ LPUSH S0 ไม่รู้ผล (cycle=…): … → UNKNOWN ไม่ส่งซ้ำ` | `[cycle …] LPUSH S0 result unknown: … -> UNKNOWN, not resent` |
| `📤 S0 ของรอบ … → EXPIRED รอบปิดก่อนส่ง S0` | `[cycle …] S0 -> EXPIRED cycle closed before S0 was sent` |
| (ใหม่ S17) | `S0 response: DISABLED (observe mode, SEND_S0=0)` / `S0 response: ENABLED (SEND_S0=1)` |
| (ใหม่ S22) | `Shadow filter: texture (win=7, ncc>0.6, flat_var<4, min blob 400px instead of MIN_AREA 150px)` / `Shadow filter: off` |

## anomaly
| เดิม | ใหม่ |
|---|---|
| `🚩 ANOMALY OUTSIDE_CYCLE (นอกรอบ) — ไม่นับยอด ภาพ: …` | `[outside cycle] anomaly image OUTSIDE_CYCLE (not counted): …` |
| `🚩 ANOMALY EXTRA_AFTER_CONFIRM (รอบ …) — ไม่นับยอด ภาพ: …` | `[cycle …] anomaly image EXTRA_AFTER_CONFIRM (not counted): …` |
| `🚩 ANOMALY NO_CONFIRM_AT_CLOSE (รอบ …) — ไม่นับยอด ภาพ: ไม่มี (ไม่มีเฟรม)` | `[cycle …] anomaly image NO_CONFIRM_AT_CLOSE (not counted): none (no frame)` |
| `🔕 [OUTSIDE_CYCLE] วัตถุนิ่งครบเกณฑ์ แต่เกินโควตาภาพ anomaly → ไม่ถ่าย` | (ยกเลิก S19 — ไม่มี rate limit แล้ว) |
| (ใหม่ S19) | `[cycle …] anomaly image ENV_CHANGE (not counted): …` |
| (ใหม่ S19) | `anomaly image limit reached: 2000 images today (ANOMALY_MAX_PER_DAY=2000) -> no more anomaly images until tomorrow (events still recorded in DB)` · แถวที่ไม่มีภาพ: `… (not counted): none (ANOMALY_MAX_PER_DAY=2000 reached)` |
| `❌ บันทึก anomaly … ลง DB ไม่ได้: …` | `cannot save anomaly … to DB: …` |

## พื้นหลัง / เฝ้าดูนอกรอบ / ROI (core/background.py, core/roi.py)
| เดิม | ใหม่ |
|---|---|
| `🧊 Background FROZEN [เฝ้าดูนอกรอบ] — ใช้ clean_bg (อายุ 0.1s)` | `background frozen [outside-cycle watch]: empty-tray background (age 0.1s)` |
| `🧊 Background FROZEN […] — fallback: ไม่มี clean_bg ใช้ bg ปัจจุบัน (…)` | `background frozen […]: fallback, no empty-tray background -> using current background (…)` |
| `🌅 Background UNFROZEN — grace period 1.5s` | `background unfrozen - grace period 1.5s` |
| `🔄 BG restored to frozen snapshot` | `background restored to frozen snapshot` |
| `⚡ Large motion detected — blob=…px / roi=…px (36%) → env change` | `env change: large motion blob=…px / roi=…px (36%)` |
| `👀 START ระหว่างเฝ้าดูนอกรอบ → เลิกเฝ้า ใช้ clean_bg ล่าสุด / เฟรมปัจจุบันเป็นพื้นหลังของรอบ` | `[cycle …] START during outside-cycle watch -> stop watching, use latest empty-tray background / current frame as cycle background` |
| `👀 จบการเฝ้าดูนอกรอบ (ROI นิ่งครบ 5 เฟรม) → ปลด freeze` | `outside-cycle watch ended (ROI still 5 frames) -> background unfrozen` |
| `🕒 พบ ROI ใหม่ระหว่างรอบ → รอใช้ตอนจบรอบ (กลับ WAIT_START)` | `new ROI found during cycle -> will apply when cycle ends (back to WAIT_START)` |
| `🗺️ ใช้ ROI ใหม่ (rect) → ล้าง tracker / clean_bg / scene history ของ ROI เดิม` | `new ROI applied (rect) -> cleared tracker / empty-tray background / scene history of old ROI` |
| `✅ Loaded quad ROI: 4 point(s)` | `loaded quad ROI: 4 point(s)` |
| `⚠️ อ่าน ROI จาก … ไม่ได้ (…) → ใช้ ROI เดิมต่อ (…)` | `cannot read ROI from … (…) -> keep current ROI (…)` |

## กล้อง (main.py / core/frame_source.py)
| เดิม | ใหม่ |
|---|---|
| `📷 ไม่มีเฟรมจากกล้อง` | `camera disconnected (no frame from camera)` |
| `📷 กล้องกลับมาแล้ว` | `camera back (frames received again)` |
| `⛔ กล้องหลุดระหว่างรอบ … → BLOCKED_WAIT_STOP (ไม่ยืนยันจนปิดรอบ)` | `[cycle …] camera disconnected during cycle -> BLOCKED_WAIT_STOP (no confirm until cycle closed)` |
| `📷 กล้องค้าง: ไม่มีเฟรมใหม่ 3.1s (เกิน CAMERA_STALL_SEC) → เปิดกล้องใหม่` | `camera stalled (no new frame) for 3.1s (over CAMERA_STALL_SEC) -> reconnecting` |
| `⚠️ กล้องหลุด กำลัง reconnect...` | `camera disconnected -> reconnecting...` |
| `🎞️ Video file @ 30.00 FPS → pacing playback ตามเวลาจริง` | `video file @ 30.00 FPS -> real-time playback pacing` |

## Redis (api/redis_controller.py)
| เดิม | ใหม่ |
|---|---|
| `🔌 Redis worker เริ่มแล้ว (RPOP CTRL / LPUSH CAMERA)` | `Redis worker started (RPOP CTRL / LPUSH CAMERA)` · โหมด 0: `(RPOP CTRL / CAMERA disabled (SEND_S0=0))` |
| `✅ เชื่อม Redis สำเร็จ` | `Redis connected` |
| `⚠️ Redis: เชื่อมต่อไม่ได้: … (ลองใหม่ทุก ≤5s)` | `Redis: cannot connect: … (retry every <= 5s)` |
| `⚠️ CTRL: ข้อความไม่รู้จัก 'x' → ไม่ตีความ` | `CTRL: unknown message 'x' -> ignored` |
| `⌨️ CONTROL_MODE=keyboard — ไม่เชื่อม Redis (ใช้ปุ่ม s/x บนหน้าต่าง)` | `CONTROL_MODE=keyboard - no Redis connection (use keys s/x on the window)` |
| `❌ Redis worker error ที่ไม่คาดคิด: …` | `unexpected Redis worker error: …` |
| (ใหม่ S17) | `S0 request ignored (cycle=…): SEND_S0=0 observe mode` (กันซ้ำใน controller — ปกติไม่เกิด) |

## cloud (api/cloud.py, api/client.py, config.cloud_summary)
| เดิม | ใหม่ |
|---|---|
| `☁️ Cloud: ปิดทั้งหมด (CLOUD_ENABLED=0) — ไม่มี HTTP` | `cloud: all off (CLOUD_ENABLED=0) - no HTTP` |
| `☁️ Cloud: register=เปิด, ROI sync=เปิด (ทุก 30s), ภาพสด=เปิด (ทุก 60s q80), ITEM_LANDED=เปิด, anomaly=ปิด` | `cloud: register=on, ROI sync=on (every 30s), live image=on (every 60s q80), ITEM_LANDED=on, anomaly=off` |
| `☁️ ส่ง ITEM_LANDED สำเร็จ (ครั้งที่ 1)` | `upload ITEM_LANDED OK (attempt 1)` |
| `⚠️ ส่ง ITEM_LANDED ไม่สำเร็จ (…) → ลองใหม่ใน 5s` | `upload ITEM_LANDED failed (…) -> retry in 5s` |
| `⚠️ register ตู้ ไม่สำเร็จ → ลองใหม่ใน 5s (ครั้งที่ 1)` / `☁️ register ตู้ สำเร็จ (หลังลองใหม่ 2 ครั้ง)` | `machine register failed -> retry in 5s (attempt 1)` / `machine register OK (after 2 retries)` |
| `[VENDING_01] ✅ ลงทะเบียนตู้สำเร็จ (SYSTEM_ONLINE)` | `[VENDING_01] machine registered (SYSTEM_ONLINE)` |
| `[VENDING_01] ☁️ ได้ ROI ใหม่จาก Server → อัปเดต …` | `[VENDING_01] new ROI from server -> updated …` |
| `☁️ มี event ค้างใน outbox 2 รายการ → ส่งต่อ` | `outbox has 2 pending event(s) -> continue upload` |
| `⚠️ ไม่พบภาพ … → ส่ง event … โดยไม่มีภาพ` | `image … not found -> upload event … without image` |
| `❌ บันทึก ITEM_LANDED ลง outbox ไม่ได้ (…) → ไม่ส่งขึ้นเว็บ (ยอด/S0 ปกติ)` | `[cycle …] cannot add ITEM_LANDED to outbox (…) -> no upload (count/S0 not affected)` |

## startup / config / ระบบ
| เดิม | ใหม่ |
|---|---|
| `🖥️ ระบบทำงานในชื่อตู้: VENDING_01` | `machine: VENDING_01` |
| `🖥️ โหมด: HEADLESS (Pi) / คำสั่งจาก redis` | `mode: HEADLESS (Pi) / commands from redis` |
| `⚙️  Active config:` | `active config:` (ตามด้วย `   KEY = value` ทุกค่า) |
| `⚠️ .env: WS_URL ไม่มีผล (ระบบ order เดิม ไม่ใช้ในโหมด START–STOP) — ลบออกหรือใส่ # ได้` | `.env: WS_URL has no effect (old order system, not used in START-STOP mode) - remove it or comment it out with #` |
| (ใหม่ S19) | `.env: ANOMALY_MIN_INTERVAL_SEC has no effect (removed: anomaly images have no rate limit, use ANOMALY_MAX_PER_DAY) - …` |
| `❌ .env: X='a' ต้องเป็นจำนวนเต็ม` | `.env: X='a' must be an integer` |
| `❌ เปิด state DB ไม่ได้ (…): …` + `→ ห้ามลบไฟล์ DB เพื่อให้บูตผ่าน: สำรองไฟล์แล้วแจ้งผู้ดูแล` | `cannot open state DB (…): …` + `-> do NOT delete the DB file to make it boot: back it up and contact the maintainer` |
| `🧹 Disk cleanup thread เริ่มแล้ว (เก็บภาพ 3 วัน, anomaly 3 วัน, cleanup ทุก 1 ชม.)` | `disk cleanup thread started (keep images 3 days, anomaly images 3 days, every 1 h)` |
| `🧹 Disk cleanup: ลบ 5 ไฟล์ (…)` | `disk cleanup: deleted 5 file(s) (…)` |
| `❌ เขียน daily log ไม่ได้ (…): …` | `cannot write daily log (…): …` |
| `🛑 ได้รับ signal 15 → ปิดโปรแกรม` / `👋 ปิดโปรแกรมแล้ว` | `signal 15 received -> shutting down` / `program stopped` |
| `… (+ซ้ำอีก 12 ครั้งใน 10s ก่อนหน้า)` | `… (+12 repeats in previous 10s)` |

ไม่เปลี่ยน: daily log `05/10/2026 13:45:12 : item drop : 1` · ชื่อไฟล์ภาพ `YYYYmmdd_HHMMSS_mmm_<KIND>_<cycle|nocycle>.jpg` ·
รหัส anomaly (`OUTSIDE_CYCLE`, `EXTRA_AFTER_CONFIRM`, `NO_CONFIRM_AT_CLOSE`, `POSSIBLE_REMOVAL`, `ENV_CHANGE`) · `S3=ADDITION/REMOVAL/UNCERTAIN` ·
ข้อความบนภาพ (เป็น ASCII อยู่แล้ว)
