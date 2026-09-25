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
		{SearchParams{CategoryIDs: []int64{1, 2}, ProviderIDs: []int64{1, 3}}, "category_id:[1,2] && provider_id:[1,3]"},
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

func TestSearchableFieldMigration(t *testing.T) {
	noIndex := false
	fields, err := searchableFieldUpdate([]api.Field{
		{Name: "category_slug", Type: "string", Index: &noIndex},
		{Name: "provider_name", Type: "string", Index: &noIndex},
	})
	if err != nil || len(fields) != 4 || fields[0].Drop == nil || !*fields[0].Drop || fields[1].Drop != nil ||
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
