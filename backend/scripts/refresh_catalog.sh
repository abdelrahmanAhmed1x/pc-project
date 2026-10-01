#!/usr/bin/env bash
set -u

backend_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parts_dir="$(cd "$backend_dir/../pc-parts" && pwd)" || exit 1
export PATH="$HOME/.local/bin:/usr/local/go/bin:$PATH"

# Keep scheduled full pipelines from overlapping through Batch and reindex.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/pc-project-catalog-refresh.lock"
if ! flock -n 9; then
    echo "catalog refresh already running; skipping this trigger" >&2
    exit 0
fi

cd "$parts_dir" || exit 1
uv run --locked pc-parts-pipeline
