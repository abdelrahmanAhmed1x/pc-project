package typesense

import "github.com/typesense/typesense-go/v3/typesense/api"

const collectionName = "products"

// ProductDocument is the denormalized public read model stored in Typesense.
// ProductID is indexed for stable sorting; ID is the canonical Typesense document ID.
type ProductDocument struct {
	ID                  string   `json:"id"`
	ProductID           int64    `json:"product_id"`
	Name                string   `json:"name"`
	CategoryID          int64    `json:"category_id"`
	CategorySlug        string   `json:"category_slug"`
	BrandID             *int64   `json:"brand_id,omitempty"`
	BrandName           *string  `json:"brand_name,omitempty"`
	ProviderID          int64    `json:"provider_id"`
	ProviderName        string   `json:"provider_name"`
	Price               *float64 `json:"price,omitempty"`
	Currency            string   `json:"currency"`
	InStock             *bool    `json:"in_stock,omitempty"`
	ImageURL            *string  `json:"image_url,omitempty"`
	CanonicalProductURL string   `json:"canonical_product_url"`
	CreatedAt           int64    `json:"created_at"`
	UpdatedAt           int64    `json:"updated_at"`
}

func productSchema() *api.CollectionSchema {
	optional, noIndex := true, false
	return &api.CollectionSchema{Name: collectionName, Fields: []api.Field{
		{Name: "product_id", Type: "int64"},
		{Name: "name", Type: "string"},
		{Name: "category_id", Type: "int64"},
		{Name: "category_slug", Type: "string"},
		{Name: "brand_id", Type: "int64", Optional: &optional},
		{Name: "brand_name", Type: "string", Optional: &optional},
		{Name: "provider_id", Type: "int64"},
		{Name: "provider_name", Type: "string"},
		{Name: "price", Type: "float", Optional: &optional},
		{Name: "currency", Type: "string", Index: &noIndex},
		{Name: "in_stock", Type: "bool", Optional: &optional},
		{Name: "image_url", Type: "string", Optional: &optional, Index: &noIndex},
		{Name: "canonical_product_url", Type: "string", Index: &noIndex},
		{Name: "created_at", Type: "int64"},
		{Name: "updated_at", Type: "int64"},
	}}
}
