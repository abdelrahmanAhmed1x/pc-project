# PC Parts crawler

One scheduled Python job crawls PC components from [Sigma Computer](https://www.sigma-computer.com/en), [El Nekhely Technology](https://www.elnekhelytechnology.com/), and [Elbadr Group](https://elbadrgroupeg.store/). It stages each provider's complete crawl, then synchronizes that provider's PostgreSQL products in one transaction. The job exits after one run. There is no queue, consumer, price history, or `last_seen_at` column.

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), [just](https://just.systems/), and Docker Compose. The Compose service binds PostgreSQL to localhost port **5433**; PostgreSQL uses port 5432 inside the container.

From the project directory, one command creates local credentials (if missing), starts PostgreSQL, installs dependencies, and performs one full crawl and synchronization **after the Go service has applied the Goose schema migration**:

```bash
cd ~/Documents/work/pc-project/pc-parts
just
```

`just setup` performs only the local setup steps. `just preview` performs a full crawl without writing products. `just sample` shows a small selection from CPU, GPU, RAM, and motherboard listings without writing products. `just test` runs the tests against the local PostgreSQL instance. Each recipe exits when finished; scheduling remains external.

The Go service owns schema migrations. Copy [init_schema.sql](init_schema.sql) into its Goose migrations directory with a versioned filename such as `00001_init_schema.sql`, then run Goose against the same PostgreSQL database before the first authoritative crawler run. The file contains Goose `Up` and `Down` sections. This project's `just setup` and Python CLI do not create or change the persistent schema. The local database created before this change already has the initial tables; the `IF NOT EXISTS` statements let Goose record this initial migration when applied to that database. Check the existing schema against the file before marking it migrated.

The first setup creates `.env` with a generated password and permissions `0600`; later runs reuse it. `.env` is ignored by Git. If you already have a `.env`, check that its `DATABASE_URL` uses host port 5433 and that the URL password matches `POSTGRES_PASSWORD`. The bootstrap script never overwrites an existing `.env`. Setup also aligns the database role password with `.env`, including when an existing Docker volume was created with older credentials.

For a Go backend running on the host, read the same `DATABASE_URL` from this `.env`. Its host is `localhost:5433`, database and user are `pcparts`, and its generated password is shared with the crawler. Keep the credential out of Git. A Go backend in the same Compose network should connect to host `postgres` on port `5432` using the same database, user, and password. The Go service needs its own Compose service or a shared Docker network for that hostname to resolve.

The equivalent manual setup is:

```bash
cd ~/Documents/work/pc-project/pc-parts
python3 scripts/bootstrap_env.py
docker compose up -d postgres
python3 scripts/sync_db_password.py
uv sync --locked --all-groups
```

`.env.example` contains example credentials only. `DATABASE_URL` is required for authoritative runs. The CLI reads `.env` from the current directory, and real environment variables take precedence.

## Run

```bash
uv run --locked pc-parts run                         # all three providers, once
uv run --locked pc-parts run --provider sigma        # one provider, once
uv run --locked pc-parts run --dry-run               # full crawl, no DB changes
uv run --locked pc-parts run --provider sigma --limit-categories 1 --limit-pages 2
uv run --locked pc-parts run --provider all --category cpu --category gpu --category ram --category motherboard --limit-pages 1 --sample-per-category 1
```

Any `--limit-pages`, `--limit-categories`, `--category`, or `--sample-per-category` run is a preview: it never calls the PostgreSQL synchronization routine. `--dry-run` also never mutates products. `--category` can be repeated to select canonical categories; `--sample-per-category` prints normalized rows and counts. A preview with no page limit validates that the selected categories reached their terminal pages. A page-limited preview checks the pages fetched but cannot claim the selected categories are complete.

The selected providers crawl concurrently, each with its own spider, staging database, request limits, and delay. The CLI returns nonzero if any requested provider fails. A provider failure does not prevent the remaining providers from being crawled and committed. An advisory lock covers the entire authoritative job, including all concurrent crawls, so overlapping scheduled runs cannot start. Interrupting a crawl does not delete products; a later run begins fresh. We intentionally do not resume partial crawler checkpoints because the transient stage is discarded after an interrupted run.

### Every 12 hours

Example crontab on a host using `Africa/Cairo` local time:

```cron
CRON_TZ=Africa/Cairo
0 0,12 * * * cd /home/abody/Documents/work/pc-project/pc-parts && /home/abody/.local/bin/uv run --locked pc-parts run >> /var/log/pc-parts.log 2>&1
```

Change `CRON_TZ` to select another scheduling timezone. The `.env` `TZ` value documents the intended local timezone for operators; database timestamps are `TIMESTAMPTZ`, and the cron daemon controls trigger times through `CRON_TZ`. Configure the executable path and writable log destination for your host. Run `uv sync --locked` during deployment, before the scheduled job.

## Crawl scope and extraction

The canonical categories are `cpu`, `gpu`, `motherboard`, `ram`, `ssd`, `hdd`, `case`, `power_supply`, and `cooling`. All are required in discovery; if a site stops exposing one, its provider crawl fails closed. We exclude unrelated accessories, services, bundles, promotional cards, external storage, and monitors. Category mapping comes from the discovered site category path, never a word in a product name.

| Canonical | El Nekhely path | Elbadr path | Sigma approved leaf categories |
| --- | --- | --- | --- |
| `cpu` | `/processors` | `/cpu` | Intel CPU, AMD CPU |
| `gpu` | `/graphics-card` | `/vga` | Nvidia GeForce, AMD RADEON |
| `motherboard` | `/motherboards` | `/motherboard` | Intel Motherboard, AMD Motherboard |
| `ram` | `/ram` | `/ram` | PC Memory, Laptop Memory |
| `ssd` | `/ssd` | `/ssd` | Internal SSD |
| `hdd` | `/hdd` | `/hdd` | Internal HDD |
| `case` | `/cases` | `/cases` | Mini Tower, Mid Tower, Full Tower |
| `power_supply` | `/power-supply` | `/power-supply` | Non modular, Sime modular, Full modular |
| `cooling` | `/fans-coolers` | `/cooling` | AIR Cooler, Liquid Cooler, Fans |

The OpenCart spiders discover category links on their homepages, select the shortest approved category path, and follow each listing's actual `a.next` link. This preserves Elbadr's category-specific `path` query. Sigma discovers its live nested category hierarchy from the server's Next.js response. It selects only approved leaves, so Sigma's `VGA Holder` and `Riser Cable` branches are excluded even though they sit beneath “Graphic Card & Accessories.” It requests the observed `/en/category/<id>` route, which redirects to `/en/search?filters=...`, and advances the observed `page` query parameter. It checks the current page index, last page index, next-button state, and product set on every page. It does not call Sigma's robots-disallowed `/api/` endpoints or require a browser for the currently server-rendered listing and Product JSON-LD data.

All spiders use Scrapling's Spider request/callback engine, request deduplication for category/listing URLs, a six-request per-domain limit, a configurable delay, robots rules, and streamed output. Detail requests are deliberately allowed to repeat when one product appears in different category paths; this preserves enough context for deterministic category selection. Both OpenCart spiders visit detail pages for stock verification and their canonical links; El Nekhely's listing stock is retained as a fallback. El Nekhely's robots-disallowed power supply detail path is kept as a listing-only product, so no prohibited request is scheduled. Sigma uses the matching detail-page Product JSON-LD for brand, price, stock, and image. Product JSON-LD entries are selected by product URL or matching slug, not by script order. The crawler fails a provider for failed requests, missing required categories, missing next links, looped or repeated pages, a populated listing that suddenly yields zero cards, or a required detail parse failure. An OpenCart category with no cards is accepted only when page 1 has no pagination and displays the site's explicit empty-category message; El Nekhely's `/hdd` currently does so.

Prices are `NUMERIC(12,2)` EGP. Listing sale prices use `.price-new` ahead of `.price-normal`; crossed-out `.price-old` is ignored. El Nekhely's `from` badge is retained as `price_label` during extraction: the stored `price` is the displayed starting price, not a guaranteed price for every variant. Unknown price or stock remains SQL `NULL`, never `0` or `false`. Canonical URLs drop fragments and tracking queries but retain Sigma's `id` and OpenCart `product_id` identity queries. Brand aliases are explicit in `normalization/brands.py`; unknown names use lowercase for consistent casing, and no fuzzy merging is used.

## Synchronization and deletion safety

1. Stream raw extracted items into batches of at most 500. Pandas cleans whitespace and nulls in each bounded batch. An item missing a name, canonical product URL, or known category is **reported and dropped**. A single invalid item does **not** fail its provider crawl, per the chosen policy.
2. A temporary disk-backed DuckDB database holds normalized rows. SQL selects one row per canonical product URL, preferring the deepest approved category path, then a fixed category order and non-null values. Its temporary directory is removed when the provider finishes.
3. After the spider reaches every category's terminal page, it checks the unique item count against `MIN_PRODUCTS_PER_PROVIDER` (default 10). The PostgreSQL transaction also refuses to delete more than `MAX_DELETE_FRACTION` (default 0.35) of that provider's existing rows. For a legitimate larger assortment change, review the crawl and temporarily raise the threshold to `1.0` for that run.
4. One transaction creates a provider-scoped temporary PostgreSQL stage, bulk copies all canonical rows, inserts providers/categories/brands, upserts changed products, and deletes only that provider's URLs missing from the complete stage. A failed statement rolls back everything. `created_at` is preserved. The upsert's `IS DISTINCT FROM` guard leaves `updated_at` unchanged on an identical rerun.

The database contains current products only. An explicit out-of-stock item stays with `in_stock = false`. An item absent from a successful complete crawl is removed. Existing rows remain untouched after a failed or limited crawl. Dropping an invalid item can make that particular product absent from an otherwise complete stage; the minimum count and deletion-fraction guard reduce the risk of broad accidental deletion, but operators should review the logged invalid-item count before increasing the deletion threshold.

The schema template is in `init_schema.sql`: BIGINT identity keys, foreign keys, unique `(provider_id, canonical_product_url)`, EGP currency, nullable unknown price/stock, and a provider index. PostgreSQL is the only persistent product database. Goose owns schema versions; the crawler never applies this template in production.

## Tests and verification

```bash
uv run --locked pytest -q
TEST_DATABASE_URL=postgresql://pcparts:change-me@localhost:5433/pcparts uv run --locked pytest -q
```

The database tests create and remove an isolated schema inside `TEST_DATABASE_URL`, loading the `Up` SQL from the Goose template as a test fixture. They cover repeat upserts without timestamp changes, provider-scoped deletion, deletion-guard preservation, and transaction rollback. Fixture tests use saved representative pages from all three retailers for discovery, card parsing, detail JSON-LD, prices, stock, URLs, and pagination. A limited live smoke command for each provider is shown under **Run**; add its provider and limits. These previews never delete rows.

On 2026-09-24, limited live Scrapling crawls reached page 2 for El Nekhely, Sigma, and Elbadr. A complete Sigma Full Tower category preview reached its terminal page. Sigma's CPU page 2 was separately checked against page 1 and had different products; CPU page 8 showed a disabled next button. El Nekhely RAM page 4 and Elbadr RAM page 18 were also checked live and had no next link. This verifies the observed pagination approaches, but **a full unrestricted crawl of all categories and a production replacement have not been run**. Markup, inventory, robots rules, and category trees can change; an unmapped category or unexplained zero-card page will fail closed until reviewed. The robots files were checked on 2026-09-24, and the spiders obey them during every run.

One Sigma CPU detail page currently has an `id` URL slug that describes an older bundle, while its visible heading and matching Product JSON-LD both describe the current CPU. The crawler retains the URL's `id` for identity and the visible product name. Review such source-data inconsistencies before using URL text as a product description.
