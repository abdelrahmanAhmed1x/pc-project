package internal

import (
	"time"

	"github.com/abdelrahmanAhmed1x/core/pagination"
)

type Category struct {
	ID   int64  `json:"id"`
	Slug string `json:"slug"`
}

type Provider struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

type Brand struct {
	ID   int64  `json:"id"`
	Name string `json:"name"`
}

type Product struct {
	ID       int64    `json:"id"`
	Name     string   `json:"name"`
	Price    *string  `json:"price"`
	Currency string   `json:"currency"`
	InStock  *bool    `json:"in_stock"`
	ImageURL *string  `json:"image_url"`
	Category Category `json:"category"`
	Provider Provider `json:"provider"`
	Brand    *Brand   `json:"brand"`
}

type ProductDetail struct {
	Product
	CanonicalProductURL string    `json:"canonical_product_url"`
	CreatedAt           time.Time `json:"created_at"`
	UpdatedAt           time.Time `json:"updated_at"`
}

type ProductURI struct {
	ID int64 `uri:"id" binding:"required,gt=0"`
}

type ListProductsQuery struct {
	Search string `form:"q"`
	pagination.Query
	PageSize    int     `form:"page_size" binding:"omitempty,min=1,max=100"`
	CategoryIDs []int64 `form:"category_ids" binding:"omitempty,dive,gt=0"`
	ProviderIDs []int64 `form:"provider_ids" binding:"omitempty,dive,gt=0"`
	BrandIDs    []int64 `form:"brand_ids" binding:"omitempty,dive,gt=0"`
	MinPrice    string  `form:"min_price"`
	MaxPrice    string  `form:"max_price"`
	InStock     *bool   `form:"in_stock"`
	Sort        string  `form:"sort" binding:"omitempty,oneof=id price_asc price_desc"`
}

type SearchProductsQuery struct {
	Q string `form:"q" binding:"required"`
	pagination.Query
}
