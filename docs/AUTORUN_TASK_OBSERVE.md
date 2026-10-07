# AUTORUN_TASK_OBSERVE — โหมดเก็บข้อมูล (ไม่ส่ง S0) + hold 0.3 + anomaly + log อังกฤษ

> วางไฟล์นี้ที่ `docs/AUTORUN_TASK_OBSERVE.md` · ทำต่อบน branch `auto/round1-finish` (commit ล่าสุดของ S15/S16)
> เหตุผล: ทดสอบที่ตู้จริงพบว่า **มีออเดอร์แต่ของไม่ตก แล้วเงาลูกค้าเข้า ROI → กล้องส่ง S0 → controller จบออเดอร์ผิด**
> ผู้ใช้จึงถอดโปรแกรมออกจากบอร์ดแล้ว และต้องการ deploy กลับเป็น **โหมดเก็บข้อมูล: ทำงานเหมือนเดิมทุกอย่าง แต่ไม่ส่งสัญญาณใด ๆ กลับไปที่ controller**

---

## กติกา (เหมือนรอบก่อน)

- ทำทีละขั้น S17 → S21 · **commit 1 ครั้งต่อขั้น** ข้อความ `autorun S<n>: <สรุป>` · **ห้าม push ห้าม merge ห้ามแตะ main**
- ทุกขั้นที่แก้โค้ด: `pytest` ต้องผ่านทั้งหมด + `tests/integration/redis_e2e.py` ทุกสถานการณ์ (1, 2, 3, 4, 5, 6, 7, 7b, 8, 8b, 8c) ก่อน commit
- ทดสอบกับ Redis ทดสอบพอร์ต 6380 และ stub HTTP เท่านั้น · **ห้ามต่อ Redis ของตู้จริงหรือ server จริง**
- ห้ามเปลี่ยนความหมายของเทสต์เดิม แก้ได้เฉพาะข้อความที่เทสต์ค้นหา (เพราะ log เปลี่ยนภาษา) และเงื่อนไขที่เปลี่ยนเพราะ S0 ถูกปิด (ระบุทุกจุดในรายงาน)
- ห้ามแก้เกณฑ์ตรวจจับอื่น (threshold, S3, STRICT_STABILITY, env change) นอกจากที่สั่งในไฟล์นี้
- เงื่อนไขหยุด (พิมพ์ `AUTORUN BLOCKED: <เหตุผล>`): เทสต์เดิมพังและแก้ไม่ได้โดยไม่เปลี่ยนพฤติกรรม, ต้องเปลี่ยน schema แบบที่ rollback image เก่าไม่ได้, หรือคำสั่งในไฟล์นี้ขัดกันเอง
- รายงานผลทุกขั้นต่อท้าย `docs/AUTORUN_REPORT.md`

---

## S17 — สวิตช์ `SEND_S0` (สำคัญที่สุด ทำก่อน)

**config**: `SEND_S0` (0/1) **ค่าเริ่มต้น = 0** · เพิ่มใน `.envexample` พร้อมคำอธิบาย

**เมื่อ `SEND_S0=0` (observe mode)**
- **ไม่มีการเขียนลง `REDIS_RESPONSE_KEY` (CAMERA) เลยไม่ว่ากรณีใด** — รวมถึง S0 ที่ค้างส่งหลัง Redis กลับมา, หลัง restart, และทางอื่นทั้งหมดที่เคยเขียน CAMERA
- ยังอ่าน `CTRL` ด้วย RPOP เหมือนเดิม (vm-camera ไม่ใช้งานแล้ว ไม่ต้องทำโหมดแอบฟัง)
- ทุกอย่างอื่น **เหมือนเดิมทุกประการ**: state machine ของรอบ (ยืนยันแล้วเข้า CONFIRMED_WAIT_STOP), ภาพ confirmed/anomaly, SQLite, daily log, ITEM_LANDED ตาม `CLOUD_SEND_EVENTS`
- บันทึกใน DB ว่า S0 "ไม่ได้ส่ง" พร้อมเวลาที่ "จะได้ส่ง" (ไว้เทียบกับเวลา STOP จริง) — ทำแบบ additive (`CREATE TABLE IF NOT EXISTS` / คอลัมน์หรือค่า status ใหม่) ที่ image เก่ายัง rollback ได้
- log ตอนยืนยัน: `... item confirmed ... -> S0 NOT SENT (observe mode)`
- log ตอน startup 1 บรรทัดชัด ๆ: `S0 response: DISABLED (observe mode, SEND_S0=0)` หรือ `ENABLED`

