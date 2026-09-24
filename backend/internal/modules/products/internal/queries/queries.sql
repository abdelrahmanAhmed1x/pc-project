-- name: GetAllProviders :many
SELECT id, name
FROM providers
ORDER BY name;

-- name: GetAllCategories :many
SELECT id, slug
FROM categories
ORDER BY slug;

-- name: GetAllBrands :many
SELECT id, name
FROM brands
ORDER BY name;

-- name: GetProduct :one
SELECT
    p.id,
    p.name,
    p.price,
    p.currency,
    p.in_stock,
    p.image_url,
    p.canonical_product_url,
    p.created_at,
    p.updated_at,
    p.category_id,
    c.slug AS category_slug,
    p.provider_id,
    pr.name AS provider_name,
    p.brand_id,
    b.name AS brand_name
FROM products AS p
JOIN categories AS c ON c.id = p.category_id
JOIN providers AS pr ON pr.id = p.provider_id
LEFT JOIN brands AS b ON b.id = p.brand_id
WHERE p.id = sqlc.arg('id');

-- name: ListProducts :many
-- Empty ID arrays and NULL price/stock values disable their filters.
-- IDs within each array are ORed; the filter groups are ANDed. Price bounds are inclusive.
SELECT
    p.id,
    p.name,
    p.price,
    p.currency,
    p.in_stock,
    p.image_url,
    p.category_id,
    c.slug AS category_slug,
    p.provider_id,
    pr.name AS provider_name,
    p.brand_id,
    b.name AS brand_name
FROM products AS p
JOIN categories AS c ON c.id = p.category_id
JOIN providers AS pr ON pr.id = p.provider_id
LEFT JOIN brands AS b ON b.id = p.brand_id
WHERE (COALESCE(cardinality(sqlc.arg('category_ids')::bigint[]), 0) = 0 OR p.category_id = ANY(sqlc.arg('category_ids')::bigint[]))
  AND (COALESCE(cardinality(sqlc.arg('provider_ids')::bigint[]), 0) = 0 OR p.provider_id = ANY(sqlc.arg('provider_ids')::bigint[]))
  AND (COALESCE(cardinality(sqlc.arg('brand_ids')::bigint[]), 0) = 0 OR p.brand_id = ANY(sqlc.arg('brand_ids')::bigint[]))
  AND (sqlc.narg('min_price')::numeric IS NULL OR p.price >= sqlc.narg('min_price')::numeric)
  AND (sqlc.narg('max_price')::numeric IS NULL OR p.price <= sqlc.narg('max_price')::numeric)
  AND (sqlc.narg('in_stock')::boolean IS NULL OR p.in_stock = sqlc.narg('in_stock')::boolean)
ORDER BY
    CASE WHEN sqlc.arg('sort')::text = 'price_asc' THEN p.price END ASC NULLS LAST,
    CASE WHEN sqlc.arg('sort')::text = 'price_desc' THEN p.price END DESC NULLS LAST,
    p.id ASC
LIMIT sqlc.arg('page_size')::integer
OFFSET sqlc.arg('page_offset')::integer;

-- name: CountProducts :one
-- Exact total for pagination metadata using the same filters as ListProducts.
SELECT count(*)
FROM products AS p
WHERE (COALESCE(cardinality(sqlc.arg('category_ids')::bigint[]), 0) = 0 OR p.category_id = ANY(sqlc.arg('category_ids')::bigint[]))
  AND (COALESCE(cardinality(sqlc.arg('provider_ids')::bigint[]), 0) = 0 OR p.provider_id = ANY(sqlc.arg('provider_ids')::bigint[]))
  AND (COALESCE(cardinality(sqlc.arg('brand_ids')::bigint[]), 0) = 0 OR p.brand_id = ANY(sqlc.arg('brand_ids')::bigint[]))
  AND (sqlc.narg('min_price')::numeric IS NULL OR p.price >= sqlc.narg('min_price')::numeric)
  AND (sqlc.narg('max_price')::numeric IS NULL OR p.price <= sqlc.narg('max_price')::numeric)
  AND (sqlc.narg('in_stock')::boolean IS NULL OR p.in_stock = sqlc.narg('in_stock')::boolean);
