package internal

import (
	"context"
	"errors"
	"testing"
	"time"

	"pc/internal/modules/products/internal/sqlc"
	"pc/internal/modules/products/internal/typesense"

	"github.com/jackc/pgx/v5/pgtype"
)

type indexingStub struct {
	after []int64
	calls int
}

func (s *indexingStub) GetProductsForIndexing(_ context.Context, p sqlc.GetProductsForIndexingParams) ([]sqlc.GetProductsForIndexingRow, error) {
	s.after = append(s.after, p.AfterID)
	if p.BatchSize != indexBatchSize {
		panic("wrong batch size")
	}
	s.calls++
	if s.calls > 2 {
		return nil, nil
	}
	id := int64(s.calls * 10)
	return []sqlc.GetProductsForIndexingRow{{ID: id, CreatedAt: pgtype.Timestamptz{Time: time.Now(), Valid: true}, UpdatedAt: pgtype.Timestamptz{Time: time.Now(), Valid: true}}}, nil
}

type importerStub struct {
	ids        []string
	existing   map[string]struct{}
	deleted    []string
	deleteCall int
	err        error
}

func (s *importerStub) ExistingProductIDs(context.Context) (map[string]struct{}, error) {
	return s.existing, nil
}

func (s *importerStub) ImportProducts(_ context.Context, docs []typesense.ProductDocument) error {
	for _, doc := range docs {
		s.ids = append(s.ids, doc.ID)
	}
	return s.err
}
func (s *importerStub) DeleteProducts(_ context.Context, ids []string) error {
	s.deleteCall++
	s.deleted = append(s.deleted, ids...)
	return nil
}
func TestReindexProductsUsesKeysetBatches(t *testing.T) {
	queries, importer := &indexingStub{}, &importerStub{existing: map[string]struct{}{"10": {}, "5": {}, "20": {}}}
	if err := NewIndexer(queries, importer).ReindexProducts(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(queries.after) != 3 || queries.after[0] != 0 || queries.after[1] != 10 || queries.after[2] != 20 || len(importer.ids) != 2 || importer.ids[0] != "10" || importer.ids[1] != "20" {
		t.Fatalf("incorrect batches: after=%v ids=%v", queries.after, importer.ids)
	}
	if importer.deleteCall != 1 || len(importer.deleted) != 1 || importer.deleted[0] != "5" {
		t.Fatalf("incorrect stale deletion: %+v", importer.deleted)
	}
	failure := errors.New("partial import")
	failed := &importerStub{existing: map[string]struct{}{"5": {}}, err: failure}
	if err := NewIndexer(&indexingStub{}, failed).ReindexProducts(context.Background()); !errors.Is(err, failure) {
		t.Fatalf("expected import failure, got %v", err)
	}
	if failed.deleteCall != 0 {
		t.Fatal("failed import must not prune documents")
	}
}
