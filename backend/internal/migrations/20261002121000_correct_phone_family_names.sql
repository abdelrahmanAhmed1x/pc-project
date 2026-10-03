-- +goose Up
-- Use the saved source name because an earlier application of the preceding
-- migration could have retained only a captured suffix such as "Pro Max".
UPDATE catalog_products p
SET canonical_name = btrim((regexp_match(l.original_name,
    '(?i)(iphone[[:space:]]*[0-9]{1,2}([[:space:]]+(pro[[:space:]]+max|pro|plus|mini|e))?)'))[1]),
    updated_at = now()
FROM phone_family_name_repair_log l
WHERE p.id=l.product_id
  AND regexp_match(l.original_name,
    '(?i)(iphone[[:space:]]*[0-9]{1,2}([[:space:]]+(pro[[:space:]]+max|pro|plus|mini|e))?)') IS NOT NULL;

-- +goose Down
UPDATE catalog_products p SET canonical_name=l.original_name,updated_at=now()
FROM phone_family_name_repair_log l WHERE p.id=l.product_id;
