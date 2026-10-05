# Handoff สำหรับ Code Agent: เปลี่ยน NewVendingCam เป็นระบบยืนยันสินค้าหนึ่งชิ้นต่อ START–STOP

**วันที่:** 5 ตุลาคม 2026 — Asia/Bangkok  
**สถานะ:** ข้อกำหนดเพื่อเริ่มพัฒนา ยังไม่ใช่โค้ดที่แก้เสร็จหรือผลรับรองบนบอร์ดจริง  
**ภาษาหลัก:** Python / OpenCV / Redis / SQLite  
**ฐานพัฒนา:** ใช้ NewVendingCam-main เป็นฐาน ใช้ main.py ตัวเก่าเป็นเอกสารอ้างอิง protocol

> เป้าหมาย: คงระบบตรวจจับสินค้าทีละชิ้นของโปรแกรมใหม่ เปิดกล้องและประมวลผลต่อเนื่อง รับ START/STOP จาก Redis CTRL ยืนยันการตกได้สูงสุดหนึ่งครั้งต่อรอบ ส่ง S0 กลับ Redis CAMERA และเก็บภาพหลักฐานกับยอดรายวันอย่างคงทน โดยไม่ต้องรู้ qty ของออเดอร์ลูกค้า

## 0. คำสั่งตั้งต้นสำหรับ agent

1. อ่าน handoff นี้ทั้งฉบับและตรวจ source จริงก่อนแก้ โดยยึดข้อกำหนดล่าสุดในเอกสารนี้เหนือแนวคิด multi-item/order qty ในเอกสารเก่า
2. งานที่ต้องทำคือแก้โปรแกรมใหม่ให้ทำงานตามข้อกำหนด พร้อม tests และเอกสารการรัน ไม่ใช่เพียงเขียนแผน
3. รักษาความสามารถตรวจสินค้าทีละชิ้นของตัวใหม่ ซึ่งผู้ใช้พอใจอยู่แล้ว หลีกเลี่ยงการรื้อ detection pipeline หรือเปลี่ยน thresholds โดยไม่มีหลักฐาน regression
4. ห้ามแทน detection ใหม่ด้วย count_detection ของตัวเก่า เพราะตัวเก่านับจำนวนเฟรมที่ผ่าน threshold ไม่ใช่จำนวนสินค้า
5. ใช้ ROI ที่ผู้ติดตั้งกำหนดเพียงหนึ่งบริเวณ ห้ามเพิ่ม Guard ROI, เส้นผ่านสินค้า, sensor หรือ AI เป็นเงื่อนไขติดตั้ง
6. แยกงานที่ทำได้จาก source ออกจากสิ่งที่ต้องยืนยันกับ controller/กล้องจริง ทำส่วนที่ไม่ขึ้นกับข้อมูลขาดให้เสร็จก่อน ไม่หยุดทั้งงานเพื่อถามค่าที่มีค่าเริ่มต้นปลอดภัยอยู่แล้ว
7. ไม่แก้โปรแกรม controller ภายนอก ไม่เปลี่ยน wire protocol หรือเปิดขายบนบอร์ดจริงโดยพลการ
8. ถ้ารายละเอียด implementation ที่เสนอต่อไปนี้มีทางเลือกที่เรียบง่ายกว่าแต่รักษา invariants ได้ ให้ใช้ได้พร้อมอธิบายเหตุผล ไม่สร้าง abstraction ที่ไม่มีผู้ใช้จริง

## 1. ไฟล์ต้นทางและขอบเขตหลักฐาน

| สิ่งที่มี | ใช้ทำอะไร | สิ่งที่ยังไม่มี |
|---|---|---|
| NewVendingCam-main.zip | ฐานโค้ดใหม่ทั้งหมด | คลิปภาคสนามและผลวัดบนบอร์ด |
| main.py ตัวเก่า 196 บรรทัด | อ้างอิง Redis CTRL/CAMERA, START/STOP/S0 และการตั้งกล้องเก่า | config.ini ของเครื่องจริง |
| รายงาน NewVendingCam_Board_Readiness_Review_TH.md | รายการข้อบกพร่องเดิมและหลักฐานทดสอบ | ไม่ใช่สเปกหลักของสถาปัตยกรรมใหม่ในงานนี้ |
| บทสรุป handoff นี้ | ข้อกำหนดล่าสุดที่ผู้ใช้ต้องการ | source ฝั่งส่ง START/STOP และรับ S0 |

**อย่าสับสน main.py สองตัว:** main.py ภายใน NewVendingCam-main คือฐานที่จะพัฒนา; main.py ที่แนบแยกต่างหากคือตัวเก่าสำหรับอ้างอิง ควรเก็บสำเนาอ้างอิงชื่อชัดเจน เช่น legacy_reference/main.py โดยไม่เขียนทับ entrypoint ใหม่

สำหรับระบุ snapshot ที่ใช้เขียน handoff:

- ZIP ใหม่ SHA-256: `c96cb14279616783804752ac7b18fa65b6b66af1f360fb656d7346b2e5145c5c`
- main.py เก่า SHA-256: `75d2a7652f4ea94738dfe4397a8d51f468e403d7f4574fc8f293381a9f63db09`

อ้างชื่อไฟล์/ฟังก์ชันเป็นหลัก เพราะเลขบรรทัดจะเปลี่ยนเมื่อพัฒนา ไม่ต้องมี path ของพื้นที่ทำงานเดิมเพื่อใช้งานเอกสารนี้

## 2. ข้อเท็จจริงล่าสุดจากผู้ใช้

### 2.1 สภาพเครื่องและข้อจำกัด

- ลูกค้ากดหลายสินค้า/หลายชิ้นได้ แต่ controller จ่ายสินค้าทีละชิ้น
- หนึ่งรอบ START–STOP ใช้กับการจ่ายสินค้าหนึ่งชิ้น
- ผู้ใช้พอใจกับการตรวจสินค้าทีละชิ้นของระบบใหม่แล้ว เป้าหมายหลักคือผูก controller และแก้ lifecycle
- กล้องต้องเปิดและอ่านภาพต่อเนื่อง ไม่เปิด–ปิดตาม START/STOP
- ต้องการ ROI เดียวเพื่อให้ติดตั้งสะดวกในแต่ละตู้
- บอร์ดมีทรัพยากรจำกัดและอินเทอร์เน็ตน้อย ไม่มี sensor เพิ่ม และไม่ใช้ AI/local หรือ cloud inference
- กล้องติดเฉียงได้ ไม่มีหลักประกันว่าจะเห็นเส้นทางเริ่มตกทั้งหมด
- มีแสงน้อย เงาและ slat ทำให้ภาพเปลี่ยนมากได้
- ลูกค้าเปิด slat นานไม่แน่นอน อาจหยิบทั้งหมด บางส่วน หรือไม่หยิบเลย
- ยอดที่ต้องการคือ log จำนวนครั้งที่ยืนยันสินค้าตกได้ในแต่ละวัน

### 2.2 คำศัพท์ที่ต้องใช้ให้ตรง

| คำ | ความหมายในงานนี้ |
|---|---|
| merchant order | ออเดอร์การซื้อของลูกค้าทั้งชุด กล้องไม่จำเป็นต้องรู้ qty |
| dispense cycle / รอบตรวจ | หนึ่ง START ถึง STOP สำหรับสินค้าหนึ่งชิ้น |
| cycle_id | UUID ภายในกล้องที่สร้างเมื่อรับ START ที่ยอมรับ ใช้ผูกหลักฐาน/ยอด/ผลในเครื่อง |
| candidate | วัตถุที่กำลังตรวจและยังไม่ยืนยัน ไม่ใช่ยอดขาย |
| confirmed | ผ่านเกณฑ์ตรวจและบันทึกหลักฐาน/สถานะสำเร็จตามนโยบายแล้ว |
| daily count | จำนวน cycle ที่ confirmed ในวันไทยนั้น ไม่ใช่จำนวนสินค้าในถาดหรือจำนวน START |
| response enqueued | Redis รับ LPUSH S0 สำเร็จ ยังไม่เท่ากับ controller อ่าน/ประมวลผล S0 แล้ว |

**การยืนยันหนึ่งครั้งต่อรอบไม่ได้พิสูจน์ว่ากลไกไม่เคยปล่อยเกินหนึ่งชิ้น:** ถ้าฮาร์ดแวร์ปล่อยสองชิ้นพร้อมกัน งานนี้ไม่ได้มีเป้าหมายนับ over-dispense ให้คงข้อจำกัดนี้ไว้ในเอกสาร

## 3. ระดับของข้อกำหนด: สิ่งที่ตกลงแล้ว vs ค่าเริ่มต้นที่เสนอ

ใช้ป้ายต่อไปนี้เพื่อไม่ให้ agent นำข้อเสนอไปอ้างว่า controller รองรับแล้ว:

- **R — ยืนยันแล้ว:** ความต้องการจากผู้ใช้ ต้องทำ
- **D — implementation default:** แนวทางเริ่มต้นที่เสนอเพื่อให้ agent ทำงานต่อได้ เปลี่ยนได้เมื่อมีเหตุผลและไม่ขัด R
- **C — contract ต้องตรวจ:** ขึ้นกับ controller/หน้างาน ห้ามเดาแล้วอ้างว่า integration ผ่าน
- **B — backlog:** นอกเส้นทางหลัก ทำเมื่อจำเป็นหรือหลังแกนงานผ่าน

### 3.1 ข้อกำหนดหลัก

| ID | ข้อกำหนด | ระดับ |
|---|---|---|
| R01 | ใช้โค้ดตรวจจับใหม่เป็นฐาน รักษาพฤติกรรมจับสินค้าทีละชิ้น | R |
| R02 | รับ START/STOP จาก Redis list CTRL ตามระบบเก่า | R |
| R03 | กล้องอ่านภาพต่อเนื่องทั้งก่อน ระหว่าง และหลังรอบ | R |
| R04 | ห้ามยืนยัน/เพิ่มยอดจาก motion นอกรอบ START–STOP | R |
| R05 | หนึ่งรอบยืนยันได้สูงสุดหนึ่งครั้ง แม้มีหลาย candidate หรือเกิด motion ซ้ำ | R |
| R06 | STOP เป็นขอบเขตปิดรอบปกติ ไม่ใช้ qty หรือ order window เดิมปิดแทน | R |
| R07 | ไม่ต้องรับ/ใช้จำนวนสินค้าใน merchant order เพื่อตัดสินรอบนี้ | R |
| R08 | เก็บภาพหลักฐานของรอบที่ยืนยันได้ | R |
| R09 | แสดง log ยอดสะสมรายวันตามรูปแบบที่ผู้ใช้กำหนด | R |
| R10 | ใช้ ROI ที่ผู้ติดตั้งวาดหนึ่งบริเวณ ไม่มี Guard ROI เพิ่ม | R |
| R11 | ไม่ใช้ AI, sensor เพิ่ม หรือการส่งวิดีโอขึ้น cloud เพื่อวิเคราะห์ | R |
| R12 | การเปิด slat/หยิบสินค้าหลังยืนยันแล้วต้องไม่เพิ่มยอดของรอบนั้น | R |
| D01 | คง LPUSH CAMERA "S0" และส่งทันทีหลัง confirmed ไม่รอ STOP | D จากพฤติกรรมตัวเก่าและข้อสรุปก่อนหน้า |
| D02 | ใช้ Asia/Bangkok และบันทึกยอดแบบคงทนข้าม restart | D ที่สอดคล้องกับความต้องการ log รายวัน |
| D03 | ใช้ SQLite เป็นแหล่งจริงของ cycle/confirmation/daily count | D |
| D04 | ในโหมด Redis ปิด WebSocket order listener และไม่เปิด fallback counting อัตโนมัติ | D |
| D05 | โปรไฟล์ติดตั้งใหม่ปิด realtime upload โดยค่าเริ่มต้น; cloud เป็นส่วนเสริม | D ตามข้อจำกัด bandwidth |
| C01 | ความหมาย E0/E1… และการตอบกลับเมื่อ STOP/กล้องเสีย/timeout | C |
| C02 | ลำดับ producer push CTRL, controller อ่าน CAMERA, stale queue และ reboot recovery | C |
| C03 | controller เริ่มมอเตอร์เมื่อไรเทียบ START และรับประกัน slat พร้อมก่อนจ่ายหรือไม่ | C |
| C04 | แหล่งกล้องจริง USB หรือ RTSP และข้อมูล config.ini ที่ต้องใช้ต่อ | C |

