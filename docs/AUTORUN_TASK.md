# AUTORUN_TASK — งานต่อเนื่องจนจบ (Round 1 ที่เหลือ + Round 2)

> ไฟล์นี้คือคำสั่งหลักของการทำงานแบบไม่มีคนเฝ้า อ่านทั้งไฟล์ก่อนเริ่ม และอ่านซ้ำทุกครั้งหลัง context ถูก compact
> ความคืบหน้าทั้งหมดบันทึกที่ `docs/AUTORUN_REPORT.md` — ถ้าลืมว่าทำถึงไหน ให้อ่านไฟล์นั้น + `git log --oneline` ก่อนเสมอ

---

## 0. บริบท

- โปรเจคนี้คือระบบกล้องยืนยันสินค้า 1 ชิ้นต่อรอบ START–STOP ผ่าน Redis (CTRL/CAMERA, S0)
- เอกสารอ้างอิง: `docs/NewVendingCam_START_STOP_Handoff_TH.md`, `legacy_reference/main.py`
- งานที่ทำมาแล้ว: ขั้น A–D commit แล้ว, ขั้น D2 (clean_bg เทียบเฟรมต่อเฟรม, invalidate เมื่อ ROI เปลี่ยน,
  START ใช้เฟรมปัจจุบันถ้าไม่มี clean_bg, watch จบเมื่อ ROI นิ่ง) แก้แล้วแต่ยังไม่ commit
- คลิปทดสอบ: `big1_pickup_cutted.mp4` ตัวเดิม (13s: ของตก 2s, นิ่ง 3s, ลูกค้าหยิบจริง 7.2–10.6s)
- สคริปต์ e2e: `tests/integration/redis_e2e.py` (ใช้ Docker ใน WSL, Redis ทดสอบพอร์ต 6380)

## 1. กติกาที่ห้ามละเมิด

1. **Git:** สร้าง branch `auto/round1-finish` จาก HEAD ปัจจุบัน แล้วทำงานบน branch นี้เท่านั้น
   - commit ทีละขั้น ข้อความรูปแบบ `autorun S<n>: <สรุป>` (ภาษาอังกฤษสั้น ๆ ได้)
   - **ห้าม push, ห้ามแตะ branch main, ห้าม merge, ห้าม force/rebase ของ commit ที่ไม่ได้สร้างใน branch นี้**
   - ห้าม commit `data/*.sqlite3*`, ภาพ, log, ไฟล์ชั่วคราว, คลิปวิดีโอ
2. **ห้ามแตะของจริง:** ห้ามต่อ Redis อื่นนอกจาก container ทดสอบพอร์ต 6380 (มี Redis ของโปรเจคอื่นที่ 6379 — ห้ามแตะ)
   ห้ามแก้ protocol (key CTRL/CAMERA, payload START/STOP/S0, RPOP/LPUSH) ห้ามเพิ่มข้อความใหม่บน wire
3. **ไฟล์ชั่วคราวอยู่ในโปรเจค:** ให้ redis_e2e.py และการทดลองทั้งหมดใช้โฟลเดอร์ `.e2e_tmp/` ในโปรเจค
   (เพิ่มใน .gitignore) แทน Temp ของ Windows เพื่อไม่ต้องขออนุญาตอ่านไฟล์นอกโปรเจค ลบเมื่อจบแต่ละขั้น
4. **ค่าตรวจจับเดิม** (CAPTURE_HOLD_SEC=1.5, MOT_THRESH, MIN_AREA, MAX_BLOB_ROI_RATIO, LANDING_STABLE_FRAMES,
   CENTROID_STABLE_DIST, GROUP_*, MORPH_*) ห้ามเปลี่ยน default ยกเว้นขั้นที่ระบุไว้ชัดในไฟล์นี้
