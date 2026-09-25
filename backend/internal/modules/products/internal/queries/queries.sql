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

-- name: GetProductsForIndexing :many
SELECT
    p.id, p.name, p.price, p.currency, p.in_stock, p.image_url,
    p.canonical_product_url, p.created_at, p.updated_at,
    p.category_id, c.slug AS category_slug,
    p.provider_id, pr.name AS provider_name,
    p.brand_id, b.name AS brand_name
FROM products AS p
JOIN categories AS c ON c.id = p.category_id
JOIN providers AS pr ON pr.id = p.provider_id
LEFT JOIN brands AS b ON b.id = p.brand_id
WHERE p.id > sqlc.arg('after_id')
ORDER BY p.id ASC
LIMIT sqlc.arg('batch_size')::integer;
