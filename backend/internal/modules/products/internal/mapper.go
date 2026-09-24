package internal

import (
	"fmt"

	"pc/internal/modules/products/internal/sqlc"

	"github.com/abdelrahmanAhmed1x/core/pagination"
	"github.com/jackc/pgx/v5/pgtype"
)

func ToCategories(rows []sqlc.Category) []Category {
	items := make([]Category, 0, len(rows))
	for _, row := range rows {
		items = append(items, Category{ID: row.ID, Slug: row.Slug})
	}
	return items
}

func ToProviders(rows []sqlc.Provider) []Provider {
	items := make([]Provider, 0, len(rows))
	for _, row := range rows {
		items = append(items, Provider{ID: row.ID, Name: row.Name})
	}
	return items
}

func ToBrands(rows []sqlc.Brand) []Brand {
	items := make([]Brand, 0, len(rows))
	for _, row := range rows {
		items = append(items, Brand{ID: row.ID, Name: row.Name})
	}
	return items
}

func productsFromRows(rows []sqlc.ListProductsRow) ([]Product, error) {
	products := make([]Product, 0, len(rows))
	for _, row := range rows {
		product, err := productFromRow(row)
		if err != nil {
			return nil, err
		}
		products = append(products, product)
	}
	return products, nil
}

func productFromRow(r sqlc.ListProductsRow) (Product, error) {
	price, err := priceFromNumeric(r.Price)
	if err != nil {
		return Product{}, err
	}
	var brand *Brand
	if r.BrandID != nil && r.BrandName != nil {
		brand = &Brand{ID: *r.BrandID, Name: *r.BrandName}
	}
	return Product{
		ID: r.ID, Name: r.Name, Price: price, Currency: r.Currency,
		InStock: r.InStock, ImageURL: r.ImageUrl,
		Category: Category{ID: r.CategoryID, Slug: r.CategorySlug},
		Provider: Provider{ID: r.ProviderID, Name: r.ProviderName}, Brand: brand,
	}, nil
}

func detailFromRow(row sqlc.GetProductRow) (ProductDetail, error) {
	product, err := productFromRow(sqlc.ListProductsRow{
		ID: row.ID, Name: row.Name, Price: row.Price, Currency: row.Currency,
		InStock: row.InStock, ImageUrl: row.ImageUrl,
		CategoryID: row.CategoryID, CategorySlug: row.CategorySlug,
		ProviderID: row.ProviderID, ProviderName: row.ProviderName,
		BrandID: row.BrandID, BrandName: row.BrandName,
	})
	if err != nil {
		return ProductDetail{}, err
	}
	return ProductDetail{
		Product: product, CanonicalProductURL: row.CanonicalProductUrl,
		CreatedAt: row.CreatedAt.Time, UpdatedAt: row.UpdatedAt.Time,
	}, nil
}

func priceFromNumeric(value pgtype.Numeric) (*string, error) {
	if !value.Valid {
		return nil, nil
	}
	raw, err := value.Value()
	if err != nil {
		return nil, fmt.Errorf("format product price: %w", err)
	}
	price := raw.(string)
	return &price, nil
}

func countParams(opts ListProductsQuery, minPrice, maxPrice pgtype.Numeric) sqlc.CountProductsParams {
	return sqlc.CountProductsParams{
		CategoryIds: opts.CategoryIDs, ProviderIds: opts.ProviderIDs, BrandIds: opts.BrandIDs,
		MinPrice: minPrice, MaxPrice: maxPrice, InStock: opts.InStock,
	}
}

func listParams(filters sqlc.CountProductsParams, q pagination.Query, sort string) sqlc.ListProductsParams {
	return sqlc.ListProductsParams{
		CategoryIds: filters.CategoryIds, ProviderIds: filters.ProviderIds, BrandIds: filters.BrandIds,
		MinPrice: filters.MinPrice, MaxPrice: filters.MaxPrice, InStock: filters.InStock,
		PageOffset: int32(q.Offset()), PageSize: int32(q.Limit), Sort: sort,
	}
}