5. คอมเมนต์และ log เป็นภาษาไทย สไตล์เดียวกับโค้ดเดิม
6. ห้ามลบ test หรือแก้ test ให้ผ่านแบบหลอก ถ้าความหมายของ test เปลี่ยนจริง ให้อธิบายใน report

## 2. ประตูทดสอบ (ทำทุกขั้นก่อน commit)

1. `.venv\Scripts\python.exe -m pytest -q` ต้องผ่านทั้งหมด
2. `redis_e2e.py` ทุกสถานการณ์ (ใช้ `--keep` เฉพาะตอน debug):
   - **ข้อ 1–6 และ 8 ต้องผ่านเสมอ** (ห้ามถอยหลัง)
   - ข้อ 7 ผ่านหรือไม่ตามขั้นที่ระบุ
   - บันทึกเวลา START→S0 ของข้อ 1 และ 3 ทุกครั้ง ถ้าช้ากว่า baseline (~3.4s) เกิน 0.3s ต้องอธิบาย
3. ถ้าขั้นไหนทำให้ประตูนี้ไม่ผ่าน และแก้ไม่ได้ภายใน 3 ความพยายามที่มีเหตุผลต่างกัน:
   **เก็บงานที่ลองไว้เป็น patch แล้วย้อนกลับ:** `git diff > docs/autorun_failed/S<n>.patch` (รวมไฟล์ใหม่ด้วย
   `git add -N` ก่อน diff) จากนั้นคืนไฟล์ของขั้นนั้นให้เท่ากับ commit ล่าสุดของ branch (งานขั้นที่ commit แล้วต้องไม่หาย)
   commit เฉพาะ patch + report เป็น `autorun S<n>: skipped (see report)` แล้วไปขั้นถัดไป — ห้ามติดอยู่ขั้นเดียว
   ถ้าขั้นถัดไปต้องพึ่งขั้นที่ข้าม ให้ข้ามตามไปและบันทึกเหตุผล

## 3. นโยบายคำถาม

**ประเภท A — ทำต่อได้ (ส่วนใหญ่):** เลือกทางที่ปลอดภัย/อนุรักษ์นิยมที่สุด ทำให้เป็นค่าที่ตั้งได้ใน config ถ้าเหมาะ
แล้วบันทึกในหัวข้อ "คำถามรอผู้ใช้" ของ report (บอกทางที่เลือก + ทางอื่น + ผลต่างกัน) แล้วทำต่อ

**ประเภท B — ต้องหยุดจริง (น้อยมาก):** หยุดเฉพาะเมื่อ
- ต้องเปลี่ยน Redis protocol / controller / ทำอะไรกับอุปกรณ์จริง
- ต้องลบหรือเขียนทับข้อมูลผู้ใช้นอก branch นี้ (main, .env จริง, data/ จริง, ภาพหลักฐานจริง)
- สภาพแวดล้อมพังจนทดสอบไม่ได้เลย (เช่น Docker/WSL ใช้ไม่ได้ทั้งหมด) — ให้ทำส่วนที่ไม่ต้องใช้ Docker ให้เสร็จก่อน แล้วจึงหยุด
เมื่อหยุด: เขียนเหตุผลใน report แล้วพิมพ์บรรทัด `AUTORUN BLOCKED: <เหตุผลสั้น>`

## 4. ขั้นงาน

### S0 — ตั้งต้น
- สร้าง branch, เพิ่ม `.e2e_tmp/` ใน .gitignore, ปรับ redis_e2e.py ให้ใช้ `.e2e_tmp/`
- สร้าง `docs/AUTORUN_REPORT.md` (โครง: สถานะแต่ละขั้น / ผลทดสอบ / commit / คำถามรอผู้ใช้ / known limitations)
- commit งาน D2 ที่ค้างอยู่ตามสภาพปัจจุบัน (หลังผ่านประตูทดสอบ) เป็น `autorun S0: step D2 baseline freshness`