## 4. ขอบเขตที่ต้องเลิกใช้ในโหมดใหม่

- WebSocket new_order / pending_order เดิมไม่ใช่แหล่งสั่งรอบพร้อมกับ Redis
- ไม่เรียก set_order() แบบเดิมเพื่อรอ qty และ ORDER_WINDOW
- ไม่สร้างรอบ/transaction จาก motion_in_ROI ขณะรอ START
- ไม่เพิ่ม item2/item3 ใน cycle เดียว
- ไม่ใช้ CAP_COUNT_TO_ORDER_QTY เป็นกลไกกันซ้ำ; ใช้ confirmation latch ต่อ cycle
- ไม่สรุป completed/anomaly ด้วยการเทียบจำนวนที่จับได้กับ qty
- ไม่ใช้ hold timeout / empty frame / env change ล้าง active cycle แล้วเปิดรับ START ใหม่เอง
- ไม่ส่ง NO_DROP/ORDER_RESULT ไป server ด้วย schema เดิมโดยเดาว่า server ยอมรับ local UUID เป็น order_id
- ห้ามลบความสามารถ debug, ROI, evidence หรือ cloud ที่ยังมีประโยชน์โดยไม่จำเป็น แยกการเปิดใช้ให้ชัด

การตรวจภาพต่อเนื่องยังทำได้ แต่การเริ่มรอบ การยืนยัน การเพิ่มยอด และการส่ง S0 ต้องผ่าน cycle gate เสมอ

## 5. สัญญา Redis ที่ต้องรักษา

### 5.1 Wire protocol พื้นฐาน

| ทิศทาง | ค่าเดิม | ความหมาย/ข้อกำหนด |
|---|---|---|
| รับ | Redis DB 0, list CTRL โดยค่าเริ่มต้น | รับคำสั่งตามลำดับที่เทียบเท่าการ RPOP ของตัวเก่า |
| รับ | `START` | เปิด cycle ใหม่เมื่อไม่มี cycle ค้างและไม่ได้ถูก recovery block |
| รับ | `STOP` | ปิด cycle ปัจจุบัน ไม่ปิดกล้อง |
| ส่ง | `LPUSH CAMERA "S0"` | ยืนยันว่ารอบนั้นจับหลักฐานสินค้าได้แล้ว |
| ข้อความอื่น | ยังไม่ระบุ | log แบบจำกัดความถี่ ไม่ตีความเป็น START/STOP โดยเดา |

- คงชื่อ key และ payload เดิมเป็นค่าเริ่มต้น เพื่อแทนโปรแกรมเดิมได้
- ไม่เปลี่ยนเป็น Redis Pub/Sub เพราะเดิมเป็น list queue
- RPOP อ่านจากขวา; ห้ามเปลี่ยนเป็น LPOP โดยไม่ตรวจ producer
- ถ้า producer ใช้ LPUSH คู่ RPOP จึงเป็น FIFO; ยังไม่เห็น producer ห้ามอ้างว่าตรวจแล้ว
- decode bytes อย่างปลอดภัย แยก key ว่าง, decode ผิด, Redis connection error ออกจากกัน
- ห้าม FLUSHDB, DEL CTRL, DEL CAMERA หรือ drain ทิ้งทั้งคิวตอน startup/reconnect
- ภายในหนึ่งชุด key ต้องมี consumer กล้องตัวเดียว ไม่เปิดตัวเก่ากับตัวใหม่อ่าน CTRL พร้อมกัน
- ถ้า Redis ใช้ร่วมหลายตู้ ต้องตรวจ isolation เดิมก่อน ห้ามเปลี่ยน key ให้มี machine_id จน controller หาไม่เจอ

### 5.2 รับคำสั่งโดยไม่หยุดกล้อง

D: ใช้ Redis worker กับ bounded queue ส่งคำสั่งให้ event loop ที่เป็นเจ้าของ cycle state เพียงตัวเดียว

- Redis calls ต้องมี connect/socket timeout และ backoff ที่ไม่ busy-loop
- ไม่ block main/capture loop ระหว่าง Redis ล่มหรือรอคำสั่ง
- worker ไม่เปลี่ยน state machine โดยตรง; ส่ง command พร้อมลำดับรับและเวลา monotonic ให้ owner
- อย่ารอ response worker จนหยุดอ่าน STOP
- ถ้าใช้ BRPOP ให้ timeout สั้นเพื่อ shutdown ได้ และวางใน worker เท่านั้น
- ถ้า application queue เต็ม ให้ backpressure ก่อนดึงคำสั่งถัดไป ห้าม drop STOP เพื่อให้คิวโล่ง
- การ preserve ลำดับ START, STOP, START สำคัญกว่าการสร้าง worker หลายตัว
- ไม่บังคับเปลี่ยนคำสั่งรับเป็น LMOVE ในรอบแรก หาก Redis version/สิทธิ์ไม่ยืนยัน; ถ้าคง RPOP ต้องรายงานช่วง command-loss หลัง pop ก่อน journal อย่างตรงไปตรงมา

### 5.3 duplicate/out-of-order commands

**D สำหรับ protocol ที่ยังไม่มี cycle ID จาก controller:**

| เหตุการณ์ | พฤติกรรมเริ่มต้น |
|---|---|
| START ขณะ WAIT_START | สร้าง local cycle_id ใหม่ ล้าง candidate ของรอบเก่า |
| START ซ้ำขณะ active/confirmed/blocked | บันทึก protocol anomaly ไม่เริ่มรอบใหม่ ไม่ล้าง confirmed latch และไม่เพิ่มยอด |
| STOP ขณะ active | จบรอบตามสถานะที่มีอยู่ |
| STOP ขณะ WAIT_START | no-op พร้อม diagnostic log ไม่เปลี่ยน daily count |
| START, STOP ติดกันโดยไม่มีภาพหลัง START | จบรอบแบบไม่ยืนยัน ไม่สร้าง S0 |
| STOP, START ติดกัน | ปิดรอบเดิมก่อนเริ่มรอบใหม่ ห้ามพา candidate/frame เก่าตามไป |

START ซ้อนอาจเป็น duplicate หรือเป็น cycle ใหม่ที่ถูกส่งผิดลำดับ ระบบเก่าแยกไม่ได้เพราะข้อความเหมือนกัน ห้าม queue ไว้เป็นคำสั่งจ่ายใหม่โดยเดา นโยบายไม่สร้างรอบซ้อนนี้ต้องตรวจยอมรับกับ controller ก่อนเปิดใช้จริง

### 5.4 S0 และข้อจำกัดการส่งซ้ำ

- ส่ง S0 หลัง confirmed โดยเร็ว ไม่รอ STOP เพราะ controller อาจรอ S0 จึงส่ง STOP
- ตั้ง logical response intent ของหนึ่ง cycle ได้เพียงหนึ่งรายการ
- การได้รับผลสำเร็จจาก LPUSH หมายถึง enqueue แล้ว ไม่ใช่ controller ACK
- ถ้า HTTP/cloud upload ไม่สำเร็จ ห้ามทำให้เกิด S0 หรือ daily count ซ้ำ
- ถ้า Redis ตอบ error ที่ยืนยันได้ว่ายังไม่ enqueue ให้ retry ได้เฉพาะตามนโยบายที่ยังผูกกับ cycle ปัจจุบันและยังไม่ STOP
- ถ้าคำสั่งอาจ enqueue แล้วแต่ response หาย ให้สถานะ DELIVERY_UNKNOWN; ห้าม blind retry LPUSH เพราะอาจมี S0 ซ้ำ
- ระวัง automatic write retries ของ Redis client; กำหนดอย่างชัดเจนและทดสอบ
- หลัง STOP หรือ reboot ห้ามปล่อย S0 ค้างจากรอบก่อนเข้าคิวให้ controller อ่านเป็นผลรอบใหม่เอง
- ถ้า STOP มาระหว่าง LPUSH ที่ส่งออกไปแล้ว ห้ามอ้างว่ายกเลิก bytes ที่ส่งได้: รักษา in-flight/unknown state และ reconcile ผล ห้ามเริ่มส่ง intent ใหม่หลัง STOP; ทดสอบ boundary นี้โดยเฉพาะ และ block การส่งผลข้ามรอบเมื่อยังสรุปไม่ได้
- ถ้ามี S0 ค้างใน CAMERA ซึ่ง controller ยังไม่อ่าน เราเอาออกแบบเจาะจง cycle ไม่ได้จาก payload เปล่า ต้องมี lifecycle/cleanup contract ฝั่ง controller ไม่แก้ด้วยการล้างทั้ง key
- local cycle_id ไม่ทำให้ START/STOP/S0 บนสายมี idempotency ขึ้นมาเอง

ทางเลือกอนาคต: controller ส่ง correlation ID หรือ Redis Lua+dedup key ภายใน operation เดียวเมื่อมีสิทธิ์และนโยบาย retention ที่ตรวจสอบแล้ว; เป็น C/B ไม่ใช่การเปลี่ยน protocol โดยอัตโนมัติ ต้องไม่อ้าง exactly-once end-to-end ก่อนทำและทดสอบครบ

## 6. State machine ที่ต้องได้

ชื่อ state ปรับได้ แต่พฤติกรรมและ invariants ต้องตรง ตารางนี้เป็นแบบเสนอ

### 6.1 Cycle states

| State | ความหมาย | นับ/ส่ง S0 ได้ไหม |
|---|---|---|
| WAIT_START | ไม่มีรอบขาย active กล้องยังทำงาน | ไม่ได้ |
| ACTIVE_UNCONFIRMED | รับ START แล้ว ยังไม่ยืนยันสินค้า | ได้เมื่อ image gate พร้อมและ candidate ผ่าน |
| CONFIRMING | ล็อก candidate หนึ่งตัว อยู่ระหว่างบันทึกภาพ/commit | ห้ามสร้าง confirmation เพิ่ม; ยังไม่ส่ง S0 ก่อนสำเร็จ |
| CONFIRMED_WAIT_STOP | หลักฐานและ confirmation commit แล้ว | ห้ามยืนยัน/เพิ่มยอดอีก; ส่งผลเดิมตาม delivery policy ได้ |
| BLOCKED_WAIT_STOP | รอบยังเปิด แต่ fault/ข้อมูลไม่พอให้ยืนยันอย่างปลอดภัย | ไม่ยืนยันใหม่จนกว่าจะปิดรอบ ตาม fault policy |
| RECOVERY_BLOCKED | หลัง restart/connection gap มีความไม่แน่ใจเรื่องรอบ | ไม่เปิดรอบจากภาพหรือ stale command เอง |

สถานะ delivery แยกเป็น PENDING / ENQUEUED / FAILED / UNKNOWN / EXPIRED ไม่ยัดทุกอย่างไว้ใน state ว่ายังไม่จับสินค้า

### 6.2 Transitions ที่สำคัญ

