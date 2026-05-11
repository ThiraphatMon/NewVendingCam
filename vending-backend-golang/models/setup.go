package models

import "gorm.io/gorm"

type Machine struct {
	ID           uint   `gorm:"primaryKey"`
	MachineID    string `gorm:"uniqueIndex;not null"`
	Name         string
	Location     string
	ImagePath    string
	Notes        string
	ROIConfig    string        `gorm:"type:text"` // 🌟 เพิ่มบรรทัดนี้: เก็บค่า JSON ของ ROI เป็น Text
	Transactions []Transaction `gorm:"foreignKey:MachineID;references:MachineID"`
}

type Transaction struct {
	ID              uint   `gorm:"primaryKey"`
	TransactionID   string `gorm:"uniqueIndex;not null"`
	MachineID       string `gorm:"index"`
	EventStatus     string
	LandTime        string
	LandedImagePath string
}

func SetupModels(db *gorm.DB) {
	db.AutoMigrate(&Machine{}, &Transaction{})
}
