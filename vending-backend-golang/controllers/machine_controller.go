package controllers

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"
	"vending-backend/config"
	"vending-backend/models"

	"github.com/gin-gonic/gin"
)

// MachineListItem ใช้ใน GetAllMachines เพื่อซ่อน ROIConfig (ข้อมูลใหญ่ ไม่จำเป็นใน list)
type MachineListItem struct {
	ID        uint   `json:"id"`
	MachineID string `json:"machine_id"`
	Name      string `json:"name"`
	Location  string `json:"location"`
	ImagePath string `json:"image_path"`
	Notes     string `json:"notes"`
}

// #16 Health check endpoint
func HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":    "ok",
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	})
}

// #12 GetAllMachines ไม่ส่ง ROIConfig กลับไปใน list (ประหยัด bandwidth)
func GetAllMachines(c *gin.Context) {
	var machines []models.Machine
	config.DB.Find(&machines)

	items := make([]MachineListItem, len(machines))
	for i, m := range machines {
		items[i] = MachineListItem{
			ID:        m.ID,
			MachineID: m.MachineID,
			Name:      m.Name,
			Location:  m.Location,
			ImagePath: m.ImagePath,
			Notes:     m.Notes,
		}
	}
	c.JSON(http.StatusOK, items)
}

func GetMachineWithTransactions(c *gin.Context) {
	machineID := c.Param("machine_id")
	var machine models.Machine

	if err := config.DB.Preload("Transactions").Where("machine_id = ?", machineID).First(&machine).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "ไม่พบข้อมูลตู้"})
		return
	}
	c.JSON(http.StatusOK, machine)
}

// GetMachineROI คืน ROI config เป็น JSON object จริง (ไม่ใช่ string)
func GetMachineROI(c *gin.Context) {
	machineID := c.Param("machine_id")
	var machine models.Machine

	if err := config.DB.Where("machine_id = ?", machineID).First(&machine).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "ไม่พบตู้"})
		return
	}

	if machine.ROIConfig == "" {
		c.JSON(http.StatusOK, gin.H{"status": "no_config"})
		return
	}

	// Parse เป็น JSON object จริงๆ ก่อนส่ง (ไม่ใช่ raw string ที่อาจ double-encode)
	var roiJSON interface{}
	if err := json.Unmarshal([]byte(machine.ROIConfig), &roiJSON); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "ROI config ในฐานข้อมูลเสียหาย"})
		return
	}
	c.JSON(http.StatusOK, roiJSON)
}

func UpdateMachineROI(c *gin.Context) {
	machineID := c.Param("machine_id")

	roiData, err := c.GetRawData()
	if err != nil || len(roiData) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "ข้อมูลไม่ถูกต้อง"})
		return
	}

	// ตรวจสอบว่าเป็น valid JSON ก่อนบันทึก
	var check interface{}
	if err := json.Unmarshal(roiData, &check); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "ข้อมูล ROI ไม่ใช่ JSON ที่ถูกต้อง"})
		return
	}

	config.DB.Model(&models.Machine{}).Where("machine_id = ?", machineID).Update("roi_config", string(roiData))

	c.JSON(http.StatusOK, gin.H{"status": "success", "message": "อัปเดต ROI เรียบร้อย"})
}

/* ------------------ เอารูปสุดท้ายมาใช้หน้า configure roi ------------------ */

func GetLatestMachineImage(c *gin.Context) {
	machineID := c.Param("machine_id")

	var transaction models.Transaction

	err := config.DB.
		Where("machine_id = ?", machineID).
		Where("landed_image_path IS NOT NULL").
		Where("landed_image_path <> ?", "").
		Order("id DESC").
		First(&transaction).Error

	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"error": "ไม่พบรูป landed ล่าสุดของตู้นี้",
		})
		return
	}

	imagePath := transaction.LandedImagePath

	// DB เก็บเป็น server_images/xxx.jpg
	// แต่ Gin static เปิดไว้ที่ /images -> ./server_images
	imageURL := strings.Replace(imagePath, "server_images/", "/images/", 1)

	c.JSON(http.StatusOK, gin.H{
		"transaction_id": transaction.TransactionID,
		"machine_id":     transaction.MachineID,
		"land_time":      transaction.LandTime,
		"image_path":     transaction.LandedImagePath,
		"image_url":      imageURL,
	})
}
