-- +goose Up
-- "Solid State Hard Drive" is retailer wording for an SSD. A drive mounting
-- kit is an accessory, even when the title names both supported drive types.
UPDATE catalog_products AS p
SET category_id = target.id, updated_at = now()
FROM categories AS current, categories AS target
WHERE current.id = p.category_id AND current.slug = 'hdd' AND target.slug = 'ssd'
  AND (SELECT count(*) FROM product_variants v WHERE v.product_id = p.id) = 1
  AND (SELECT count(*) FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
       WHERE v.product_id = p.id) = 1
  AND EXISTS (
      SELECT 1 FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
      WHERE v.product_id = p.id
        AND o.raw_name ~* '(^|[^[:alnum:]])(ssd|nvme)([^[:alnum:]]|$)|solid[ -]state (drive|disk)'
        AND o.raw_name ~* 'hard[ -]drive'
        AND o.raw_name !~* '(^|[^[:alnum:]])hdd([^[:alnum:]]|$)|hard[ -]disk|mechanical hard[ -]drive|mounting kit|drive enclosure|drive caddy'
  );

UPDATE catalog_products AS p
SET category_id = target.id, updated_at = now()
FROM categories AS current, categories AS target
WHERE current.id = p.category_id AND current.slug IN ('ssd', 'hdd')
  AND target.slug = 'accessories'
  AND (SELECT count(*) FROM product_variants v WHERE v.product_id = p.id) = 1
  AND (SELECT count(*) FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
       WHERE v.product_id = p.id) = 1
  AND EXISTS (
      SELECT 1 FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
      WHERE v.product_id = p.id
        AND o.raw_name ~* 'mounting kit|drive enclosure|drive caddy'
  );

-- +goose Down
-- Historical retailer category labels are not retained for safe reversal.
SELECT 1;
