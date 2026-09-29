package typesense

import (
	"context"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	client "github.com/typesense/typesense-go/v3/typesense"
	"github.com/typesense/typesense-go/v3/typesense/api"
)

// Run with RETRIEVAL_INTEGRATION_TEST=1 and the normal Typesense environment.
func TestLiveRetrievalCases(t *testing.T) {
	if os.Getenv("RETRIEVAL_INTEGRATION_TEST") != "1" {
		t.Skip("set RETRIEVAL_INTEGRATION_TEST=1 to test the local catalog")
	}
	url, key := os.Getenv("TYPESENSE_URL"), os.Getenv("TYPESENSE_API_KEY")
	if url == "" || key == "" {
		t.Fatal("TYPESENSE_URL and TYPESENSE_API_KEY are required")
	}
	ts := client.NewClient(client.WithServer(url), client.WithAPIKey(key), client.WithConnectionTimeout(20*time.Second))
	r := NewRepository(ts)
	maxPrice, stock := 35000.0, true
	cases := []struct {
		query, category, term string
		hybrid                bool
		max                   *float64
		stock                 *bool
	}{
		{"RX 9070", "gpu", "9070", false, nil, nil},
		{"GPU for 1440p gaming", "gpu", "", true, &maxPrice, &stock},
		{"2TB NVMe gaming SSD", "ssd", "2TB", true, nil, nil},
		{"quiet AM5 CPU cooler", "cooling", "", true, nil, nil},
		{"750 watt gaming PSU", "power_supply", "750", true, nil, nil},
		{"CPU for Docker and programming", "cpu", "", true, nil, nil},
	}
	for _, tc := range cases {
		t.Run(tc.query, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			params := SearchParams{Query: tc.query, MaxPrice: tc.max, InStock: tc.stock, Page: 1, PageSize: 10}
			// Resolve the ID from live data so this fixture survives category ID changes.
			wildcard, queryBy, filter, one := "*", "name", "category_slug:="+tc.category, 1
			lookup, err := ts.Collection(collectionName).Documents().Search(ctx, &api.SearchCollectionParams{
				Q: &wildcard, QueryBy: &queryBy, FilterBy: &filter, PerPage: &one,
			})
			if err != nil || lookup.Hits == nil || len(*lookup.Hits) == 0 {
				t.Fatalf("category lookup: %v", err)
			}
			if (*lookup.Hits)[0].Document == nil {
				t.Fatal("category document missing")
			}
			categoryID, ok := (*(*lookup.Hits)[0].Document)["category_id"].(float64)
			if !ok {
				t.Fatal("category ID missing")
			}
			params.CategoryIDs = []int64{int64(categoryID)}
			var result SearchResult
			err = nil
			if tc.hybrid {
				result, err = r.RecommendProducts(ctx, params)
			} else {
				result, err = r.SearchProducts(ctx, params)
			}
			if err != nil {
				t.Fatal(err)
			}
			if len(result.Documents) == 0 {
				t.Fatal("no catalog candidates")
			}
			for _, doc := range result.Documents {
				if doc.CategorySlug != tc.category || doc.CanonicalProductURL == "" {
					t.Fatalf("ungrounded or wrong category: %+v", doc)
				}
				if tc.max != nil && (doc.Price == nil || *doc.Price > *tc.max) {
					t.Fatalf("price filter failed: %+v", doc)
				}
				if tc.stock != nil && (doc.InStock == nil || !*doc.InStock) {
					t.Fatalf("stock filter failed: %+v", doc)
				}
				if _, err := strconv.ParseInt(doc.ID, 10, 64); err != nil {
					t.Fatalf("bad ID: %q", doc.ID)
				}
			}
			if tc.term != "" {
				matched := false
				for _, doc := range result.Documents {
					if strings.Contains(strings.ToLower(doc.Name), strings.ToLower(tc.term)) {
						matched = true
						break
					}
				}
				if !matched {
					t.Fatalf("expected model/spec family %q in candidate set", tc.term)
				}
			}
		})
	}
}
