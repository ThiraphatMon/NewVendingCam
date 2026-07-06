import os
from dotenv import load_dotenv

load_dotenv()

# CAMERA_INDEX รับได้ทั้งเลขกล้อง (0,1,...) และ path ไฟล์วิดีโอ
#   - เป็นตัวเลขล้วน  → กล้องจริง
#   - ไม่ใช่ตัวเลข     → path คลิป (เช่น C:\\...\\clip.mp4)
_cam_src = os.getenv("CAMERA_INDEX", "0").strip().strip('"').strip("'")
CAMERA_INDEX = int(_cam_src) if _cam_src.isdigit() else _cam_src
FRAME_W = 640
FRAME_H = 480
MIN_AREA = int(os.getenv("MIN_AREA", "150"))

# GROUP_DIST : ระยะห่าง (px) ระหว่างขอบกล่องที่ยังรวมเป็นชิ้นเดียว (โหมด distance)
#   - เล็ก (~40-60) → เชื่อมเฉพาะชิ้นส่วนของวัตถุเดียวที่ mask ขาด
#     แต่ของ 2 ชิ้นที่ตกห่างกันจะไม่ถูกรวม → แยกนับเป็นหลายชิ้นได้ (ตรงตามที่ต้องการ)
#   - ใหญ่ (~100+) → รวมของที่ห่างกันด้วย เสี่ยง 2 ชิ้นกลายเป็นก้อนเดียว
#   [FIX] เดิม 200 กว้างเกินไป (และ MAIN ไม่ได้ใช้เป็นเกณฑ์รวมด้วย) → ตั้ง 60
GROUP_DIST = int(os.getenv("GROUP_DIST", "60"))

# GROUP_MODE : วิธีรวมกล่องที่แตกจาก contour
#   - "distance" → รวมกล่องที่ขอบห่างกันน้อยกว่า GROUP_DIST (สไตล์ OLD ที่ detect แม่น)
#                  เชื่อมชิ้นส่วนวัตถุเดียวกลับเป็นก้อน แต่ของที่ตกห่างยังแยกกัน
#   - "overlap"  → รวมเฉพาะกล่องที่ซ้อนทับกันจริง (±GROUP_OVERLAP_PAD)
#                  แยกของที่บินใกล้กันได้ดี แต่วัตถุเดียวที่ mask ขาดจะไม่ถูกเชื่อม
GROUP_MODE = os.getenv("GROUP_MODE", "distance").strip().lower()

CONFIRM_TIME = 1
DROP_TIMEOUT = 25.0

# ── Capture responsiveness (จับของให้ไว = "ของหยุดนิ่ง" คือ "ตกถึงที่แล้ว") ──────
# แนวคิด: ของที่กำลังตกจะเคลื่อนที่ (ไม่นิ่ง) → พอถึงที่แล้วจะนิ่ง = จังหวะที่ควร capture
# ระบบจึง capture ทันทีที่ของ "นิ่ง" ไม่ต้องรอ timer ยาว ๆ แล้วพร้อมรับชิ้นถัดไปเลย
#
# LANDING_STABLE_FRAMES : จำนวนเฟรมที่ centroid ต้องนิ่งจึงถือว่า "ตกถึงที่/ลงจอด"
#   - น้อยลง (2-3) → จับไวขึ้น แต่เสี่ยงจับตอนของสะดุด/เด้งกลางอากาศ
#   - มากขึ้น (6-8) → มั่นใจว่านิ่งจริง แต่ช้าลง
LANDING_STABLE_FRAMES = int(os.getenv("LANDING_STABLE_FRAMES", "4"))

# CAPTURE_HOLD_SEC : เวลาที่ต้องนิ่งเพิ่ม "หลัง" ลงจอดก่อน capture
#   - 0 = จับทันทีที่นิ่ง (ไวสุด, ตรงกับที่ต้องการให้ชิ้นถัดไปตกมาก็จับทัน)
CAPTURE_HOLD_SEC = float(os.getenv("CAPTURE_HOLD_SEC", "0"))

# MIN_PRESENCE_SEC : เวลาขั้นต่ำที่ object ต้องอยู่ใน ROI ก่อน capture (กัน noise แวบเดียว)
#   - เดิม logic นี้ไว้กันมือ แต่ตอนนี้ slat บังมือแล้ว จึงลดลงเหลือแค่กัน noise
#   - ตั้ง 0 เพื่อจับทันทีที่นิ่ง (ถ้า noise ไม่เป็นปัญหา)
MIN_PRESENCE_SEC = float(os.getenv("MIN_PRESENCE_SEC", "0.2"))

# CENTROID_STABLE_DIST : ระยะ (px) ที่ centroid ขยับได้ต่อเฟรมแล้วยังถือว่า "นิ่ง"
#   - ของชิ้นเล็ก + mask กระพริบ อาจต้องเพิ่มเล็กน้อย (12-15) ให้ลงจอดได้ไว
CENTROID_STABLE_DIST = int(os.getenv("CENTROID_STABLE_DIST", "10"))