**เมื่อ `SEND_S0=1`**: พฤติกรรมเดิมทุกอย่าง

**ทดสอบ**
- pytest ใหม่: ทุกเส้นทางที่เคยส่ง S0 (ยืนยันปกติ, ส่งค้างหลัง Redis หลุด, restart) → เมื่อ SEND_S0=0 ไม่มีการเขียน CAMERA
- redis_e2e: รันครบ **2 โหมด**
  - `SEND_S0=1`: ผลเหมือนเดิมทุกข้อ
  - `SEND_S0=0`: ทุกข้อ **ความยาว list CAMERA = 0 และไม่มี LPUSH/RPUSH CAMERA เลย** (ตรวจด้วย MONITOR หรือเทียบเท่า) และ outcome ของทุกรอบใน DB **เหมือนโหมด 1**
  - ใน e2e ที่เคยวัด START→S0 ให้วัด START→confirm (จาก DB/log) แทนในโหมด 0

## S18 — `CAPTURE_HOLD_SEC` ค่าเริ่มต้น 0.3 + วัดเวลาละเอียด

- เปลี่ยน default ใน `config.py` เป็น **0.3** + `.envexample` + HANDOVER
- วัดจากคลิปด้วย e2e ข้อ 1 และ 3 ที่ hold **0.1 / 0.3 / 0.5 / 1.0** แยกช่วงเวลา (หน่วยวินาทีของคลิป):
  START → ของเริ่มเห็นใน ROI → tracker เริ่มนิ่ง (เริ่มนับ hold) → ครบ hold → ตรวจ S3 → confirm
  ระบุชัดว่านอกจาก hold มีขั้นไหนกินเวลาเท่าไร (เช่น จำนวนเฟรมความนิ่งของ STRICT_STABILITY)
- รัน e2e ครบทุกข้อที่ hold 0.1 และ 0.3: ข้อไหนผลเปลี่ยน (ยืนยันผิด/ไม่ยืนยัน) ให้รายงาน **ไม่ต้องแก้**
- ตารางผลใส่ใน AUTORUN_REPORT

## S19 — ภาพ anomaly

1. **ยกเลิก rate limit เดิม** (30 วิ/ภาพ, 20 ภาพ/ชม.) → ทุกเหตุการณ์ได้ 1 ภาพ
   - ตรวจว่า anomaly ทุกชนิด (`OUTSIDE_CYCLE`, `EXTRA_AFTER_CONFIRM`, `NO_CONFIRM_AT_CLOSE`, `POSSIBLE_REMOVAL`) เกิด **1 ครั้งต่อเหตุการณ์ ไม่ใช่ทุกเฟรม** ถ้ามีชนิดไหนยิงซ้ำได้ทุกเฟรมเมื่อไม่มี rate limit ให้เพิ่มกันซ้ำต่อเหตุการณ์ และรายงาน
2. **เพดานกันดิสก์เต็ม**: `ANOMALY_MAX_PER_DAY=2000` (นับทุกชนิดรวม ตามวันเวลาไทย) ถึงเพดานแล้วไม่เก็บภาพเพิ่ม + log เตือน 1 ครั้งต่อวัน (ยังบันทึกเหตุการณ์ใน DB ต่อ)
3. **anomaly ใหม่ `ENV_CHANGE`**: เกิด env change → เก็บ **1 ภาพ** ตอนเริ่มเหตุการณ์ · ไม่ถ่ายซ้ำจน ROI กลับมานิ่ง (เกณฑ์เดียวกับ clean_bg: `CLEAN_BG_STABLE_FRAMES`) แล้ว env change ครั้งถัดไปจึงถ่ายใหม่ · เกิดได้ทุก state (ว่างและระหว่างรอบ) · ผูกกับ cycle_id ถ้าอยู่ในรอบ · **ไม่เปลี่ยนตรรกะการตรวจจับ**
4. ยังลบภาพเก่ากว่า 3 วันเหมือนเดิม · ไม่ส่งขึ้นเว็บ
5. เทสต์: ไม่มี rate limit, เพดานต่อวัน, ENV_CHANGE 1 ภาพต่อเหตุการณ์ (env change ค้างหลายเฟรม = 1 ภาพ; เปลี่ยน-นิ่ง-เปลี่ยน = 2 ภาพ) · e2e ข้อ 7, 8, 8b ต้องเห็นภาพ ENV_CHANGE ตามจริงในคลิป (รายงานจำนวน)

