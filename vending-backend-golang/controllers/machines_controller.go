package controllers

import (
	"MotionDetectionForVendingMachine/models"
	"encoding/json"
	"net/http"
	"strconv"
	"time"

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

// HealthCheck (ไม่ต้อง API Key)
func HealthCheck(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":    "ok",
		"timestamp": time.Now().UTC().Format(time.RFC3339),
	})
}

// Get_list ดึงรายการตู้ทั้งหมด (ไม่ส่ง ROIConfig กลับ ประหยัด bandwidth)
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

	var machines_raw []models.Machine
	machines_db.Find(&machines_raw)

	// ซ่อน ROIConfig ใน list
	items := make([]models.MachineListItem, len(machines_raw))
	for i, m := range machines_raw {
		items[i] = models.MachineListItem{
			ID:        m.ID,
			MachineID: m.MachineID,
			Name:      m.Name,
			Location:  m.Location,
			ImagePath: m.ImagePath,
			Notes:     m.Notes,
		}
	}

	c.JSON(http.StatusOK, gin.H{
		"status":      "000",
		"message":     "success",
		"machines":    items,
		"count_total": count_total,
	})
}

// Get_roi ดึง ROI config ของตู้ที่ระบุ
func (self_db machines) Get_roi(c *gin.Context) {

	machine_id := c.Param("machine_id")

	main_db := self_db.main_db.Session(&gorm.Session{})

	var machine models.Machine
	if err := main_db.Where("machine_id = ?", machine_id).First(&machine).Error; err != nil {
		c.JSON(http.StatusNotFound, gin.H{
			"status":  "404",
			"message": "ไม่พบตู้",
		})
		return
	}

	if machine.ROIConfig == "" {
		c.JSON(http.StatusOK, gin.H{"status": "no_config"})
		return
	}

	// Parse เป็น JSON object จริงๆ ก่อนส่ง (ไม่ใช่ raw string ที่อาจ double-encode)
	var roi_json interface{}
	if err := json.Unmarshal([]byte(machine.ROIConfig), &roi_json); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"status":  "500",
			"message": "ROI config ในฐานข้อมูลเสียหาย",
		})
		return
	}

	c.JSON(http.StatusOK, roi_json)
}

// Update_roi อัปเดต ROI config ของตู้ที่ระบุ
func (self_db machines) Update_roi(c *gin.Context) {

	machine_id := c.Param("machine_id")

	roi_data, err := c.GetRawData()
	if err != nil || len(roi_data) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{
			"status":  "400",
			"message": "ข้อมูลไม่ถูกต้อง",
		})
		return
	}

	// ตรวจสอบว่าเป็น valid JSON ก่อนบันทึก
	var check interface{}
	if err := json.Unmarshal(roi_data, &check); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{
			"status":  "400",
			"message": "ข้อมูล ROI ไม่ใช่ JSON ที่ถูกต้อง",
		})
		return
	}

	main_db := self_db.main_db.Session(&gorm.Session{})
	main_db.Model(&models.Machine{}).Where("machine_id = ?", machine_id).Update("roi_config", string(roi_data))

	c.JSON(http.StatusOK, gin.H{
		"status":  "000",
		"message": "อัปเดต ROI เรียบร้อย",
	})
}
