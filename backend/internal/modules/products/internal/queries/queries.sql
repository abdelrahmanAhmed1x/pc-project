-- name: GetAllProviders :many
SELECT id, name
FROM providers
WHERE trust_classification IN ('VERIFIED_DIRECT_RETAILER', 'VERIFIED_DIRECT_WITH_MARKETPLACE')
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
    p.id, p.canonical_name AS name,
    best.price, best.price_status, best.last_seen_price, best.last_seen_at,
    best.condition,
    best.currency, best.in_stock, best.stock_known, best.image_url,
    best.url AS canonical_product_url, p.created_at, p.updated_at,
    p.category_id, c.slug AS category_slug,
    best.provider_id, best.provider_name,
    ARRAY(SELECT DISTINCT pr.id FROM offers o
     JOIN product_variants v ON v.id=o.product_variant_id
     JOIN providers pr ON pr.id=o.provider_id
     WHERE v.product_id=p.id AND pr.trust_classification IN
       ('VERIFIED_DIRECT_RETAILER', 'VERIFIED_DIRECT_WITH_MARKETPLACE')
       AND (pr.trust_classification='VERIFIED_DIRECT_RETAILER'
            OR o.seller_id = ANY(pr.approved_seller_ids))
       AND pr.last_crawl_status IS DISTINCT FROM 'failed'
       AND o.last_seen_at >= now() - interval '9 days')::bigint[] AS provider_ids,
    p.brand_id, b.name AS brand_name,
    best.product_variant_id,
    (SELECT count(*) FROM product_variants v WHERE v.product_id=p.id) AS variant_count,
    (SELECT count(*) FROM offers o JOIN product_variants v ON v.id=o.product_variant_id
     JOIN providers pr ON pr.id=o.provider_id
     WHERE v.product_id=p.id AND pr.trust_classification IN
       ('VERIFIED_DIRECT_RETAILER', 'VERIFIED_DIRECT_WITH_MARKETPLACE')
       AND (pr.trust_classification='VERIFIED_DIRECT_RETAILER'
            OR o.seller_id = ANY(pr.approved_seller_ids))
       AND pr.last_crawl_status IS DISTINCT FROM 'failed'
       AND o.last_seen_at >= now() - interval '9 days') AS offer_count
FROM catalog_products AS p
JOIN categories AS c ON c.id = p.category_id
LEFT JOIN brands AS b ON b.id = p.brand_id
JOIN LATERAL (
    SELECT (CASE WHEN pr.last_crawl_status IS DISTINCT FROM 'failed'
                     AND o.last_seen_at >= now() - interval '9 days'
                THEN o.price ELSE NULL::numeric END)::numeric(12,2) AS price,
           CASE WHEN pr.last_crawl_status IS DISTINCT FROM 'failed'
                     AND o.last_seen_at >= now() - interval '9 days'
                THEN o.price_status
                WHEN o.price_status='known' THEN 'stale'
                ELSE 'not_found' END AS price_status,
           (CASE WHEN (pr.last_crawl_status='failed'
                            OR o.last_seen_at < now() - interval '9 days')
                       AND o.price_status='known'
                  THEN o.price ELSE NULL::numeric END)::numeric(12,2) AS last_seen_price,
           o.last_seen_at,
           o.currency,
           (CASE WHEN pr.last_crawl_status IS DISTINCT FROM 'failed'
                     AND o.last_seen_at >= now() - interval '9 days'
                THEN COALESCE(o.in_stock, false) ELSE false END)::boolean AS in_stock,
           (pr.last_crawl_status IS DISTINCT FROM 'failed'
            AND o.last_seen_at >= now() - interval '9 days'
            AND o.in_stock IS NOT NULL) AS stock_known,
           o.condition, o.image_url,
           o.url, o.provider_id, pr.name AS provider_name, o.product_variant_id
    FROM product_variants v
    JOIN offers o ON o.product_variant_id=v.id
    JOIN providers pr ON pr.id=o.provider_id
    WHERE v.product_id=p.id AND pr.trust_classification IN
      ('VERIFIED_DIRECT_RETAILER', 'VERIFIED_DIRECT_WITH_MARKETPLACE')
      AND (pr.trust_classification='VERIFIED_DIRECT_RETAILER'
           OR o.seller_id = ANY(pr.approved_seller_ids))
    ORDER BY (pr.last_crawl_status IS DISTINCT FROM 'failed'
              AND o.last_seen_at >= now() - interval '9 days') DESC,
             (o.in_stock IS TRUE AND o.price_status='known' AND o.condition='new') DESC,
             (o.price_status='known' AND o.condition='new') DESC,
             (o.price_status='known') DESC,
             CASE WHEN pr.last_crawl_status IS DISTINCT FROM 'failed'
                        AND o.last_seen_at >= now() - interval '9 days'
                  THEN o.price END ASC NULLS LAST,
             o.last_seen_at DESC, o.price ASC NULLS LAST, o.id ASC
    LIMIT 1
) best ON TRUE
WHERE p.id > sqlc.arg('after_id')
ORDER BY p.id ASC
LIMIT sqlc.arg('batch_size')::integer;

-- name: GetOffersForProduct :many
SELECT o.id, o.provider_id, pr.name AS provider_name, o.product_variant_id,
       v.configuration, o.sku, o.raw_name, o.price, o.old_price, o.price_status,
       o.currency, o.in_stock, o.condition, o.warranty, o.url, o.image_url,
       o.last_seen_at,
       (pr.last_crawl_status IS DISTINCT FROM 'failed'
        AND o.last_seen_at >= now() - interval '9 days') AS is_current
FROM offers o
JOIN product_variants v ON v.id=o.product_variant_id
JOIN providers pr ON pr.id=o.provider_id
WHERE v.product_id=sqlc.arg('product_id')
  AND pr.trust_classification IN ('VERIFIED_DIRECT_RETAILER', 'VERIFIED_DIRECT_WITH_MARKETPLACE')
  AND (pr.trust_classification='VERIFIED_DIRECT_RETAILER'
       OR o.seller_id = ANY(pr.approved_seller_ids))
ORDER BY is_current DESC,
         (o.in_stock IS TRUE AND o.price_status='known' AND o.condition='new') DESC,
         o.price ASC NULLS LAST, o.id ASC;
