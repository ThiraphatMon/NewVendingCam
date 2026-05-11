package models

type MachineDB struct {
	ID        uint   `json:"id" gorm:"primary_key"`
	MachineID string `json:"machine_id" gorm:"uniqueIndex;not null"`
	Name      string `json:"name" gorm:""`
	Location  string `json:"location" gorm:""`
	ImagePath string `json:"image_path" gorm:""`
	Notes     string `json:"notes" gorm:""`
	ROIConfig string `json:"roi_config" gorm:"type:text"`
}

func (MachineDB) TableName() string {
	return "machines"
}

type Machine struct {
	ID           uint          `json:"id" gorm:"primary_key"`
	MachineID    string        `json:"machine_id" gorm:"uniqueIndex;not null"`
	Name         string        `json:"name" gorm:""`
	Location     string        `json:"location" gorm:""`
	ImagePath    string        `json:"image_path" gorm:""`
	Notes        string        `json:"notes" gorm:""`
	ROIConfig    string        `json:"roi_config" gorm:"type:text"`
	Transactions []Transaction `json:"transactions" gorm:"foreignKey:MachineID;references:MachineID"`
}

func (Machine) TableName() string {
	return "machines"
}

// MachineListItem ใช้ใน Get_list เพื่อซ่อน ROIConfig (ข้อมูลใหญ่ ไม่จำเป็นใน list)
type MachineListItem struct {
	ID        uint   `json:"id"`
	MachineID string `json:"machine_id"`
	Name      string `json:"name"`
	Location  string `json:"location"`
	ImagePath string `json:"image_path"`
	Notes     string `json:"notes"`
}
