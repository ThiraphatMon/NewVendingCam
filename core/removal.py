"""
core/removal.py — แยก "ของหายไป" (ลูกค้าหยิบออก) กับ "ของใส่เข้า" (สินค้าตก) ก่อนยืนยันในรอบ ACTIVE

ปัญหา: พื้นหลังของรอบมีของวางอยู่แล้ว (ของนิ่งก่อน START) → ลูกค้าหยิบออกระหว่างรอบ
→ ตำแหน่งที่ของเคยอยู่ต่างจากพื้นหลังและนิ่ง → tracker เห็นเป็นวัตถุลงจอด → S0 ผิด (redis_e2e ข้อ 7)

pure logic (numpy/cv2 เท่านั้น ไม่แตะ state) — main เรียกตอนมี candidate ที่จะยืนยัน

วัดเฉพาะ "พิกเซลที่เปลี่ยน" (|ปัจจุบัน − พื้นหลังรอบ| > MOT_THRESH) ในกล่องของ candidate
(กล่องจาก tracker กว้างกว่าของจริงมาก — วัดทั้งกล่องสัญญาณจะจางจนแยกไม่ออก: คลิปได้ ×0.82 vs ×1.14)

สัญญาณ 2 อย่าง:
  1) ความคม (ค่าเฉลี่ย Sobel magnitude) "ลดลง" เทียบพื้นหลังของรอบ
     ของจริงมีขอบ/ลาย ถาดว่างเรียบกว่า → ใส่เข้า = ขอบเพิ่ม, หยิบออก = ขอบลด
     (คลิปทดสอบผ่าน App จริง: ใส่เข้า ×1.52, หยิบออก ×0.40)
  2) ปัจจุบัน "กลับไปเหมือนฉากนิ่งก่อนหน้า" (scene history ที่บันทึกก่อนการเปลี่ยนแปลงนี้)
     มากกว่าเหมือนพื้นหลังของรอบ (คลิป หยิบออก: ต่างจากฉากก่อนหน้า 13.1 vs ต่างจากพื้นหลังรอบ 77.6;
     ใส่เข้า: 76.6 vs 76.8 — ไม่ตรง)

ผล:
  ADDITION  ขอบไม่ลด → ของใส่เข้า (ยืนยันตามปกติ) — ซื้อซ้ำที่ตำแหน่งเดิมก็ยังเป็น ADDITION
            (สัญญาณ 2 อย่างเดียวแยกไม่ได้: ว่าง→ของ→ว่าง กับ ของ→ว่าง→ของ หน้าตาเหมือนกัน)
  REMOVAL   ขอบลด + กลับไปเหมือนฉากก่อนหน้า → หยิบออกแน่นอน
  UNCERTAIN ขอบลด แต่ไม่มีฉากก่อนหน้าที่ตรง (เช่นเพิ่งเปิดเครื่องตอนมีของในถาด / ของเรียบกว่าพื้น)
            → นโยบายตาม REMOVAL_UNCERTAIN_SEND_S0 (default ไม่ส่ง S0)
"""

from dataclasses import dataclass

import cv2
import numpy as np

ADDITION = "ADDITION"
REMOVAL = "REMOVAL"
UNCERTAIN = "UNCERTAIN"


@dataclass
class Verdict:
    kind: str
    edge_ratio: float     # ความคม patch ปัจจุบัน / พื้นหลังของรอบ
    diff_base: float      # ค่าเฉลี่ย |ปัจจุบัน − พื้นหลังของรอบ| ใน patch
    diff_history: float   # ค่าเฉลี่ย |ปัจจุบัน − ฉากก่อนหน้าที่ใกล้สุด| (inf = ไม่มีฉากให้เทียบ)

    def describe(self, edge_threshold=None):
        """ข้อความ log (ASCII) เช่น edge_ratio=1.12 (threshold 0.60), diff_bg=77.5, diff_prev=12.0"""
        hist = "-" if self.diff_history == float("inf") else f"{self.diff_history:.1f}"
        thr = "" if edge_threshold is None else f" (threshold {edge_threshold:.2f})"
        return f"edge_ratio={self.edge_ratio:.2f}{thr}, diff_bg={self.diff_base:.1f}, diff_prev={hist}"


# ขยายกล่องออกทุกด้าน (px) ให้ขอบของวัตถุอยู่ใน patch เสมอ
# (ของสีเรียบที่เต็มกล่องพอดีจะไม่มีขอบใน patch → ดูเรียบกว่าพื้นที่มีลาย → ถูกมองว่าหยิบออก)
BOX_PAD = 8


def box_of(obj, shape, pad=BOX_PAD):
    """กล่องของวัตถุจาก tracker (centroid + shape) + ขอบ pad ตัดให้อยู่ในภาพ → (x, y, w, h) หรือ None"""
    cx, cy = obj["centroid"]
    w, h = obj["shape"]
    x0, y0 = max(0, int(cx - w / 2) - pad), max(0, int(cy - h / 2) - pad)
    x1, y1 = min(shape[1], int(cx + w / 2) + pad), min(shape[0], int(cy + h / 2) + pad)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    return x0, y0, x1 - x0, y1 - y0


# พิกเซลที่เปลี่ยนน้อยกว่านี้ → ใช้ทั้งกล่องแทน (กันค่าเฉลี่ยจากไม่กี่พิกเซล)
MIN_CHANGED_PX = 20


def _patch(img, box):
    x, y, w, h = box
    return img[y:y + h, x:x + w].astype(np.float32)


def _sharpness(p, mask):
    gx = cv2.Sobel(p, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(p, cv2.CV_32F, 0, 1)
    return float(np.mean(cv2.magnitude(gx, gy)[mask]))


def classify(current, baseline, history, box, edge_ratio_max, match_ratio, diff_thresh):
    """current / baseline / history[*] = ภาพ gray ขนาดเดียวกัน, box = (x, y, w, h)
    history: ฉากนิ่งที่บันทึกก่อนการเปลี่ยนแปลงนี้ (ผู้เรียกกรองตามเวลาแล้ว)
    diff_thresh: ความต่างที่นับว่า "พิกเซลเปลี่ยน" (MOT_THRESH)"""
    cur, base = _patch(current, box), _patch(baseline, box)
    mask = np.abs(cur - base) > diff_thresh
    if np.count_nonzero(mask) < MIN_CHANGED_PX:
        mask = np.ones_like(mask)
    edge_ratio = _sharpness(cur, mask) / max(_sharpness(base, mask), 1e-3)
    diff_base = float(np.mean(np.abs(cur - base)[mask]))
    diff_hist = min(
        (float(np.mean(np.abs(cur - _patch(s, box))[mask])) for s in history), default=float("inf")
    )

    if edge_ratio >= edge_ratio_max:
        kind = ADDITION
    elif diff_hist < diff_base * match_ratio:
        kind = REMOVAL
    else:
        kind = UNCERTAIN
    return Verdict(kind, edge_ratio, diff_base, diff_hist)