1. WAIT_START + START → ACTIVE_UNCONFIRMED; สร้าง cycle_id และเวลารับคำสั่ง
2. ACTIVE_UNCONFIRMED + candidate valid → CONFIRMING; จับสำเนาภาพหลักฐานและล็อก candidate
3. CONFIRMING + ภาพบันทึกและ confirmation transaction สำเร็จ โดย cycle ยังเปิด → CONFIRMED_WAIT_STOP; เพิ่ม daily count ครั้งเดียวและตั้ง intent ส่ง S0
4. CONFIRMING + STOP ที่ owner รับก่อน commit → ยกเลิกการยืนยัน; completion ที่ตามมาห้ามเพิ่มยอดหรือส่ง S0
5. CONFIRMED_WAIT_STOP + motion/slat/removal/START ซ้ำ → ยังเป็นรอบเดิม ยอดไม่เปลี่ยน
6. active state + STOP → ปิด cycle; confirmed คงอยู่ในประวัติ; ล้าง transient candidates; กล้องไม่ถูกปิด
7. active unconfirmed + fault ที่ทำให้ช่วงตรวจขาดความต่อเนื่อง → BLOCKED_WAIT_STOP เป็นค่าเริ่มต้นที่อนุรักษ์นิยม
8. watchdog ถ้ามี → แจ้ง fault/หยุดยืนยันได้ แต่ไม่กลายเป็น START ใหม่หรือ successful cycle
9. restart → กู้ daily ledger; cycle ที่ค้างต้อง reconcile/blocked ไม่ resume count โดยสมมติว่า controller ยังอยู่รอบเดิม

### 6.3 Invariants ที่ต้องบังคับด้วย tests

- ไม่มี active cycle ⇒ confirmations ใหม่ = 0, daily increment = 0, S0 intent ใหม่ = 0
- หนึ่ง cycle_id มี confirmation record ได้ไม่เกินหนึ่งแถว
- การออกจาก confirmed ไป WAIT_START ต้องเกิดจาก STOP/recovery resolution ที่มีบันทึก ไม่ใช่แค่ภาพว่างหรือ hold timeout
- daily count ไม่ลดเมื่อผู้ใช้หยิบสินค้าออก และไม่เพิ่มจาก START/STOP/response retry
- START/STOP ไม่เรียก release/open กล้อง
- candidate/frame/async callback ต้องถูกผูกกับ cycle_id และ generation เพื่อกันผลของรอบเก่าย้อนมาในรอบใหม่
- frame ก่อน START หรือหลัง STOP ที่ถูกใช้ผิดรอบต้องถูกปฏิเสธ
- ไม่มี thread ที่เขียน cycle state แข่งกันโดยตรง

### 6.4 Event ordering และ STOP race

กำหนด linearization point ที่ชัด: confirmation เกิดเมื่อ owner commit local confirmation transaction สำเร็จ; STOP มีผลเมื่อถูกนำมาประมวลผลโดย owner ตามลำดับรับ

- ในแต่ละ iteration ประมวลผล commands ที่รออยู่ก่อนยอมรับ detection/worker completion
- ถ้า STOP ถูกประมวลผลก่อน confirmation commit: ไม่เพิ่มยอด ไม่ส่ง S0 ภายหลัง
- ถ้า confirmation commit สำเร็จก่อน STOP: ยอดยังคงนับ แม้ response delivery ภายหลังจะหมดสิทธิ์ส่ง
- ห้ามถือว่ารู้เวลาที่ controller ส่งจริงจากเวลา dequeue ในกล้อง; protocol ปัจจุบันไม่มี timestamp/correlation ให้พิสูจน์ขอบเขตฝั่ง controller
- ตัวอย่าง START→STOP→START ในหนึ่งช่วงเฟรมต้องไม่ทำให้เฟรมของ cycle แรกถูกใช้ยืนยัน cycle ถัดไป

## 7. กล้องและการจับภาพต่อเนื่อง

### 7.1 Lifecycle

- สร้าง FrameSource เมื่อ process เริ่ม และ release เมื่อ shutdown หรือ reconnect เพราะอุปกรณ์เสียเท่านั้น
- START/STOP เปลี่ยนสิทธิ์การนับ ไม่เปลี่ยน lifecycle ของ camera connection
- ระหว่าง WAIT_START, confirmed และ blocked ยังอ่าน/drain เฟรมต่อไป เพื่อคงความสดของภาพและเตรียมพื้นหลัง
- ใช้ USB camera ตาม config ใหม่ หรือ RTSP ถ้าเครื่องจริงต้องใช้ ห้ามบังคับ RTSP เพราะตัวเก่าใช้
- แยก source_type = camera/file/stream ให้ชัด ไม่ถือว่า str ทุกตัวเป็น video file แล้วใช้ file pacing กับ RTSP
- วัด frame freshness/ช่องว่างระหว่าง valid frames; เวลา cap.read() กลับมาอย่างเดียวไม่ยืนยันว่า buffer ไม่มีเฟรมเก่า โดยเฉพาะ RTSP
- ถ้า backend อาจ read ค้าง ต้องแยก capture worker/process พร้อม watchdog เพื่อให้ command owner ยังประมวลผล STOP ได้
- bounded latest-frame slot เหมาะกว่าเก็บเฟรมต่อคิวยาว; ต้องไม่ปล่อย frame-age เพิ่มไม่จำกัด

### 7.2 การเตรียมพร้อมก่อน START

- มี camera readiness และ baseline readiness บน log/debug overlay แม้ wire protocol ยังไม่มี READY
- ไม่ส่ง READY หรือ ACK ใหม่ไป CAMERA เองจนกว่า controller รองรับ
- ถ้า controller จ่ายทันทีหลัง START โดยไม่รอ handshake ต้องใช้พื้นหลังที่เชื่อถือได้ก่อน START และรักษา camera freshness
- ถ้าไม่มีภาพก่อนจ่ายที่ใช้ได้ ห้ามเอาภาพที่มีสินค้าตกแล้วมาเป็นพื้นหลังแล้วอ้างว่าตรวจรอบนั้นครบ
- START ในช่วงกล้องเสียยังต้องถูกบันทึกเป็น cycle ที่ถูก block และต้องรับ STOP ได้ ไม่มี false success

## 8. Background, ROI และ slat

### 8.1 แยกสิ่งที่จำเป็นตอนนี้กับการพัฒนาต่อ

**แกนงานที่ต้องทำตอนนี้:** cycle gate, latch หนึ่งครั้ง, เตรียมพื้นหลังก่อน START, ป้องกัน candidate ข้ามรอบ, ไม่ใช้ slat/removal หลัง confirmed มานับซ้ำ

**ฐานที่ควรรองรับ:** ภาพอ้างอิงช่องว่างแยกจากฉากล่าสุด และ image-quality gate ภายใน ROI เดียว

**สิ่งที่ยังไม่ผ่านการยืนยัน:** classifier ที่แยก slat เปิด/ปิดได้แน่นอนจาก ROI เดียว ยังไม่มีคลิป/ภาพจริง จึงห้าม agent สร้าง heuristics แล้วประกาศว่าแก้ทุกกรณี 100% หรือทำให้การเชื่อม START/STOP ติดรอการสร้าง classifier สมบูรณ์

### 8.2 ภาพอ้างอิงที่มีความหมายต่างกัน

| Reference | ความหมาย | กติกาอัปเดต |
|---|---|---|
| B_empty | ช่องว่างที่ยืนยันแล้ว และอยู่ในสภาพพร้อมรับสินค้า | ไม่ถูกทับเพียงเพราะสินค้า/slat นิ่ง; ถ้ายังไม่มีให้ระบุ unavailable |
| B_scene | ฉากล่าสุดที่ยอมรับ อาจมีสินค้าที่นับแล้วค้างอยู่ | อัปเดตที่ safe boundary เมื่อฉากพร้อม ไม่ใช่กลาง candidate |
| B_cycle | snapshot ของ baseline ที่ใช้กับ cycle ปัจจุบัน | เลือกจาก pre-START reference ที่ยัง valid และตรึงไม่ให้กลืนสินค้าใหม่ |

- ไม่จำเป็นต้องเป็น array แยกทุกตัวหากใช้ immutable reference ได้ แต่ต้องรักษาความหมาย
- B_empty ไม่ใช่เฟรมแรกของ process โดยอัตโนมัติ
- ถ้าไม่มี empty calibration ให้ core START/STOP ทำงานได้ภายใต้ baseline policy ที่รายงานข้อจำกัดอย่างตรงไปตรงมา; ไม่สร้าง empty reference ปลอมจากสินค้าค้าง
- เวลารับ START ห้าม overwrite B_cycle ด้วย frame ที่อาจมีสินค้าเข้ามาแล้ว
- ขณะไม่มี cycle ใช้การนิ่งช่วยหา B_scene ที่เหมาะสม แต่ “นิ่ง” ไม่เท่ากับ slat ปิด; ต้องมี validity/staleness flags
- หลัง ROI/มุมกล้อง/ขนาดภาพเปลี่ยน reference เก่าต้อง invalidated/versioned

### 8.3 Slat และ removal

- หลัง confirmed latch แล้ว slat เปิด/หยิบหมด/หยิบบางชิ้น/ไม่หยิบ ต้องไม่เพิ่มยอด
- การเปิด slat ไม่ใช่หลักฐานว่าสินค้าถูกหยิบจริง ห้ามลด daily count หรือส่ง ITEM_REMOVED=1 โดยเดา
- ในช่วงก่อน confirmed หาก env change ทำให้ภาพไม่น่าเชื่อถือ ให้ระงับ candidate และ mark quality; ห้ามถือเป็นสินค้าเพียงเพราะก้อนใหญ่แล้วนิ่ง
- ห้ามใช้ fixed sleep/grace แล้วเปิดการนับใหม่อัตโนมัติ ทั้งที่ slat อาจยังเปิดค้าง
- การตรวจ motion หยุดต้องเทียบเฟรมติดกัน; การเทียบพื้นหลังเก่าอย่างเดียวทำให้ความต่างหลังหยิบค้างตลอด
- ก่อน rearm ต้องมี baseline ที่ใช้ได้และภาพใหม่ที่สด/นิ่งต่อเนื่อง; missing frames ไม่นับเป็น stable frames
- ห้ามใช้ `env_change=True` เป็น `STOP` หรือเป็นการล้างยอด/รอบ
- ห้ามถือว่ารูปต่างมากกว่า 30% แปลว่า slat เปิดแน่นอน สินค้าใหญ่และเงาก็เป็นได้
- ถ้าสินค้าอาจตกขณะภาพถูกบัง ให้ระบุ observation gap/uncertain ไม่สมมติว่าไม่มีสินค้า
- ออกแบบ visual gate ที่รับ readiness signal/quality assessment ได้ภายใน ROI เดียว; ใช้ recorded clips และข้อมูล controller เพื่อตัดสิน field policy ภายหลัง

### 8.4 รับฉากหลังจบรอบอย่างครบถ้วน

เมื่อยอมรับ B_scene ใหม่ ต้อง invalidate/update ภาพอ้างอิงที่เกี่ยวข้องให้สอดคล้อง (`bg`, `snapshot`, `clean_bg` เดิม) ไม่ให้ freeze() ดึงพื้นหลังเก่ากลับมาโดยไม่ตั้งใจ

ล้างเฉพาะ tracker/candidate/timing ของการตรวจ ไม่ล้าง daily ledger หรือ evidence ที่ commit แล้ว ไม่ถือว่าสินค้าที่เหลือในถาดเป็นสินค้าใหม่ใน START ถัดไปหากเป็นส่วนหนึ่งของ baseline ที่ยอมรับแล้ว