### S1 — ปิดงาน D2
ผู้ใช้อนุมัติ 3 จุดที่ทำต่างจาก spec แล้ว (watch จบเมื่อนิ่ง+tracker ว่าง, ย้าย cvtColor, แยก test เป็น 2 ข้อ)
และให้ทำ "ตั้งพื้นหลังใหม่หลัง env change สงบ" ที่เสนอไว้:
- ในรอบ ACTIVE ที่ยังไม่ยืนยัน: ถ้ามี env change แล้ว ROI กลับมานิ่งครบ N เฟรม (ใช้ CLEAN_BG_STABLE_FRAMES หรือค่าใหม่ใน config)
  ให้ตั้งพื้นหลังของรอบเป็นเฟรมนั้น + ล้าง tracker + log 1 บรรทัด (ทำได้หลายครั้งต่อรอบ แต่ต้องนิ่งก่อนทุกครั้ง)
- เพิ่ม e2e: 8b START @9.0 (slat ยังเปิด) → คาดหวัง UNCONFIRMED, log แสดงการตั้งพื้นหลังใหม่หลัง ~10.6s
  และ 8c START @11.0 (ถาดนิ่งแล้ว) → คาดหวังใช้ clean_bg, UNCONFIRMED
- รายงานว่าข้อ 7 เปลี่ยนไปอย่างไร (คาดว่ายังไม่ผ่าน)

### S2 — ขั้น E (พร้อมลง Orange Pi)
- `config.py` / `.envexample`: ครบทุกค่าใหม่ จัดหมวดพร้อมคอมเมนต์ไทย, ค่าที่ไม่มีผลใน redis mode ต้องมี warning ตอน startup
- `requirements.txt`: เพิ่ม redis, tzdata (pin เวอร์ชันที่ใช้ทดสอบ) / `requirements-dev.txt`: pytest, fakeredis
- `docker-compose.yml`: `network_mode: host`, `TZ=Asia/Bangkok`, volumes `data/ evidence_images/ logs/`, `/dev/video0`
  ห้ามเพิ่ม Redis service
- `Dockerfile`: COPY โฟลเดอร์ใหม่ครบ (ui/, tests ไม่ต้อง), ไม่ bake .env/data
- `.gitignore`: `data/*.sqlite3*`, `.e2e_tmp/` / `.gitattributes`: `* text=auto eol=lf` (+ binary สำหรับ jpg/mp4)
- ทดสอบ Docker บน WSL: `docker build` ผ่าน และรัน container สั้น ๆ ต่อ Redis ทดสอบ 6380 ด้วยคลิป (mount เข้า)
  ยืนยัน START→S0 ได้ 1 ครั้ง (ถ้า network_mode: host ใน WSL ใช้ไม่ได้ ให้ใช้วิธีทดสอบอื่นและบันทึกไว้)
- `HANDOVER.md` + `ORANGE_PI_DOCKER.md`: วงจร START/STOP, state diagram, daily log, config,
  ขั้นตอนลงบอร์ด (**หยุดโปรแกรมเก่าก่อนเสมอ**, ตรวจด้วย `redis-cli MONITOR`, controlled test), rollback,
  known limitations (ข้อ 7, จ่ายเกินนับเป็น 1, ฯลฯ)

### S3 — Round 2 ข้อ 1: แยก "หยิบออก" กับ "ใส่เข้า" (แก้ข้อ 7)
เป้าหมาย: ในรอบ ACTIVE วัตถุนิ่งที่เกิดจาก "ของหายไป" ต้องไม่ถูกยืนยันเป็นสินค้า
- แนวทางที่แนะนำ (เลือก/ปรับได้ถ้ามีเหตุผล): เก็บ snapshot ของฉากนิ่งย้อนหลัง (ring buffer, จำกัดหน่วยความจำ)
  เมื่อมี candidate ให้เทียบ patch ปัจจุบันกับ baseline ของรอบ และกับ snapshot เก่ากว่า
  ถ้า patch ปัจจุบัน "กลับไปเหมือนฉากก่อนหน้า" มากกว่าเหมือน baseline → ถือเป็น removal: ไม่ยืนยัน
  + ตั้งพื้นหลังรอบใหม่ + บันทึก anomaly ชนิดใหม่ `POSSIBLE_REMOVAL` (นับรวมโควตา anomaly)
