# AUTORUN_REPORT — ความคืบหน้างานต่อเนื่อง (branch `auto/round1-finish`)

> คำสั่งหลัก: `docs/AUTORUN_TASK.md` | review: `git log main..auto/round1-finish`

## สถานะแต่ละขั้น

| ขั้น | สถานะ | commit | pytest | e2e (1–6, 8 / 7) | START→S0 ข้อ 1 / ข้อ 3 |
|---|---|---|---|---|---|
| S0 ตั้งต้น + D2 baseline freshness | ✅ เสร็จ | autorun S0 | 100 passed | ✅ / ❌ (คาดไว้) | 3.41s / 3.40s, 3.40s |
| S1 ปิดงาน D2 (ตั้งพื้นหลังใหม่หลัง env change สงบ) | รอ | | | | |
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

## ไฟล์ที่เปลี่ยน (สะสม)
- S0: `core/background.py`, `main.py` (D2), `tests/test_evidence.py`, `tests/integration/redis_e2e.py` (ข้อ 8, `.e2e_tmp/`),
  `.gitignore`, `docs/AUTORUN_TASK.md`, `docs/AUTORUN_REPORT.md`

## ความหมายของ test ที่เปลี่ยน
- S0 (D2): `test_start_during_watch_uses_pre_motion_background` แยกเป็น
  `test_start_during_watch_while_item_falling_is_confirmed` (ของกำลังตกตอน START ยังนับได้) และ
  `test_start_during_watch_uses_latest_still_scene_not_watch_freeze` (ของนิ่งก่อน START ≥5 เฟรมไม่นับ — เหมือนตัวเก่า,
  ผู้ใช้อนุมัติแล้ว)

## คำถามรอผู้ใช้ (ประเภท A — ทำต่อไปแล้วด้วยทางที่ปลอดภัย)
- (ยังไม่มี)

## Known limitations
- ข้อ 7: ของวางนิ่งก่อน START แล้วถูกหยิบออกระหว่างรอบ → หลุมถูกยืนยันเป็นของ → S0 ผิด (S3 จะแก้)
- ของที่นิ่งอยู่ก่อน START ≥5 เฟรม ไม่ถูกนับในรอบนั้น (เหมือนตัวเก่า)