# ── Detection tuning (ปรับความแม่นยำของการจับของ) ──────────────────────────────
# ทุกค่าปรับผ่าน .env ได้ ไม่ต้องแก้โค้ด
#
# MOT_THRESH : ความไวการจับ motion (ค่า diff ของสีเทาที่ถือว่า "เปลี่ยน")
#   - ต่ำลง (เช่น 5-18) → จับของชิ้นเล็ก/สีใกล้พื้นหลังได้ แต่ noise/แสงสะท้อนพุ่ง
#   - สูงขึ้น (เช่น 25-30) → เงียบขึ้น กรอบแนบของจริง แต่ของจาง ๆ อาจหลุด
#   [FIX] คืนค่ากลับเป็น 25 (เท่ากับเวอร์ชันที่ detect แม่น) — ค่า 5 ต่ำเกินไป
#   ทำให้เงา/แสงสั่น/สัญญาณรบกวนกล้องถูกนับเป็น motion จนกรอบวัตถุเพี้ยน
MOT_THRESH = int(os.getenv("MOT_THRESH", "25"))

# MEDIAN_BLUR_KSIZE : ลบ speckle noise ก่อน threshold (เลขคี่ 3/5; 0=ปิด)
#   สำคัญมากตอน MOT_THRESH ต่ำ ๆ — median ลบจุด noise กระจายได้ดีโดยแทบไม่กินของตัน
#   [FIX] เมื่อ MOT_THRESH กลับเป็น 25 แล้ว noise น้อยลงมาก จึงปิด median (0)
#   ให้ pipeline ตรงกับเวอร์ชันที่ detect แม่น (median อาจกัดขอบของชิ้นเล็ก)
MEDIAN_BLUR_KSIZE = int(os.getenv("MEDIAN_BLUR_KSIZE", "0"))

# MIN_SOLIDITY : สัดส่วน (พื้นที่จริงของ blob / พื้นที่กรอบ) ขั้นต่ำ (0.0-1.0; 0=ปิด)
#   ของจริงเป็นก้อนตัน (solidity สูง) / noise กระจายเป็นเส้น-จุด (solidity ต่ำ) → ตัดทิ้ง
#   [FIX] ปิด (0) — จำเป็นเฉพาะตอน MOT_THRESH ต่ำที่มี noise เยอะ
#   เมื่อ threshold=25 + DILATE เชื่อม mask แล้ว ของจริงจะตันอยู่แล้ว
#   ถ้าเปิดไว้อาจตัดวัตถุจริงที่รูปร่างโปร่ง (เช่น ซองใส) ทิ้งโดยไม่ตั้งใจ
MIN_SOLIDITY = float(os.getenv("MIN_SOLIDITY", "0.0"))

# ขนาด kernel ของ morphology (เลขคี่).
# เวอร์ชันที่ detect แม่นใช้ OPEN 5x5 แล้ว DILATE 5x5 iterations=2
#   OPEN → ลบ noise จุดเล็ก, DILATE → เชื่อม mask ของชิ้นเดียวที่ขาดให้ตัน
MORPH_OPEN_KSIZE = int(os.getenv("MORPH_OPEN_KSIZE", "5"))   # ลบ noise จุดเล็ก (0=ปิด)
MORPH_CLOSE_KSIZE = int(os.getenv("MORPH_CLOSE_KSIZE", "0"))  # อุดรูในชิ้นเดิม (0=ปิด)

# [FIX] คืน DILATE กลับเข้า pipeline (สไตล์ OLD ที่ detect รูปร่างแม่น)
#   ทำให้ mask ของวัตถุชิ้นเดียวที่ขาดเป็นหย่อม ๆ เชื่อมเป็นก้อนตัน
#   → contour เดียว, กรอบครอบของเต็ม, รูปร่างไม่กระท่อนกระแท่น
#   หมายเหตุ: DILATE ทำให้กรอบพองออกเล็กน้อย (~ksize/2 px รอบด้าน) ซึ่งเป็น
#   trade-off ที่เวอร์ชันแม่นยอมรับเพื่อให้ได้รูปร่างที่ต่อเนื่อง
MORPH_DILATE_KSIZE = int(os.getenv("MORPH_DILATE_KSIZE", "5"))  # 0=ปิด
MORPH_DILATE_ITER = int(os.getenv("MORPH_DILATE_ITER", "2"))    # 0=ปิด

# ระยะ (px) ที่ยอมให้กล่องซ้อน/ชิดกันแล้วรวมเป็นชิ้นเดียว (เผื่อชิ้นเดียวแตกเป็นหลาย contour)
GROUP_OVERLAP_PAD = int(os.getenv("GROUP_OVERLAP_PAD", "4"))

# ระยะสูงสุด (px) ที่ tracker ยอม match detection เข้ากับ object เดิม
#   - ต่ำลง → ของ 2 ชิ้นที่อยู่ใกล้กันไม่สลับ id กัน แต่ของที่ตกเร็วอาจหลุด track
#   - สูงขึ้น → ทน motion เร็วได้ แต่เสี่ยงจับ 2 ชิ้นรวมเป็น id เดียว
TRACK_MATCH_DIST = int(os.getenv("TRACK_MATCH_DIST", "150"))

