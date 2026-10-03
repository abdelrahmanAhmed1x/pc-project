package internal

import (
	"testing"
	"time"

	"pc/internal/modules/products/internal/sqlc"

	"github.com/jackc/pgx/v5/pgtype"
)

func TestIndexDocumentConversion(t *testing.T) {
	var price pgtype.Numeric
	if err := price.Scan("999.99"); err != nil {
		t.Fatal(err)
	}
	brandID, brandName := int64(7), "AMD"
	now := time.Date(2026, 9, 24, 12, 0, 0, 0, time.UTC)
	doc, err := documentFromRow(sqlc.GetProductsForIndexingRow{
		ID: 829, Name: "GPU", Price: price, Currency: "EGP", CategoryID: 2, CategorySlug: "gpu", VariantCount: 2,
		ProviderID: 1, ProviderIds: []int64{1, 2}, ProviderName: "sigma", BrandID: &brandID, BrandName: &brandName,
		CreatedAt: pgtype.Timestamptz{Time: now, Valid: true}, UpdatedAt: pgtype.Timestamptz{Time: now, Valid: true},
		LastSeenAt: pgtype.Timestamptz{Time: now, Valid: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	if doc.ID != "829" || doc.ProductID != 829 || doc.Price == nil || *doc.Price != 999.99 || doc.BrandID == nil || *doc.BrandID != 7 || doc.VariantCount != 2 || doc.CreatedAt != now.Unix() {
		t.Fatalf("incorrect document: %+v", doc)
	}
	product, err := productFromDocument(doc)
	if err != nil || product.ID != 829 || product.Price == nil || *product.Price != "999.99" || product.Brand == nil || product.ProviderCount != 2 || product.VariantCount != 2 {
		t.Fatalf("incorrect product: %+v %v", product, err)
	}
	doc.BrandID, doc.BrandName, doc.Price = nil, nil, nil
	product, err = productFromDocument(doc)
	if err != nil || product.Brand != nil || product.Price != nil {
		t.Fatalf("incorrect null mapping: %+v %v", product, err)
	}
	doc.PriceStatus, doc.LastSeenPrice, doc.LastSeenAt = "stale", new(float64), now.Unix()
	*doc.LastSeenPrice = 550
	product, err = productFromDocument(doc)
	if err != nil || product.Price != nil || product.LastSeenPrice == nil || *product.LastSeenPrice != "550.00" || product.LastSeenAt == nil || product.PriceStatus != "stale" {
		t.Fatalf("incorrect stale price mapping: %+v %v", product, err)
	}
}
