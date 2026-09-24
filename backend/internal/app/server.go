package app

import (
	"fmt"
	"net/http"
	"time"

	"github.com/abdelrahmanAhmed1x/core/httpx"
	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/abdelrahmanAhmed1x/core/middleware"
	"github.com/gin-gonic/gin"
)

func Server(cfg *Config, log logger.Logger) *gin.Engine {
	r := gin.New()
	r.Use(gin.CustomRecovery(func(c *gin.Context, recovered any) {
		log.Error(c.Request.Context(), "request panic", "error", fmt.Sprint(recovered))
		c.AbortWithStatus(http.StatusInternalServerError)
	}))
	r.Use(logger.Middleware(log))
	r.Use(middleware.SecurityHeaders())
	r.Use(middleware.MaxBodySize(10 << 20))
	r.Use(middleware.Timeout(30 * time.Second))
	corsConfig := middleware.CORSConfig{
		AllowedOrigins:   cfg.CORSOrigins,
		AllowedMethods:   []string{http.MethodGet, http.MethodPost, http.MethodPut, http.MethodPatch, http.MethodDelete, http.MethodOptions},
		AllowedHeaders:   []string{"Origin", "Accept", "Content-Type", "Authorization", "X-Request-ID"},
		ExposedHeaders:   []string{"X-Request-ID"},
		AllowCredentials: cfg.CORSAllowCredentials,
		MaxAge:           3600,
	}
	if len(corsConfig.AllowedOrigins) == 1 && corsConfig.AllowedOrigins[0] == "*" {
		r.Use(allowAllOrigins())
	} else {
		r.Use(middleware.CORS(corsConfig))
	}
	r.GET("/health", func(c *gin.Context) { httpx.OK(c, gin.H{"status": "ok"}) })
	return r
}

func allowAllOrigins() gin.HandlerFunc {
	return func(c *gin.Context) {
		h := c.Writer.Header()
		h.Set("Access-Control-Allow-Origin", "*")
		h.Set("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
		h.Set("Access-Control-Allow-Headers", "Origin, Accept, Content-Type, Authorization, X-Request-ID")
		h.Set("Access-Control-Expose-Headers", "X-Request-ID")
		h.Set("Access-Control-Max-Age", "3600")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}
