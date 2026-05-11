package models

type TransactionDB struct {
	ID              uint   `json:"id" gorm:"primaryKey"`
	TransactionID   string `json:"transaction_id" gorm:"uniqueIndex;not null"`
	EventStatus     string `json:"event_status" gorm:""`
	LandTime        string `json:"land_time" gorm:""`
	LandedImagePath string `json:"landed_image_path" gorm:""`

	MachineID string  `json:"machine_id" gorm:"index"`
	Machin    Machine `json:"machine" gorm:"foreignKey:machine_id;references:Id;constraint:OnUpdate:CASCADE,OnDelete:CASCADE;"`
}

func (TransactionDB) TableName() string {
	return "transactions"
}

type Transaction struct {
	ID              uint   `json:"id" gorm:"primaryKey"`
	TransactionID   string `json:"transaction_id" gorm:"uniqueIndex;not null"`
	EventStatus     string `json:"event_status" gorm:""`
	LandTime        string `json:"land_time" gorm:""`
	LandedImagePath string `json:"landed_image_path" gorm:""`

	MachineID string `json:"machine_id" gorm:"index"`
}

func (Transaction) TableName() string {
	return "transactions"
}
