-- +goose Up
-- Retailer storage sections can include both SSDs and mechanical drives.
-- Change only isolated source products with one unambiguous title. Shared
-- canonical products require review because changing them affects all offers.
UPDATE catalog_products AS p
SET category_id = target.id, updated_at = now()
FROM categories AS current, categories AS target
WHERE current.id = p.category_id
  AND current.slug = 'hdd'
  AND target.slug = 'ssd'
  AND (SELECT count(*) FROM product_variants v WHERE v.product_id = p.id) = 1
  AND (SELECT count(*) FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
       WHERE v.product_id = p.id) = 1
  AND EXISTS (
      SELECT 1 FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
      WHERE v.product_id = p.id
        AND o.raw_name ~* '(^|[^[:alnum:]])(ssd|nvme)([^[:alnum:]]|$)|solid[ -]state (drive|disk)'
        AND o.raw_name !~* '(^|[^[:alnum:]])hdd([^[:alnum:]]|$)|hard[ -]disk|hard[ -]drive'
  );

UPDATE catalog_products AS p
SET category_id = target.id, updated_at = now()
FROM categories AS current, categories AS target
WHERE current.id = p.category_id
  AND current.slug = 'ssd'
  AND target.slug = 'hdd'
  AND (SELECT count(*) FROM product_variants v WHERE v.product_id = p.id) = 1
  AND (SELECT count(*) FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
       WHERE v.product_id = p.id) = 1
  AND EXISTS (
      SELECT 1 FROM offers o JOIN product_variants v ON v.id = o.product_variant_id
      WHERE v.product_id = p.id
        AND o.raw_name ~* '(^|[^[:alnum:]])hdd([^[:alnum:]]|$)|hard[ -]disk|hard[ -]drive'
        AND o.raw_name !~* '(^|[^[:alnum:]])(ssd|nvme)([^[:alnum:]]|$)|solid[ -]state (drive|disk)'
  );

-- +goose Down
-- Source category evidence is not retained for historical offers. Reversing
-- this data correction would reintroduce known misclassifications.
SELECT 1;
