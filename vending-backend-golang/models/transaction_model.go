package models

type TransactionDB struct {
	ID              uint   `json:"id" gorm:"primaryKey"`
	TransactionID   string `json:"transaction_id" gorm:"uniqueIndex;not null"`
	MachineID       string `json:"machine_id" gorm:"index"`
	EventStatus     string `json:"event_status" gorm:""`
	LandTime        string `json:"land_time" gorm:""`
	LandedImagePath string `json:"landed_image_path" gorm:""`
}

func (TransactionDB) TableName() string {
	return "transactions"
}

type Transaction struct {
	ID              uint   `json:"id" gorm:"primaryKey"`
	TransactionID   string `json:"transaction_id" gorm:"uniqueIndex;not null"`
	MachineID       string `json:"machine_id" gorm:"index"`
	EventStatus     string `json:"event_status" gorm:""`
	LandTime        string `json:"land_time" gorm:""`
	LandedImagePath string `json:"landed_image_path" gorm:""`
}

func (Transaction) TableName() string {
	return "transactions"
}
