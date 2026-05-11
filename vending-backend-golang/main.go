package main

import (
	"MotionDetectionForVendingMachine/configs"
	"MotionDetectionForVendingMachine/databases"
	"fmt"
	"log"
	"os"
	"time"

	"github.com/joho/godotenv"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

var main_db *gorm.DB

func main() {
	var err error

	err = godotenv.Load()
	if err != nil {
		log.Fatalf("Error while reading config file")
	}

	// สร้างโฟลเดอร์เก็บรูป
	os.MkdirAll("server_images", os.ModePerm)

	RUNNING_PORT := os.Getenv("RUNNING_PORT")
	DB_HOST := os.Getenv("DB_HOST")
	DB_NAME := os.Getenv("DB_NAME")
	DB_PORT := os.Getenv("DB_PORT")
	DB_USERNAME := os.Getenv("DB_USERNAME")
	DB_PASSWORD := os.Getenv("DB_PASSWORD")

	if RUNNING_PORT == "" {
		RUNNING_PORT = "5000"
	}

	psqlInfo := fmt.Sprintf("host=%s user=%s dbname=%s port=%s password=%s sslmode=disable TimeZone=Asia/Bangkok", DB_HOST, DB_USERNAME, "postgres", DB_PORT, DB_PASSWORD)
	db, err_db := gorm.Open(postgres.Open(psqlInfo), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Info),
	})
	if err_db != nil {
		log.Println(err_db)
		os.Exit(0)
	}

	// create DB ถ้ายังไม่มี
	stmt := fmt.Sprintf("SELECT * FROM pg_database WHERE datname = '%s';", DB_NAME)
	var rec = make(map[string]interface{})
	rs := db.Raw(stmt)
	if rs.Error != nil {
		log.Println(rs.Error)
		os.Exit(0)
	}
	rs.Find(&rec)
	if len(rec) == 0 {
		stmt := fmt.Sprintf("CREATE DATABASE \"%s\";", DB_NAME)
		if rs := db.Exec(stmt); rs.Error != nil {
			log.Println("Error create DB")
			log.Println(rs.Error)
			os.Exit(0)
		}
	}

	psqlInfo = fmt.Sprintf("host=%s user=%s dbname=%s port=%s password=%s sslmode=disable TimeZone=Asia/Bangkok", DB_HOST, DB_USERNAME, DB_NAME, DB_PORT, DB_PASSWORD)
	main_db, err_db = gorm.Open(postgres.Open(psqlInfo), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Info),
	})
	if err_db != nil {
		log.Println(err_db)
		os.Exit(0)
	}

	// #14 ตั้งค่า Connection Pool
	sqlDB, err := main_db.DB()
	if err != nil {
		log.Fatal("ไม่สามารถดึง sql.DB ได้:", err)
	}
	sqlDB.SetMaxOpenConns(10)
	sqlDB.SetMaxIdleConns(5)
	sqlDB.SetConnMaxLifetime(time.Hour)
	sqlDB.SetConnMaxIdleTime(time.Minute * 30)

	databases.SetupDB(psqlInfo)

	router := configs.SetupRouter(main_db)

	log.Println("🚀 Golang API Server running on :" + RUNNING_PORT)
	if err := router.Run("0.0.0.0:" + RUNNING_PORT); err != nil {
		log.Fatalf("failed to run server: %v", err)
	}
}
