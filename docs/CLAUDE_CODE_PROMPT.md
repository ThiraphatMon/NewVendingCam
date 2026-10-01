# Prompt สำหรับ Claude Code (copy ทั้งหมดในกรอบไปวางตอนเริ่ม session)

```
ช่วย cleanup โปรเจค VendingCam ตามแผนใน docs/CLEANUP_PLAN.md

กติกา (สำคัญ ห้ามละเมิด):
1. ห้าม git commit / push / stash / reset เด็ดขาด — ฉันจะตรวจและ commit เองทีละเฟส
2. ห้ามเปลี่ยนพฤติกรรมการนับของในเฟส 1–4: หลังแก้แต่ละเฟสต้องรัน
   python tools/regression/run_regression.py แล้วผลต้องตรง baseline ทุกคลิป
   ถ้าไม่ตรง ให้หาสาเหตุและแก้ ห้ามแก้ baseline.json เอง
3. ทำทีละเฟส จบแต่ละเฟสให้หยุด สรุปสิ่งที่เปลี่ยน + ผล regression แล้วรอฉันสั่ง "ต่อ"
4. ไม่ต้องอ่านหรือค้นใน .venv, evidence_images, logs, tools/regression/clips
5. ชื่อค่าใน .env เดิมต้องใช้ได้เหมือนเดิม (เช่น MACHINE_ID_DEFAULT) เพราะ Orange Pi ใช้ .env เดิมอยู่
6. คอมเมนต์ในโค้ดเป็นภาษาไทย สไตล์เดียวกับโค้ดเดิม

เฟส 0 — เตรียม (ทำก่อนแก้โค้ดใดๆ):
- python tools/regression/make_clips.py
- python tools/regression/run_regression.py --update-baseline   ← บันทึกพฤติกรรมของโค้ดปัจจุบัน
- รันซ้ำอีกรอบโดยไม่ใส่ --update-baseline ต้องผ่านทุกคลิป (ยืนยันว่าผลไม่แกว่ง)
- สรุปตาราง baseline ให้ฉันดู แล้วหยุด

เฟส 1 — config:
- แทน config.py ด้วย proposed/config.py และ .envexample ด้วย proposed/.envexample
  (ถ้าค่า default ใน config.py ปัจจุบันต่างจากร่าง ให้ถามฉันก่อน)
- ต่อค่าที่ดึงเข้ามาใหม่ไปใช้แทนเลข hardcode: LR→BG_LEARNING_RATE, LR_RELEARN→BG_RELEARN_RATE,
  RESET_GRACE_PERIOD→RESET_GRACE_SEC, CLEAN_BG_INTERVAL, RECONNECT_DELAY→CAMERA_RECONNECT_SEC,
  GHOST_FRAME_TOLERANCE (tracker), ROI_CHECK_INTERVAL (roi), ROI_POLL_INTERVAL (main),
  RETRY_INTERVAL (retry_queue), WS_RECONNECT_SEC (order_listener),
  CLEANUP_KEEP_DAYS/CLEANUP_INTERVAL_HOURS (disk_cleanup ให้ import จาก config), ROI_CONFIG_PATH
- SEND_INTERVAL=0 ต้องหมายถึงปิดการส่งภาพสด
- ตัด MIN_PRESENCE_SEC, REBASELINE_ON_CAPTURE (ถือว่าเปิดถาวร), ENV_SETTLE_FRAMES (ถือว่า 0) ออกจากโค้ด
- ตัด dead code: all_gone, branch item_visible ใน draw_captured_items,
  sm.land_obj_id / capture_time / land_img_path, else: pass ท้าย loop, import datetime ใน loop
- print(config.summary()) ตอน startup

เฟส 2 — ย้ายไฟล์ (ไม่เปลี่ยน logic):
- draw_captured_items + render_overlay → ui/overlay.py
- roi_polling_task → api/client.py: start_roi_polling(machine_id)
- group_close_boxes → core/detect.py
- api/sent_frame.py → รวมเข้า api/client.py (ยังเรียกแบบเดิมก่อน เฟส 5 ค่อยทำ thread)
- อัปเดต Dockerfile COPY ให้ครบโฟลเดอร์ใหม่ (เช่น ui/)

เฟส 3 — แยก main loop:
- core/frame_source.py: เปิดกล้อง/วิดีโอ, resize, reconnect, pacing วิดีโอ
- core/background.py: class BackgroundModel รวม bg_np, freeze, clean_bg, grace period,
  reset (do_reset), rebaseline หลัง capture, env change / large motion
- รวมตรรกะ reset ทั้ง 3 จุดเป็นฟังก์ชันเดียว และ has_active_motion ใช้ฟังก์ชันเดียว
- sm.new_transaction_id() แทนการสร้าง TXN 3 ที่
- ปุ่ม r ใช้ reset ตัวเดียวกับระบบ
- เป้าหมาย main.py < 250 บรรทัด อ่านจากบนลงล่างแล้วเห็นลำดับ: อ่านเฟรม → mask → ก้อน → tracker → ตัดสินใจ → วาด

เฟส 4 — ความเรียบร้อย:
- print → logger (utils/logger.py) ทั้งระบบ, log ที่พ่นทุกเฟรมให้จำกัดความถี่
- ตั้งชื่อเลขลอยใน tracker (0.75, 30, 0.95, 0.5) เป็นค่าคงที่มีคอมเมนต์
- state_machine: รวม 3 emit เป็น _emit() ตัวเดียว, ตัด parameter default_machine
- อัปเดต HANDOVER.md ให้ตรงโค้ดใหม่ (Orange Pi แทน Raspberry Pi, โครงสร้างไฟล์, ตาราง config)

เฟส 5 — พร้อมลง Orange Pi (เปลี่ยนพฤติกรรมเล็กน้อย ทำแยกเฟส):
- send_frame ทำงานใน background thread ถือเฉพาะเฟรมล่าสุด ไม่ block main loop
- fetch_remote_roi เขียนไฟล์เฉพาะเมื่อข้อมูลเปลี่ยน แบบ atomic (tmp + os.replace)
- ROIManager.load() ไฟล์พัง → log warning แล้วใช้ ROI เดิมต่อ ไม่ทำให้โปรแกรมตาย
- requirements.txt: opencv-python → opencv-python-headless (เวอร์ชันเดิม)
- Dockerfile: ENV TZ=Asia/Bangkok
- regression ยังต้องผ่าน
```

## หลังจบแต่ละเฟส (ทำเอง)

```powershell
git diff --stat                # ดูไฟล์ที่เปลี่ยน
python main.py                 # ลองรันกับกล้อง/คลิปจริง (HEADLESS=0)
git add -A
git commit -m "cleanup phase N: ..."
```
