package ai

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"strings"

	"pc/internal/modules/products"

	"github.com/abdelrahmanAhmed1x/core/pagination"
	"google.golang.org/adk/v2/agent"
	"google.golang.org/adk/v2/tool"
	"google.golang.org/adk/v2/tool/functiontool"
	"google.golang.org/genai"
)

// Catalog is the existing product read service, without exposing Typesense to AI.
type Catalog interface {
	List(context.Context, products.ListProductsQuery) (pagination.Result[products.Product], error)
	Recommend(context.Context, products.ListProductsQuery) (pagination.Result[products.Product], error)
	Get(context.Context, int64) (products.ProductDetail, error)
	Categories(context.Context) ([]products.Category, error)
}

type SearchProductsInput struct {
	Query    string   `json:"query"`
	Category string   `json:"category,omitempty"`
	Brand    string   `json:"brand,omitempty"`
	MinPrice *float64 `json:"min_price,omitempty"`
	MaxPrice *float64 `json:"max_price,omitempty"`
	InStock  *bool    `json:"in_stock,omitempty"`
	Sort     string   `json:"sort,omitempty"`
	Limit    int      `json:"limit,omitempty"`
}

type RecommendProductsInput struct {
	Need     string   `json:"need"`
	Category string   `json:"category,omitempty"`
	MinPrice *float64 `json:"min_price,omitempty"`
	MaxPrice *float64 `json:"max_price,omitempty"`
	InStock  *bool    `json:"in_stock,omitempty"`
	Limit    int      `json:"limit,omitempty"`
}

type CatalogProduct struct {
	ID                  int64   `json:"id"`
	Name                string  `json:"name"`
	Price               string  `json:"price"`
	Currency            string  `json:"currency"`
	InStock             *bool   `json:"in_stock"`
	Category            string  `json:"category"`
	Brand               string  `json:"brand,omitempty"`
	Provider            string  `json:"provider"`
	CanonicalProductURL string  `json:"canonical_product_url"`
	ImageURL            *string `json:"image_url,omitempty"`
}

type SearchProductsOutput struct {
	Products   []CatalogProduct `json:"products"`
	TotalFound int              `json:"total_found"`
}

type GetProductInput struct {
	ID int64 `json:"id"`
}

type GetProductOutput struct {
	Product CatalogProduct `json:"product"`
}

type catalogTools struct{ catalog Catalog }

func newCatalogTools(catalog Catalog) ([]tool.Tool, error) {
	adapter := catalogTools{catalog: catalog}
	search, err := functiontool.New(functiontool.Config{
		Name: "search_products", Description: "Use for a named product, model, or concrete specification. Lexical and typo-tolerant catalog search with category, price, stock and sort filters. Returns at most 10 real listings.",
	}, func(ctx agent.Context, input SearchProductsInput) (SearchProductsOutput, error) {
		return adapter.search(ctx, applyUserSearchIntent(contentText(ctx.UserContent()), input))
	})
	if err != nil {
		return nil, fmt.Errorf("create search_products tool: %w", err)
	}
	recommend, err := functiontool.New(functiontool.Config{
		Name: "recommend_products", Description: "Use for a use case, workload, priorities, or desired characteristics when the exact model is unknown. Hybrid catalog retrieval combines keywords and semantic meaning. Returns at most 20 real listings.",
	}, func(ctx agent.Context, input RecommendProductsInput) (SearchProductsOutput, error) {
		return adapter.recommend(ctx, applyUserRecommendationIntent(contentText(ctx.UserContent()), input))
	})
	if err != nil {
		return nil, fmt.Errorf("create recommend_products tool: %w", err)
	}
	get, err := functiontool.New(functiontool.Config{
		Name: "get_product", Description: "Retrieve one current catalog listing by a product ID already mentioned in the conversation. Returns its exact price, stock, provider, and purchase URL.",
	}, func(ctx agent.Context, input GetProductInput) (GetProductOutput, error) {
		return adapter.get(ctx, input)
	})
	if err != nil {
		return nil, fmt.Errorf("create get_product tool: %w", err)
	}
	return []tool.Tool{search, recommend, get}, nil
}

