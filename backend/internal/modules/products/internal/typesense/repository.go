package typesense

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"

	client "github.com/typesense/typesense-go/v3/typesense"
	"github.com/typesense/typesense-go/v3/typesense/api"
)

var ErrNotFound = errors.New("product not found")
var ErrUnavailable = errors.New("typesense unavailable")

func requestError(err error) error {
	var httpErr *client.HTTPError
	var netErr net.Error
	if errors.Is(err, context.DeadlineExceeded) || errors.As(err, &netErr) ||
		(errors.As(err, &httpErr) && httpErr.Status >= http.StatusInternalServerError) {
		return fmt.Errorf("%w: %w", ErrUnavailable, err)
	}
	return err
}

type SearchParams struct {
	Query                              string
	CategoryIDs, ProviderIDs, BrandIDs []int64
	MinPrice, MaxPrice                 *float64
	InStock                            *bool
	Sort                               string
	Page, PageSize                     int
}

type SearchResult struct {
	Documents []ProductDocument
	Found     int
}

type Repository struct {
	client *client.Client
}

func NewRepository(c *client.Client) *Repository {
	return &Repository{client: c}
}

func (r *Repository) EnsureCollection(ctx context.Context) error {
	_, err := r.client.Collection(collectionName).Retrieve(ctx)
	if err == nil {
		return nil
	}
	var httpErr *client.HTTPError
	if !errors.As(err, &httpErr) || httpErr.Status != http.StatusNotFound {
		return fmt.Errorf("retrieve products collection: %w", requestError(err))
	}
	if _, err := r.client.Collections().Create(ctx, productSchema()); err != nil {
		// Another instance may have created the collection concurrently.
		var conflict *client.HTTPError
		if errors.As(err, &conflict) && conflict.Status == http.StatusConflict {
			return nil
		}
		return fmt.Errorf("create products collection: %w", requestError(err))
	}
	return nil
}

// PrepareReindex changes the two display fields into searchable fields on an
// existing collection. It is called by the explicit reindex job, not startup.
func (r *Repository) PrepareReindex(ctx context.Context) error {
	collection := r.client.Collection(collectionName)
	current, err := collection.Retrieve(ctx)
	if err != nil {
		return fmt.Errorf("retrieve products schema: %w", requestError(err))
	}
	fields, err := searchableFieldUpdate(current.Fields)
	if err != nil {
		return err
	}
	if len(fields) == 0 {
		return nil
	}
	if _, err := collection.Update(ctx, &api.CollectionUpdateSchema{Fields: fields}); err != nil {
		return fmt.Errorf("make product fields searchable: %w", requestError(err))
	}
	return nil
}

func searchableFieldUpdate(existing []api.Field) ([]api.Field, error) {
	var changes []api.Field
	for _, name := range []string{"category_slug", "provider_name"} {
		var found *api.Field
		for i := range existing {
			if existing[i].Name == name {
				found = &existing[i]
				break
			}
		}
		if found == nil || found.Type != "string" {
			return nil, fmt.Errorf("products schema has missing or incompatible %s field", name)
		}
		if found.Index != nil && !*found.Index {
			drop := true
			changes = append(changes, api.Field{Name: name, Type: "string", Drop: &drop}, api.Field{Name: name, Type: "string"})
		}
	}
	return changes, nil
}

func (r *Repository) GetProduct(ctx context.Context, id int64) (ProductDocument, error) {
	doc, err := client.GenericCollection[ProductDocument](r.client, collectionName).Document(strconv.FormatInt(id, 10)).Retrieve(ctx)
	if err != nil {
		var httpErr *client.HTTPError
		if errors.As(err, &httpErr) && httpErr.Status == http.StatusNotFound {
			return ProductDocument{}, ErrNotFound
		}
		return ProductDocument{}, fmt.Errorf("retrieve product %d: %w", id, requestError(err))
	}
	return doc, nil
}

func (r *Repository) SearchProducts(ctx context.Context, p SearchParams) (SearchResult, error) {
	params, err := productSearchRequest(p)
	if err != nil {
		return SearchResult{}, err
	}
	response, err := r.client.Collection(collectionName).Documents().Search(ctx, params)
	if err != nil {
		return SearchResult{}, fmt.Errorf("search products: %w", requestError(err))
	}
	if response.Found == nil {
		return SearchResult{}, errors.New("search products: missing found count")
	}
	result := SearchResult{Documents: []ProductDocument{}, Found: *response.Found}
	if response.Hits != nil {
		for _, hit := range *response.Hits {
			if hit.Document == nil {
				return SearchResult{}, errors.New("search products: missing document in hit")
			}
			raw, err := json.Marshal(hit.Document)
			if err != nil {
				return SearchResult{}, fmt.Errorf("encode product hit: %w", err)
			}
			var doc ProductDocument
			if err := json.Unmarshal(raw, &doc); err != nil {
				return SearchResult{}, fmt.Errorf("decode product hit: %w", err)
			}
			result.Documents = append(result.Documents, doc)
		}
	}
	return result, nil
}

