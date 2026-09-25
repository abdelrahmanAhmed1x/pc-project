package internal

import (
	"context"
	"errors"
	"net/http"
	"strings"

	"pc/internal/modules/products/internal/typesense"

	"github.com/abdelrahmanAhmed1x/core/httpx"
	"github.com/abdelrahmanAhmed1x/core/logger"
	"github.com/abdelrahmanAhmed1x/core/pagination"
	"github.com/gin-gonic/gin"
)

// ProductService lives with its consumer, the HTTP handler.
type ProductService interface {
	Categories(context.Context) ([]Category, error)
	Providers(context.Context) ([]Provider, error)
	Brands(context.Context) ([]Brand, error)
	Get(context.Context, int64) (ProductDetail, error)
	List(context.Context, ListProductsQuery) (pagination.Result[Product], error)
	Search(context.Context, string, pagination.Query) (pagination.Result[Product], error)
}

type Handler struct {
	service ProductService
	log     logger.Logger
}

func NewHandler(service ProductService, log logger.Logger) *Handler {
	return &Handler{service: service, log: log}
}

func (h *Handler) List(c *gin.Context) {
	// Gin binds repeated slice values; accept comma-separated IDs too.
	values := c.Request.URL.Query()
	for _, key := range []string{"category_ids", "provider_ids", "brand_ids"} {
		if raw, ok := values[key]; ok {
			var ids []string
			for _, value := range raw {
				ids = append(ids, strings.Split(value, ",")...)
			}
			values[key] = ids
		}
	}
	c.Request.URL.RawQuery = values.Encode()
	query, ok := httpx.BindQuery[ListProductsQuery](c)
	if !ok {
		return
	}
	page, err := h.service.List(c.Request.Context(), query)
	if err != nil {
		h.abort(c, err)
		return
	}
	httpx.OK(c, page)
}

func (h *Handler) Search(c *gin.Context) {
	query, ok := httpx.BindQuery[SearchProductsQuery](c)
	if !ok {
		return
	}
	page, err := h.service.Search(c.Request.Context(), query.Q, query.Query)
	if err != nil {
		h.abort(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"success": true, "data": page.Items, "meta": page.Meta})
}

func (h *Handler) Get(c *gin.Context) {
	uri, ok := httpx.BindURI[ProductURI](c)
	if !ok {
		return
	}
	product, err := h.service.Get(c.Request.Context(), uri.ID)
	if err != nil {
		h.abort(c, err)
		return
	}
	httpx.OK(c, product)
}

func (h *Handler) Categories(c *gin.Context) {
	items, err := h.service.Categories(c.Request.Context())
	if err != nil {
		h.abort(c, err)
		return
	}
	httpx.OK(c, items)
}

func (h *Handler) Providers(c *gin.Context) {
	items, err := h.service.Providers(c.Request.Context())
	if err != nil {
		h.abort(c, err)
		return
	}
	httpx.OK(c, items)
}

func (h *Handler) Brands(c *gin.Context) {
	items, err := h.service.Brands(c.Request.Context())
	if err != nil {
		h.abort(c, err)
		return
	}
	httpx.OK(c, items)
}

func (h *Handler) abort(c *gin.Context, err error) {
	switch {
	case errors.Is(err, ErrInvalidFilter):
		httpx.AbortBadRequest(c, err.Error(), nil)
	case errors.Is(err, ErrNotFound):
		httpx.AbortNotFound(c, "Product not found")
	case errors.Is(err, typesense.ErrUnavailable):
		h.log.Error(c.Request.Context(), "product search unavailable", "error", err)
		c.AbortWithStatusJSON(http.StatusServiceUnavailable, gin.H{
			"success": false,
			"error":   gin.H{"code": "SERVICE_UNAVAILABLE", "message": "Product search is temporarily unavailable"},
		})
	default:
		h.log.Error(c.Request.Context(), "product request failed", "error", err)
		c.AbortWithStatusJSON(http.StatusInternalServerError, gin.H{
			"success": false,
			"error":   gin.H{"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"},
		})
	}
}
