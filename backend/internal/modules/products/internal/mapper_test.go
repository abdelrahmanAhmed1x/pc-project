package internal

import (
	"testing"
	"time"

	"pc/internal/modules/products/internal/sqlc"

	"github.com/jackc/pgx/v5/pgtype"
)

func TestProductMappers(t *testing.T) {
	var price pgtype.Numeric
	if err := price.Scan("999.99"); err != nil {
		t.Fatal(err)
	}
	brandID := int64(7)
	brandName := "AMD"
	image := "https://example.com/cpu.png"
	stock := true
	now := time.Date(2026, 9, 24, 12, 0, 0, 0, time.UTC)
	detail, err := detailFromRow(sqlc.GetProductRow{
		ID: 1, Name: "CPU", Price: price, Currency: "EGP", InStock: &stock,
		ImageUrl: &image, CanonicalProductUrl: "https://example.com/cpu",
		CategoryID: 2, CategorySlug: "cpu", ProviderID: 3, ProviderName: "sigma",
		BrandID: &brandID, BrandName: &brandName,
		CreatedAt: pgtype.Timestamptz{Time: now, Valid: true},
		UpdatedAt: pgtype.Timestamptz{Time: now, Valid: true},
	})
	if err != nil {
		t.Fatal(err)
	}
	if detail.Price == nil || *detail.Price != "999.99" || detail.Brand == nil || detail.Brand.Name != "AMD" ||
		detail.Category.Slug != "cpu" || detail.Provider.Name != "sigma" || detail.CanonicalProductURL != "https://example.com/cpu" ||
		!detail.CreatedAt.Equal(now) || detail.InStock == nil || !*detail.InStock {
		t.Fatalf("incorrect detail mapping: %+v", detail)
	}
	listed, err := productFromRow(sqlc.ListProductsRow{
		ID: 2, Name: "RAM", CategoryID: 4, CategorySlug: "ram", ProviderID: 3, ProviderName: "sigma",
	})
	if err != nil {
		t.Fatal(err)
	}
	if listed.ID != 2 || listed.Price != nil || listed.Brand != nil || listed.Category.Slug != "ram" {
		t.Fatalf("incorrect list mapping: %+v", listed)
	}
	withPrice, err := productFromRow(sqlc.ListProductsRow{
		ID: 3, Name: "GPU", Price: price, Currency: "EGP", BrandID: &brandID, BrandName: &brandName,
	})
	if err != nil {
		t.Fatal(err)
	}
	if withPrice.ID != 3 || withPrice.Price == nil || *withPrice.Price != "999.99" ||
		withPrice.Brand == nil || withPrice.Brand.ID != 7 {
		t.Fatalf("incorrect priced mapping: %+v", withPrice)
	}
}