## S20 — log เป็นภาษาอังกฤษ ASCII ล้วน

- ทุกข้อความที่ออก **log/print ตอนรัน** (`docker compose logs`, `logs/vending.log`, startup config summary) → **ภาษาอังกฤษง่าย ๆ ASCII ล้วน ไม่มีอีโมจิ ไม่มีอักษรไทย ไม่มี ×**
- **comment / docstring / เอกสาร ยังเป็นภาษาไทย** ไม่ต้องแก้
- รูปแบบเมื่อเกี่ยวกับรอบ: `[cycle <id8>] <ข้อความ>` เช่น
  ```
  [cycle a1b2c3d4] START received -> cycle opened (background: empty-tray, age 0.3s)
  [cycle a1b2c3d4] S3=ADDITION edge_ratio=1.12 (threshold 0.60) -> item confirmed -> S0 NOT SENT (observe mode)
  [cycle a1b2c3d4] STOP received -> cycle closed: CONFIRMED
  ```
- ใช้คำตามตารางนี้ให้สม่ำเสมอ (ผู้ใช้ตกลงแล้ว):

| ไทย | อังกฤษ |
|---|---|
| รอบ / เปิดรอบ / ปิดรอบ | cycle / cycle opened / cycle closed |
| ยืนยันของ | item confirmed |
| ไม่มีของตกตอนจบรอบ | no item at close (`NO_CONFIRM_AT_CLOSE`) |
| ของตกนอกรอบ | item outside cycle (`OUTSIDE_CYCLE`) |
| ชิ้นที่ 2 ในรอบ | extra item (`EXTRA_AFTER_CONFIRM`) |
| หยิบออก / ไม่แน่ใจ / ใส่เข้า | item removed (`S3=REMOVAL`) / uncertain (`S3=UNCERTAIN`) / item added (`S3=ADDITION`) |
| ขอบ ×1.12 | edge_ratio=1.12 |
| พื้นหลัง / ภาพถาดว่าง / ตั้งพื้นหลังใหม่ | background / empty-tray background / background reset |
| สภาพแวดล้อมเปลี่ยน | env change |
| นิ่ง | still |
| START ซ้ำ | duplicate START (ignored) |
| หมดเวลา | cycle timeout |
| restart กลางรอบ | interrupted (program restarted) |
| กล้องหลุด / กล้องค้าง / ต่อใหม่ | camera disconnected / camera stalled (no new frame) / reconnecting |
| ภาพผิดปกติ | anomaly image |
| ส่งขึ้นเว็บ / คิวรอส่ง | upload / outbox |

- คงไว้: รหัส anomaly, `S3=...`, รูปแบบ daily log `dd/mm/yyyy HH:MM:SS : item drop : N`, ชื่อไฟล์ภาพ
- แก้เทสต์ที่ค้นหาข้อความไทย (เช่น e2e 7b ที่หา `ดูเหมือนหยิบออก`) ให้หาข้อความอังกฤษที่ความหมายเดียวกัน
- เทสต์ใหม่: รัน e2e แล้ว **ทุกบรรทัด log ที่โปรแกรมพิมพ์ต้องเป็น ASCII** (fail ถ้ามีอักขระ > 0x7F)
- ทำ **ตารางเทียบข้อความเดิม → ใหม่** ของข้อความสำคัญทั้งหมด (รอบ, ยืนยัน, S3, anomaly, กล้อง, Redis, cloud, startup) ใส่ใน `docs/LOG_MESSAGES.md`

## S21 — สรุป

- อัปเดต `HANDOVER.md` (observe mode, SEND_S0, hold 0.3, anomaly ใหม่, ตัวอย่าง log อังกฤษ) และ `.envexample`
- รันครบ: pytest + redis_e2e ทุกข้อ **ทั้ง SEND_S0=0 และ 1** + `docker_smoke.py` (SEND_S0=0 ต้องไม่มี CAMERA)
- AUTORUN_REPORT: ตารางขั้น S17–S21 (commit, pytest, e2e) + ตารางเวลา S18 + จุดที่แก้เทสต์ทั้งหมด
- พิมพ์ `AUTORUN DONE` พร้อมผลล่าสุด
