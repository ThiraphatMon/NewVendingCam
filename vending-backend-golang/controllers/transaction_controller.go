package controllers

import (
	"MotionDetectionForVendingMachine/models"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type transactions struct {
	main_db *gorm.DB
}

func Transaction(db *gorm.DB) transactions {
	u := transactions{
		main_db: db,
	}
	return u
}

// Get_list ดึง transactions ของตู้ที่ระบุ (พร้อม Preload machine)
func (self_db transactions) Get_list(c *gin.Context) {

	machine_id := c.Param("machine_id")

	var input_v map[string]any = map[string]any{
		"keyword": c.DefaultQuery("keyword", ""),
		"limit":   c.DefaultQuery("limit", "50"),
		"offset":  c.DefaultQuery("offset", "0"),
	}

	main_db := self_db.main_db.Session(&gorm.Session{})

	var machine models.Machine
	if err := main_db.Preload("Transactions").Where("machine_id = ?", machine_id).First(&machine).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"status":  "404",
			"message": "ไม่พบข้อมูลตู้",
		})
		return
	}

	transaction_db := main_db.Session(&gorm.Session{}).Table("transactions")

	if machine_id != "" {
		transaction_db = transaction_db.Where("machine_id = ?", machine_id)
	}

	if input_v["keyword"] != "" {
		transaction_db = transaction_db.Where("transaction_id ~* ?",
			input_v["keyword"])
	}

	var count_total int64
	transaction_db.Count(&count_total)

	transaction_db = transaction_db.Order("transaction_id desc")
	offset, _ := strconv.Atoi(input_v["offset"].(string))
	limit, _ := strconv.Atoi(input_v["limit"].(string))
	transaction_db = transaction_db.Offset(offset).Limit(limit)

	var transactions_list []models.Transaction
	transaction_db.Find(&transactions_list)

	c.JSON(http.StatusOK, gin.H{
		"status":       "000",
		"message":      "success",
		"machine":      machine,
		"transactions": transactions_list,
		"count_total":  count_total,
	})
}

// Get_latest_image ดึงรูป landed ล่าสุดของตู้ที่ระบุ
func (self_db transactions) Get_latest_image(c *gin.Context) {

	machine_id := c.Param("machine_id")

	main_db := self_db.main_db.Session(&gorm.Session{})

	var transaction models.Transaction
	err := main_db.
		Where("machine_id = ?", machine_id).
		Where("landed_image_path IS NOT NULL").
		Where("landed_image_path <> ?", "").
		Order("id DESC").
		First(&transaction).Error

	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"status":  "404",
			"message": "ไม่พบรูป landed ล่าสุดของตู้นี้",
		})
		return
	}

	// DB เก็บเป็น server_images/xxx.jpg
	// แต่ Gin static เปิดไว้ที่ /images -> ./server_images
	image_url := strings.Replace(transaction.LandedImagePath, "server_images/", "/images/", 1)

	c.JSON(http.StatusOK, gin.H{
		"status":         "000",
		"message":        "success",
		"transaction_id": transaction.TransactionID,
		"machine_id":     transaction.MachineID,
		"land_time":      transaction.LandTime,
		"image_path":     transaction.LandedImagePath,
		"image_url":      image_url,
	})
}