func applyUserSearchIntent(message string, input SearchProductsInput) SearchProductsInput {
	if wantsCheapest(message) {
		inStock := true
		input.InStock = &inStock
		input.Sort = "price_asc"
	}
	if max := hardBudgetFromMessage(message); max > 0 {
		limit := float64(max) / 100
		if input.MaxPrice == nil || *input.MaxPrice > limit {
			input.MaxPrice = &limit
		}
	}
	return input
}

func applyUserRecommendationIntent(message string, input RecommendProductsInput) RecommendProductsInput {
	if message != "" && len(message) <= 500 && !strings.Contains(strings.ToLower(input.Need), strings.ToLower(strings.TrimSpace(message))) {
		input.Need = strings.TrimSpace(input.Need + " " + message)
	}
	if input.InStock == nil {
		stock := true
		input.InStock = &stock
	}
	max := hardBudgetFromMessage(message)
	if max == 0 {
		if soft := budgetFromMessage(message); soft > 0 {
			max = int64(math.Round(float64(soft) * 1.1))
		}
	}
	if max > 0 {
		limit := float64(max) / 100
		if input.MaxPrice == nil || *input.MaxPrice > limit {
			input.MaxPrice = &limit
		}
	}
	return input
}

func wantsCheapest(message string) bool {
	text := strings.ToLower(message)
	return strings.Contains(text, "cheapest") || strings.Contains(text, "lowest price")
}

func contentText(content *genai.Content) string {
	if content == nil {
		return ""
	}
	var text strings.Builder
	for _, part := range content.Parts {
		if part != nil {
			text.WriteString(part.Text)
		}
	}
	return text.String()
}

func (t catalogTools) search(ctx context.Context, input SearchProductsInput) (SearchProductsOutput, error) {
	return t.find(ctx, input, false)
}

func (t catalogTools) recommend(ctx context.Context, input RecommendProductsInput) (SearchProductsOutput, error) {
	if strings.TrimSpace(input.Need) == "" || strings.TrimSpace(input.Need) == "*" {
		return SearchProductsOutput{}, fmt.Errorf("%w: need is required", ErrInvalidRequest)
	}
	limit := input.Limit
	if limit < 0 {
		return SearchProductsOutput{}, fmt.Errorf("%w: limit must be positive", ErrInvalidRequest)
	}
	if limit < 10 {
		limit = 10
	}
	return t.find(ctx, SearchProductsInput{Query: input.Need, Category: input.Category,
		MinPrice: input.MinPrice, MaxPrice: input.MaxPrice, InStock: input.InStock,
		Limit: min(limit, 20)}, true)
}

