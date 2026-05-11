package configs

import (
	"MotionDetectionForVendingMachine/controllers"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

func SetupRouter(db *gorm.DB) *gin.Engine {
	router := gin.Default()

	// ==========================================
	// ตั้งค่า CORS (จำกัด origin เฉพาะที่กำหนด)
	// ==========================================
	corsConfig := cors.DefaultConfig()
	corsConfig.AllowOrigins = []string{
		"http://localhost:5173",
		"http://127.0.0.1:5173",
		"http://localhost:3000",
	}
	corsConfig.AllowMethods = []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
	corsConfig.AllowHeaders = []string{"Origin", "Content-Type", "Accept", "Authorization", "X-API-Key"}
	router.Use(cors.New(corsConfig))
	// ==========================================

	// เปิดให้เข้าถึงโฟลเดอร์รูปภาพได้ผ่าน URL /images
	router.Static("/images", "./server_images")

	// Health check (ไม่ต้อง API Key)
	router.GET("/health", controllers.HealthCheck)

	// --- API Routes (ป้องกันด้วย API Key) ---
	api := router.Group("/api")
	api.Use(controllers.APIKeyMiddleware())
	{
		api.POST("/events", controllers.Event(db).Receive)

		api.GET("/machines", controllers.Machine(db).Get_list)
		api.GET("/machines/:machine_id", controllers.Transaction(db).Get_list)
		api.GET("/machines/:machine_id/roi", controllers.Machine(db).Get_roi)
		api.PUT("/machines/:machine_id/roi", controllers.Machine(db).Update_roi)
		api.GET("/machines/:machine_id/latest-image", controllers.Transaction(db).Get_latest_image)
	}

	return router
}
