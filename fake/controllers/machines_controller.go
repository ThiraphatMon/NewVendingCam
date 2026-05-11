package controllers

import (
	"MotionDetectionForVendingMachine/models"
	"net/http"
	"strconv"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

type machines struct {
	main_db *gorm.DB
}

func Machine(db *gorm.DB) machines {
	i := machines{
		main_db: db,
	}
	return i
}

func (self_db machines) Get_list(c *gin.Context) {

	var input_v map[string]any = map[string]any{
		"keyword": c.DefaultQuery("keyword", ""),
		"limit":   c.DefaultQuery("limit", "50"),
		"offset":  c.DefaultQuery("offset", "0"),
	}

	main_db := self_db.main_db.Session(&gorm.Session{})
	machines_db := main_db.Session(&gorm.Session{}).Table("machines")

	if input_v["keyword"] != "" {
		machines_db = machines_db.Where("machine_id ~* ?",
			input_v["keyword"],
		)
	}

	var count_total int64
	machines_db.Count(&count_total)

	machines_db = machines_db.Order("id asc")
	offset, _ := strconv.Atoi(input_v["offset"].(string))
	limit, _ := strconv.Atoi(input_v["limit"].(string))
	machines_db = machines_db.Offset(offset).Limit(limit)

	var machines []models.Machine
	machines_db.Find(&machines)

	c.JSON(http.StatusOK, gin.H{
		"status":      "000",
		"message":     "success",
		"machines":    machines,
		"count_total": count_total,
	})
}
