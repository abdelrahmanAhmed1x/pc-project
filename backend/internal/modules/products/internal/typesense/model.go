package typesense

import "github.com/typesense/typesense-go/v3/typesense/api"

const collectionName = "products"

// ProductDocument is the denormalized public read model stored in Typesense.
// ProductID is indexed for stable sorting; ID is the canonical Typesense document ID.
type ProductDocument struct {
	ID                  string   `json:"id"`
	ProductID           int64    `json:"product_id"`
	Name                string   `json:"name"`
	SemanticText        string   `json:"semantic_text,omitempty"`
	CategoryID          int64    `json:"category_id"`
	CategorySlug        string   `json:"category_slug"`
	BrandID             *int64   `json:"brand_id,omitempty"`
	BrandName           *string  `json:"brand_name,omitempty"`
	ProviderID          int64    `json:"provider_id"`
	ProviderIDs         []int64  `json:"provider_ids"`
	ProviderName        string   `json:"provider_name"`
	Price               *float64 `json:"price,omitempty"`
	PriceStatus         string   `json:"price_status,omitempty"`
	Condition           string   `json:"condition,omitempty"`
	OfferCount          int64    `json:"offer_count,omitempty"`
	ProductVariantID    int64    `json:"product_variant_id,omitempty"`
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
		{Name: "semantic_text", Type: "string", Optional: &optional},
		embeddingField(),
		{Name: "category_id", Type: "int64"},
		{Name: "category_slug", Type: "string"},
		{Name: "brand_id", Type: "int64", Optional: &optional},
		{Name: "brand_name", Type: "string", Optional: &optional},
		{Name: "provider_id", Type: "int64"},
		{Name: "provider_ids", Type: "int64[]", Optional: &optional},
		{Name: "provider_name", Type: "string"},
		{Name: "price", Type: "float", Optional: &optional},
		{Name: "price_status", Type: "string", Optional: &optional},
		{Name: "condition", Type: "string", Optional: &optional},
		{Name: "offer_count", Type: "int64", Optional: &optional},
		{Name: "product_variant_id", Type: "int64", Optional: &optional},
		{Name: "currency", Type: "string", Index: &noIndex},
		{Name: "in_stock", Type: "bool", Optional: &optional},
		{Name: "image_url", Type: "string", Optional: &optional, Index: &noIndex},
		{Name: "canonical_product_url", Type: "string", Index: &noIndex},
		{Name: "created_at", Type: "int64"},
		{Name: "updated_at", Type: "int64"},
	}}
}

// The model runs inside Typesense. Only stable catalog facts enter embed.from.
const embeddingModel = "ts/multilingual-e5-small"

func embeddingField() api.Field {
	optional := true
	field := api.Field{Name: "embedding", Type: "float[]", Optional: &optional}
	field.Embed = &struct {
		From        []string `json:"from"`
		ModelConfig struct {
			AccessToken    *string `json:"access_token,omitempty"`
			ApiKey         *string `json:"api_key,omitempty"`
			ClientId       *string `json:"client_id,omitempty"`
			ClientSecret   *string `json:"client_secret,omitempty"`
			IndexingPrefix *string `json:"indexing_prefix,omitempty"`
			ModelName      string  `json:"model_name"`
			ProjectId      *string `json:"project_id,omitempty"`
			QueryPrefix    *string `json:"query_prefix,omitempty"`
			RefreshToken   *string `json:"refresh_token,omitempty"`
			Url            *string `json:"url,omitempty"`
		} `json:"model_config"`
	}{From: []string{"semantic_text"}}
	field.Embed.ModelConfig.ModelName = embeddingModel
	return field
}
