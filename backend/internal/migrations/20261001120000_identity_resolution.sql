-- +goose Up
ALTER TABLE offers ADD COLUMN raw_name TEXT;
UPDATE offers AS o SET raw_name = p.canonical_name
FROM product_variants AS v JOIN catalog_products AS p ON p.id = v.product_id
WHERE o.product_variant_id = v.id;
ALTER TABLE offers ADD CONSTRAINT offers_raw_name_nonempty
    CHECK (raw_name IS NULL OR btrim(raw_name) <> '');

CREATE TABLE variant_identity_aliases (
    identity_key TEXT PRIMARY KEY,
    variant_id BIGINT NOT NULL REFERENCES product_variants(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX variant_identity_aliases_variant_idx ON variant_identity_aliases(variant_id);

CREATE TABLE identity_decisions (
    pair_key TEXT PRIMARY KEY,
    left_signature TEXT NOT NULL,
    right_signature TEXT NOT NULL,
    rule_version INTEGER NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN
        ('same_exact_variant', 'same_product_different_variant', 'different_product', 'uncertain')),
    method TEXT NOT NULL CHECK (method IN ('deterministic', 'luna_medium', 'human')),
    explanation TEXT NOT NULL DEFAULT '',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    reviewed BOOLEAN NOT NULL DEFAULT false,
    applied_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX identity_decisions_pending_idx ON identity_decisions(verdict, applied_at)
    WHERE applied_at IS NULL;

CREATE TABLE identity_batches (
    id TEXT PRIMARY KEY,
    input_sha256 TEXT NOT NULL UNIQUE,
    openai_batch_id TEXT UNIQUE,
    reserved_usd NUMERIC(10,4) NOT NULL,
    actual_usd NUMERIC(10,4),
    status TEXT NOT NULL CHECK (status IN ('reserved', 'submitted', 'completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE identity_batches;
DROP TABLE identity_decisions;
DROP TABLE variant_identity_aliases;
ALTER TABLE offers DROP CONSTRAINT offers_raw_name_nonempty;
ALTER TABLE offers DROP COLUMN raw_name;
