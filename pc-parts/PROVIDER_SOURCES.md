# New provider source investigation

Verified against the public storefronts on 2026-09-29. Each spider still validates discovery and pagination before synchronizing products.

## Alfrensia (`alfrensia`)

- **Platform/source:** WooCommerce. The public [Store API](https://alfrensia.com/wp-json/wc/store/v1/products?per_page=1) exposes product records; its [category API](https://alfrensia.com/wp-json/wc/store/v1/products/categories?per_page=100) exposes IDs, slugs, and counts. This is cleaner than HTML cards.
- **Discovery/pagination:** Approved category IDs feed `/wp-json/wc/store/v1/products?category=<id>&per_page=100&page=<n>`. A processor request reported 246 products and 123 pages at two per page.
- **Fields:** `permalink` is the product page; `name`, `brands[0].name`, `images[0].src`, and `is_in_stock` supply the other facts. Current `prices.price` is scaled by `currency_minor_unit`; `regular_price` can be the old price. Require `currency_code=EGP`.
- **Category map:** `processor→cpu`, `graphics-card→gpu`, `motherboard→motherboard`, `ram→ram`, `ssd→ssd`, `hdd→hdd`, `cases→case`, `power-supply→power_supply`, `air-liquid-cooling` and `case-fans→cooling`.
- **Complications:** Non-component categories are excluded. Names may contain HTML entities. Variable products can represent a starting price, following the existing one-price product contract.

## Maximum Hardware (`maximum`)

- **Platform/source:** OpenCart with Journal theme. The checked public API route did not expose a catalog. Server-rendered [category listings](https://maximumhardware.store/processors) and Product JSON-LD on [detail pages](https://maximumhardware.store/processors/amd-ryzen-9-9950x3d-granite-ridge-zen-5-16-core-4-3-ghz-socket-am5-170w-tray-without-fan) provide product data.
- **Discovery/pagination:** Approved homepage links lead to categories. Listings expose `?page=<n>` next links, handled by the existing OpenCart pagination checks.
- **Fields:** Current `.price-new` or `.price-normal` beats `.price-old`. Detail canonical URL and JSON-LD provide EGP price, image, and availability. A sampled card has `.stat-1` for stock and `.stat-2` for brand, opposite the two existing OpenCart stores.
- **Category map:** `processors→cpu`, `graphic-card→gpu`, `motherboards→motherboard`, `memory→ram`, `ssd→ssd`, `hard-disks→hdd`, `cases→case`, `power-supply→power_supply`, `fans-pc-cooling→cooling`.
- **Complications:** Some prices say “from”; the stored value is the displayed starting price, as with El Nekhely.

## Compumarts (`compumarts`)

- **Platform/source:** Shopify. Public [collection JSON](https://www.compumarts.com/collections/pc-parts-proccesor/products.json?limit=2) exposes product IDs, handles, vendor, images, and variants. The [collections page](https://www.compumarts.com/collections) exposes approved paths and declares the active currency as EGP.
- **Discovery/pagination:** `/collections/<handle>/products.json?limit=100&page=<n>` returned distinct pages in the live check. Stop after a short page and reject repeated pages.
- **Fields:** `title`, `vendor`, `images[0].src`, and `/products/<handle>` identify the offer. Variant `available` determines stock. Use the lowest price among available variants as a starting price; for fully unavailable products use the lowest listed price and mark out of stock. `compare_at_price` is an old price.
- **Category map:** `pc-parts-proccesor→cpu`, `pc-parts-graphic-card→gpu`, `pc-parts-mother-board→motherboard`, `pc-parts-ram-1→ram`, `storage-ssd→ssd`, `storage-hdd→hdd`, `pc-parts-computer-cases→case`, `pc-parts-power-supply→power_supply`, `pc-parts-cooling-solutions` and `computer-fan→cooling`.
- **Complications:** Collections overlap, so staging deduplicates by canonical product URL. Multi-variant products have one stored starting price under the existing schema.

No new canonical category or product column was needed. New-provider prices of 0–2 EGP are stored as unknown rather than genuine offers. The provider-name database check is removed by a versioned Goose migration; `providers.name` remains unique and products still reference `providers.id`.
