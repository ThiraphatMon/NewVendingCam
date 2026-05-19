# 1. เริ่มจาก Python บน Linux เวอร์ชันเล็ก
FROM python:3.11-slim

# 2. ลง library ที่ OpenCV ต้องการ (ระบบ)
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 3. กำหนดโฟลเดอร์ทำงานในกล่อง
WORKDIR /app

# 4. copy requirements แล้วลง library Python ก่อน
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. copy code ทั้งหมดเข้าไป
COPY . .

# 6. สร้างโฟลเดอร์เก็บรูป
RUN mkdir -p evidence_images data

# 7. คำสั่งรันโปรแกรม
CMD ["python", "main.py"]