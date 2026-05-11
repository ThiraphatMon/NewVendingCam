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

/* ---------------------------- GET list machine ---------------------------- */

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

/* ----------------------------- PATCH api/machine/:machine_id ----------------------------- */
func (self_db machines) Update(c *gin.Context) {

	main_db := self_db.main_db.Session(&gorm.Session{})

	type struct_input_v struct {
		Name      string `json:"name" gorm:""`
		Location  string `json:"location" gorm:""`
		ImagePath string `json:"image_path" gorm:""`
		Notes     string `json:"note" gorm:""`
	}
	input_v := struct_input_v{}
	err := c.ShouldBind(&input_v)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{
			"status":  "001",
			"message": err.Error(),
		})
		return
	}

	var machine models.Machine
	err = main_db.Where("id = ?", c.Param("id")).First(&machine).Error
	if err != nil {
		c.JSON(http.StatusOK, gin.H{
			"status":  "002",
			"message": "machine not found",
		})
		return
	}

	machine.Name = input_v.Name
	machine.Location = input_v.Location
	machine.ImagePath = input_v.ImagePath
	machine.Notes = input_v.Notes

	err = main_db.Model(&machine).Updates(&machine).Error
	if err != nil {
		c.JSON(http.StatusOK, gin.H{
			"status":  "001",
			"message": err.Error(),
		})
		return
	}

	c.JSON(http.StatusOK, gin.H{
		"status":  "000",
		"message": "success",
		"machine": machine,
	})
}
