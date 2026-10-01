package internal

import (
	"encoding/json"
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
	ID               int64    `json:"id"`
	Name             string   `json:"name"`
	Price            *string  `json:"price"`
	PriceStatus      string   `json:"price_status"`
	Condition        string   `json:"condition"`
	OfferCount       int64    `json:"offer_count"`
	ProductVariantID int64    `json:"product_variant_id"`
	Currency         string   `json:"currency"`
	InStock          *bool    `json:"in_stock"`
	ImageURL         *string  `json:"image_url"`
	Category         Category `json:"category"`
	Provider         Provider `json:"provider"`
	Brand            *Brand   `json:"brand"`
}

type ProductDetail struct {
	Product
	CanonicalProductURL string    `json:"canonical_product_url"`
	Offers              []Offer   `json:"offers"`
	CreatedAt           time.Time `json:"created_at"`
	UpdatedAt           time.Time `json:"updated_at"`
}

type Offer struct {
	ID               int64           `json:"id"`
	Provider         Provider        `json:"provider"`
	ProductVariantID int64           `json:"product_variant_id"`
	Configuration    json.RawMessage `json:"configuration"`
	SKU              *string         `json:"sku"`
	Price            *string         `json:"price"`
	OldPrice         *string         `json:"old_price"`
	PriceStatus      string          `json:"price_status"`
	Currency         string          `json:"currency"`
	InStock          *bool           `json:"in_stock"`
	Condition        string          `json:"condition"`
	Warranty         *string         `json:"warranty"`
	URL              string          `json:"url"`
	ImageURL         *string         `json:"image_url"`
	LastSeenAt       time.Time       `json:"last_seen_at"`
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
	ListProductsQuery
	Q string `form:"q" binding:"required"`
}
