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
GROUP_DIST = 200
CONFIRM_TIME = 0.5
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
#   - ต่ำลง (เช่น 18) → จับของชิ้นเล็ก/สีใกล้พื้นหลังได้ดีขึ้น แต่ noise/แสงสะท้อนมากขึ้น
#   - สูงขึ้น (เช่น 30) → เงียบขึ้น แต่ของจาง ๆ อาจหลุด
MOT_THRESH = int(os.getenv("MOT_THRESH", "5"))

# MEDIAN_BLUR_KSIZE : ลบ speckle noise ก่อน threshold (เลขคี่ 3/5; 0=ปิด)
#   สำคัญมากตอน MOT_THRESH ต่ำ ๆ — median ลบจุด noise กระจายได้ดีโดยแทบไม่กินของตัน
#   → กัน "นับเกินเพราะ noise" ได้ตรงจุด โดยไม่ต้องดัน MOT_THRESH สูงจนของเล็กหลุด
MEDIAN_BLUR_KSIZE = int(os.getenv("MEDIAN_BLUR_KSIZE", "5"))

# MIN_SOLIDITY : สัดส่วน (พื้นที่จริงของ blob / พื้นที่กรอบ) ขั้นต่ำ (0.0-1.0; 0=ปิด)
#   ของจริงเป็นก้อนตัน (solidity สูง) / noise กระจายเป็นเส้น-จุด (solidity ต่ำ) → ตัดทิ้ง
MIN_SOLIDITY = float(os.getenv("MIN_SOLIDITY", "0.35"))

# ขนาด kernel ของ morphology (เลขคี่). เดิมใช้ DILATE 5x5 x2 ซึ่งทำให้กรอบบวม
# และรวมของ 2 ชิ้นที่อยู่ใกล้กันเป็นก้อนเดียว → ตอนนี้ใช้ OPEN+CLOSE เล็ก ๆ แทน
MORPH_OPEN_KSIZE = int(os.getenv("MORPH_OPEN_KSIZE", "3"))   # ลบ noise จุดเล็ก (0=ปิด)
MORPH_CLOSE_KSIZE = int(os.getenv("MORPH_CLOSE_KSIZE", "3"))  # อุดรูในชิ้นเดิม (0=ปิด)

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

# ── Re-baseline on capture (จับชิ้นแล้ว "กลืน" เข้า bg เพื่อพร้อมจับชิ้นถัดไปทันที) ──
# เมื่อ capture ของชิ้นหนึ่งได้ → เขียนภาพบริเวณนั้นทับเข้า background
# ผล: ของชิ้นนั้นหยุดเป็น motion, ROI ที่เหลือยังไวต่อของชิ้นใหม่ที่ตกมา
REBASELINE_ON_CAPTURE = os.getenv("REBASELINE_ON_CAPTURE", "1") == "1"
REBASELINE_PAD = int(os.getenv("REBASELINE_PAD", "6"))  # px เผื่อรอบกรอบตอนกลืน

# ── Displacement guard: ของที่นับแล้วถูกชนขยับ → ไม่นับซ้ำ (conservation) ──────
# ระยะ (px) จากจุดเดิมที่ยังถือว่า blob ใหม่ = ของเดิมที่ขยับมา
DISPLACE_RADIUS = int(os.getenv("DISPLACE_RADIUS", "130"))
# ค่าเฉลี่ย diff ในกรอบเดิม ที่ถือว่า "ของออกจากจุดเดิมแล้ว (ว่างลง)"
VACATE_MEAN_DIFF = float(os.getenv("VACATE_MEAN_DIFF", "12"))
# blob ใหม่ที่ทับ anchor เดิม >= สัดส่วนนี้ = ของตกทับ (นับใหม่) ไม่ใช่ของเดิมขยับ
STACK_OVERLAP_RATIO = float(os.getenv("STACK_OVERLAP_RATIO", "0.4"))

# ── Count cap: ถ้ามี order → ห้ามนับเกินจำนวนที่สั่ง (กัน over-count 1→2→3) ─────
# backstop ที่เชื่อถือได้สุดสำหรับกันการนับเกิน เพราะรู้ qty ที่สั่งอยู่แล้ว
# [แก้ bug] เดิม '== "0"' ทำให้ตรรกะกลับด้าน — แก้เป็น '== "1"' (1=เปิด, 0=ปิด)
CAP_COUNT_TO_ORDER_QTY = os.getenv("CAP_COUNT_TO_ORDER_QTY", "1") == "1"

# ระยะเวลาสูงสุดที่ระบบจะค้างอยู่ใน EVIDENCE_CAPTURED
# ก่อน force reset — ป้องกันกรณีของค้างใน ROI นานเกินไป
CONFIRMED_HOLD_TIMEOUT = 20  # วินาที (ปรับได้)

# ระยะเวลาที่ confirmed item หายจาก ROI (ถูกบัง/slat) ก่อนจะถือว่าหายจริง
# ถ้ากลับมาปรากฏก่อน timeout → ยังอยู่, reset hold timeout ใหม่
CONFIRMED_ITEM_GONE_TIMEOUT = 5  # วินาที (ปรับได้)

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