### 8.5 คง detector แต่ปิดช่องโหว่ที่ขัดคำว่า “นิ่ง”

- รักษา threshold/morphology/grouping ของตัวใหม่ก่อน อย่านำค่า threshold หน่วย sum(binary pixels) ของตัวเก่ามาแทน
- แก้ SHAPE_CONFIRMED ที่ไม่ถอนเมื่อ object ขยับ; ตรวจความนิ่งต่อเนื่องตลอด capture hold
- เมื่อหาย/ghost ให้ reset continuity ตาม policy ที่ทดสอบ ไม่สะสม stable count ข้ามช่วงหายแบบเงียบ
- ถ้ามี candidate สองตัวใน cycle เดียว ให้หนึ่ง confirmation สูงสุด ไม่ได้แปลว่ารับรอง over-dispense ถูกต้อง
- ไม่จำเป็นต้องแก้ F02 multi-item simultaneous ให้เป็นตัวนับหลายชิ้นในงานนี้
- ใช้ monotonic time สำหรับ duration/hold, wall-clock แบบ timezone-aware สำหรับวันที่/log

## 9. การยืนยัน หลักฐาน และยอดรายวัน

### 9.1 นิยามคำว่า confirmed ใน release นี้

D: ถือว่า confirmed เมื่อ candidate ผ่านเกณฑ์, ภาพหลักฐานบันทึกสำเร็จ และ confirmation record commit สำเร็จใน local durable store ขณะที่ cycle ยังเปิด

- ถ้าเขียนภาพหรือ DB ไม่ได้ ไม่ส่ง S0 และไม่เพิ่ม daily count; บันทึก EVIDENCE/STORAGE fault ภายใน
- ถ้าธุรกิจต้องการให้ตรวจตกสำเร็จแม้รูปหาย ต้องเปลี่ยน policy อย่างชัดเจนก่อน ไม่ปล่อยให้เกิดโดย ignore imwrite return
- ไม่รอ cloud upload เพื่อ confirmed; cloud offline ไม่ควรหยุดการยืนยันที่บันทึกในเครื่องสำเร็จ

### 9.2 ลำดับที่เสนอ

1. Owner ตรวจ cycle ยังเปิด, image gate พร้อม, candidate ใหม่และยังไม่มี confirmation
2. เข้าสู่ CONFIRMING พร้อม candidate/cycle generation; สำเนา frame ที่จะใช้เป็นหลักฐาน
3. เขียนภาพ temp ใน filesystem เดียวกัน ตรวจผล imwrite/encode, flush/fsync ตาม durability target แล้ว atomic rename เป็นชื่อสุดท้าย
4. Owner รับ completion และตรวจอีกครั้งว่า cycle/generation ยังตรงและยังไม่ STOP
5. SQLite transaction: insert confirmation ที่ unique ต่อ cycle, กำหนด confirmed_at/day/daily_sequence และบันทึก response intent
6. เมื่อ commit สำเร็จ latch confirmed, อัปเดต UI/log projection และสั่งส่ง S0 ตาม delivery policy
7. รอ STOP โดยไม่สร้าง confirmation ใหม่

ฐานข้อมูลและไฟล์ภาพไม่ใช่ transaction เดียวกัน: ถ้าไฟดับหลังภาพเสร็จก่อน DB commit อาจมี orphan image แต่ห้ามมี daily count ที่อ้างว่าภาพสำเร็จทั้งที่ไม่มี ตรวจ/จัดการ orphan แยกจากภาพที่ referenced

ถ้าใช้ worker ให้ bounded และหนึ่ง candidate ที่กำลัง commit ต่อ cycle ไม่เปิด thread ใหม่ทุกเฟรม; ถ้าเขียน synchronous ต้องวัด latency และไม่ทำให้ STOP/camera ขาดช่วงโดยไม่รู้ตัว

### 9.3 ข้อมูลขั้นต่ำใน SQLite

ใช้ไฟล์เช่น `data/vending_state.sqlite3` ใน persistent volume; schema ปรับได้ แต่ต้องมีข้อมูลเทียบเท่า:

| Entity | ฟิลด์สำคัญ |
|---|---|
| cycles | cycle_id UUID, machine_id, started_at_utc, stopped_at_utc, outcome, fault_reason, protocol/recovery status |
| confirmations | cycle_id UNIQUE, machine_id, confirmed_at_utc, local_date, daily_sequence, evidence_path, evidence_status, ROI/config version |
| response intents | cycle_id+response_type UNIQUE, payload S0, delivery_state, attempt time, last error, expiry/cancel reason |
| optional cloud outbox | event_id UNIQUE, cycle_id, payload, image reference, pending/acked/error state |

- ยอดจริงหาได้จาก confirmations ตาม machine_id/local_date ไม่ต้องมี totals สองแหล่งที่แก้แยกกัน
- ถ้ามี cached totals ต้อง update ใน transaction เดียวกับ unique confirmation
- `(machine_id, local_date, daily_sequence)` ต้องไม่ชน; count/sequence assignment ต้องอยู่ใน transaction ไม่ใช่อ่าน–บวกนอก lock
- response retry, process replay และ async completion ซ้ำต้องไม่สร้าง confirmation เพิ่ม
- configure journal/synchronous/busy_timeout อย่างมีเหตุผลและทดสอบบน local storage; ไม่อ้าง SQLite ป้องกัน storage/ไฟเลี้ยงเสียได้ทุกกรณี
- ถ้าฐานข้อมูลอ่านไม่ได้/เสีย ให้ fault ไม่เริ่มนับจาก 0 เงียบ ๆ

### 9.4 รูปแบบ log ที่ผู้ใช้ต้องการ

```text
05/10/2026 13:45:12 : item drop : 1
05/10/2026 13:46:30 : item drop : 2
05/10/2026 13:48:05 : item drop : 3
06/10/2026 00:00:08 : item drop : 1
```

- วัน/เดือน/ปี ค.ศ. เวลา 24 ชั่วโมง ใช้ `Asia/Bangkok` ชัดเจน ไม่พึ่ง timezone ของ host อย่างเดียว
- วันของยอด = local date ของ confirmed_at ที่ freeze ตอน confirmation commit ไม่ใช่วันที่รับ START, STOP หรือวันที่ retry S0
- START ก่อนเที่ยงคืน แต่ confirmed หลังเที่ยงคืน ⇒ อยู่วันใหม่
- confirmed ก่อนเที่ยงคืน แต่ S0/STOP หลังเที่ยงคืน ⇒ ยังอยู่วันเดิม
- เก็บประวัติวันก่อน ไม่ล้างตารางทั้งระบบตอนเปลี่ยนวัน
- UI/log status แสดงยอดวันนี้เป็น 0 ได้แม้ยังไม่มี confirmation แรก และไม่ต้องสร้างบรรทัด item drop : 0 ปลอม
- รันโปรแกรมใหม่วันเดียวกันต้องต่อจากยอดเดิม; ถ้าวันใหม่ให้ day partition ใหม่
- เก็บ daily_date เป็นส่วนหนึ่งของ record ที่ confirmed แล้ว ห้ามย้ายประวัติเมื่อปรับนาฬิกาหรือ retry
- ถ้าเวลาเครื่องผิด ให้มี diagnostic/commissioning check; offline operation ไม่ควรถูกออกแบบให้ต้องเรียก internet time ทุก cycle

### 9.5 Log เป็น projection ไม่ใช่แหล่งจริงของยอด

D: ทำ log รายวันเฉพาะ เช่น `logs/item_drops/2026-10-05.log` ตามรูปแบบข้างต้น และเก็บ operational log แยกสำหรับ cycle_id/Redis/fault

- ไม่ให้ logger เติม timestamp/prefix ซ้ำจนรูปแบบไม่ตรง
- อย่า parse rotating vending.log เพื่อกู้ยอด
- ระบุวิธีทำ daily log ให้ตรงกับ confirmations หลัง crash: เช่น regenerate daily file แบบ atomic จาก ledger เมื่อ startup/repair และ append ระหว่างทำงาน
- stdout/file logging ไม่ได้ atomic กับ SQLite; ห้ามอ้างทุก sink exactly-once จากการตั้ง bool อย่างเดียว
- daily file หลัง recovery ต้องไม่มีบรรทัดซ้ำ/ข้ามจากเหตุการณ์เดียว หาก stdout replay มีเพื่อ diagnostic ต้องแยกให้ผู้ใช้ไม่เข้าใจว่าเป็น drop ใหม่
- ไม่ rewrite log ทั้งประวัติทุก frame หรือทุก cycle โดยไม่จำเป็น

## 10. STOP, failure และ recovery policy

### 10.1 เมื่อได้รับ STOP

| สถานะรอบ | สิ่งที่ต้องทำ |
|---|---|
| confirmed แล้ว | ปิดเป็น confirmed cycle คงยอดและหลักฐาน ไม่ส่ง S0 เพิ่มเพราะ STOP |
| ยังไม่ confirmed แต่ภาพต่อเนื่องปกติ | ปิดด้วย internal outcome `UNCONFIRMED` ไม่มี S0/ไม่มีเพิ่มยอด |
| กล้อง/ฉาก/Redis ทำให้ข้อมูลขาด | ปิดด้วย internal outcome `UNCERTAIN` หรือ fault ที่บอกเหตุผล ไม่กล่าวว่าไม่มีสินค้าตกแน่นอน |
| อยู่ระหว่างเขียนภาพ แต่ยังไม่ commit | invalidate attempt; late completion ห้ามเพิ่มยอด; orphan image แยก cleanup |

ชื่อ outcome ภายในไม่ใช่รหัสที่ส่ง controller ห้ามเพิ่ม E0/E1 เองจนกว่า C01 จะชัด

### 10.2 ไม่มี STOP นานผิดปกติ

- ปิด order-window และ hold-timeout เดิมในเส้นทาง Redis
- สามารถมี `CYCLE_WATCHDOG_SEC` ค่าเริ่มต้นเสนอ 0=ปิด หรือใช้ค่าที่ผู้ดูแลกำหนดหลังทราบ controller
- watchdog ต้อง log/mark blocked/แจ้ง health ไม่สร้าง order ใหม่และไม่ล้าง latch เพื่อเริ่มนับซ้ำ
- ห้ามยก timeout 300 วินาทีของตัวเก่ามาเป็นขอบเขตปิดรอบโดยไม่แจ้งว่าต่างจากข้อกำหนด STOP

### 10.3 Camera gap / Redis disconnect / process restart

- คำสั่ง STOP ต้องประมวลผลได้แม้ไม่มี valid frame; ห้าม `continue` หนี command handling แบบ main เดิม
- camera gap ก่อน confirmed: ค่าเริ่มต้นถือ cycle ไม่ต่อเนื่องและ block การยืนยันที่อาจผิด; ต้องมี policy ที่ชัดหากจะยอม recover ใน cycle เดิม
- Redis disconnect ระหว่าง active: controller อาจส่ง STOP ที่กล้องยังไม่เห็น จึงหยุดสร้าง confirmation ใหม่และบันทึก uncertainty เป็นค่าเริ่มต้น
- confirmed ที่ commit ก่อน fault ไม่ถูกนับซ้ำและไม่ถูกลบ
- reconnect ต้องรักษาลำดับ command, ไม่ replay/drop โดยเดา; unresolved delivery ไม่ถูกส่งข้าม cycle
- restart กู้ ledger แล้วตรวจ unfinished cycles; ห้ามเริ่มด้วย state WAIT_START สะอาดโดยไม่สนใจรอบเก่าที่ค้าง
- แนวทาง recovery เริ่มต้น: บันทึก active เดิมเป็น interrupted และเข้า RECOVERY_BLOCKED จนมีการ reconcile กับ controller/ผู้ดูแล; STOP ตามด้วย START ใหม่ใช้เป็น boundary ได้เฉพาะเมื่อ controller contract รับรองว่าไม่ใช่ stale queue
- ไม่มีวิธีพิสูจน์ stale START/STOP จาก plain string ล้วน ต้องรายงานข้อจำกัดและทำ integration test ไม่ซ่อนความไม่แน่ใจ

