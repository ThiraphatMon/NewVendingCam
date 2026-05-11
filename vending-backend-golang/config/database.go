package config

import (
	"log"
	"os"
	"time"

	"github.com/joho/godotenv"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

var DB *gorm.DB

func ConnectDatabase() {
	err := godotenv.Load()
	if err != nil {
		log.Println("⚠️ ไม่พบไฟล์ .env (ระบบจะลองใช้ Environment Variable ของเครื่องแทน)")
	}

	dsn := os.Getenv("DB_DSN")
	if dsn == "" {
		log.Fatal("❌ ไม่พบข้อมูล DB_DSN ในไฟล์ .env")
	}

	database, err := gorm.Open(postgres.Open(dsn), &gorm.Config{})
	if err != nil {
		log.Fatal("❌ ไม่สามารถเชื่อมต่อ Database ได้:", err)
	}

	// #14 ตั้งค่า Connection Pool
	sqlDB, err := database.DB()
	if err != nil {
		log.Fatal("❌ ไม่สามารถดึง sql.DB ได้:", err)
	}
	sqlDB.SetMaxOpenConns(10)                  // connection สูงสุดที่เปิดพร้อมกัน
	sqlDB.SetMaxIdleConns(5)                   // connection ที่เก็บไว้ idle
	sqlDB.SetConnMaxLifetime(time.Hour)        // ปิด connection ที่ใช้นานเกิน 1 ชม.
	sqlDB.SetConnMaxIdleTime(time.Minute * 30) // ปิด idle connection หลัง 30 นาที

	DB = database
	log.Println("✅ เชื่อมต่อ Database สำเร็จ!")
}