# TRACK_CONFIRMED_ITEMS : ให้กรอบของที่ confirm แล้ว "ตามของจริง" แทนการตรึงอยู่กับที่
#   - 1 = กรอบ track ตามของที่ขยับ/กลิ้ง (แก้ปัญหากรอบค้าง) — เหมาะเมื่อ slat บังมือแล้ว
#   - 0 = ตรึงกรอบไว้ที่จุด confirm (ดีไซน์เดิม กันกรอบดริฟต์ตามมือ)
#   ⚠️ เห็นผลเฉพาะเมื่อของยัง "มองเห็น" อยู่ → ต้องตั้ง REBASELINE_ON_CAPTURE=0 ด้วย
#      (ถ้า REBASELINE=1 ของถูกกลืนเข้า bg จนมองไม่เห็น กรอบจะ track ไม่ได้)
TRACK_CONFIRMED_ITEMS = os.getenv("TRACK_CONFIRMED_ITEMS", "1") == "1"

# ── Re-baseline on capture (จับชิ้นแล้วล้าง motion ทั้งเฟรม เพื่อพร้อมจับชิ้นถัดไป) ──
# เมื่อ capture item ได้ → เอาเฟรมปัจจุบัน "ทั้งภาพ" มาเป็น background ใหม่
# ผล: motion mask ว่างเปล่าทันที, ROI สะอาดเอี่ยม, env ที่เปลี่ยนจากการกระแทกถูกล้างหมด
#     ของชิ้นถัดไป (แม้ตกทับที่เดิม) จะเป็น motion ใหม่ → นับเป็นชิ้นใหม่ได้
#     กรอบเขียว confirm ค้างไว้ที่ตำแหน่งเดิม (overlay จาก captured_items)
# ตั้ง 0 = ปิด (ของที่นับแล้วจะยังเป็น motion ค้าง — ไม่แนะนำ)
REBASELINE_ON_CAPTURE = os.getenv("REBASELINE_ON_CAPTURE", "1") == "1"

# ── Count cap: ถ้ามี order → ห้ามนับเกินจำนวนที่สั่ง (กัน over-count 1→2→3) ─────
# backstop ที่เชื่อถือได้สุดสำหรับกันการนับเกิน เพราะรู้ qty ที่สั่งอยู่แล้ว
# [แก้ bug] เดิม '== "0"' ทำให้ตรรกะกลับด้าน — แก้เป็น '== "1"' (1=เปิด, 0=ปิด)
CAP_COUNT_TO_ORDER_QTY = os.getenv("CAP_COUNT_TO_ORDER_QTY", "1") == "1"

# ระยะเวลาสูงสุดที่ระบบจะค้างอยู่ใน EVIDENCE_CAPTURED ก่อน reset (กรณีไม่มี order)
# ตีความ: "รอว่าไม่มีของตกเพิ่มอีกแล้วจริง" — ทุกครั้งที่มี motion/ของใหม่เข้ามา
# ตัวนับนี้จะถูกรีเซ็ตกลับไปนับใหม่ (ดู has_active_motion ใน main.py)
# → นับครบโดยไม่มี motion แทรก = ไม่มีของตกเพิ่มแล้ว → reset
# หมายเหตุ: ในโหมด re-baseline ของถูกกลืนเข้า bg หลัง capture จึงมองไม่เห็นของที่นับ
# แล้ว การตรวจ "ของออกจาก ROI จริง" เป็นไปไม่ได้ → ใช้ hold timeout นี้เป็นตัวตัดสิน
CONFIRMED_HOLD_TIMEOUT = int(os.getenv("CONFIRMED_HOLD_TIMEOUT", "20"))  # วินาที

# สัดส่วนพื้นที่ blob ใน ROI area ที่ถือว่าเป็น env change (แสง/bg เปลี่ยน)
MAX_BLOB_ROI_RATIO = 0.60  # สัดส่วน 0.0-1.0 (ปรับได้)

# ── Order Window ──────────────────────────────────────────────────────────────
# เวลารอของตกหลังได้รับ order (วินาที)
# - reset ทุกครั้งที่ confirm item ได้
# - หมดเวลา → สรุปผล order (completed / anomaly / no_drop)
ORDER_WINDOW = int(os.getenv("ORDER_WINDOW", "30"))  # วินาที (ปรับได้)

MACHINE_ID = os.getenv("MACHINE_ID_DEFAULT", "VENDING_01")
CLOUD_API_URL = os.getenv("CLOUD_API_URL")
WS_URL = os.getenv("WS_URL", "ws://localhost:5100/ws")
API_KEY = os.getenv("API_KEY", "")

# HEADLESS mode:
#   - ตั้งเป็น "0" ตอนทดสอบบน PC เพื่อเปิด imshow window
#   - ตั้งเป็น "1" ตอนรันบน Raspberry Pi (ไม่มีจอ)
HEADLESS = os.getenv("HEADLESS", "1") == "1"

SEND_INTERVAL = 1