func (t catalogTools) find(ctx context.Context, input SearchProductsInput, hybrid bool) (SearchProductsOutput, error) {
	limit := input.Limit
	if limit == 0 {
		limit = 5
	}
	if limit < 0 {
		return SearchProductsOutput{}, fmt.Errorf("%w: limit must be positive", ErrInvalidRequest)
	}
	if hybrid {
		limit = min(limit, 20)
	} else {
		limit = min(limit, 10)
	}
	query := strings.TrimSpace(input.Query)
	if brand := strings.TrimSpace(input.Brand); brand != "" {
		query = strings.TrimSpace(query + " " + brand)
	}
	if query == "" && strings.TrimSpace(input.Category) == "" {
		return SearchProductsOutput{}, fmt.Errorf("%w: query or category is required", ErrInvalidRequest)
	}
	var sort string
	switch input.Sort {
	case "", "relevance":
	case "price_asc", "price_desc":
		sort = input.Sort
	default:
		return SearchProductsOutput{}, fmt.Errorf("%w: unsupported sort", ErrInvalidRequest)
	}
	if !validBound(input.MinPrice) || !validBound(input.MaxPrice) ||
		(input.MinPrice != nil && input.MaxPrice != nil && *input.MinPrice > *input.MaxPrice) {
		return SearchProductsOutput{}, fmt.Errorf("%w: invalid price range", ErrInvalidRequest)
	}
	opts := products.ListProductsQuery{Search: query, InStock: input.InStock, Sort: sort,
		Query: pagination.Query{Page: 1, Limit: limit}}
	if input.MinPrice != nil {
		opts.MinPrice = strconv.FormatFloat(*input.MinPrice, 'f', -1, 64)
	}
	if input.MaxPrice != nil {
		opts.MaxPrice = strconv.FormatFloat(*input.MaxPrice, 'f', -1, 64)
	}
	if slug := strings.TrimSpace(input.Category); slug != "" {
		categories, err := t.catalog.Categories(ctx)
		if err != nil {
			return SearchProductsOutput{}, fmt.Errorf("resolve category: %w", err)
		}
		for _, category := range categories {
			if strings.EqualFold(category.Slug, slug) {
				opts.CategoryIDs = []int64{category.ID}
				break
			}
		}
		if len(opts.CategoryIDs) == 0 {
			return SearchProductsOutput{Products: []CatalogProduct{}}, nil
		}
	}
	var page pagination.Result[products.Product]
	var err error
	if hybrid {
		page, err = t.catalog.Recommend(ctx, opts)
	} else {
		page, err = t.catalog.List(ctx, opts)
	}
	if err != nil {
		return SearchProductsOutput{}, fmt.Errorf("search catalog: %w", err)
	}
	result := SearchProductsOutput{Products: make([]CatalogProduct, 0, len(page.Items)), TotalFound: page.Meta.TotalItems}
	for _, item := range page.Items {
		// Product detail is another Typesense read through the product service.
		// Search is bounded to 10, and detail supplies the canonical purchase URL.
		detail, err := t.catalog.Get(ctx, item.ID)
		if errors.Is(err, products.ErrNotFound) {
			continue // A listing may disappear between search and detail retrieval.
		}
		if err != nil {
			return SearchProductsOutput{}, fmt.Errorf("get catalog product %d: %w", item.ID, err)
		}
		product, err := catalogProduct(detail)
		if err != nil {
			continue // Incomplete listings are not recommendation-capable.
		}
		result.Products = append(result.Products, product)
	}
	return result, nil
}

func (t catalogTools) get(ctx context.Context, input GetProductInput) (GetProductOutput, error) {
	if input.ID <= 0 {
		return GetProductOutput{}, fmt.Errorf("%w: id must be positive", ErrInvalidRequest)
	}
	detail, err := t.catalog.Get(ctx, input.ID)
	if err != nil {
		return GetProductOutput{}, fmt.Errorf("get catalog product: %w", err)
	}
	product, err := catalogProduct(detail)
	if err != nil {
		return GetProductOutput{}, err
	}
	return GetProductOutput{Product: product}, nil
}

func validBound(value *float64) bool {
	return value == nil || (!math.IsNaN(*value) && !math.IsInf(*value, 0) && *value >= 0)
}

func catalogProduct(detail products.ProductDetail) (CatalogProduct, error) {
	if detail.ID <= 0 || strings.TrimSpace(detail.Name) == "" || detail.Price == nil ||
		strings.TrimSpace(detail.Currency) == "" || strings.TrimSpace(detail.Provider.Name) == "" {
		return CatalogProduct{}, errors.New("catalog product lacks required listing fields")
	}
	price, err := strconv.ParseFloat(*detail.Price, 64)
	if err != nil || !validBound(&price) || price == 0 {
		return CatalogProduct{}, errors.New("catalog product has invalid price")
	}
	parsed, err := url.Parse(detail.CanonicalProductURL)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
		return CatalogProduct{}, errors.New("catalog product has invalid purchase URL")
	}
	var brand string
	if detail.Brand != nil {
		brand = detail.Brand.Name
	}
	return CatalogProduct{ID: detail.ID, Name: detail.Name, Price: *detail.Price,
		Currency: detail.Currency, InStock: detail.InStock, Category: detail.Category.Slug,
		Brand: brand, Provider: detail.Provider.Name,
		CanonicalProductURL: detail.CanonicalProductURL, ImageURL: detail.ImageURL}, nil
}
