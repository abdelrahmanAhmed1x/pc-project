-- +goose Up
ALTER TABLE providers ADD COLUMN last_crawl_status TEXT
    CHECK (last_crawl_status IN ('succeeded', 'failed'));
ALTER TABLE providers ADD COLUMN last_crawl_finished_at TIMESTAMPTZ;

CREATE TABLE provider_crawl_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id BIGINT NOT NULL REFERENCES providers(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    error_summary TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed'))
);
CREATE INDEX provider_crawl_runs_provider_started_idx
    ON provider_crawl_runs(provider_id, started_at DESC);
CREATE INDEX product_variants_mpn_lower_idx
    ON product_variants(lower(manufacturer_part_number))
    WHERE manufacturer_part_number IS NOT NULL;

-- +goose Down
DROP INDEX product_variants_mpn_lower_idx;
DROP TABLE provider_crawl_runs;
ALTER TABLE providers DROP COLUMN last_crawl_finished_at;
ALTER TABLE providers DROP COLUMN last_crawl_status;
