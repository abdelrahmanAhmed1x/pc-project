package products

import (
	"pc/internal/modules/products/internal"
	"pc/internal/modules/products/internal/sqlc"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
)

func RegisterRoutes(router gin.IRouter, pool *pgxpool.Pool, log logger.Logger) {
	queries := sqlc.New(pool)
	service := internal.NewService(queries)
	handler := internal.NewHandler(service, log)
	internal.RegisterRoutes(router, handler)
}
