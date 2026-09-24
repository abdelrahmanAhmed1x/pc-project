# PC Parts API tests

Open this directory as a collection in Bruno and select the `Local` environment.
Set `baseUrl` in that environment if the API is running elsewhere. Start the
backend and its PostgreSQL and Typesense dependencies before running the collection.

Run the entire collection in order with the Bruno CLI:

```sh
cd bruno
bru run --env Local
```

If the `bru` command is unavailable, install `@usebruno/cli` with npm or use
Bruno's desktop collection runner.

The list request stores the first returned product ID for the detail request.
When the catalog is empty, the detail request checks the expected not-found
response instead. Run the list request before running the detail request alone.
The filtered request uses example positive IDs; its assertions accept an empty
result, so it runs against any catalog. Change those IDs to values returned by
the metadata endpoints to inspect matching products interactively.