### 10.4 Shutdown

- จัด SIGTERM/SIGINT, stop event, try/finally, bounded worker join และ release camera
- คำสั่ง STOP ของตู้ไม่ใช่ process shutdown
- commit state ที่ทำได้ และให้ durable recovery รับช่วงกรณีไฟดับทันที
- อย่า rely บน daemon threads เพื่อรักษาหลักฐาน/ยอด

## 11. แผนแก้รายไฟล์

ชื่อโมดูลใหม่ด้านล่างเป็นข้อเสนอ ใช้จำนวนไฟล์เท่าที่จำเป็น แต่แยก I/O จากกติกา cycle เพื่อทดสอบได้

| ไฟล์/ส่วน | งานที่ต้องทำ | สิ่งที่ต้องระวัง |
|---|---|---|
| main.py | จัด lifecycle กล้องค้าง, เริ่ม Redis adapter, command owner, scene gate, detector, confirmation commit และ shutdown | ไม่ trigger cycle จาก motion; ไม่ข้าม STOP ตอน frame None |
| config.py | เพิ่ม Redis/response/state DB/timezone/source-type/feature flags และ validation | machine_id ต้องมี effective value เดียว; redact URL ที่มี credentials |
| api/redis_controller.py — ใหม่ | รับ CTRL, ส่ง CAMERA, decode, reconnect, timeouts, ordered command queue, delivery states | ไม่เปิด Redis server ใหม่เอง; ไม่ blind retry mutating writes |
| api/order_listener.py | ปิดเส้นทาง WebSocket ใน Redis mode; ลบ/แยก legacy mode ตามความจำเป็น | ห้ามสองแหล่งคำสั่งแย่งสร้าง cycle |
| core/state_machine.py | เปลี่ยนเป็น single-cycle lifecycle และ confirmation latch; internal outcomes แทน qty comparison | ไม่ส่ง network จาก transition โดยเปิด thread กระจาย; inject transport/store |
| core/reset_policy.py | แยก cycle close (STOP) ออกจาก vision reset/fault/watchdog | empty frame/env change ไม่ล้าง active cycle |
| core/frame_source.py | เปิดค้าง, จำแนก USB/file/RTSP, timestamps/freshness, capture isolation เมื่อ backend ค้าง | START/STOP ไม่ open/release; reconnect จริงยังทำได้ |
| core/background.py | ทำ baseline validity/version/age, pre-START snapshot, reference reset ให้ครบ, optional B_empty | clean_bg เดิมหมายถึงไม่มี raw motion ไม่ได้รับรองว่าถาดว่าง |
| core/detect.py | รักษา detector หลัก; อาจ cache kernels และส่ง quality signals | ไม่เพิ่ม neural model, ไม่เปลี่ยน thresholds แบบสุ่ม |
| core/tracker.py | แก้ stability revoke/ghost continuity ที่จำเป็น และกัน track ข้าม cycle | one cycle ไม่ยืนยันหลาย candidate; เก็บ next_id monotonic หรือ namespace ต่อ cycle |
| core/roi.py | รองรับติดตั้งหนึ่ง rect/polygon/quad, validate config, defer update ระหว่าง cycle | ไม่สร้าง Guard ROI; ไม่เงียบแล้ว fallback ครึ่งภาพเมื่อตั้งผิด |
| core/scene_readiness.py — ถ้าจำเป็น | readiness/stability/fault state ภายใน ROI เดียว ใช้ interface ที่ทดสอบได้ | ข้อมูลจริงยังไม่พออ้าง slat classifier สมบูรณ์ |
| utils/state_store.py — ใหม่ | SQLite schema/migration/cycle/unique confirmation/daily query/response ledger | transactions, recovery, schema_version และ persistent path |
| utils/image_saver.py | unique filename, return/exception handling, atomic save, metadata linkage | JPEG temp ต้องมี extension ที่ encoder รองรับ; orphan cleanup ไม่ลบ referenced |
| utils/daily_log.py — ใหม่หรือรวม logger | projection ของ confirmations ตามวันไทยและรูปแบบผู้ใช้ | ไม่ derive count จากข้อความ log หรือ reset RAM counter ตอน restart |
| utils/logger.py | operational logs + timezone-aware formatting/redaction/rotation | ไม่ใช้ last_activity ไปเขียนทับ confirmed_at |
| utils/disk_cleanup.py | แยก acknowledged/pending/orphan image retention และ disk quota | ห้ามลบ DB, daily count ledger, pending evidence หรือหลักฐานของ active cycle |
| api/client.py | cloud เป็น optional telemetry, ROI sync/evidence upload แยกจาก controller result | ไม่ใส่ local UUID ลง server order_id โดยเดา schema |
| api/retry_queue.py | ถ้ายังใช้ cloud ต้องแก้ snapshot overwrite race และ persistence/expiry ตามชนิด event | S0 ห้ามใช้ retry policy เดียวกับรูป/HTTP ที่ส่งช้าได้ |
| ui/overlay.py | แสดง cycle state, local cycle_id สั้น, confirmed latch, daily count, Redis/camera/scene health | เลิกแสดง qty countdown หรือ completed/anomaly จำนวนแบบเดิมใน Redis mode |
| requirements.txt / requirements-pc.txt | เพิ่ม redis client รุ่นที่ทดสอบกับ Python 3.11 และ pin ทั้งสองชุด | SQLite อยู่ใน stdlib; ไม่ต้องเพิ่มแพ็กเกจฐานข้อมูลใหญ่ |
| .envexample | ตัวอย่าง config ใหม่ที่ใช้งาน Redis และ bandwidth ต่ำ | ไม่มี credentials จริง ไม่มี server placeholder ที่ถูกเรียกทั้งที่ cloud ปิด |
| docker-compose.yml / Dockerfile | persistent data/evidence/logs, Redis connectivity, camera source mapping, shutdown | localhost ใน container ไม่ใช่ host Redis; ไม่สร้าง Redis คนละตัวโดยเงียบ |
| HANDOVER.md / ORANGE_PI_DOCKER.md | อัปเดต startup, state diagram, daily logging, config, deploy/rollback, limitations | ข้อความ multi-item/order qty เดิมต้องไม่ขัดกับ mode ใหม่ |
| tests/ — ใหม่ | pure state tests + fake adapter + synthetic frames + isolated Redis integration | ไม่เชื่อม production queues ใน tests |

## 12. การตั้งค่าและความเข้ากันได้กับระบบเดิม

### 12.1 ตารางค่าตั้งที่เสนอ

| ค่า | ค่าเริ่มต้น/แนวทาง | หมายเหตุ |
|---|---|---|
| CONTROL_MODE | redis | ถ้ามี legacy websocket mode ต้อง explicit ไม่ fallback อัตโนมัติ |
| REDIS_HOST | localhost สำหรับ native run | ใน Docker ต้องตั้งให้ตรง Redis ที่ controller ใช้ |
| REDIS_PORT | 6379 | อ่านจาก env |
| REDIS_DB | 0 | ต้องตรง controller |
| REDIS_USERNAME / REDIS_PASSWORD | ว่างถ้าเดิมไม่ใช้ | ห้าม log secrets |
| REDIS_CTRL_KEY | CTRL | default compatible |
| REDIS_RESPONSE_KEY | CAMERA | default compatible |
| REDIS_CONNECT_TIMEOUT_SEC | ค่าจำกัดที่ agent เลือกและทดสอบ | ไม่ปล่อย block capture/STOP |
| REDIS_SOCKET_TIMEOUT_SEC | ค่าจำกัดที่ agent เลือกและทดสอบ | สอดคล้องกับ blocking pop ถ้าใช้ |
| STATE_DB_PATH | data/vending_state.sqlite3 | persistent directory |
| COUNT_TIMEZONE | Asia/Bangkok | explicit ZoneInfo |
| DAILY_LOG_DIR | logs/item_drops | projection เท่านั้น |
| CAMERA_INDEX / CAMERA_SOURCE | ใช้ naming ที่ไม่ซ้ำซ้อนกับเดิม | รองรับ numeric camera/path/RTSP ตาม explicit type |
| CAMERA_SOURCE_TYPE | auto ที่จำแนกได้ถูก หรือ camera/file/stream | RTSP ไม่ใช้ video file pace |
| HEADLESS | 1 บนบอร์ด | PC debug ยังใช้ได้ |
| CYCLE_WATCHDOG_SEC | 0 เป็น default เสนอ | alarm/block ตาม policy ไม่ปิดรอบแทน STOP |
| CLOUD_ENABLED | 0 สำหรับโปรไฟล์ติดตั้งใหม่นี้ | ค่าเดิมที่ผู้ใช้ตั้งต้อง migrate/document ไม่ถูกละเลยเงียบ |
| SEND_INTERVAL | 0 สำหรับโปรไฟล์ bandwidth ต่ำ | เปิดได้เมื่อผู้ดูแลต้องการ |
| REMOTE_ROI_ENABLED | explicit | ปิดแล้วต้องไม่ fetch/push ROI เอง |

ค่าตรวจจับ MOT_THRESH, MIN_AREA, CAPTURE_HOLD_SEC, LANDING_STABLE_FRAMES, CENTROID_STABLE_DIST, GROUP_MODE และ morphology ให้คงค่าปัจจุบันก่อน แล้วจูนเฉพาะที่มี regression/ข้อมูลหน้างานรองรับ

ORDER_WINDOW, DROP_TIMEOUT, CONFIRMED_HOLD_TIMEOUT, CAP_COUNT_TO_ORDER_QTY ไม่มีสิทธิ์ปิด/สร้างรอบใน Redis mode หากเก็บเพื่อ mode เดิมต้อง log ว่าไม่ถูกใช้ใน mode นี้ ไม่ให้ admin คิดว่าปรับแล้วมีผล

### 12.2 config.ini และกล้องแบบเก่า

ผู้ใช้ระบุว่าจะใช้การสั่งการ/ดึงข้อมูลเดิมบางส่วน แต่ยังไม่ได้ยืนยันว่าต้องใช้ config.ini ทั้งชุดหรือ RTSP เดิม จึงให้ทำดังนี้:

1. คง `.env` และ `data/roi_config.json` ของโปรแกรมใหม่เป็น default configuration
2. รองรับกล้องเดิมผ่าน RTSP source ได้โดยไม่ต้องปิด–เปิดตามคำสั่ง ถ้าหน้างานใช้กล้องนั้นจริง
3. ถ้าจำเป็นต้อง import config.ini ให้มี adapter/migration ที่ชัดเจน ระบุ precedence เช่น explicit env > imported ini > default; ห้ามมีค่าซ้ำสองแหล่งแล้วเลือกแบบเงียบ
4. อย่า copy threshold/detect_frame ของเก่ามาเป็นค่าของ detector ใหม่ เพราะหน่วยและความหมายต่างกัน
5. ROI points ของเก่าอิงความละเอียดภาพเดิม ซึ่งยังไม่ทราบ ต้องระบุ source dimensions แล้ว scale เป็น 640×480 อย่างถูกต้อง ไม่เดาว่าพิกัดตรงกัน
6. username/password ใน RTSP ต้อง encode/จัดการอย่างปลอดภัยและ redact ทั้ง config summary, reconnect logs และ exception messages
7. ห้าม hardcode IP/password ของเครื่องจริงลง source หรือ test fixtures

