package internal

import (
	"context"
	"errors"
	"fmt"
	"math"
	"math/big"

	"pc/internal/modules/products/internal/sqlc"

	"github.com/abdelrahmanAhmed1x/core/pagination"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"
)

var (
	ErrNotFound      = errors.New("product not found")
	ErrInvalidFilter = errors.New("invalid product filter")
)

type productQueries interface {
	GetAllCategories(context.Context) ([]sqlc.Category, error)
	GetAllProviders(context.Context) ([]sqlc.Provider, error)
	GetAllBrands(context.Context) ([]sqlc.Brand, error)
	GetProduct(context.Context, int64) (sqlc.GetProductRow, error)
	CountProducts(context.Context, sqlc.CountProductsParams) (int64, error)
	ListProducts(context.Context, sqlc.ListProductsParams) ([]sqlc.ListProductsRow, error)
}

type Service struct {
	queries productQueries
}

func NewService(queries productQueries) *Service {
	return &Service{queries: queries}
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
	row, err := s.queries.GetProduct(ctx, id)
	if errors.Is(err, pgx.ErrNoRows) {
		return ProductDetail{}, ErrNotFound
	}
	if err != nil {
		return ProductDetail{}, fmt.Errorf("get product: %w", err)
	}
	return detailFromRow(row)
}

func (s *Service) List(ctx context.Context, opts ListProductsQuery) (pagination.Result[Product], error) {
	q := opts.Query
	if q.Page < 0 || q.Limit < 0 || q.Limit > 100 {
		return pagination.Result[Product]{}, fmt.Errorf("%w: invalid pagination", ErrInvalidFilter)
	}
	q.EnsureDefaults()
	if q.Page-1 > math.MaxInt32/q.Limit {
		return pagination.Result[Product]{}, fmt.Errorf("%w: page is too large", ErrInvalidFilter)
	}
	for _, ids := range [][]int64{opts.CategoryIDs, opts.ProviderIDs, opts.BrandIDs} {
		for _, id := range ids {
			if id <= 0 {
				return pagination.Result[Product]{}, fmt.Errorf("%w: filter IDs must be positive", ErrInvalidFilter)
			}
		}
	}
	minPrice, minValue, err := parsePrice(opts.MinPrice)
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("%w: min_price: %v", ErrInvalidFilter, err)
	}
	maxPrice, maxValue, err := parsePrice(opts.MaxPrice)
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("%w: max_price: %v", ErrInvalidFilter, err)
	}
	if minValue != nil && maxValue != nil && minValue.Cmp(maxValue) > 0 {
		return pagination.Result[Product]{}, fmt.Errorf("%w: min_price exceeds max_price", ErrInvalidFilter)
	}
	if opts.Sort == "" {
		opts.Sort = "id"
	}
	if opts.Sort != "id" && opts.Sort != "price_asc" && opts.Sort != "price_desc" {
		return pagination.Result[Product]{}, fmt.Errorf("%w: unknown sort %q", ErrInvalidFilter, opts.Sort)
	}
	filters := countParams(opts, minPrice, maxPrice)
	total, err := s.queries.CountProducts(ctx, filters)
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("count products: %w", err)
	}
	items := []Product{}
	if int64(q.Offset()) >= total {
		return pagination.NewResult(items, int(total), q), nil
	}
	rows, err := s.queries.ListProducts(ctx, listParams(filters, q, opts.Sort))
	if err != nil {
		return pagination.Result[Product]{}, fmt.Errorf("list products: %w", err)
	}
	items, err = productsFromRows(rows)
	if err != nil {
		return pagination.Result[Product]{}, err
	}
	return pagination.NewResult(items, int(total), q), nil
}
func parsePrice(raw string) (pgtype.Numeric, *big.Rat, error) {
	if raw == "" {
		return pgtype.Numeric{}, nil, nil
	}
	value, ok := new(big.Rat).SetString(raw)
	if !ok || value.Sign() < 0 {
		return pgtype.Numeric{}, nil, errors.New("must be a non-negative decimal")
	}
	var numeric pgtype.Numeric
	if err := numeric.Scan(raw); err != nil {
		return pgtype.Numeric{}, nil, err
	}
	return numeric, value, nil
}
