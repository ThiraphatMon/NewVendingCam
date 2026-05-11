package controllers

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"vending-backend/config"
	"vending-backend/models"

	"github.com/gin-gonic/gin"
)

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
			c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "Unauthorized"})
			return
		}
		c.Next()
	}
}

func ReceiveEvent(c *gin.Context) {
	event := strings.TrimSpace(c.PostForm("event"))
	transactionID := strings.TrimSpace(c.PostForm("transaction_id"))
	machineID := strings.TrimSpace(c.PostForm("machine_id"))
	landTime := strings.TrimSpace(c.PostForm("land_time"))

	// #9 Validate required fields
	if event == "" || transactionID == "" || machineID == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "event, transaction_id และ machine_id ต้องไม่ว่าง"})
		return
	}

	var machine models.Machine
	if err := config.DB.Where("machine_id = ?", machineID).FirstOrCreate(&machine, models.Machine{
		MachineID: machineID,
		Name:      "ตู้เพิ่มใหม่ (" + machineID + ")",
		Location:  "ยังไม่ระบุ",
	}).Error; err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "ไม่สามารถตรวจสอบตู้ได้"})
		return
	}

	// #10 Handle duplicate transaction_id
	var existing models.Transaction
	if err := config.DB.Where("transaction_id = ?", transactionID).First(&existing).Error; err == nil {
		// มีอยู่แล้ว → ส่ง 200 กลับเลย ไม่ insert ซ้ำ
		c.JSON(http.StatusOK, gin.H{"status": "duplicate", "message": "transaction_id นี้ถูกบันทึกแล้ว"})
		return
	}

	// #11 บันทึกรูปภาพและสร้าง URL แทน path ดิบ
	var landedImageURL string
	file, err := c.FormFile("landed_image")
	if err == nil {
		filename := fmt.Sprintf("%s_landed%s", transactionID, filepath.Ext(file.Filename))
		savePath := "server_images/" + filename
		if saveErr := c.SaveUploadedFile(file, savePath); saveErr == nil {
			// สร้าง URL ที่ frontend เรียกได้โดยตรง
			landedImageURL = "/images/" + filename
		}
	}

	txn := models.Transaction{
		TransactionID:   transactionID,
		MachineID:       machineID,
		EventStatus:     event,
		LandTime:        landTime,
		LandedImagePath: landedImageURL,
	}
	config.DB.Create(&txn)

	c.JSON(http.StatusOK, gin.H{"status": "success"})
}