## 13. Cloud, ภาพหลักฐาน และพื้นที่เก็บ

- Redis/local controller path ต้องทำงานได้แม้ CLOUD_API_URL ว่างและไม่มีอินเทอร์เน็ต
- ปิด cloud แล้วไม่เริ่ม register_machine, realtime sender, ROI polling หรือ HTTP retry ที่ไม่จำเป็น
- ถ้าเปิด cloud ภายหลัง ให้ event_id/cycle_id ใช้สำหรับ telemetry แยกจาก merchant order ID และตกลง API schema จริง
- S0 success ไม่ใช่ cloud image ACK และ cloud image ACK ก็ไม่ใช่ controller success ACK
- ห้ามนำ `_delete_image()` ของ retry_queue เดิมมาลบ local evidence ทันทีหลังส่ง S0; Redis ไม่ได้รับไฟล์ภาพ
- ระบุ retention ของ local evidence ที่ acknowledged/ยัง pending ให้ชัด ภาพสำเร็จอาจเก็บตามจำนวนวัน; pending มีนโยบาย quota/fault แทนลบทิ้งเงียบ
- เมื่อ disk ใกล้เต็มให้มี health warning; ถ้าไม่มีที่บันทึกหลักฐาน/DB ให้ block confirmation ตาม policy ไม่รายงานสำเร็จโดยไม่มีหลักฐาน
- daily count history และภาพมี retention คนละนโยบาย การลบภาพเก่าตามนโยบายต้องไม่ทำให้ยอดรายวันลดลง
- การเก็บภาพนานขึ้นต้องวัด I/O/พื้นที่บนบอร์ดจริง ไม่กำหนดตัวเลขความจุจากการเดา

## 14. Main loop ที่ควรได้ในเชิงแนวคิด

Pseudocode นี้อธิบายลำดับ ไม่ใช่โค้ดให้คัดลอกโดยไม่ออกแบบ async/fault ordering:

```python
start_camera_once()
start_redis_workers()
recover_local_ledger_and_cycle_state()

while running:
    # Commands remain serviceable even when camera has no usable frame.
    for command in ordered_commands_available():
        cycle_owner.handle(command)

    for completion in completed_evidence_jobs():
        cycle_owner.commit_only_if_current_cycle_still_open(completion)

    service_health_shutdown_and_response_delivery()
    frame = latest_fresh_frame_or_none()
    if frame is None:
        mark_camera_quality_and_continue_without_counting()
        continue

    scene.observe(frame)  # Continue outside an active cycle too.

    if cycle_owner.can_consider_new_candidate(scene):
        candidate = detector.observe(frame, cycle_owner.baseline)
        if candidate.is_continuously_stable:
            cycle_owner.begin_one_confirmation(candidate, frame.copy())

    render_optional_debug_overlay()

shutdown_workers_and_camera()
```

ข้อควรระวังในการลงโค้ดจริง:

- can_consider_new_candidate ต้อง false นอกรอบ หลัง confirmed, ระหว่าง confirming และเมื่อภาพใช้ไม่ได้
- completed job ต้องตรวจ cycle_id/generation และ STOP อีกครั้งก่อน commit
- service response ไม่ block owner และห้ามส่ง intent ที่ expired หลัง STOP
- capture timestamp/generation และ command ordering ต้องถูกทดสอบ; pseudocode ไม่ได้แก้ queue races ด้วยตัวเอง
- preparation ของ background ระหว่าง WAIT_START ไม่สร้าง cycle/event/drop count

## 15. แผนพัฒนาเป็นลำดับ

### Phase 0 — สำรวจและบันทึก baseline

- อ่าน AGENTS.md ถ้ามีใน repository จริง ตามลำดับ scope
- ตรวจว่า source ตรง snapshot หรือมีงานผู้ใช้ใหม่; ห้าม overwrite งานที่ไม่เกี่ยวข้อง
- บันทึก detection parameters และรวบรวมคลิป single-item ที่มีอยู่
- ทำ characterization tests จาก detector ใหม่และ legacy Redis behavior ที่จะคง
- จด C01–C04 ที่ยังไม่เห็นหลักฐาน แต่ไม่หยุดการทำ pure state/adapter/tests ที่ไม่ขึ้นกับข้อมูลเหล่านั้น

**ผลส่งมอบ:** รายการไฟล์ที่จะแก้, baseline behavior, protocol facts/assumptions

### Phase 1 — Cycle gate และ Redis adapter

- เพิ่ม ordered command source/sink ที่ทดสอบโดย fake ได้
- ปิด WS order path ใน Redis mode
- ทำ START/STOP state transitions, confirmed latch, duplicate command policy
- ทำกล้องเปิดค้างและ STOP serviceable โดยไม่พึ่ง frame success
- ยังไม่เปลี่ยน detector ให้ซับซ้อน

**Gate:** ไม่เกิด confirmation นอกรอบ; หนึ่ง cycle สร้าง logical success ได้หนึ่งครั้ง; START/STOP ไม่ reopen กล้อง

### Phase 2 — หลักฐานและยอดรายวันที่คงทน

- ทำ unique confirmation transaction และ daily sequence
- ทำ image save error/atomicity, daily log projection และ recovery
- แยก intent S0/delivery state; ทดสอบ STOP ระหว่าง commit และ delivery ambiguity

**Gate:** restart ไม่ทำยอดซ้ำ/หาย, rollover ไทยถูกต้อง, ไม่ส่ง S0 เมื่อหลักฐาน commit ไม่สำเร็จ

### Phase 3 — Background boundary และ fault handling

- pre-START baseline, tracker reset/generation, scene quality/staleness
- image gate ช่วง slat/env change และ optional trusted B_empty
- แก้ stability revoke/ghost continuity ที่จำเป็น
- camera/Redis gap, watchdog, safe shutdown และ recovery blocked

**Gate:** removal หลัง confirmed ไม่เพิ่มยอด; candidate เก่าไม่หลุดสู่รอบใหม่; ไม่อ้างนิ่ง=slat ปิด

### Phase 4 — Configuration, integration และ deployment docs

- dependency, Compose networking กับ Redis เดิม, source_type, persistent directories
- อัปเดต overlay/config/HANDOVER/คู่มือบอร์ด
- isolated Redis integration test และ controller replay ตาม protocol จริงเมื่อได้ source
- ทดสอบ USB/RTSP บนบอร์ดตามอุปกรณ์ที่ใช้จริง

**Gate:** controller เดิมเข้ากันได้, ไม่มี hidden cloud dependency, rollback มีคู่มือและรักษา DB/evidence

### Phase 5 — Field validation

- ใช้ SKU/แสง/slat จริงและ timing controller จริง
- วัด false confirmation, miss, latency, recovery, CPU/RAM/อุณหภูมิ/พื้นที่
- ทดสอบระยะยาวและตัดระบบแบบควบคุมในเครื่องทดสอบ
- ทำ field tuning เฉพาะที่มีข้อมูล ไม่ไล่แก้ heuristics โดยไม่มีวิดีโออ้างอิง

**Gate:** ผ่าน acceptance ที่ทีมกำหนดจากข้อมูลจริง ห้ามรายงาน production-ready จาก unit tests อย่างเดียว

## 16. Test matrix ที่ agent ต้องส่งมอบ

ใช้ fake clock/adapter/camera กับ unit tests และใช้ Redis แยกสำหรับ integration tests ห้ามยิง CTRL/CAMERA ของตู้ production เพื่อทดสอบโดยไม่ตั้งใจ

### 16.1 รอบคำสั่งและการยืนยัน

| Test ID | สถานการณ์ | ผลที่ต้องได้ |
|---|---|---|
| T01 | ไม่มี START แต่มี motion และ candidate stable | count=0, ไม่มี S0, กล้องยังอ่านภาพ |
| T02 | START → สินค้าผ่านเกณฑ์ → STOP | confirmation=1, daily +1, logical S0 intent=1 |
| T03 | ยืนยันแล้วมี motion ซ้ำหลายร้อยเฟรม | count และ intent ไม่เพิ่ม |
| T04 | ยืนยันแล้ว slat เปิดและหยิบหมด | count ไม่เพิ่ม/ไม่ลด |
| T05 | ยืนยันแล้วหยิบบางชิ้น/ไม่หยิบ/ขยับของ | ไม่มี confirmation ใหม่ในรอบเดิม |
| T06 | START → STOP โดยไม่พบ candidate | ปิด unconfirmed ไม่มี S0/ไม่มีเพิ่มยอด |
| T07 | STOP ขณะ WAIT_START หรือ STOP ซ้ำ | no-op ต่อ count ไม่มี camera reopen |
| T08 | START ซ้ำขณะ active | ไม่ reset baseline/latch/counter ไม่สร้างรอบซ้อน |
| T09 | START ซ้ำหลัง confirmed แต่ยังไม่ STOP | ไม่เพิ่มยอด/ส่ง S0 ใหม่ |
| T10 | START → STOP → START อย่างรวดเร็ว | cycle IDs แยก, old candidate/completion ใช้กับรอบใหม่ไม่ได้ |
| T11 | candidate สองตัวผ่านพร้อมกัน | หนึ่ง confirmation สูงสุดต่อ cycle |
| T12 | STOP ถึง owner ก่อน evidence commit | late completion ไม่เพิ่มยอด/ไม่ส่ง S0 |
| T13 | confirmation commit ก่อน STOP | ยอดคงอยู่หลัง STOP ไม่ถูก increment ใหม่ |
| T14 | ไม่มี STOP นาน/เกินค่า timeout เดิม | ไม่เปิดรอบใหม่เอง; watchdog ตาม policy เท่านั้น |

### 16.2 ภาพ พื้นหลัง และการคง detector

| Test ID | สถานการณ์ | ผลที่ต้องได้ |
|---|---|---|
| T15 | เปิดกล้องครั้งเดียวแล้วทำหลาย START/STOP | open/release count ไม่เปลี่ยนจาก commands |
| T16 | สินค้าค้างจากรอบก่อนและ baseline ยอมรับแล้ว | ไม่ยืนยันค้างนั้นอีกเพียงเพราะ START ใหม่ |
| T17 | สินค้าเข้าทันทีหลัง START | ใช้ pre-START baseline ไม่กลืนสินค้าเป็นพื้นหลัง |
| T18 | ไม่มี baseline ที่เชื่อถือได้ตอน START | fault/blocked ตาม policy ไม่สร้าง empty reference ปลอม |
| T19 | candidate เคย confirmed-shape แล้วขยับ | ถอนความนิ่ง/reset hold ไม่ capture ทันทีจาก timer เก่า |
| T20 | detection หายช่วงหนึ่งแล้วกลับ | stable continuity ตาม policy ไม่สะสมข้าม gap เงียบ |
| T21 | slat เปิดค้างนานแต่ภาพนิ่ง | ไม่สรุป ready จากความนิ่งเพียงอย่างเดียว |
| T22 | ROI เปลี่ยนระหว่าง cycle | defer/abort ตาม policy และ reference version สอดคล้อง |
| T23 | scene rebaseline แล้ว freeze รอบถัดไป | ไม่ดึง clean_bg/snapshot เก่าที่ invalid กลับมา |
| T24 | RTSP URL และ path วิดีโอ | ใช้ capture/pacing ตามประเภทอย่างถูกต้อง |
| T25 | เฟรมเก่าก่อน START ยังอยู่ใน buffer/queue | ไม่ยืนยันจาก candidate เก่าหรือผิด generation |
| T26 | ภาพเหมือนเดิมแต่ frame stream หาย | ไม่ถือว่า missing frames เป็น stable evidence |
| T27 | คลิป single-item ที่ผู้ใช้ยอมรับเดิม | ไม่ทำ detection แย่ลงโดยไม่มีเหตุผล/รายงานผล |