- พิจารณาด้วยว่าจะให้มี B_empty calibration (คำสั่ง/ปุ่มให้ผู้ติดตั้งเก็บภาพถาดว่าง) เป็นตัวเสริมหรือไม่
  ถ้าทำ ต้องเป็น optional ระบบต้องทำงานได้โดยไม่มีมัน
- นโยบายเมื่อไม่แน่ใจ: **default = ไม่ส่ง S0** (กัน S0 ผิด) + บันทึก anomaly → ใส่เป็นคำถามประเภท A ใน report
- ทดสอบ: unit tests ด้วยเฟรมสังเคราะห์ (ทั้ง removal และ addition ที่ตำแหน่งเดียวกัน/สีใกล้กัน)
  e2e ข้อ 7 ต้องผ่าน และข้อ 1–6, 8, 8b, 8c ต้องยังผ่าน, เวลา START→S0 ไม่ช้าลงเกิน 0.3s

### S4 — Round 2 ข้อ 2: ความนิ่งของ tracker (F03/F04)
- ถอนสถานะ SHAPE_CONFIRMED เมื่อ centroid ขยับเกิน CENTROID_STABLE_DIST ระหว่าง hold
- ghost/หายไปแล้วกลับมา: เริ่มนับความนิ่งใหม่ ไม่สะสมข้ามช่วงหาย
- **เปลี่ยน detection — ต้องระวังที่สุด:** ทำหลัง config flag (เช่น `STRICT_STABILITY`) แล้ววัดทั้ง 2 แบบ
  ถ้าเปิดแล้วไม่ถอยหลังและเวลา START→S0 ไม่ช้าลงเกิน 0.3s → default เปิด; ถ้าไม่ → default ปิด และรายงานตัวเลข

### S5 — Round 2 ข้อ 3: กล้องค้าง
- อ่านกล้องใน thread แยก ถือเฉพาะเฟรมล่าสุด (slot ขนาด 1) พร้อม timestamp
- ไม่มีเฟรมใหม่เกิน `CAMERA_STALL_SEC` → ถือเป็น camera gap (ACTIVE → BLOCKED ตามกติกาเดิม), log, reconnect
- STOP/START ต้องประมวลผลได้แม้กล้องค้าง; ไฟล์วิดีโอยังต้องเล่นตามเวลาจริง
- tests ด้วยกล้องปลอมที่ค้าง + e2e ทั้งชุด

### S6 — สรุป
- รัน pytest + e2e ทั้งชุดรอบสุดท้าย, อัปเดต HANDOVER ตามงาน S3–S5
- เขียน report ให้ครบ: ตารางทุกขั้น (ผล/commit/เวลา START→S0), ไฟล์ที่เปลี่ยน, คำถามรอผู้ใช้ทั้งหมด,
  known limitations, สิ่งที่ต้องทดสอบที่ตู้จริง, วิธี review/merge (`git log main..auto/round1-finish`)
- ลบ `.e2e_tmp/` และ container ทดสอบ
- พิมพ์บรรทัดสุดท้าย `AUTORUN DONE` พร้อมผล pytest และ e2e ล่าสุด

## 5. หลัง context ถูก compact หรือกลับมาทำต่อหลัง usage limit
อ่านไฟล์นี้ → อ่าน `docs/AUTORUN_REPORT.md` → `git status` + `git log --oneline -10` → ทำขั้นถัดไปต่อ
ห้ามเริ่มขั้นที่ commit แล้วซ้ำ
