-- +goose Up
CREATE TABLE IF NOT EXISTS providers (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name IN ('sigma', 'elnekhely', 'elbadr'))
);

CREATE TABLE IF NOT EXISTS categories (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    CHECK (slug IN ('cpu', 'gpu', 'motherboard', 'ram', 'ssd', 'hdd', 'case', 'power_supply', 'cooling'))
);

CREATE TABLE IF NOT EXISTS brands (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS products (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id BIGINT NOT NULL REFERENCES providers(id),
    category_id BIGINT NOT NULL REFERENCES categories(id),
    brand_id BIGINT REFERENCES brands(id),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    price NUMERIC(12,2) CHECK (price >= 0),
    currency CHAR(3) NOT NULL DEFAULT 'EGP' CHECK (currency = 'EGP'),
    in_stock BOOLEAN,
    canonical_product_url TEXT NOT NULL CHECK (btrim(canonical_product_url) <> ''),
    image_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT products_provider_url_key UNIQUE (provider_id, canonical_product_url)
);

CREATE INDEX IF NOT EXISTS products_provider_id_idx ON products (provider_id);

-- +goose Down
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS brands;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS providers;