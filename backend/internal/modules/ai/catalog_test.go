package ai

import (
	"context"
	"errors"
	"testing"

	"pc/internal/modules/products"

	"github.com/abdelrahmanAhmed1x/core/pagination"
)

type catalogStub struct {
	options    products.ListProductsQuery
	hybrid     bool
	categories []products.Category
	items      []products.Product
	details    map[int64]products.ProductDetail
	getCalls   int
}

func (s *catalogStub) List(_ context.Context, options products.ListProductsQuery) (pagination.Result[products.Product], error) {
	s.options = options
	return pagination.NewResult(s.items, len(s.items), options.Query), nil
}
func (s *catalogStub) Recommend(ctx context.Context, options products.ListProductsQuery) (pagination.Result[products.Product], error) {
	s.hybrid = true
	return s.List(ctx, options)
}
func (s *catalogStub) Categories(context.Context) ([]products.Category, error) {
	return s.categories, nil
}
func (s *catalogStub) Get(_ context.Context, id int64) (products.ProductDetail, error) {
	s.getCalls++
	if detail, ok := s.details[id]; ok {
		return detail, nil
	}
	return products.ProductDetail{}, products.ErrNotFound
}

func TestCatalogSearchMapsSemanticFiltersAndPurchaseURL(t *testing.T) {
	price := "36500.00"
	stock := true
	catalog := &catalogStub{
		categories: []products.Category{{ID: 2, Slug: "gpu"}},
		items:      []products.Product{{ID: 242}},
		details: map[int64]products.ProductDetail{242: {Product: products.Product{
			ID: 242, Name: "ASRock RX 9070", Price: &price, Currency: "EGP", InStock: &stock,
			Category: products.Category{ID: 2, Slug: "gpu"}, Provider: products.Provider{ID: 1, Name: "sigma"},
		}, CanonicalProductURL: "https://retailer.example/rx-9070"}},
	}
	minPrice, maxPrice := 30000.0, 40000.0
	result, err := (catalogTools{catalog}).search(context.Background(), SearchProductsInput{
		Query: "RX 9070", Category: "GPU", Brand: "ASRock", MinPrice: &minPrice, MaxPrice: &maxPrice,
		InStock: &stock, Sort: "price_asc", Limit: 50,
	})
	if err != nil {
		t.Fatal(err)
	}
	if catalog.options.Search != "RX 9070 ASRock" || len(catalog.options.CategoryIDs) != 1 ||
		catalog.options.CategoryIDs[0] != 2 || catalog.options.MinPrice != "30000" ||
		catalog.options.MaxPrice != "40000" || catalog.options.InStock == nil || !*catalog.options.InStock ||
		catalog.options.Sort != "price_asc" || catalog.options.Query.Limit != 10 || catalog.getCalls != 1 {
		t.Fatalf("incorrect product search: %+v", catalog.options)
	}
	if len(result.Products) != 1 || result.Products[0].ID != 242 ||
		result.Products[0].CanonicalProductURL != "https://retailer.example/rx-9070" ||
		result.Products[0].Price != price || result.Products[0].Provider != "sigma" {
		t.Fatalf("incorrect tool result: %+v", result)
	}
}

func TestCatalogValidationAndUnknownCategory(t *testing.T) {
	catalog := &catalogStub{categories: []products.Category{{ID: 2, Slug: "gpu"}}}
	adapter := catalogTools{catalog}
	for _, input := range []SearchProductsInput{
		{}, {Query: "GPU", Sort: "price:asc"}, {Query: "GPU", Limit: -1},
		{Query: "GPU", MinPrice: ptrFloat(-1)},
		{Query: "GPU", MinPrice: ptrFloat(50), MaxPrice: ptrFloat(20)},
	} {
		if _, err := adapter.search(context.Background(), input); !errors.Is(err, ErrInvalidRequest) {
			t.Fatalf("expected invalid input for %+v: %v", input, err)
		}
	}
	result, err := adapter.search(context.Background(), SearchProductsInput{Query: "battery", Category: "phone"})
	if err != nil || len(result.Products) != 0 {
		t.Fatalf("unknown category should produce no matches: %+v %v", result, err)
	}
	if _, err := adapter.get(context.Background(), GetProductInput{ID: 0}); !errors.Is(err, ErrInvalidRequest) {
		t.Fatalf("invalid get ID: %v", err)
	}
}

