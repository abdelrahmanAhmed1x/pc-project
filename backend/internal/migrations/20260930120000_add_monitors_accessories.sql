-- +goose Up
ALTER TABLE categories DROP CONSTRAINT IF EXISTS categories_slug_check;
ALTER TABLE categories ADD CONSTRAINT categories_slug_check
    CHECK (slug IN ('cpu', 'gpu', 'motherboard', 'ram', 'ssd', 'hdd', 'case', 'power_supply', 'cooling', 'monitor', 'accessories'));

-- +goose Down
DELETE FROM categories WHERE slug IN ('monitor', 'accessories');
ALTER TABLE categories DROP CONSTRAINT categories_slug_check;
ALTER TABLE categories ADD CONSTRAINT categories_slug_check
    CHECK (slug IN ('cpu', 'gpu', 'motherboard', 'ram', 'ssd', 'hdd', 'case', 'power_supply', 'cooling'));
