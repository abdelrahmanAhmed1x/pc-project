package internal

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
	"time"

	"pc/internal/modules/products/internal/sqlc"
	"pc/internal/modules/products/internal/typesense"

	"github.com/jackc/pgx/v5/pgtype"
)

func ToCategories(rows []sqlc.Category) []Category {
	items := make([]Category, 0, len(rows))
	for _, row := range rows {
		items = append(items, Category{ID: row.ID, Slug: row.Slug})
	}
	return items
}
func ToProviders(rows []sqlc.GetAllProvidersRow) []Provider {
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

func documentFromRow(row sqlc.GetProductsForIndexingRow) (typesense.ProductDocument, error) {
	price, err := priceFromNumeric(row.Price)
	if err != nil {
		return typesense.ProductDocument{}, fmt.Errorf("product %d: %w", row.ID, err)
	}
	if !row.CreatedAt.Valid || !row.UpdatedAt.Valid {
		return typesense.ProductDocument{}, fmt.Errorf("product %d: missing timestamps", row.ID)
	}
	var stock *bool
	if row.StockKnown != nil && *row.StockKnown {
		stock = &row.InStock
	}
	return typesense.ProductDocument{
		ID: strconv.FormatInt(row.ID, 10), ProductID: row.ID, Name: row.Name,
		SemanticText: semanticText(row.Name, row.CategorySlug, row.BrandName),
		Price:        price, Currency: row.Currency, InStock: stock, ImageURL: row.ImageUrl,
		PriceStatus: row.PriceStatus, Condition: row.Condition, OfferCount: row.OfferCount,
		ProductVariantID: row.ProductVariantID,
		CategoryID:       row.CategoryID, CategorySlug: row.CategorySlug,
		ProviderID: row.ProviderID, ProviderIDs: row.ProviderIds, ProviderName: row.ProviderName,
		BrandID: row.BrandID, BrandName: row.BrandName,
		CanonicalProductURL: row.CanonicalProductUrl,
		CreatedAt:           row.CreatedAt.Time.Unix(), UpdatedAt: row.UpdatedAt.Time.Unix(),
	}, nil
}

func semanticText(name, category string, brand *string) string {
	text := strings.TrimSpace(name) + "\nCategory: " + strings.TrimSpace(category)
	if brand != nil && strings.TrimSpace(*brand) != "" {
		text += "\nBrand: " + strings.TrimSpace(*brand)
	}
	return text
}

// NUMERIC(12,2) fits within float64 with far less than half a cent of error.
// Round to cents before indexing; the canonical decimal remains in PostgreSQL.
func priceFromNumeric(n pgtype.Numeric) (*float64, error) {
	if !n.Valid {
		return nil, nil
	}
	if n.NaN || n.InfinityModifier != pgtype.Finite || n.Int == nil {
		return nil, fmt.Errorf("invalid numeric price")
	}
	rat := new(big.Rat).SetInt(n.Int)
	if n.Exp < 0 {
		rat.Quo(rat, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(-n.Exp)), nil)))
	}
	if n.Exp > 0 {
		rat.Mul(rat, new(big.Rat).SetInt(new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(n.Exp)), nil)))
	}
	value, _ := rat.Float64()
	if math.IsInf(value, 0) || math.IsNaN(value) || value < 0 || value > 9999999999.99 {
		return nil, fmt.Errorf("price outside NUMERIC(12,2) range")
	}
	value = math.Round(value*100) / 100
	return &value, nil
}

func productFromDocument(doc typesense.ProductDocument) (Product, error) {
	id, err := strconv.ParseInt(doc.ID, 10, 64)
	if err != nil || id <= 0 {
		return Product{}, fmt.Errorf("invalid indexed product id %q", doc.ID)
	}
	var price *string
	if doc.Price != nil {
		formatted := fmt.Sprintf("%.2f", *doc.Price)
		price = &formatted
	}
	var brand *Brand
	if doc.BrandID != nil && doc.BrandName != nil {
		brand = &Brand{ID: *doc.BrandID, Name: *doc.BrandName}
	}
	status := doc.PriceStatus
	if status == "" {
		if price == nil {
			status = "not_found"
		} else {
			status = "known"
		}
	}
	return Product{ID: id, Name: doc.Name, Price: price, PriceStatus: status, Condition: doc.Condition,
		OfferCount: doc.OfferCount, ProviderCount: int64(len(doc.ProviderIDs)),
		ProductVariantID: doc.ProductVariantID, Currency: doc.Currency,
		InStock: doc.InStock, ImageURL: doc.ImageURL,
		Category: Category{ID: doc.CategoryID, Slug: doc.CategorySlug},
		Provider: Provider{ID: doc.ProviderID, Name: doc.ProviderName}, Brand: brand,
	}, nil
}

func offerFromRow(row sqlc.GetOffersForProductRow) (Offer, error) {
	price, err := priceFromNumeric(row.Price)
	if err != nil {
		return Offer{}, err
	}
	old, err := priceFromNumeric(row.OldPrice)
	if err != nil {
		return Offer{}, err
	}
	var displayed, displayedOld *string
	if price != nil {
		value := fmt.Sprintf("%.2f", *price)
		displayed = &value
	}
	if old != nil {
		value := fmt.Sprintf("%.2f", *old)
		displayedOld = &value
	}
	if !row.LastSeenAt.Valid {
		return Offer{}, fmt.Errorf("offer %d: missing last_seen_at", row.ID)
	}
	return Offer{
		ID: row.ID, Provider: Provider{ID: row.ProviderID, Name: row.ProviderName},
		ProductVariantID: row.ProductVariantID, Configuration: row.Configuration,
		SKU: row.Sku, Price: displayed, OldPrice: displayedOld,
		PriceStatus: row.PriceStatus, Currency: row.Currency, InStock: row.InStock,
		Condition: row.Condition, Warranty: row.Warranty, URL: row.Url,
		ImageURL: row.ImageUrl, LastSeenAt: row.LastSeenAt.Time.UTC(),
	}, nil
}

func detailFromDocument(doc typesense.ProductDocument) (ProductDetail, error) {
	product, err := productFromDocument(doc)
	if err != nil {
		return ProductDetail{}, err
	}
	return ProductDetail{Product: product, CanonicalProductURL: doc.CanonicalProductURL,
		CreatedAt: time.Unix(doc.CreatedAt, 0).UTC(), UpdatedAt: time.Unix(doc.UpdatedAt, 0).UTC()}, nil
}
