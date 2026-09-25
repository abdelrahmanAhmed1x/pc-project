package products

import (
	"context"
	"pc/internal/modules/products/internal"
	"pc/internal/modules/products/internal/sqlc"
	"pc/internal/modules/products/internal/typesense"

	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	typesenseclient "github.com/typesense/typesense-go/v3/typesense"
)

// Public catalog types let other modules use the same product read service.
type Product = internal.Product
type ProductDetail = internal.ProductDetail
type Category = internal.Category
type Provider = internal.Provider
type Brand = internal.Brand
type ListProductsQuery = internal.ListProductsQuery
type Service = internal.Service

var ErrNotFound = internal.ErrNotFound

func NewService(pool *pgxpool.Pool, client *typesenseclient.Client) *Service {
	return internal.NewService(sqlc.New(pool), typesense.NewRepository(client))
}

func RegisterRoutes(router gin.IRouter, pool *pgxpool.Pool, client *typesenseclient.Client, log logger.Logger) {
	service := NewService(pool, client)
	handler := internal.NewHandler(service, log)
	internal.RegisterRoutes(router, handler)
}

// ReindexProducts explicitly rebuilds the read model from canonical PostgreSQL rows.
func ReindexProducts(ctx context.Context, pool *pgxpool.Pool, client *typesenseclient.Client) error {
	search := typesense.NewRepository(client)
	if err := search.PrepareReindex(ctx); err != nil {
		return err
	}
	return internal.NewIndexer(sqlc.New(pool), search).ReindexProducts(ctx)
}

func EnsureCollection(ctx context.Context, client *typesenseclient.Client) error {
	return typesense.NewRepository(client).EnsureCollection(ctx)
}
