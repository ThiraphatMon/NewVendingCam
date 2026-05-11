package models

type MachineDB struct {
	ID        uint   `json:"id" gorm:"primary_key"`
	MachineID string `json:"machine_id" gorm:"uniqueIndex;not null"`
	Name      string `json:"name" gorm:""`
	Location  string `json:"location" gorm:""`
	ImagePath string `json:"image_path" gorm:""`
	Notes     string `json:"note" gorm:""`
	ROIConfig string `json:"roi_config" gorm:"type:text"`
}

func (MachineDB) TableName() string {
	return "machines"
}

type Machine struct {
	ID        uint   `json:"id" gorm:"primary_key"`
	MachineID string `json:"machine_id" gorm:"uniqueIndex;not null"`
	Name      string `json:"name" gorm:""`
	Location  string `json:"location" gorm:""`
	ImagePath string `json:"image_path" gorm:""`
	Notes     string `json:"note" gorm:""`
	ROIConfig string `json:"roi_config" gorm:"type:text"`
}

func (Machine) TableName() string {
	return "machines"
}

type MachineFull struct {
	Machine

	Transactions []Transaction `gorm:"foreignKey:MachineID;references:MachineID"`
}

func (MachineFull) TableName() string {
	return "machines"
}
