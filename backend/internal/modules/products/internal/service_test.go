package internal

import (
	"context"
	"errors"
	"testing"

	"pc/internal/modules/products/internal/sqlc"

	"github.com/abdelrahmanAhmed1x/core/pagination"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

type queryStub struct {
	listArgs sqlc.ListProductsParams
	listRows []sqlc.ListProductsRow
	total    int64
}

func (*queryStub) GetAllCategories(context.Context) ([]sqlc.Category, error) { return nil, nil }
func (*queryStub) GetAllProviders(context.Context) ([]sqlc.Provider, error)  { return nil, nil }
func (*queryStub) GetAllBrands(context.Context) ([]sqlc.Brand, error)        { return nil, nil }
func (*queryStub) GetProduct(context.Context, int64) (sqlc.GetProductRow, error) {
	return sqlc.GetProductRow{}, pgx.ErrNoRows
}
func (q *queryStub) CountProducts(context.Context, sqlc.CountProductsParams) (int64, error) {
	return q.total, nil
}
func (q *queryStub) ListProducts(_ context.Context, args sqlc.ListProductsParams) ([]sqlc.ListProductsRow, error) {
	q.listArgs = args
	return q.listRows, nil
}
func TestListProductsPageAndMapping(t *testing.T) {
	var price pgtype.Numeric
	if err := price.Scan("123.45"); err != nil {
		t.Fatal(err)
	}
	queries := &queryStub{total: 5, listRows: []sqlc.ListProductsRow{
		{ID: 11, Name: "CPU", Price: price, Currency: "EGP", CategoryID: 1, CategorySlug: "cpu", ProviderID: 2, ProviderName: "sigma"},
		{ID: 12, Name: "GPU", CategoryID: 3, CategorySlug: "gpu", ProviderID: 2, ProviderName: "sigma"},
	}}
	page, err := NewService(queries).List(context.Background(), ListProductsQuery{CategoryIDs: []int64{1, 3}, Query: pagination.Query{Page: 2, Limit: 2}})
	if err != nil {
		t.Fatal(err)
	}
	if queries.listArgs.PageOffset != 2 || queries.listArgs.PageSize != 2 || len(queries.listArgs.CategoryIds) != 2 {
		t.Fatalf("incorrect sqlc arguments: %+v", queries.listArgs)
	}
	if page.Meta.Page != 2 || page.Meta.Limit != 2 || page.Meta.TotalItems != 5 || page.Meta.TotalPages != 3 || len(page.Items) != 2 ||
		page.Items[0].Price == nil || *page.Items[0].Price != "123.45" || page.Items[1].Price != nil || page.Items[0].Brand != nil {
		t.Fatalf("incorrect page: %+v", page)
	}
}

func TestPricePageAndValidation(t *testing.T) {
	queries := &queryStub{total: 3, listRows: []sqlc.ListProductsRow{{ID: 5}}}
	stock := false
	service := NewService(queries)
	page, err := service.List(context.Background(), ListProductsQuery{
		Sort: "price_desc", Query: pagination.Query{Page: 2, Limit: 1}, MinPrice: "10.50", MaxPrice: "20", InStock: &stock,
		ProviderIDs: []int64{1, 2},
	})
	if err != nil {
		t.Fatal(err)
	}
	if queries.listArgs.PageOffset != 1 || queries.listArgs.PageSize != 1 || queries.listArgs.Sort != "price_desc" || queries.listArgs.InStock == nil ||
		*queries.listArgs.InStock || !queries.listArgs.MinPrice.Valid || !queries.listArgs.MaxPrice.Valid ||
		len(queries.listArgs.ProviderIds) != 2 || page.Meta.TotalItems != 3 || page.Meta.TotalPages != 3 {
		t.Fatalf("incorrect price page: args=%+v page=%+v", queries.listArgs, page)
	}
	if _, err := service.List(context.Background(), ListProductsQuery{Sort: "price_asc"}); err != nil || queries.listArgs.Sort != "price_asc" {
		t.Fatalf("ascending sort: args=%+v err=%v", queries.listArgs, err)
	}
	for _, opts := range []ListProductsQuery{
		{MinPrice: "20", MaxPrice: "10"},
		{CategoryIDs: []int64{-1}},
		{Query: pagination.Query{Page: -1}},
		{Query: pagination.Query{Limit: 101}},
	} {
		if _, err := service.List(context.Background(), opts); !errors.Is(err, ErrInvalidFilter) {
			t.Fatalf("expected invalid filter for %+v, got %v", opts, err)
		}
	}
	if _, err := service.Get(context.Background(), 1); !errors.Is(err, ErrNotFound) {
		t.Fatalf("expected not found, got %v", err)
	}
}