func TestRecommendUsesHybridReadWithBoundedCandidates(t *testing.T) {
	catalog := &catalogStub{categories: []products.Category{{ID: 2, Slug: "gpu"}}}
	stock, maxPrice := true, 35000.0
	_, err := (catalogTools{catalog}).recommend(context.Background(), RecommendProductsInput{
		Need: "GPU for 1440p gaming", Category: "gpu", InStock: &stock,
		MaxPrice: &maxPrice, Limit: 200,
	})
	if err != nil || !catalog.hybrid || catalog.options.Search != "GPU for 1440p gaming" ||
		catalog.options.Query.Limit != 20 || catalog.options.MaxPrice != "35000" ||
		len(catalog.options.CategoryIDs) != 1 || catalog.options.CategoryIDs[0] != 2 {
		t.Fatalf("hybrid routing or filters: %+v, %v", catalog, err)
	}
	for _, need := range []string{"", "  ", "*"} {
		if _, err := (catalogTools{catalog}).recommend(context.Background(), RecommendProductsInput{Need: need}); !errors.Is(err, ErrInvalidRequest) {
			t.Fatalf("invalid need %q: %v", need, err)
		}
	}
	if _, err := (catalogTools{catalog}).recommend(context.Background(), RecommendProductsInput{Need: "GPU", Limit: -1}); !errors.Is(err, ErrInvalidRequest) {
		t.Fatalf("negative recommendation limit: %v", err)
	}
}

func TestCheapestIntentOverridesModelSortAndStock(t *testing.T) {
	stock := false
	input := applyUserSearchIntent("Find the cheapest available RX 9070", SearchProductsInput{
		Query: "RX 9070", Sort: "relevance", InStock: &stock,
	})
	if input.Sort != "price_asc" || input.InStock == nil || !*input.InStock {
		t.Fatalf("cheapest request must be sorted and in stock: %+v", input)
	}
	input = applyUserSearchIntent("Compare RX 9070 models", SearchProductsInput{Sort: "relevance"})
	if input.Sort != "relevance" || input.InStock != nil {
		t.Fatalf("ordinary comparison changed: %+v", input)
	}
}

func TestRecommendationIntentConstrainsStockAndBudget(t *testing.T) {
	input := applyUserRecommendationIntent("I need a GPU around 35k for 1440p", RecommendProductsInput{Need: "1440p GPU"})
	if input.InStock == nil || !*input.InStock || input.MaxPrice == nil || *input.MaxPrice != 38500 {
		t.Fatalf("soft budget or stock not applied: %+v", input)
	}
	input = applyUserRecommendationIntent("GPU under 35000", RecommendProductsInput{Need: "GPU", MaxPrice: ptrFloat(40000)})
	if input.MaxPrice == nil || *input.MaxPrice != 35000 {
		t.Fatalf("hard budget exceeded: %+v", input)
	}
	search := applyUserSearchIntent("Find an SSD under 7000", SearchProductsInput{Query: "NVMe", MaxPrice: ptrFloat(9000)})
	if search.MaxPrice == nil || *search.MaxPrice != 7000 {
		t.Fatalf("exact-search budget exceeded: %+v", search)
	}
}

func TestCatalogRejectsIncompleteListing(t *testing.T) {
	price := "100.00"
	base := products.ProductDetail{Product: products.Product{ID: 1, Name: "GPU", Price: &price,
		Currency: "EGP", Provider: products.Provider{Name: "sigma"}}, CanonicalProductURL: "https://example.com/item"}
	if _, err := catalogProduct(base); err != nil {
		t.Fatal(err)
	}
	base.CanonicalProductURL = "https://example.com/"
	base.Price = nil
	if _, err := catalogProduct(base); err == nil {
		t.Fatal("unknown price must not be recommended")
	}
	base.Price = &price
	base.CanonicalProductURL = "javascript:bad"
	if _, err := catalogProduct(base); err == nil {
		t.Fatal("invalid URL must not be recommended")
	}
	zero := "0.00"
	base.Price = &zero
	base.CanonicalProductURL = "https://example.com/item"
	if _, err := catalogProduct(base); err == nil {
		t.Fatal("zero-price listing must not be recommended")
	}
}

func ptrFloat(value float64) *float64 { return &value }
