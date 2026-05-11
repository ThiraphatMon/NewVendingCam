# 🛒 Vending Machine Motion Detection System (Full-Stack IoT)

ระบบตรวจจับสินค้าตกอัจฉริยะสำหรับตู้จำหน่ายสินค้าอัตโนมัติ โดยใช้เทคโนโลยี Computer Vision ประมวลผลที่หน้าตู้ (Edge) เชื่อมต่อกับระบบจัดการหลังบ้านผ่าน Cloud API เพื่อความแม่นยำและการตรวจสอบย้อนหลังที่สมบูรณ์แบบ

## 🏗️ สถาปัตยกรรมระบบ (System Architecture)

ระบบถูกออกแบบด้วยสถาปัตยกรรม **Edge-to-Cloud** เพื่อประสิทธิภาพสูงสุด:

1.  **📷 Edge Node (Python AI):** ทำหน้าที่เป็น "ดวงตาและสมองส่วนหน้า" ประมวลผลภาพจากกล้องในตู้ ใช้ PyTorch และ OpenCV ตรวจจับการเคลื่อนไหวและติดตามสินค้า
2.  **☁️ Backend Server (Golang API):** ทำหน้าที่เป็น "ศูนย์กลางข้อมูล" รับข้อมูลเหตุการณ์และรูปภาพหลักฐานจากทุกตู้ บันทึกลง PostgreSQL และบริหารจัดการการตั้งค่าตู้
3.  **💻 Web Dashboard (Vue.js Frontend):** ทำหน้าที่เป็น "หน้าจอควบคุม" ให้ผู้ดูแลระบบดูประวัติการขาย (Transactions) ตรวจสอบรูปหลักฐาน และตั้งค่ากรอบตรวจจับ (ROI) ระยะไกล

---

## ✨ ฟีเจอร์สำคัญ (Key Features)

* 🧠 **State Machine Intelligence:** ระบบจัดการสถานะอัจฉริยะ (IDLE -> DROP_DETECTED -> EVIDENCE_CAPTURED) เพื่อป้องกันการถ่ายรูปซ้ำซ้อน
* 🎯 **Remote Multi-Polygon ROI:** สามารถวาดกรอบพื้นที่ตรวจจับ (ROI) ได้หลายรูปแบบผ่านหน้าเว็บ และตู้จะดาวน์โหลดการตั้งค่าไปใช้โดยอัตโนมัติ (Polling System)
* 🛡️ **Anti-Shake Protection:** ระบบป้องกันการสั่นสะเทือนของตู้หรือแสงเปลี่ยนกะทันหัน โดยจะรีเซ็ตพื้นหลังอัตโนมัติเมื่อพบการขยับของภาพเกิน 30% (Global Motion Rejection)
* 🧹 **Auto-Storage Management:** ระบบ Disk Cleanup ลบรูปภาพในเครื่องตู้อัตโนมัติเมื่อครบกำหนด เพื่อป้องกันหน่วยความจำ (SD Card) เต็ม
* 📋 **System Logging:** บันทึกประวัติการทำงานทุกขั้นตอนลงไฟล์ `logs/vending.log` เพื่อการซ่อมบำรุงที่รวดเร็ว

---

## 🛠️ เทคโนโลยีที่ใช้ (Tech Stack)

* **AI/Vision:** Python 3, PyTorch (Tensor math), OpenCV, NumPy
* **Backend:** Golang, Gin Framework, GORM, PostgreSQL
* **Frontend:** Vue 3 (Vite), Axios, Tailwind CSS
* **DevOps:** Systemd (Auto-run), Python Virtual Environment

---

## 🚀 ขั้นตอนการติดตั้งและใช้งาน (Setup Guide)

### 1. ส่วนหลังบ้าน (vending-backend-golang)
1.  ติดตั้ง PostgreSQL และสร้างฐานข้อมูลชื่อ `vending_db`
2.  ไปที่โฟลเดอร์ `vending-backend-golang/` สร้างไฟล์ `.env`:
    ```env
    DB_DSN="host=localhost user=postgres password=YOUR_PASSWORD dbname=vending_db port=5432 sslmode=disable"
    PORT=5000
    ```
3.  รันเซิร์ฟเวอร์: `go mod tidy` และ `go run main.go`

### 2. ส่วนหน้าจอแอดมิน (Front-end web)
1.  ไปที่โฟลเดอร์ `Front-end web/Vending Machine Web/`
2.  ติดตั้งและรัน:
    ```bash
    npm install
    npm run dev
    ```
3.  เข้าใช้งานผ่านบราวเซอร์ที่ `http://localhost:5173`

### 3. ส่วนระบบกล้อง AI (vending-camera-python)
1.  ไปที่โฟลเดอร์ `vending-camera-python/`
2.  เตรียมสภาพแวดล้อม:
    ```bash
    python -m venv .venv
    .\.venv\Scripts\activate  # Windows
    pip install -r requirements.txt
    ```
3.  ตั้งค่าไฟล์ `.env`:
    ```env
    CLOUD_API_URL=http://localhost:5000/api/events
    MACHINE_ID_DEFAULT=VENDING_01
    ```
4.  เริ่มการตรวจจับ: `python main.py`

---

## 📁 โครงสร้างโฟลเดอร์ (Project Structure)

```text
ProjectMotionDetection/
├── vending-camera-python/         # ฝั่งตู้ Vending (Edge)
│   ├── core/                      # หัวใจ AI (ROI, Tracker, State Machine)
│   ├── api/                       # การสื่อสารกับ Cloud และ Remote Config
│   ├── utils/                     # ระบบ Cleanup, Logger, Image Saver
│   ├── data/                      # ที่เก็บไฟล์ค่าตั้งค่า (roi_config.json)
│   └── logs/                      # ไฟล์บันทึก Error และสถานะเครื่อง
│
├── vending-backend-golang/        # ฝั่งเซิร์ฟเวอร์ (Cloud)
│   ├── controllers/               # API Endpoints (รับรูป/ดึงข้อมูล)
│   ├── models/                    # นิยามตาราง Database
│   └── server_images/             # แหล่งรวมรูปภาพหลักฐานจากทุกตู้
│
└── Front-end web/                 # ฝั่งจัดการ (Dashboard)
    └── Vending Machine Web/       # ระบบ Vue.js Frontend