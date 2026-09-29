# อัพเดทใหม่สำหรับลง Orange Pi:
# ระบุ Debian release ให้แน่นอนและใช้ image ที่มี linux/arm64 รองรับ
FROM python:3.11-slim-bookworm

# ส่ง log ออก docker logs ทันที และไม่สร้าง __pycache__ บน eMMC
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 2. ลง library ที่ OpenCV ต้องการ (ระบบ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 3. กำหนดโฟลเดอร์ทำงานในกล่อง
WORKDIR /app

# 4. copy requirements แล้วลง library Python ก่อน
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 5. copy เฉพาะ source ที่ต้องใช้
# ไม่ใช้ COPY . . เพื่อป้องกัน .env, .venv ของ Windows และไฟล์ทดสอบหลุดเข้า image
COPY main.py config.py ./
COPY api ./api
COPY core ./core
COPY utils ./utils
COPY data ./data

# 6. สร้างโฟลเดอร์ runtime ซึ่ง docker-compose จะ bind mount จาก host
RUN mkdir -p evidence_images data logs

# 7. คำสั่งรันโปรแกรม
CMD ["python", "main.py"]
