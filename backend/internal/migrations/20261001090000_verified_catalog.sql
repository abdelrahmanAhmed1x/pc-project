-- +goose Up
ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_slug_check;
ALTER TABLE categories ADD CONSTRAINT categories_slug_check CHECK (slug IN (
    'cpu', 'gpu', 'motherboard', 'ram', 'ssd', 'hdd', 'case', 'power_supply',
    'cooling', 'monitor', 'accessories', 'laptops', 'mobile_phones',
    'headphones', 'headsets', 'earphones', 'true_wireless_earbuds'
));

ALTER TABLE providers ADD COLUMN trust_classification TEXT NOT NULL DEFAULT 'UNVERIFIED'
    CHECK (trust_classification IN (
        'VERIFIED_DIRECT_RETAILER', 'VERIFIED_DIRECT_WITH_MARKETPLACE',
        'MARKETPLACE', 'UNVERIFIED'
    ));
ALTER TABLE providers ADD COLUMN approved_seller_ids TEXT[] NOT NULL DEFAULT '{}';

UPDATE providers SET trust_classification = 'VERIFIED_DIRECT_RETAILER'
WHERE name IN ('sigma', 'elnekhely', 'elbadr', 'compumarts', 'alfrensia', 'maximum');

CREATE TABLE catalog_products (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    legacy_source_id BIGINT UNIQUE,
    category_id BIGINT NOT NULL REFERENCES categories(id),
    brand_id BIGINT REFERENCES brands(id),
    canonical_name TEXT NOT NULL CHECK (btrim(canonical_name) <> ''),
    model_number TEXT,
    specifications JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE product_variants (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id BIGINT NOT NULL REFERENCES catalog_products(id),
    identity_key TEXT NOT NULL UNIQUE,
    configuration JSONB NOT NULL DEFAULT '{}',
    manufacturer_part_number TEXT,
    gtin TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX product_variants_product_id_idx ON product_variants(product_id);
CREATE INDEX product_variants_gtin_idx ON product_variants(gtin) WHERE gtin IS NOT NULL;

CREATE TABLE offers (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_variant_id BIGINT NOT NULL REFERENCES product_variants(id),
    provider_id BIGINT NOT NULL REFERENCES providers(id),
    source_key TEXT NOT NULL,
    provider_product_id TEXT,
    provider_variant_id TEXT,
    seller_id TEXT,
    sku TEXT,
    price NUMERIC(12,2),
    old_price NUMERIC(12,2),
    price_status TEXT NOT NULL CHECK (price_status IN (
        'known', 'not_found', 'placeholder', 'price_on_request'
    )),
    raw_price_text TEXT,
    currency CHAR(3) NOT NULL DEFAULT 'EGP' CHECK (currency = 'EGP'),
    in_stock BOOLEAN,
    condition TEXT NOT NULL DEFAULT 'new' CHECK (condition IN ('new', 'used', 'refurbished', 'unknown')),
    warranty TEXT,
    url TEXT NOT NULL CHECK (btrim(url) <> ''),
    image_url TEXT,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    price_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT offers_price_state_check CHECK (
        (price_status = 'known' AND price > 0) OR
        (price_status <> 'known' AND price IS NULL)
    ),
    CONSTRAINT offers_old_price_check CHECK (old_price IS NULL OR old_price > 0),
    CONSTRAINT offers_source_key_unique UNIQUE (provider_id, source_key)
);
CREATE INDEX offers_variant_idx ON offers(product_variant_id);
CREATE INDEX offers_current_price_idx ON offers(product_variant_id, price)
    WHERE price_status = 'known' AND in_stock IS TRUE AND condition = 'new';

-- Preserve the currently displayed PC-parts catalog while new provider crawls
-- progressively replace source-only identities with exact model identities.
INSERT INTO catalog_products (legacy_source_id, category_id, brand_id, canonical_name)
SELECT id, category_id, brand_id, name FROM products;
INSERT INTO product_variants (product_id, identity_key)
SELECT cp.id, 'legacy:' || p.provider_id || ':' || p.canonical_product_url
FROM products p JOIN catalog_products cp ON cp.legacy_source_id = p.id;
INSERT INTO offers (product_variant_id, provider_id, source_key, price, price_status,
                    currency, in_stock, url, image_url, last_seen_at)
SELECT pv.id, p.provider_id, p.canonical_product_url,
       CASE WHEN p.price > 0 THEN p.price ELSE NULL END,
       CASE WHEN p.price > 0 THEN 'known' ELSE 'not_found' END,
       p.currency, p.in_stock, p.canonical_product_url, p.image_url, p.updated_at
FROM products p
JOIN catalog_products cp ON cp.legacy_source_id = p.id
JOIN product_variants pv ON pv.product_id = cp.id;

-- +goose Down
DROP TABLE offers;
DROP TABLE product_variants;
DROP TABLE catalog_products;
ALTER TABLE providers DROP COLUMN approved_seller_ids;
ALTER TABLE providers DROP COLUMN trust_classification;
ALTER TABLE categories DROP CONSTRAINT categories_slug_check;
ALTER TABLE categories ADD CONSTRAINT categories_slug_check CHECK (slug IN (
    'cpu', 'gpu', 'motherboard', 'ram', 'ssd', 'hdd', 'case', 'power_supply',
    'cooling', 'monitor', 'accessories'
));
