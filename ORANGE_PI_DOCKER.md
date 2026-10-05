# ติดตั้งและทดสอบ Docker บน Orange Pi 5B

สำหรับ Orange Pi 5B ระบบ Ubuntu 22.04 ARM64 — ภาพรวมระบบ / protocol / known limitations ดู `HANDOVER.md`

> ⚠ **ก่อนเปิด container ทุกครั้ง: หยุดโปรแกรมกล้องตัวเก่าก่อน** (ตัวที่ RPOP CTRL)
> สองโปรแกรมอ่าน CTRL พร้อมกันจะแย่งคำสั่ง START/STOP กัน — ผลคือ S0 หายหรือรอบเพี้ยน

## 1. ตรวจระบบและกล้อง

```bash
uname -m                       # ต้องเป็น aarch64
cat /etc/os-release
sudo apt update
sudo apt install -y v4l-utils redis-tools
v4l2-ctl --list-devices
ls -l /dev/video*
```

กล้องที่ใช้กับ Compose ค่าเริ่มต้นคือ `/dev/video0`

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
sudo usermod -aG docker "$USER"     # แล้ว logout/login ใหม่
```

## 3. ตั้งค่าโปรเจกต์

คัดลอกเฉพาะ source (ไม่เอา `.venv` ของ Windows, `.env` ของเครื่องอื่น, `data/*.sqlite3`, `evidence_images/`, `logs/`)
ไฟล์ข้อความใน repo เป็น LF (`.gitattributes`) — ถ้าคัดลอกจาก Windows ด้วยวิธีอื่นที่ไม่ใช่ git ให้ตรวจว่าไม่มี CRLF

```bash
cd ~/MotionDetectionForVendingMachine
cp .envexample .env
nano .env                         # หมวด 1: MACHINE_ID_DEFAULT, CAMERA_INDEX, REDIS_* ให้ตรงกับ controller
mkdir -p evidence_images data logs
ls data/roi_config.json           # ต้องมี ROI ของตู้นี้
```

ค่าที่ต้องคงไว้บนบอร์ด:

```env
HEADLESS=1
CONTROL_MODE=redis
REDIS_HOST=127.0.0.1
CLOUD_ENABLED=0
```

- `docker-compose.yml` ใช้ `network_mode: host` → `127.0.0.1:6379` คือ Redis ของ controller บนบอร์ด
  (ไม่มี Redis service ใน compose — ห้ามเพิ่ม)
- ถ้ากล้องไม่ได้อยู่ที่ `/dev/video0` ต้องแก้ทั้ง `CAMERA_INDEX` และ `devices` ใน `docker-compose.yml`

## 4. หยุดตัวเก่า → build → เปิดระบบ

```bash
# 4.1 หยุดโปรแกรมกล้องตัวเก่า (วิธีขึ้นกับที่ติดตั้งไว้ เช่น systemctl stop <service> / kill process)
# 4.2 ยืนยันว่าไม่มีใคร RPOP CTRL แล้ว (ดู 10 วินาที ไม่ควรเห็น "RPOP" "CTRL")
timeout 10 redis-cli MONITOR | grep -i rpop

docker compose config
docker compose build --pull       # pip ต้องดาวน์โหลดไฟล์ aarch64 ไม่ใช่ x86_64
docker compose up -d
docker compose ps
docker compose logs --tail=100 -f vending-cam
```

ใน log ต้องเห็น: `Active config` (ค่าถูก), `✅ เชื่อม Redis สำเร็จ`, ไม่มี `⚠️ .env: ... ไม่มีผล` ที่ไม่ได้ตั้งใจ
ถ้า log แสดงกล้องหลุดซ้ำ ๆ ให้ `docker compose down` แล้วตรวจ `/dev/video*` อีกครั้ง

## 5. Controlled test (ก่อนเปิดขายจริง)

เปิด 2 terminal: ซ้าย `redis-cli MONITOR`, ขวาส่งคำสั่ง

```bash
# ก) มีของตก → ต้องได้ S0 ครั้งเดียว
redis-cli LPUSH CTRL START        # แล้วปล่อยสินค้า 1 ชิ้น (หรือวางของลงช่อง)
# รอ ~3-4 วินาทีหลังของนิ่ง → MONITOR ต้องเห็น "LPUSH" "CAMERA" "S0" ครั้งเดียว
redis-cli LPUSH CTRL STOP

# ข) ไม่มีของ → ต้องไม่มี S0
redis-cli LPUSH CTRL START
redis-cli LPUSH CTRL STOP

# ตรวจผล
cat logs/item_drops/$(date +%F).log      # ก) ต้องมี 1 บรรทัด "... : item drop : N"
ls evidence_images/confirmed/ | tail
docker compose logs --tail=50 vending-cam | grep -E "เปิดรอบ|ปิดรอบ|ยืนยัน"
```

ล้างคิว CAMERA ที่เกิดจากการทดสอบตามที่ controller ต้องการ (โปรแกรมกล้องไม่ลบคิวเอง)

## 6. อัปเดตและ rollback

```bash
docker tag vending-cam:latest vending-cam:prev   # เก็บ image ที่ใช้อยู่
# อัปเดต source แล้ว
docker compose up -d --build

# มีปัญหา → กลับ image เดิมทันที
docker tag vending-cam:prev vending-cam:latest
docker compose up -d --no-build

# กลับไปโปรแกรมตัวเก่าทั้งหมด
docker compose down               # ต้องหยุดตัวใหม่ก่อนเปิดตัวเก่าเสมอ
```

`data/` (ยอด + ROI), `evidence_images/`, `logs/` อยู่นอก container ไม่หายตอน rebuild / rollback

## 7. คำสั่งดูแลระบบ

```bash
docker compose logs --tail=200 vending-cam   # log ล่าสุด
tail -f logs/vending.log                     # log ไฟล์ (เก็บย้อนหลัง ~25MB)
cat logs/item_drops/$(date +%F).log          # ยอดวันนี้
docker stats vending-cam                     # CPU/RAM
df -h                                        # พื้นที่ eMMC
docker compose down                          # หยุดระบบ
```

**ห้ามลบ** `data/vending_state.sqlite3` — ถ้าโปรแกรมแจ้ง DB เสีย ให้สำรองไฟล์แล้วแจ้งผู้ดูแล
