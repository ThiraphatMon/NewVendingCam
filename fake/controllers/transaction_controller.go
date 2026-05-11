package controllers

import (
	"MotionDetectionForVendingMachine/models"
	"net/http"
	"strconv"

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

func (self_db transactions) Get_list(c *gin.Context) {

	machine_id := c.Param("machine_id")

	var input_v map[string]any = map[string]any{
		"keyword": c.DefaultQuery("keyword", ""),
		"limit":   c.DefaultQuery("limit", "50"),
		"offset":  c.DefaultQuery("offset", "0"),
	}

	main_db := self_db.main_db.Session(&gorm.Session{})
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

	var transactions []models.Transaction
	transaction_db.Find(&transactions)

	c.JSON(http.StatusOK, gin.H{
		"status":       "000",
		"message":      "success",
		"transactions": transactions,
		"count_total":  count_total,
	})
}
