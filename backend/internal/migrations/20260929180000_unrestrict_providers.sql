-- +goose Up
ALTER TABLE providers DROP CONSTRAINT IF EXISTS providers_name_check;

-- +goose Down
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM providers WHERE name NOT IN ('sigma', 'elnekhely', 'elbadr')) THEN
        RAISE EXCEPTION 'Cannot restore legacy provider constraint while new providers exist';
    END IF;
END $$;
ALTER TABLE providers ADD CONSTRAINT providers_name_check
    CHECK (name IN ('sigma', 'elnekhely', 'elbadr'));
