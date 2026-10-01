# Verified technology catalog

The crawler now writes three related records in PostgreSQL:

| Table | Meaning |
| --- | --- |
| `catalog_products` | A product family or exact model, such as an iPhone model or a particular laptop model. |
| `product_variants` | A sellable configuration, such as storage/color or an exact laptop hardware configuration. |
| `offers` | One retailer's current listing for one configuration. Contains price, stock, URL, and observation time. |

The existing `products` table and PC component spiders remain as a compatibility write path. The migration backfills those listings into the new catalog. The backend now indexes `catalog_products`, prefers the lowest **in-stock, new, known-price** trusted offer for each product, and loads all trusted offers for product details. If none are in stock, it displays a retailer's known listed price with its stock status. The UI lets the shopper select a configuration before comparing its offers. A catalog card's price is a starting price across configurations.

## Price representation

`offers.price` is nullable. `price_status` is one of `known`, `not_found`, `placeholder`, and `price_on_request`. A database constraint requires a positive price for `known` and SQL `NULL` for every other state. A scraped 0 or 1 EGP placeholder becomes `placeholder` with a null price. `old_price` is separate and nullable. A real retailer price remains visible even when the item is sold out; the UI labels it **Listed price · out of stock**. Only in-stock new offers are labeled as the lowest currently available price. The frontend renders a null price as **Price not found**.

## Trust boundary

`providers.trust_classification` is `VERIFIED_DIRECT_RETAILER`, `VERIFIED_DIRECT_WITH_MARKETPLACE`, `MARKETPLACE`, or `UNVERIFIED`. An authoritative crawl refuses unapproved providers. For a mixed marketplace provider, every offer must have a seller ID in `approved_seller_ids`; the backend applies the same filter when reading offers. A manually changed provider classification is never overwritten by the crawler. No Amazon, Noon, Jumia, OLX, Facebook Marketplace, or unidentified seller ingestion is configured.

| Provider | Method | Automatic ingestion |
| --- | --- | --- |
| Dream 2000 | Shopify collection `products.json`, one offer per variant | Yes |
| Tradeline | Shopify collection `products.json`, one offer per variant | Yes |
| 2B | Magento category pages plus product JSON-LD and specifications | Yes |
| Switch Plus | Storefront's public customer category and product API | Explicit `--provider switchplus` only; stock needs further verification |
| Raya Shop | Mixed direct and partner seller inventory | Disabled. No spider registered until an exact first-party seller filter is validated across the catalog. |
| Existing component stores | Existing spider plus new category seeds where supported | Yes |

Dream 2000, Tradeline, and CompuMarts Shopify variants are separate offer records. Tradeline and Switch Plus Apple part numbers are retained when present. 2B specification fields and JSON-LD identifiers are retained. The matching key uses a validated GTIN or brand plus manufacturer part number. Without a reliable shared identifier, a product stays source-specific rather than risking a wrong merge. All configurations of a retailer product are grouped under one canonical product. Laptop model names alone do not merge different CPU/GPU/RAM/storage combinations. Exact-key category or brand conflicts fail the transaction.

The crawler stages a complete provider run before replacing its offers in one transaction. A missing/failed page prevents replacement. The deletion-fraction guard blocks unexpectedly large removals. Limited previews do not write to PostgreSQL. `just run` now performs identity resolution and Typesense reindexing after authoritative crawls. If using the lower-level `pc-parts run` command, reindex separately with `just reindex-products` from `backend/`.

The UI and API return current offers; they do not keep historical price snapshots. `last_seen_at` and `price_checked_at` describe the latest successful scrape. Price sort/filter applies to the lowest currently available price and ignores products without a known current price.
