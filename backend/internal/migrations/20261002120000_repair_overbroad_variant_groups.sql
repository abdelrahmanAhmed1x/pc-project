-- +goose Up
-- Repair the observed GPU board-model grouping error. Keep offers and source
-- identities intact; exact-variant matches remain one variant and are untouched.
CREATE TABLE gpu_group_repair_log (
    variant_id BIGINT PRIMARY KEY,
    original_product_id BIGINT NOT NULL,
    original_name TEXT NOT NULL,
    new_product_id BIGINT UNIQUE
);
CREATE TABLE phone_family_name_repair_log (
    product_id BIGINT PRIMARY KEY,
    original_name TEXT NOT NULL
);
-- +goose StatementBegin
DO $$
DECLARE
    grouped RECORD;
    member RECORD;
    created_product_id BIGINT;
    keep_first BOOLEAN;
BEGIN
    FOR grouped IN
        SELECT p.id
        FROM catalog_products p
        JOIN categories c ON c.id = p.category_id
        JOIN product_variants v ON v.product_id = p.id
        WHERE c.slug = 'gpu'
        GROUP BY p.id
        HAVING count(*) > 1
    LOOP
        keep_first := TRUE;
        INSERT INTO gpu_group_repair_log (variant_id, original_product_id, original_name)
        SELECT v.id, p.id, p.canonical_name FROM product_variants v
        JOIN catalog_products p ON p.id=v.product_id WHERE p.id=grouped.id;
        FOR member IN
            SELECT v.id, COALESCE(
                (SELECT NULLIF(btrim(o.raw_name), '') FROM offers o
                 WHERE o.product_variant_id = v.id AND o.raw_name IS NOT NULL
                 ORDER BY length(o.raw_name) DESC, o.id LIMIT 1),
                p.canonical_name) AS listing_name
            FROM product_variants v
            JOIN catalog_products p ON p.id = v.product_id
            WHERE v.product_id = grouped.id
            ORDER BY v.id
        LOOP
            IF keep_first THEN
                UPDATE catalog_products SET canonical_name = member.listing_name,
                    updated_at = now() WHERE id = grouped.id;
                keep_first := FALSE;
            ELSE
                INSERT INTO catalog_products (category_id, brand_id, canonical_name)
                SELECT category_id, brand_id, member.listing_name
                FROM catalog_products WHERE id = grouped.id
                RETURNING id INTO created_product_id;
                UPDATE product_variants SET product_id = created_product_id,
                    updated_at = now() WHERE id = member.id;
                UPDATE gpu_group_repair_log SET new_product_id = created_product_id
                WHERE variant_id = member.id;
            END IF;
        END LOOP;
    END LOOP;
END $$;
-- +goose StatementEnd

-- A family page must not advertise the storage/color of one variant while
-- showing the cheapest price of another. Keep iPhone family names neutral.
INSERT INTO phone_family_name_repair_log (product_id, original_name)
SELECT p.id, p.canonical_name FROM catalog_products p
JOIN categories c ON c.id=p.category_id
WHERE c.slug='mobile_phones'
  AND (SELECT count(*) FROM product_variants v WHERE v.product_id=p.id) > 1
  AND p.canonical_name ~* 'iphone[[:space:]]*[0-9]{1,2}';
UPDATE catalog_products p
SET canonical_name = btrim((regexp_match(p.canonical_name,
    '(?i)(iphone[[:space:]]*[0-9]{1,2}([[:space:]]+(pro[[:space:]]+max|pro|plus|mini|e))?)'))[1]),
    updated_at = now()
FROM categories c
WHERE c.id = p.category_id AND c.slug = 'mobile_phones'
  AND (SELECT count(*) FROM product_variants v WHERE v.product_id = p.id) > 1
  AND p.canonical_name ~* 'iphone[[:space:]]*[0-9]{1,2}'
  AND regexp_match(p.canonical_name,
      '(?i)(iphone[[:space:]]*[0-9]{1,2}([[:space:]]+(pro[[:space:]]+max|pro|plus|mini|e))?)') IS NOT NULL;

-- +goose Down
UPDATE catalog_products p SET canonical_name=l.original_name,updated_at=now()
FROM phone_family_name_repair_log l WHERE p.id=l.product_id;
UPDATE product_variants v SET product_id=l.original_product_id,updated_at=now()
FROM gpu_group_repair_log l WHERE v.id=l.variant_id;
UPDATE catalog_products p SET canonical_name=l.original_name,updated_at=now()
FROM gpu_group_repair_log l WHERE p.id=l.original_product_id;
DELETE FROM catalog_products p USING gpu_group_repair_log l
WHERE p.id=l.new_product_id AND l.new_product_id IS NOT NULL;
DROP TABLE phone_family_name_repair_log;
DROP TABLE gpu_group_repair_log;
