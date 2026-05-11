package databases

import (
	"log"

	"MotionDetectionForVendingMachine/models"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
)

func SetupDB(psqlInfo string) {
	db, err := gorm.Open(postgres.Open(psqlInfo), &gorm.Config{})
	if err != nil {
		log.Println(db)
		log.Printf("Error DB connection: %s", err)
		return
	}

	db.AutoMigrate(&models.MachineDB{})
	db.AutoMigrate(&models.TransactionDB{})
}
