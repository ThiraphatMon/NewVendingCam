# ติดตั้งและทดสอบ Docker บน Orange Pi 5B

เอกสารนี้อัพเดทใหม่สำหรับนำโปรเจกต์ไปทดสอบบน Orange Pi 5B ระบบ Ubuntu 22.04 ARM64

## 1. ตรวจระบบและกล้อง

```bash
uname -m
cat /etc/os-release
sudo apt update
sudo apt install -y v4l-utils
v4l2-ctl --list-devices
ls -l /dev/video*
```

`uname -m` ควรแสดง `aarch64` และกล้องที่ใช้กับ Compose ค่าเริ่มต้นต้องเป็น `/dev/video0`

## 2. ติดตั้ง Docker Engine และ Compose plugin

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

เพิ่ม user ปัจจุบันเข้า Docker group แล้ว logout/login ใหม่:

```bash
sudo usermod -aG docker "$USER"
```

## 3. ตั้งค่าโปรเจกต์

อย่าคัดลอก `.venv` จาก Windows มาที่บอร์ด ให้คัดลอกเฉพาะ source ของโปรเจกต์ จากนั้น:

```bash
cd ~/MotionDetectionForVendingMachine
cp .envexample .env
nano .env
mkdir -p evidence_images data logs
```

แก้ `CLOUD_API_URL`, `WS_URL`, `MACHINE_ID_DEFAULT` และ `API_KEY` ให้ตรงกับระบบจริง โดยคง:

```env
HEADLESS=1
CAMERA_INDEX=0
```

ถ้ากล้องไม่ได้อยู่ที่ `/dev/video0` ต้องแก้ทั้ง `CAMERA_INDEX` และ `devices` ใน `docker-compose.yml`

## 4. ตรวจ config, build และเปิดระบบ

```bash
docker compose config
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 -f vending-cam
```

ระหว่าง build ให้ตรวจว่า pip ดาวน์โหลดไฟล์ที่มีคำว่า `aarch64` ไม่ใช่ `x86_64`

ถ้า log แสดง `กล้องหลุด กำลัง reconnect...` ซ้ำ ให้หยุดระบบและตรวจ `/dev/video*` อีกครั้ง:

```bash
docker compose down
v4l2-ctl --list-devices
```

## 5. คำสั่งดูแลระบบ

```bash
# เปิดหรือสร้างใหม่หลังแก้ source
docker compose up -d --build

# ดู log ล่าสุด
docker compose logs --tail=200 vending-cam

# ดู CPU/RAM
docker stats vending-cam

# ดูพื้นที่ eMMC
df -h

# หยุดระบบ
docker compose down
```
