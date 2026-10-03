# Product identity resolution

`just run` now executes the full pipeline: complete crawl, deterministic
candidate preparation, budgeted GPT-6 Luna Batch requests, collection, safe
merges, and Typesense reindexing. It requires `OPENAI_API_KEY` in the process
environment before the crawl begins. The command waits for Batch completion;
OpenAI allows up to 24 hours per batch, and a large first run may need more
than one batch. If interrupted, `just resume` collects submitted jobs and
continues matching without recrawling. `just pipeline-test` uses existing
catalog data and limits the model portion to 10 requests; it still waits for
the Batch result. `just apply-matches` applies collected decisions and
reindexes without crawling or submitting a new Batch; it does not need an
OpenAI key. A missing key fails before a full crawl.

The lower-level `pc-parts run` command remains crawl only. Use it when you
intentionally want to refresh offers without running identity resolution.

Run this job **after** a complete crawl and after applying the Goose migration
`20261001120000_identity_resolution.sql`. It never loads a `.env` file. Export
`DATABASE_URL` into the process environment. Only `submit` and `collect` also
need `OPENAI_API_KEY` in the process environment.

```bash
cd pc-parts
uv run pc-parts-resolve prepare /tmp/identity.jsonl --limit 1000
uv run pc-parts-resolve submit /tmp/identity.jsonl
uv run pc-parts-resolve collect <batch_id>
uv run pc-parts-resolve review --limit 20
uv run pc-parts-resolve decide <pair_key> same_exact_variant
uv run pc-parts-resolve apply
```

`prepare` is repeatable. It writes deterministic decisions to PostgreSQL and
creates a Batch API JSONL file only for ambiguous pairs. Candidate discovery
uses all current trusted offer titles attached to a variant, while each model
request sends the strongest matching title pair. Ambiguous pairs are ranked by
evidence score before filling a paid batch. Inspect its request count and
maximum reserved cost before submitting. `submit` enforces a local
$10 calendar-month cap. Pending batches retain their full reservation;
completed batches with fully usable answers count twice their calculated
actual cost, with a 5% reservation floor. Incomplete, failed, or unmeasured
batches retain the full reservation. The cap
is for this resolver's Batch submissions; API usage outside this database is
not visible to it. Duplicate batch files are rejected. Batch jobs can take up
to 24 hours. `collect` accepts only completed, structurally valid results and
skips pairs whose source evidence changed during the job. If a batch fails,
rerun `prepare`.

The model is `gpt-6-luna` with medium reasoning, strict JSON output, no tools,
and `store=false`. Names, identifiers, variants, and parsed attributes are sent;
prices, stock, URLs, retailer names, and customer data are excluded. The prompt
asks for one of `same_exact_variant`, `same_product_different_variant`,
`different_product`, or `uncertain`.

The `apply` command checks current evidence and hard conflicts again inside a
database transaction. An exact GTIN or MPN match, or a complete matching CPU
model/package fingerprint, can merge automatically. A Luna `same_exact_variant`
decision now merges without a second shared identifier when the current
evidence has no hard conflict. Luna `same_product_different_variant` decisions
can group phones with the same explicit model/generation and CPUs with the same
model, retaining separate `product_variants` and offers. Other categories use
exact purchasable configurations as their product boundary; a Luna variant
verdict cannot group different GPU boards, laptop builds, RAM kits, or drives.
Different critical specifications still prevent an exact-variant merge.
`different_product` and `uncertain` decisions
never merge. Applying a Luna verdict without independent identifiers increases
the chance of a false merge; inspect grouped offers if a retailer's data is
ambiguous.

`identity_decisions` records the evidence signatures, rule version, method,
verdict, explanation, review state, and token counts. The raw retailer title is
preserved in `offers.raw_name`. Price and stock changes do not invalidate an
identity decision. Repeated evidence reuses previous decisions without another
API call. Existing provider crawls and legacy product rows are not rewritten by
`prepare`, `submit`, or `collect`. Only `apply` changes product/offer links.

When using the lower-level commands, run the backend reindex after `apply` to
refresh Typesense documents. The full pipeline does this automatically. Review
the `review` output before accepting broad variant grouping. Cases,
motherboards, accessories, and power supplies participate in candidate review,
but do not receive automatic name-based merges because the source data does not
yet support safe exact matching there.
