package typesense

import (
	"errors"
	"net/http"
	"strings"
	"testing"

	client "github.com/typesense/typesense-go/v3/typesense"
	"github.com/typesense/typesense-go/v3/typesense/api"
)

func TestBuildProductFilter(t *testing.T) {
	min, max, stock := 10000.0, 50000.0, true
	cases := []struct {
		params SearchParams
		want   string
	}{
		{SearchParams{}, ""},
		{SearchParams{CategoryIDs: []int64{1, 2}}, "category_id:[1,2]"},
		{SearchParams{CategoryIDs: []int64{1, 2}, ProviderIDs: []int64{1, 3}}, "category_id:[1,2] && provider_ids:[1,3]"},
		{SearchParams{MinPrice: &min, MaxPrice: &max, InStock: &stock}, "price:>=10000 && price:<=50000 && in_stock:=true"},
	}
	for _, tc := range cases {
		if got := buildProductFilter(tc.params); got != tc.want {
			t.Errorf("filter = %q, want %q", got, tc.want)
		}
	}
}
func TestProductSort(t *testing.T) {
	for _, tc := range []struct {
		input    string
		wildcard bool
		want     string
		invalid  bool
	}{
		{"", true, "product_id:asc", false}, {"", false, "_text_match:desc,product_id:asc", false},
		{"id", false, "product_id:asc", false}, {"price_asc", true, "price:asc,product_id:asc", false},
		{"price_desc", true, "price:desc,product_id:asc", false}, {"arbitrary", true, "", true},
	} {
		got, err := productSort(tc.input, tc.wildcard)
		if got != tc.want || (err != nil) != tc.invalid {
			t.Errorf("sort %q = %q, %v", tc.input, got, err)
		}
	}
}

func TestImportProductsDetectsPartialFailure(t *testing.T) {
	docs := []ProductDocument{{ID: "1"}, {ID: "829"}}
	results := []*api.ImportDocumentResponse{{Success: true}, {Success: false, Error: "invalid price"}}
	err := validateImportResults(docs, results)
	if err == nil || !strings.Contains(err.Error(), "829") || !strings.Contains(err.Error(), "invalid price") {
		t.Fatalf("expected contextual import failure, got %v", err)
	}
	if err := validateImportResults(docs, results[:1]); err == nil {
		t.Fatal("missing result should fail")
	}
}

func TestRequestErrorClassifiesUnavailable(t *testing.T) {
	if !errors.Is(requestError(&client.HTTPError{Status: http.StatusServiceUnavailable}), ErrUnavailable) {
		t.Fatal("server error should be unavailable")
	}
	if errors.Is(requestError(&client.HTTPError{Status: http.StatusBadRequest}), ErrUnavailable) {
		t.Fatal("bad request is not an outage")
	}
}

func TestSearchPriorityParameters(t *testing.T) {
	params, err := productSearchRequest(SearchParams{Query: "  rtx  ", Page: 1, PageSize: 10})
	if err != nil {
		t.Fatal(err)
	}
	if *params.Q != "rtx" || *params.QueryBy != "name,category_slug,brand_name,provider_name" ||
		*params.QueryByWeights != "8,4,2,1" || *params.TextMatchType != "max_weight" ||
		*params.SplitJoinTokens != "always" ||
		*params.SortBy != "_text_match:desc,product_id:asc" || *params.PrioritizeExactMatch ||
		*params.PrioritizeNumMatchingFields || *params.DropTokensThreshold != 0 ||
		*params.EnableTyposForNumericalTokens || *params.EnableTyposForAlphaNumericalTokens ||
		*params.Page != 1 || *params.PerPage != 10 {
		t.Fatalf("incorrect text search parameters: %+v", params)
	}
	wildcard, err := productSearchRequest(SearchParams{Page: 1, PageSize: 10})
	if err != nil || *wildcard.Q != "*" || *wildcard.SortBy != "product_id:asc" {
		t.Fatalf("incorrect listing parameters: %+v %v", wildcard, err)
	}
}