func productSearchRequest(p SearchParams) (*api.SearchCollectionParams, error) {
	q := strings.TrimSpace(p.Query)
	if q == "" {
		q = "*"
	}
	queryBy, weights, matchType := "name,category_slug,brand_name,provider_name", "8,4,2,1", "max_weight"
	prioritizeExact, prioritizeFields := false, false
	// Keep every query token, and preserve model numbers while retaining typo
	// tolerance for ordinary words (for example, a misspelled brand name).
	dropTokensThreshold, allowModelNumberTypos := 0, false
	params := &api.SearchCollectionParams{
		Q: &q, QueryBy: &queryBy, QueryByWeights: &weights, TextMatchType: &matchType,
		PrioritizeExactMatch: &prioritizeExact, PrioritizeNumMatchingFields: &prioritizeFields,
		DropTokensThreshold: &dropTokensThreshold, EnableTyposForNumericalTokens: &allowModelNumberTypos,
		EnableTyposForAlphaNumericalTokens: &allowModelNumberTypos,
		Page:                               &p.Page, PerPage: &p.PageSize,
	}
	if filter := buildProductFilter(p); filter != "" {
		params.FilterBy = &filter
	}
	sort, err := productSort(p.Sort, q == "*")
	if err != nil {
		return nil, err
	}
	if sort != "" {
		params.SortBy = &sort
	}
	return params, nil
}

// ExistingProductIDs streams only document IDs before a full reconciliation.
func (r *Repository) ExistingProductIDs(ctx context.Context) (map[string]struct{}, error) {
	include := "id"
	stream, err := r.client.Collection(collectionName).Documents().Export(ctx, &api.ExportDocumentsParams{IncludeFields: &include})
	if err != nil {
		return nil, fmt.Errorf("export product IDs: %w", requestError(err))
	}
	defer stream.Close()
	ids, err := decodeExportedProductIDs(stream)
	if err != nil {
		return nil, fmt.Errorf("read exported product IDs: %w", err)
	}
	return ids, nil
}

func decodeExportedProductIDs(stream io.Reader) (map[string]struct{}, error) {
	ids := make(map[string]struct{})
	decoder := json.NewDecoder(stream)
	for {
		var row struct {
			ID string `json:"id"`
		}
		if err := decoder.Decode(&row); err != nil {
			if errors.Is(err, io.EOF) {
				return ids, nil
			}
			return nil, fmt.Errorf("decode exported product ID: %w", err)
		}
		id, err := strconv.ParseInt(row.ID, 10, 64)
		if err != nil || id <= 0 {
			return nil, fmt.Errorf("invalid exported product ID %q", row.ID)
		}
		ids[row.ID] = struct{}{}
	}
}

func (r *Repository) DeleteProducts(ctx context.Context, ids []string) error {
	const deleteBatchSize = 100
	for start := 0; start < len(ids); start += deleteBatchSize {
		end := min(start+deleteBatchSize, len(ids))
		for _, raw := range ids[start:end] {
			id, err := strconv.ParseInt(raw, 10, 64)
			if err != nil || id <= 0 {
				return fmt.Errorf("invalid product ID for deletion %q", raw)
			}
		}
		filter := "id:[" + strings.Join(ids[start:end], ",") + "]"
		deleted, err := r.client.Collection(collectionName).Documents().Delete(ctx, &api.DeleteDocumentsParams{FilterBy: &filter})
		if err != nil {
			return fmt.Errorf("delete stale products: %w", requestError(err))
		}
		if deleted != end-start {
			return fmt.Errorf("delete stale products: deleted %d of %d documents", deleted, end-start)
		}
	}
	return nil
}

func (r *Repository) ImportProducts(ctx context.Context, products []ProductDocument) error {
	if len(products) == 0 {
		return nil
	}
	docs := make([]interface{}, len(products))
	for i := range products {
		docs[i] = products[i]
	}
	action := api.Upsert
	results, err := r.client.Collection(collectionName).Documents().Import(ctx, docs, &api.ImportDocumentsParams{Action: &action})
	if err != nil {
		return fmt.Errorf("import products: %w", requestError(err))
	}
	return validateImportResults(products, results)
}

func validateImportResults(products []ProductDocument, results []*api.ImportDocumentResponse) error {
	if len(results) != len(products) {
		return fmt.Errorf("import products: got %d results for %d documents", len(results), len(products))
	}
	for i, result := range results {
		if result == nil {
			return fmt.Errorf("import product %s: missing result", products[i].ID)
		}
		if !result.Success {
			return fmt.Errorf("import product %s: %s", products[i].ID, result.Error)
		}
	}
	return nil
}

func buildProductFilter(p SearchParams) string {
	var clauses []string
	ids := func(field string, values []int64) {
		if len(values) == 0 {
			return
		}
		parts := make([]string, len(values))
		for i, id := range values {
			parts[i] = strconv.FormatInt(id, 10)
		}
		clauses = append(clauses, field+":["+strings.Join(parts, ",")+"]")
	}
	ids("category_id", p.CategoryIDs)
	ids("provider_id", p.ProviderIDs)
	ids("brand_id", p.BrandIDs)
	if p.MinPrice != nil {
		clauses = append(clauses, "price:>="+strconv.FormatFloat(*p.MinPrice, 'f', -1, 64))
	}
	if p.MaxPrice != nil {
		clauses = append(clauses, "price:<="+strconv.FormatFloat(*p.MaxPrice, 'f', -1, 64))
	}
	if p.InStock != nil {
		clauses = append(clauses, "in_stock:="+strconv.FormatBool(*p.InStock))
	}
	return strings.Join(clauses, " && ")
}

func productSort(sort string, wildcard bool) (string, error) {
	switch sort {
	case "", "id":
		if wildcard || sort == "id" {
			return "product_id:asc", nil
		}
		return "_text_match:desc,product_id:asc", nil
	case "price_asc":
		return "price:asc,product_id:asc", nil
	case "price_desc":
		return "price:desc,product_id:asc", nil
	default:
		return "", fmt.Errorf("invalid product sort %q", sort)
	}
}
