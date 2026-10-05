# AUTORUN_REPORT — ความคืบหน้างานต่อเนื่อง (branch `auto/round1-finish`)

> คำสั่งหลัก: `docs/AUTORUN_TASK.md` | review: `git log main..auto/round1-finish`

## สถานะแต่ละขั้น

| ขั้น | สถานะ | commit | pytest | e2e (1–6, 8 / 7) | START→S0 ข้อ 1 / ข้อ 3 |
|---|---|---|---|---|---|
| S0 ตั้งต้น + D2 baseline freshness | ✅ เสร็จ | autorun S0 | 100 passed | ✅ / ❌ (คาดไว้) | 3.41s / 3.40s, 3.40s |
| S1 ปิดงาน D2 (ตั้งพื้นหลังใหม่หลัง env change สงบ) | ✅ เสร็จ | autorun S1 | 103 passed | ✅ (+8b, 8c) / ✅* | 3.41s / 3.41s, 3.42s |
| S2 ขั้น E (พร้อมลง Orange Pi) | รอ | | | | |
| S3 แยกหยิบออก / ใส่เข้า (ข้อ 7) | รอ | | | | |
| S4 ความนิ่งของ tracker | รอ | | | | |
| S5 กล้องค้าง | รอ | | | | |
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

## ไฟล์ที่เปลี่ยน (สะสม)
- S0: `core/background.py`, `main.py` (D2), `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (ข้อ 8, `.e2e_tmp/`),
  `.gitignore`, `docs/AUTORUN_TASK.md`, `docs/AUTORUN_REPORT.md`
- S1: `main.py`, `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (8b, 8c)

## ความหมายของ test ที่เปลี่ยน
- S0 (D2): `test_start_during_watch_uses_pre_motion_background` แยกเป็น
  `test_start_during_watch_while_item_falling_is_confirmed` (ของกำลังตกตอน START ยังนับได้) และ
  `test_start_during_watch_uses_latest_still_scene_not_watch_freeze` (ของนิ่งก่อน START ≥5 เฟรมไม่นับ — เหมือนตัวเก่า,
  ผู้ใช้อนุมัติแล้ว)

## คำถามรอผู้ใช้ (ประเภท A — ทำต่อไปแล้วด้วยทางที่ปลอดภัย)
- S1: ตั้งพื้นหลังใหม่หลัง env change สงบ ใช้ CLEAN_BG_STABLE_FRAMES (5 เฟรม ≈ 0.17s) ร่วมกัน ไม่แยกค่า
  ทางอื่น: แยกค่า ENV_SETTLE_FRAMES ให้นานกว่า (เช่น 15) → กันการตั้งใหม่ตอน slat ค้างกลางทางได้ดีขึ้น แต่ถาดต้องนิ่งนานขึ้นก่อนเห็นของ
- S1: ของที่ตก "พร้อมกับ" ตอน env change (เช่นตกขณะ slat ปิด) จะถูกกลืนเข้าพื้นหลังใหม่ → ไม่ยืนยัน (ไม่ส่ง S0) — เลือกทางกัน S0 ผิด

## Known limitations
- ข้อ 7: ของวางนิ่งก่อน START แล้วถูกหยิบออกระหว่างรอบ → หลุมถูกยืนยันเป็นของ → S0 ผิด (S3 จะแก้)
- ของที่นิ่งอยู่ก่อน START ≥5 เฟรม ไม่ถูกนับในรอบนั้น (เหมือนตัวเก่า)