func TestNormalizeSearchQuery(t *testing.T) {
	for _, tc := range []struct{ input, want string }{
		{"RTX4060Ti", "RTX 4060 Ti"},
		{"rtx 4060 ti", "rtx 4060 ti"},
		{"rx9070xt", "rx 9070 xt"},
		{"ryzen 7600 x", "ryzen 7600x"},
		{"Ryzen 5 7600 X", "Ryzen 5 7600X"},
		{"Core i5 13400 f", "Core i5 13400f"},
		{"1920 x 1080 monitor", "1920 x 1080 monitor"},
		{"32 gb ddr5", "32 gb ddr5"},
		{"1 tb nvme", "1 tb nvme"},
		{"750 w power supply", "750 w power supply"},
		{"b650m-a", "b650m-a"},
		{"gigabyt rtx 4070 super", "gigabyt rtx 4070 super"},
	} {
		if got := normalizeSearchQuery(tc.input); got != tc.want {
			t.Errorf("normalizeSearchQuery(%q) = %q, want %q", tc.input, got, tc.want)
		}
	}
}

func TestModelTypoFallbackKeepsStrictRequest(t *testing.T) {
	strict, err := productSearchRequest(SearchParams{Query: "rtx 4061 ti", Page: 1, PageSize: 10})
	if err != nil {
		t.Fatal(err)
	}
	retry := modelTypoFallback(strict)
	if *strict.EnableTyposForNumericalTokens || *strict.EnableTyposForAlphaNumericalTokens || strict.NumTypos != nil {
		t.Fatal("normal search must keep model numbers strict")
	}
	if !*retry.EnableTyposForNumericalTokens || !*retry.EnableTyposForAlphaNumericalTokens ||
		*retry.NumTypos != "1" || *retry.Q != *strict.Q || *retry.SplitJoinTokens != "always" {
		t.Fatalf("incorrect model typo fallback: %+v", retry)
	}
}

func TestHybridSearchRequest(t *testing.T) {
	stock, maxPrice := true, 35000.0
	p, err := recommendationSearchRequest(SearchParams{Query: "GPU for 1440p gaming", CategoryIDs: []int64{5},
		MaxPrice: &maxPrice, InStock: &stock, Page: 1, PageSize: 10})
	if err != nil || *p.QueryBy != "name,brand_name,semantic_text,embedding" ||
		*p.VectorQuery != "embedding:([], alpha: 0.35)" || *p.ExcludeFields != "embedding" ||
		*p.DropTokensThreshold != 0 || *p.FilterBy != "category_id:[5] && price:<=35000 && in_stock:=true" ||
		*p.PerPage != 10 {
		t.Fatalf("hybrid request: %+v %v", p, err)
	}
	if _, err := recommendationSearchRequest(SearchParams{}); err == nil {
		t.Fatal("empty semantic need accepted")
	}
}

func TestEmbeddingUsesStableFactsOnly(t *testing.T) {
	field := embeddingField()
	if field.Embed == nil || field.Embed.ModelConfig.ModelName != embeddingModel ||
		len(field.Embed.From) != 1 || field.Embed.From[0] != "semantic_text" {
		t.Fatalf("invalid embedding source: %+v", field)
	}
}

func TestSearchableFieldMigration(t *testing.T) {
	noIndex := false
	fields, err := searchableFieldUpdate([]api.Field{
		{Name: "category_slug", Type: "string", Index: &noIndex},
		{Name: "provider_name", Type: "string", Index: &noIndex},
	})
	if err != nil || len(fields) != 11 || fields[0].Drop == nil || !*fields[0].Drop || fields[1].Drop != nil ||
		fields[2].Drop == nil || !*fields[2].Drop || fields[3].Drop != nil {
		t.Fatalf("incorrect schema update: %+v %v", fields, err)
	}
	fields, err = searchableFieldUpdate(productSchema().Fields)
	if err != nil || len(fields) != 0 {
		t.Fatalf("new schema should need no update: %+v %v", fields, err)
	}
}

func TestDecodeExportedProductIDs(t *testing.T) {
	ids, err := decodeExportedProductIDs(strings.NewReader("{\"id\":\"829\"}\n{\"id\":\"7\"}\n"))
	if err != nil || len(ids) != 2 {
		t.Fatalf("ids=%v err=%v", ids, err)
	}
	if _, err := decodeExportedProductIDs(strings.NewReader("{\"id\":\"bad\"}\n")); err == nil {
		t.Fatal("non-numeric product ID should fail")
	}
}