### 16.3 ยอดรายวัน หลักฐาน และ recovery

| Test ID | สถานการณ์ | ผลที่ต้องได้ |
|---|---|---|
| T28 | confirm 3 cycles ในวันเดียว | log ลงท้าย 1,2,3 ตามลำดับ ไม่มี 0 หรือเลขซ้ำ |
| T29 | restart หลังยอด 3 แล้ว confirm ใหม่ | ได้ 4 ในวันเดิม |
| T30 | วันใหม่ใน Asia/Bangkok | confirmed แรกของวันได้ 1; ประวัติวันเก่ายังอยู่ |
| T31 | START ก่อนเที่ยงคืน confirm หลังเที่ยงคืน | นับวันใหม่ |
| T32 | confirm ก่อนเที่ยงคืน S0/STOP หลังเที่ยงคืน | นับวันเดิม ไม่สร้างยอดวันใหม่ |
| T33 | host เป็น UTC แต่ COUNT_TIMEZONE เป็น Asia/Bangkok | วันที่/log เป็นวันไทยถูกต้อง |
| T34 | duplicate commit request ของ cycle เดิม | unique confirmation กันยอดเพิ่มและ daily sequence ซ้ำ |
| T35 | imwrite=False / disk full / rename fail | ไม่มี confirmed count/S0; fault มีเหตุผล |
| T36 | รูปเสร็จแต่ DB commit fail | ไม่มี count/S0; orphan ไม่ถูกถือเป็น confirmation |
| T37 | DB commit สำเร็จแต่ process ตายก่อน log/S0 | กู้ยอดถูกและจัด delivery/log ตาม recovery policy ไม่ blind replay |
| T38 | daily text log ขาด/ซ้ำหลัง crash | repair projection จาก ledger ได้โดยไม่เปลี่ยนยอดจริง |
| T39 | cleanup เจอรูป pending/active และรูปเก่าที่หมด retention | pending/active ไม่ถูกลบ; ledger ไม่ถูกลบตามภาพ |
| T40 | clock เดินหน้า/ย้อนระหว่าง hold | duration ใช้ monotonic; record ที่ commit ไม่เปลี่ยนวันย้อนหลัง |
| T41 | DB เสียหรือเปิดไม่ได้ | ไม่เงียบแล้วเริ่มนับใหม่จาก 0 |

### 16.4 Redis, fault และ deployment

| Test ID | สถานการณ์ | ผลที่ต้องได้ |
|---|---|---|
| T42 | Redis key ว่าง | ไม่มี error-loop ถี่ กล้องยังทำงาน |
| T43 | Redis อ่านไม่ได้ | health แตกต่างจากคิวว่าง; ไม่ block capture/STOP owner |
| T44 | malformed/unknown command | ไม่เปิดรอบ ไม่ crash ไม่ถูกตีความเป็น START |
| T45 | Redis LPUSH S0 สำเร็จ | มี payload S0 หนึ่งรายการใน test queue; mark ENQUEUED |
| T46 | ยืนยันได้ว่าส่งไม่ได้ก่อน enqueue | retry ตาม current-cycle policy โดยไม่เพิ่ม daily count |
| T47 | Redis รับ S0 แล้วจำลอง response หาย | DELIVERY_UNKNOWN, ไม่ blind retry จนเกิด S0 สองรายการ |
| T48 | STOP/reboot ขณะมี S0 intent ค้าง | ไม่ส่งผลเก่าข้ามรอบใหม่เอง |
| T49 | active process crash หลัง RPOP ก่อน journal | แสดง/ทดสอบข้อจำกัดหรือ reliable intake ที่เลือก ไม่อ้าง command durability เกินจริง |
| T50 | กล้องอ่านไม่ได้ขณะมี STOP | STOP ยังปิด cycle ได้ |
| T51 | cap.read ค้างใน backend | command owner/shutdown ไม่ค้างตาม; watchdog รายงานได้ |
| T52 | camera/Redis reconnect ระหว่าง cycle | ไม่ resume counting จาก stale state โดยเดา |
| T53 | cloud ปิดและเครื่องไม่มี internet | local Redis cycle/evidence/daily count ทำงาน ไม่มี HTTP background requests |
| T54 | app restart ขณะ cycle ค้าง | recovery block/reconcile ตาม policy ไม่รับ stale START เป็นรอบสดเงียบ |
| T55 | SIGTERM ระหว่างทำงาน | เก็บ state เท่าที่ทำได้ ปิด worker/camera มีขอบเขตเวลา |
| T56 | Docker bridge ต่อ Redis ที่ controller ใช้ | เข้าถึง Redis instance/DB/key ที่ถูกต้อง ไม่มี Redis แยกโดยไม่ตั้งใจ |
| T57 | มี consumer อีกตัวพยายามรันบนชุด key เดียว | deployment ป้องกัน/ตรวจพบตามวิธีที่เลือก ห้ามสองตัวนับแข่ง |
| T58 | dependency/env/config ผิด | fail startup ชัดเจน secrets ไม่หลุด log |

T49 และ T54 อาจแสดงข้อจำกัดของ legacy protocol แทนการรับรองครบ หากยังไม่ได้แก้ controller ต้องรายงาน residual risk และเงื่อนไขใช้งาน ไม่ลบ tests เพื่อทำให้ผลดูผ่าน

### 16.5 Field acceptance ที่ต้องทำเมื่อมีอุปกรณ์

- controller START ก่อนจ่าย, STOP หลังรับผล และ STOP เมื่อไม่พบของ: ตรวจเวลาจริงทั้งสาย
- สินค้าจริงหลายสี/ขนาด/พื้นผิว หนึ่งชิ้นต่อรอบ โดยมี ground truth จากผู้ทดสอบ
- slat เปิดสั้น/ยาว เปิดค้าง หยิบทั้งหมด/บางส่วน/ไม่หยิบ และสินค้าค้างก่อน START ถัดไป
- เงา แสงเปิด–ปิด ถาดสั่น และกล้องขยับ
- กล้องหลุด เน็ตภายใน/Redis หลุด อุปกรณ์ storage เต็ม และ power cut ในเครื่องทดลอง
- ทดสอบต่อเนื่อง 48–72 ชั่วโมงเป็นข้อเสนอเริ่มต้น ไม่ใช่มาตรฐานรับรองหรือผลที่ผ่านแล้ว
- วัด false confirmed, missed confirmation, evidence completeness, START→confirmation/S0 latency, STOP response latency, frame age, CPU/RAM/temperature/disk growth
- ห้ามตั้งตัวเลข accuracy/FPS เป้าหมายแทนผู้ใช้โดยไม่มีข้อมูล; รายงานตัวเลขที่วัดพร้อมสภาพแวดล้อม

## 17. Deployment และ rollback

### 17.1 ก่อนเปิดแทนตัวเก่า

1. ทดสอบบน Redis/กล้องจำลองหรือ staging ที่แยกจากเครื่องขายจริง
2. ยืนยัน C01–C04 โดยเฉพาะลำดับ START–S0–STOP และ stale response handling
3. สำรอง source/config/image tag เก่า และสร้าง DB backup ที่ถูกวิธีหากมี schema migration
4. ยืนยันไม่มีรอบขายกำลัง active และจัดการ queue ค้างร่วมกับ controller ก่อน cutover ห้ามลบทิ้งเอง
5. หยุด consumer ตัวเก่าก่อนเริ่มตัวใหม่บน CTRL/CAMERA ชุดเดียวกัน
6. ตรวจ Redis host/DB/key และ camera permissions/source จริง
7. เปิดตัวใหม่ ตรวจ health พร้อม แล้วทำ controlled dispense test ก่อนเปิดใช้งานตามปกติ

### 17.2 Docker และ storage

- mount data/ evidence_images/ logs/ คงเดิมหรือ migrate แบบชัดเจน; DB และไฟล์ WAL/SHM ถ้าใช้ต้องอยู่ใน directory ที่คงอยู่
- ไม่ mount เฉพาะไฟล์ DB โดยละเลย journal/sidecar; ไม่เก็บ DB ไว้ใน image layer
- localhost ภายใน container ชี้ container เอง: กำหนด network ให้ต่อ Redis เดิมบน host/another service/LAN ตามสภาพจริง
- ไม่เพิ่ม service Redis ใหม่ใน Compose แล้วเปลี่ยนปลายทางโดยไม่แจ้ง เพราะจะทำให้แยกจาก controller เดิม
- ไม่เปิด Redis port สู่อินเทอร์เน็ต และไม่เพิ่ม privileged เพียงเพื่อแก้สิทธิ์กล้อง
- restart policy ไม่ใช่ camera watchdog และ healthcheck อย่างเดียวไม่ได้กู้ state/application hang ให้ครบ
- image tag/version/config/schema ต้อง trace ได้; native run และ Docker ใช้ effective config เดียวกัน

### 17.3 Rollback

- เก็บ image/source เก่าที่ใช้งานได้จริงก่อนเปลี่ยน
- หยุดตัวใหม่ก่อนเริ่มตัวเก่าเพื่อไม่ให้แย่ง CTRL
- จัดการ cycle/response ที่ค้างกับ controller ไม่ replay S0 หรือ START แบบเดา
- เก็บ DB/หลักฐาน/ยอดรายวันของตัวใหม่ไว้แม้ rollback โปรแกรม ไม่ลบทิ้งเพื่อให้บูตผ่าน
- ถ้า schema migration ไม่ backward compatible ให้ใช้ backup/migration strategy ที่ระบุ ไม่ downgrade ทับโดยหวังว่าจะอ่านได้

## 18. สิ่งที่อยู่ใน backlog และไม่ควรทำให้งานนี้บาน

รายงาน audit เดิมมี 35 ประเด็น แต่ไม่ใช่ทุกประเด็นต้องแก้ด้วยการรื้อระบบในครั้งนี้

| ประเด็นเดิม | การจัดการในงานนี้ |
|---|---|
| F01 หยิบออกแล้วนับซ้ำ | ปิดด้วย cycle gate + confirmed latch สำหรับรอบที่ยืนยันแล้ว; ข้ามรอบ/slat ก่อนยืนยันต้องมี baseline/readiness tests |
| F02 สองชิ้นพร้อมกันนับหนึ่ง | ไม่พัฒนาเป็น multi-item counter ในงานนี้; ระบุ over-dispense limitation |
| F03/F04 ความนิ่งไม่ถูกถอน/ghost continuity | แก้เฉพาะที่จำเป็นเพื่อรักษาความหมายของการยืนยันสินค้านิ่ง |
| F05 cap qty ซ่อนการจ่ายเกิน | เลิกใช้ qty comparison; ไม่อ้างว่าระบบตรวจจ่ายเกินได้ |
| F06 ของใหญ่ถูกตัดเป็น env | เก็บเป็น known detection risk และทดสอบ SKU; ไม่จูนแก้สุ่มระหว่างเปลี่ยน protocol |
| F07 multi-ROI ใช้ขนาด ROI ผิด | active setup ใช้หนึ่ง ROI; ไม่ขยาย multi-ROI UI ในงานนี้ |
| F08 env change ค้าง | ไม่ให้ค้างแล้วล้าง cycleเอง; quality/fault handling แยกจาก START/STOP |
| F11/F12 คิวหาย/รีสตาร์ตสูญข้อมูล | cycle/confirmation/daily ledger ต้องคงทน; cloud queue ถ้าเปิดใช้งานต้องแก้ race/persistence ด้วย |
| F13/F14/F16 WebSocket order ปัญหา | ปิดเส้นทางนี้ใน Redis mode; ไม่จำเป็นต้องพัฒนาระบบ order WS คู่ขนานใหม่ |
| F15 machine identity ไม่ตรง | effective machine_id เดียวสำหรับ logs/DB/cloud/CLI |
| F18 duplicate/out-of-order events | internal unique IDs และ response state; ระบุ legacy wire correlation limitation |
| F19/F27/F28 กล้องหลุด/watchdog/shutdown | อยู่ใน core integration เพราะ STOP ต้องทำงานแม้กล้องผิดปกติ |
| F21/F22 ภาพไม่ถูกเขียน/cleanup | อยู่ใน core evidence correctness |
| F23–F26 ROI/config/timers | validation, reference version, monotonic ที่กระทบ release นี้ |
| การเพิ่ม AI/ติด sensor/Guard ROI | นอกขอบเขตและขัดข้อจำกัดผู้ใช้ |
| การทำ dashboard ใหม่/เปลี่ยน controller protocol ทั้งหมด | ไม่ทำโดยอัตโนมัติ |
| security/package refresh ที่ไม่เกี่ยวข้องโดยตรง | ตรวจและบันทึก; อัปเดตที่จำเป็นพร้อม regression ไม่ยกเครื่องทุก dependency เพียงเพราะมีรุ่นใหม่ |

