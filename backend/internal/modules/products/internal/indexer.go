package internal

import (
	"context"
	"fmt"
	"sort"

	"pc/internal/modules/products/internal/sqlc"
	"pc/internal/modules/products/internal/typesense"
)

const indexBatchSize = 500

type indexingQueries interface {
	GetProductsForIndexing(context.Context, sqlc.GetProductsForIndexingParams) ([]sqlc.GetProductsForIndexingRow, error)
}
type productImporter interface {
	ExistingProductIDs(context.Context) (map[string]struct{}, error)
	ImportProducts(context.Context, []typesense.ProductDocument) error
	DeleteProducts(context.Context, []string) error
}

type Indexer struct {
	queries indexingQueries
	search  productImporter
}

func NewIndexer(queries indexingQueries, search productImporter) *Indexer {
	return &Indexer{queries: queries, search: search}
}

// ReindexProducts upserts PostgreSQL products in keyset batches, then removes
// documents absent from PostgreSQL. Pruning starts only after every import succeeds.
func (i *Indexer) ReindexProducts(ctx context.Context) error {
	existing, err := i.search.ExistingProductIDs(ctx)
	if err != nil {
		return fmt.Errorf("read existing product IDs: %w", err)
	}
	var afterID int64
	for {
		rows, err := i.queries.GetProductsForIndexing(ctx, sqlc.GetProductsForIndexingParams{AfterID: afterID, BatchSize: indexBatchSize})
		if err != nil {
			return fmt.Errorf("read products after %d for indexing: %w", afterID, err)
		}
		if len(rows) == 0 {
			break
		}
		docs := make([]typesense.ProductDocument, 0, len(rows))
		for _, row := range rows {
			doc, err := documentFromRow(row)
			if err != nil {
				return fmt.Errorf("map product for indexing: %w", err)
			}
			docs = append(docs, doc)
		}
		if err := i.search.ImportProducts(ctx, docs); err != nil {
			return fmt.Errorf("index products after %d: %w", afterID, err)
		}
		for _, doc := range docs {
			delete(existing, doc.ID)
		}
		afterID = rows[len(rows)-1].ID
	}
	stale := make([]string, 0, len(existing))
	for id := range existing {
		stale = append(stale, id)
	}
	sort.Strings(stale)
	if err := i.search.DeleteProducts(ctx, stale); err != nil {
		return fmt.Errorf("remove stale products: %w", err)
	}
	return nil
}
