package internal

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"

	"pc/internal/modules/products/internal/sqlc"
	"pc/internal/modules/products/internal/typesense"

	"github.com/abdelrahmanAhmed1x/core/pagination"
)

var (
	ErrNotFound      = errors.New("product not found")
	ErrInvalidFilter = errors.New("invalid product filter")
)

type lookupQueries interface {
	GetAllCategories(context.Context) ([]sqlc.Category, error)
	GetAllProviders(context.Context) ([]sqlc.Provider, error)
	GetAllBrands(context.Context) ([]sqlc.Brand, error)
}
type productSearch interface {
	GetProduct(context.Context, int64) (typesense.ProductDocument, error)
	SearchProducts(context.Context, typesense.SearchParams) (typesense.SearchResult, error)
	RecommendProducts(context.Context, typesense.SearchParams) (typesense.SearchResult, error)
}

type Service struct {
	queries lookupQueries
	search  productSearch
}

func NewService(queries lookupQueries, search productSearch) *Service {
	return &Service{queries: queries, search: search}
}

func (s *Service) Categories(ctx context.Context) ([]Category, error) {
	rows, err := s.queries.GetAllCategories(ctx)
	if err != nil {
		return nil, fmt.Errorf("list categories: %w", err)
	}
	return ToCategories(rows), nil
}
func (s *Service) Providers(ctx context.Context) ([]Provider, error) {
	rows, err := s.queries.GetAllProviders(ctx)
	if err != nil {
		return nil, fmt.Errorf("list providers: %w", err)
	}
	return ToProviders(rows), nil
}
func (s *Service) Brands(ctx context.Context) ([]Brand, error) {
	rows, err := s.queries.GetAllBrands(ctx)
	if err != nil {
		return nil, fmt.Errorf("list brands: %w", err)
	}
	return ToBrands(rows), nil
}
func (s *Service) Get(ctx context.Context, id int64) (ProductDetail, error) {
	if id <= 0 {
		return ProductDetail{}, fmt.Errorf("%w: id must be positive", ErrInvalidFilter)
	}
	doc, err := s.search.GetProduct(ctx, id)
	if errors.Is(err, typesense.ErrNotFound) {
		return ProductDetail{}, ErrNotFound
	}
	if err != nil {
		return ProductDetail{}, fmt.Errorf("get product: %w", err)
	}
	return detailFromDocument(doc)
}
func (s *Service) List(ctx context.Context, opts ListProductsQuery) (pagination.Result[Product], error) {
	return s.list(ctx, opts, false)
}

func (s *Service) Recommend(ctx context.Context, opts ListProductsQuery) (pagination.Result[Product], error) {
	if strings.TrimSpace(opts.Search) == "" {
		return pagination.Result[Product]{}, fmt.Errorf("%w: recommendation need is required", ErrInvalidFilter)
	}
	return s.list(ctx, opts, true)
}

func (s *Service) list(ctx context.Context, opts ListProductsQuery, hybrid bool) (pagination.Result[Product], error) {
	q := opts.Query
	if opts.PageSize > 0 {
		q.Limit = opts.PageSize
	}
	if q.Page < 0 || q.Limit < 0 || q.Limit > 100 {
		return pagination.Result[Product]{}, fmt.Errorf("%w: invalid pagination", ErrInvalidFilter)
	}
	q.EnsureDefaults()
	if q.Page > math.MaxInt32 || q.Page-1 > math.MaxInt32/q.Limit {
		return pagination.Result[Product]{}, fmt.Errorf("%w: page is too large", ErrInvalidFilter)
	}
	for _, ids := range [][]int64{opts.CategoryIDs, opts.ProviderIDs, opts.BrandIDs} {
		for _, id := range ids {
			if id <= 0 {
				return pagination.Result[Product]{}, fmt.Errorf("%w: filter IDs must be positive", ErrInvalidFilter)
			}
		}
	}
	min, err := parsePrice(opts.MinPrice)
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("%w: min_price: %v", ErrInvalidFilter, err)
	}
	max, err := parsePrice(opts.MaxPrice)
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("%w: max_price: %v", ErrInvalidFilter, err)
	}
	if min != nil && max != nil && *min > *max {
		return pagination.Result[Product]{}, fmt.Errorf("%w: min_price exceeds max_price", ErrInvalidFilter)
	}
	if opts.Sort != "" && opts.Sort != "id" && opts.Sort != "price_asc" && opts.Sort != "price_desc" {
		return pagination.Result[Product]{}, fmt.Errorf("%w: unknown sort %q", ErrInvalidFilter, opts.Sort)
	}
	params := typesense.SearchParams{
		Query: opts.Search, CategoryIDs: opts.CategoryIDs, ProviderIDs: opts.ProviderIDs, BrandIDs: opts.BrandIDs,
		MinPrice: min, MaxPrice: max, InStock: opts.InStock, Sort: opts.Sort, Page: q.Page, PageSize: q.Limit,
	}
	var result typesense.SearchResult
	if hybrid {
		result, err = s.search.RecommendProducts(ctx, params)
	} else {
		result, err = s.search.SearchProducts(ctx, params)
	}
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("list products: %w", err)
	}
	items := make([]Product, 0, len(result.Documents))
	for _, doc := range result.Documents {
		product, err := productFromDocument(doc)
		if err != nil {
			return pagination.Result[Product]{}, err
		}
		items = append(items, product)
	}
	return pagination.NewResult(items, result.Found, q), nil
}

// Search applies the same catalog filters and sorting to a required text query.
func (s *Service) Search(ctx context.Context, opts ListProductsQuery) (pagination.Result[Product], error) {
	opts.Search = strings.TrimSpace(opts.Search)
	if opts.Search == "" || opts.Search == "*" {
		return pagination.Result[Product]{}, fmt.Errorf("%w: q must contain search text", ErrInvalidFilter)
	}
	return s.List(ctx, opts)
}
func parsePrice(raw string) (*float64, error) {
	if raw == "" {
		return nil, nil
	}
	if strings.TrimSpace(raw) != raw {
		return nil, errors.New("must be a non-negative decimal")
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil || math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
		return nil, errors.New("must be a non-negative decimal")
	}
	return &value, nil
}