## 19. สิ่งที่ต้องตรวจเพิ่มกับ controller โดยไม่หยุดงานส่วนอื่น

| คำถาม | ทำไมสำคัญ | ค่าเริ่มต้นระหว่างพัฒนา |
|---|---|---|
| controller push CTRL ด้วยคำสั่งอะไร และอ่าน CAMERA จากด้านไหน? | ลำดับ queue และความเข้ากันได้ | รักษา RPOP CTRL / LPUSH CAMERA แบบตัวเก่า |
| S0 ทำให้ส่ง STOP หรือสั่งมอเตอร์รอบถัดไปเมื่อไร? | ห้ามส่งผลช้า/ค้างข้ามรอบ | S0 ทันทีหลัง confirmed, รอ STOP ปิดรอบ |
| STOP มาถึงได้ก่อน S0 หรือหลัง timeout อะไร? | outcome/no_drop/cancel semantics | STOP ปิดทันที ไม่มีรหัสล้มเหลวใหม่บน wire |
| E0–E4 มีความหมาย/ถูกใช้จริงอย่างไร? | comment เก่าไม่ใช่ contract ที่พิสูจน์แล้ว | เก็บ failure เป็น internal state/log ก่อน |
| รีสตาร์ตแล้วใครจัดการ stale CTRL/CAMERA? | raw strings ไม่มี correlation | recovery blocked ไม่ flush/replay เอง |
| controller รับ READY/FAULT ได้ไหม และสั่งจ่ายขณะ slat เปิดได้ไหม? | การมองเห็นไม่ครบ/พื้นหลังไม่พร้อม | ไม่เพิ่ม wire message; ใช้ health ภายในและระบุ limitation |
| Redis อยู่ที่ไหน version อะไร persistence/auth ตั้งอย่างไร? | Docker routing, LMOVE/dedup/availability | ไม่สร้าง Redis ใหม่ และไม่สมมติ persistence |
| กล้องจริงคือ USB หรือ RTSP? config.ini ต้องคงหรือไม่? | source type/ROI scaling/credentials | รองรับ config ใหม่ก่อนและทำ adapter เมื่อจำเป็น |
| ต้องเก็บภาพ/ประวัติกี่วัน และ cloud ยังใช้ endpoint อะไร? | retention/bandwidth/API compatibility | local evidence + ledger เป็นหลัก cloud off ใน profile ใหม่ |

ถ้ายังไม่ได้คำตอบ ให้ agent ส่งโค้ดที่ unit/integration fixture ทดสอบได้ พร้อมรายการ field-blockers เฉพาะจุด ห้ามสร้างผลทดสอบ controller จริงปลอมหรืออ้างว่าครบทุก failure mode

## 20. Definition of Done

- [ ] ใช้ detector ใหม่เป็นฐาน และแสดงหลักฐานว่า single-item behavior ที่เกี่ยวข้องยังทำงาน
- [ ] Redis CTRL รับ START/STOP และ CAMERA ส่ง S0 ตาม protocol เดิมที่ตรวจสอบแล้ว
- [ ] กล้องอ่านต่อเนื่อง START/STOP ไม่ reopen/release
- [ ] นอกรอบไม่มี confirmation/drop count/S0
- [ ] หนึ่ง cycle ยืนยันและเพิ่ม daily count ได้ครั้งเดียว; หลังจับได้รอ STOP
- [ ] เลิกพึ่ง qty/ORDER_WINDOW/without-order capture ในโหมด Redis
- [ ] STOP ทำงานได้แม้ frame หาย และ async work ไม่กลับมานับหลัง STOP
- [ ] ภาพหลักฐานมีชื่อไม่ชน ตรวจผลเขียน และเชื่อมกับ cycle/confirmation
- [ ] daily ledger อยู่บน persistent storage; log รูปแบบถูกต้องตามวันไทย
- [ ] restart/เที่ยงคืน/retry ไม่ทำยอดซ้ำหรือเริ่มใหม่ผิดวัน
- [ ] ไม่มีภาพ/คิว pending ถูก cleanup ทิ้งเงียบ
- [ ] มี explicit response delivery state และไม่ blind replay S0 ข้ามรอบ
- [ ] จัดการ duplicate commands, recovery, faults และ shutdown ตาม policy ที่ระบุ
- [ ] ติดตั้งใช้ ROI เดียว ไม่มี AI/sensor/Guard ROI เพิ่ม
- [ ] cloud ปิดแล้ว local operation ทำงานได้ ไม่พึ่งอินเทอร์เน็ต
- [ ] config/source type/Redis networking รองรับวิธีติดตั้งจริง
- [ ] tests ครอบคลุม success, negative paths และ race boundaries ที่เกี่ยวข้อง พร้อมผลรันจริง
- [ ] อัปเดต .envexample, HANDOVER, คู่มือ run/deploy/rollback และ known limitations
- [ ] แยกสิ่งที่ทดสอบจริงออกจาก hardware/controller checks ที่ยังไม่ได้ทำ
- [ ] ไม่มีการลบ source/config/ข้อมูลผู้ใช้ที่ไม่เกี่ยวข้องหรือเปลี่ยน controller protocol โดยไม่ตกลง

## 21. สิ่งที่ code agent ต้องส่งกลับเมื่อทำเสร็จ

1. สรุปพฤติกรรมใหม่และขอบเขตการแก้ โดยบอกว่ามีอะไรต่างจาก detector/flow เดิม
2. รายชื่อไฟล์ที่เปลี่ยน พร้อมเหตุผลและ entrypoints สำคัญ
3. วิธีติดตั้ง/ตั้งค่า Redis, camera, persistent DB, timezone และตัวอย่าง config ที่ไม่มี secrets
4. คำสั่งรัน tests และผลจริง แยก unit, isolated Redis integration, recorded video และ board/controller tests
5. ตัวอย่าง daily log และหลักฐานว่า restart/rollover ไม่ทำยอดผิด
6. state/response/fault policies ที่เลือก โดยเฉพาะ STOP race, delivery unknown และ recovery blocked
7. migration/rollback steps และ schema/config compatibility
8. ข้อจำกัดที่ยังเหลือและคำตอบ C01–C04 ที่ยังต้องการ ไม่อ้างแก้ปัญหาจากภาพทุกกรณีหรือ exactly-once บน raw Redis strings

## 22. Prompt พร้อมนำไปใช้กับ code agent

```text
ให้พัฒนา NewVendingCam-main ตาม handoff ฉบับนี้ โดยใช้ source ใหม่เป็นฐานและใช้ main.py ตัวเก่าเป็น reference ของ Redis protocol เท่านั้น

ข้อกำหนดหลัก:
- กล้องเปิดและอ่านภาพต่อเนื่อง ไม่เปิด/ปิดตาม START/STOP
- รับ START/STOP จาก Redis list CTRL ตามทิศทางเดิม RPOP และส่ง S0 ผ่าน LPUSH CAMERA เมื่อ confirmed
- หนึ่ง START–STOP คือ dispense cycle สำหรับสินค้าหนึ่งชิ้น ไม่ใช้ qty ของ merchant order
- นอกรอบไม่ยืนยัน/ไม่นับ และภายในรอบยืนยันได้ครั้งเดียว เมื่อ confirmed แล้วรอ STOP
- ส่ง S0 หลังหลักฐานและ local confirmation commit ไม่รอ STOP ไม่รอ cloud
- เก็บภาพหลักฐาน unique ต่อ cycle และยอดรายวันแบบ persistent ตาม Asia/Bangkok
- log เช่น 05/10/2026 13:45:12 : item drop : 1 และนับต่อข้าม restart; วันใหม่เริ่ม 1 เมื่อจับชิ้นแรกได้
- ROI ที่ผู้ติดตั้งกำหนดมีหนึ่งบริเวณ ไม่ใช้ Guard ROI, sensor หรือ AI
- รักษา detector ใหม่ที่ผู้ใช้พอใจ ไม่ย้อนไปใช้ count_detection แบบตัวเก่า
- แยก cycle state ออกจาก camera/scene/response state; STOP ยังทำงานได้แม้กล้องอ่านไม่ได้
- ห้าม async completion นับหลัง STOP หรือใช้ candidate ข้าม cycle
- ห้าม blind replay S0 เก่าข้ามรอบ/หลัง restart; raw START/STOP/S0 ไม่มี correlation ID ต้องรายงานข้อจำกัดจริง

อ่าน handoff ทั้งหมดก่อนลงมือ ทำ implementation และ meaningful tests เป็นระยะ ไม่หยุดที่การเสนอแผน ถ้ารายละเอียด controller ยังไม่มี ให้ทำส่วนที่ทดสอบด้วย fixtures ได้ให้เสร็จและระบุ field-blocker ชัดเจน ห้ามเดารหัส E0–E4 หรือแก้ protocol/controller เอง

ส่งกลับโค้ดที่แก้ รายงานไฟล์เปลี่ยน ผล tests จริง วิธีรัน/config/migration/rollback และข้อจำกัดที่ยังเหลือ โดยไม่แตะ production queues หรืออุปกรณ์จริงนอกขอบเขตที่ได้รับอนุญาต
```

## 23. เอกสารอ้างอิงทางเทคนิค

แหล่งเหล่านี้ใช้ตรวจความหมายของ API/การเก็บข้อมูล ไม่ได้เป็นหลักฐานว่า deployment นี้ทดสอบผ่านแล้ว ให้ตรวจเวอร์ชันที่เลือกใช้อีกครั้งระหว่าง implementation

- [Redis RPOP — อ่านและนำรายการออกจาก list](https://redis.io/docs/latest/commands/rpop/)
- [Redis LMOVE — การย้ายรายการระหว่าง list และ reliable queue pattern](https://redis.io/docs/latest/commands/lmove/)
- [Redis Python connection guidance](https://redis.io/docs/latest/develop/clients/redis-py/connect/)
- [SQLite transactions](https://www.sqlite.org/transactional.html)
- [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html)
- [OpenCV background subtraction](https://docs.opencv.org/4.x/d1/dc5/tutorial_background_subtraction.html)

**หมายเหตุสถานะเอกสาร:** handoff นี้กำหนดงานสำหรับ code agent เท่านั้น ยังไม่ได้แก้โปรแกรมใหม่ เชื่อม controller เปลี่ยน Redis/config ของตู้ หรือทดสอบฮาร์ดแวร์ตามเนื้อหาในเอกสาร
