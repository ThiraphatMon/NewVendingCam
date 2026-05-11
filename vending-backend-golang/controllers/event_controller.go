package controllers

import (
	"MotionDetectionForVendingMachine/models"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type events struct {
	main_db *gorm.DB
}

func Event(db *gorm.DB) events {
	e := events{
		main_db: db,
	}
	return e
}

// APIKeyMiddleware ตรวจสอบ X-API-Key header
// ถ้า API_KEY env ว่างเปล่า → ข้ามการตรวจสอบ (ช่วง development)
func APIKeyMiddleware() gin.HandlerFunc {
	secret := os.Getenv("API_KEY")
	return func(c *gin.Context) {
		if secret == "" {
			c.Next()
			return
		}
		key := c.GetHeader("X-API-Key")
		if key != secret {
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{
				"status":  "401",
				"message": "Unauthorized",
			})
			return
		}
		c.Next()
	}
}

// Receive รับ event และรูปภาพจากตู้ vending
func (self_db events) Receive(c *gin.Context) {

	event := strings.TrimSpace(c.PostForm("event"))
	transaction_id := strings.TrimSpace(c.PostForm("transaction_id"))
	machine_id := strings.TrimSpace(c.PostForm("machine_id"))
	land_time := strings.TrimSpace(c.PostForm("land_time"))

	// Validate required fields
	if event == "" || transaction_id == "" || machine_id == "" {
		c.JSON(http.StatusBadRequest, gin.H{
			"status":  "400",
			"message": "event, transaction_id และ machine_id ต้องไม่ว่าง",
		})
		return
	}

	main_db := self_db.main_db.Session(&gorm.Session{})

	// หาตู้หรือสร้างใหม่ถ้ายังไม่มี
	var machine models.Machine
	if err := main_db.Where("machine_id = ?", machine_id).FirstOrCreate(&machine, models.Machine{
		MachineID: machine_id,
		Name:      "ตู้เพิ่มใหม่ (" + machine_id + ")",
		Location:  "ยังไม่ระบุ",
	}).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"status":  "500",
			"message": "ไม่สามารถตรวจสอบตู้ได้",
		})
		return
	}

	// Handle duplicate transaction_id
	var existing models.Transaction
	if err := main_db.Where("transaction_id = ?", transaction_id).First(&existing).Error; err == nil {
		// มีอยู่แล้ว → ส่ง 200 กลับเลย ไม่ insert ซ้ำ
		c.JSON(http.StatusOK, gin.H{
			"status":  "duplicate",
			"message": "transaction_id นี้ถูกบันทึกแล้ว",
		})
		return
	}

	// บันทึกรูปภาพ
	var landed_image_path string
	file, err := c.FormFile("landed_image")
	if err == nil {
		filename := fmt.Sprintf("%s_landed%s", transaction_id, filepath.Ext(file.Filename))
		save_path := "server_images/" + filename
		if save_err := c.SaveUploadedFile(file, save_path); save_err == nil {
			landed_image_path = save_path
		}
	}

	txn := models.Transaction{
		TransactionID:   transaction_id,
		MachineID:       machine_id,
		EventStatus:     event,
		LandTime:        land_time,
		LandedImagePath: landed_image_path,
	}
	main_db.Create(&txn)

	c.JSON(http.StatusOK, gin.H{
		"status":  "000",
		"message": "success",
	})
}
