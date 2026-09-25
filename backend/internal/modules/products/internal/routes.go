package internal

import "github.com/gin-gonic/gin"

func RegisterRoutes(router gin.IRouter, handler *Handler) {
	products := router.Group("/products")
	products.GET("", handler.List)
	products.GET("/categories", handler.Categories)
	products.GET("/providers", handler.Providers)
	products.GET("/brands", handler.Brands)
	products.GET("/search", handler.Search)
	products.GET("/:id", handler.Get)
}
