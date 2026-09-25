#!/usr/bin/env bash
set -u

backend_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parts_dir="$(cd "$backend_dir/../pc-parts" && pwd)" || exit 1
export PATH="$HOME/.local/bin:/usr/local/go/bin:$PATH"

# Keep scheduled runs from overlapping, including the reindex phase.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/pc-project-catalog-refresh.lock"
if ! flock -n 9; then
    echo "catalog refresh already running; skipping this trigger" >&2
    exit 0
fi

cd "$parts_dir" || exit 1
uv run --locked pc-parts run
crawl_status=$?

# Some providers may have committed even when the overall crawl failed.
cd "$backend_dir" || exit 1
go run ./cmd/reindex
index_status=$?

if (( crawl_status != 0 || index_status != 0 )); then
    echo "catalog refresh failed: crawl=$crawl_status reindex=$index_status" >&2
    exit 1
fi
