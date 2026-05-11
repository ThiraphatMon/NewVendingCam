package main

import (
	"os"
	"vending-backend/config"
	"vending-backend/controllers"
	"vending-backend/models"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func main() {
	// สร้างโฟลเดอร์เก็บรูป
	os.MkdirAll("server_images", os.ModePerm)

	// เชื่อม DB
	config.ConnectDatabase()
	models.SetupModels(config.DB)

	r := gin.Default()

	// ==========================================
	// ตั้งค่า CORS
	// ==========================================
	corsConfig := cors.DefaultConfig()
	corsConfig.AllowOrigins = []string{
		"http://localhost:5173",
		"http://127.0.0.1:5173",
		"http://localhost:3000",
	}
	corsConfig.AllowMethods = []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
	corsConfig.AllowHeaders = []string{"Origin", "Content-Type", "Accept", "Authorization", "X-API-Key"}
	r.Use(cors.New(corsConfig))
	// ==========================================

	// เปิดให้เข้าถึงโฟลเดอร์รูปภาพได้ผ่าน URL /images
	r.Static("/images", "./server_images")

	// #16 Health check (ไม่ต้อง API Key)
	r.GET("/health", controllers.HealthCheck)

	// --- API Routes (ป้องกันด้วย API Key) ---
	api := r.Group("/api")
	api.Use(controllers.APIKeyMiddleware())
	{
		api.POST("/events", controllers.ReceiveEvent)
		api.GET("/machines", controllers.GetAllMachines)
		api.GET("/machines/:machine_id", controllers.GetMachineWithTransactions)
		api.GET("/machines/:machine_id/roi", controllers.GetMachineROI)
		api.PUT("/machines/:machine_id/roi", controllers.UpdateMachineROI)

		api.GET("/machines/:machine_id/latest-image", controllers.GetLatestMachineImage)
	}

	// ดึง Port จาก .env ถ้าไม่มีให้ใช้ 5000
	port := os.Getenv("PORT")
	if port == "" {
		port = "5000"
	}

	println("🚀 Golang API Server running on :" + port)
	r.Run(":" + port)
}
