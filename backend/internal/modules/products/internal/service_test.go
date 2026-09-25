package internal

import (
	"context"
	"errors"
	"testing"

	"pc/internal/modules/products/internal/sqlc"
	"pc/internal/modules/products/internal/typesense"

	"github.com/abdelrahmanAhmed1x/core/pagination"
)

type queryStub struct{ categories int }

func (q *queryStub) GetAllCategories(context.Context) ([]sqlc.Category, error) {
	q.categories++
	return []sqlc.Category{{ID: 2, Slug: "gpu"}}, nil
}
func (*queryStub) GetAllProviders(context.Context) ([]sqlc.Provider, error) { return nil, nil }
func (*queryStub) GetAllBrands(context.Context) ([]sqlc.Brand, error)       { return nil, nil }

type searchStub struct {
	params typesense.SearchParams
	calls  int
	result typesense.SearchResult
	doc    typesense.ProductDocument
	err    error
}

func (s *searchStub) SearchProducts(_ context.Context, p typesense.SearchParams) (typesense.SearchResult, error) {
	s.calls++
	s.params = p
	return s.result, s.err
}
func (s *searchStub) GetProduct(context.Context, int64) (typesense.ProductDocument, error) {
	s.calls++
	return s.doc, s.err
}

func TestProductReadsUseSearchRepository(t *testing.T) {
	queries := &queryStub{}
	price := 123.45
	search := &searchStub{result: typesense.SearchResult{Found: 5, Documents: []typesense.ProductDocument{{ID: "11", Name: "GPU", Price: &price, CategoryID: 2, CategorySlug: "gpu"}}}, doc: typesense.ProductDocument{ID: "11", Name: "GPU", Price: &price, CreatedAt: 1780000000}}
	service := NewService(queries, search)
	page, err := service.List(context.Background(), ListProductsQuery{Search: "rtx", CategoryIDs: []int64{2}, Query: pagination.Query{Page: 2, Limit: 2}})
	if err != nil {
		t.Fatal(err)
	}
	if search.calls != 1 || search.params.Query != "rtx" || search.params.Page != 2 || search.params.PageSize != 2 || page.Meta.TotalItems != 5 || page.Meta.TotalPages != 3 || len(page.Items) != 1 || *page.Items[0].Price != "123.45" {
		t.Fatalf("incorrect search: %+v %+v", search, page)
	}
	detail, err := service.Get(context.Background(), 11)
	if err != nil || detail.ID != 11 || detail.Price == nil || *detail.Price != "123.45" || search.calls != 2 {
		t.Fatalf("incorrect detail: %+v %v", detail, err)
	}
	if queries.categories != 0 {
		t.Fatal("product reads touched lookup repository")
	}
	_, err = service.Categories(context.Background())
	if err != nil || queries.categories != 1 {
		t.Fatalf("lookup failed: %v", err)
	}
	search.err = typesense.ErrNotFound
	if _, err := service.Get(context.Background(), 12); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected not found, got %v", err)
	}
}

func TestProductSearchValidation(t *testing.T) {
	service := NewService(&queryStub{}, &searchStub{})
	for _, opts := range []ListProductsQuery{
		{MinPrice: "20", MaxPrice: "10"}, {MinPrice: "NaN"}, {CategoryIDs: []int64{-1}},
		{Sort: "unknown"}, {Query: pagination.Query{Page: -1}}, {Query: pagination.Query{Limit: 101}},
	} {
		if _, err := service.List(context.Background(), opts); !errors.Is(err, ErrInvalidFilter) {
			t.Fatalf("expected validation error for %+v: %v", opts, err)
		}
	}
}

func TestSearchBarReturnsProductsFromDocuments(t *testing.T) {
	search := &searchStub{result: typesense.SearchResult{Found: 23, Documents: []typesense.ProductDocument{
		{ID: "829", Name: "RTX 5070", CategoryID: 2, CategorySlug: "gpu"},
	}}}
	service := NewService(&queryStub{}, search)
	result, err := service.Search(context.Background(), "  rtx  ", pagination.Query{Page: 2, Limit: 5})
	if err != nil || search.params.Query != "rtx" || search.params.Page != 2 || search.params.PageSize != 5 ||
		result.Meta.TotalItems != 23 || result.Meta.TotalPages != 5 ||
		len(result.Items) != 1 || result.Items[0].ID != 829 || result.Items[0].Category.Slug != "gpu" {
		t.Fatalf("incorrect search results: result=%+v params=%+v err=%v", result, search.params, err)
	}
	for _, query := range []string{"", "  ", "*"} {
		if _, err := service.Search(context.Background(), query, pagination.Query{Page: 1, Limit: 5}); !errors.Is(err, ErrInvalidFilter) {
			t.Fatalf("expected invalid search %q: %v", query, err)
		}
	}
	if _, err := service.Search(context.Background(), "rtx", pagination.Query{Page: 1, Limit: 101}); !errors.Is(err, ErrInvalidFilter) {
		t.Fatalf("expected invalid limit: %v", err)
	}
}
