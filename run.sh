#!/bin/sh
# Usage:
#   ./run.sh pre  [--config FILE] [--out DIR]
#   ./run.sh post [--manifest out/pre-<run-id>/manifest.json]
#   ./run.sh report --pre out/pre-<run-id> [--post out/post-<run-id>]
#   ./run.sh setup [--delete]     dev only: token, license, repositories
# Uses the published runner image; `docker compose build` builds it locally instead.
set -eu
cd "$(dirname "$0")"

case "${1:-}" in
  pre|post|report) module=aut ;;
  setup) module=aut.setup; shift ;;
  *) echo "usage: $0 pre|post|report|setup [options]" >&2; exit 64 ;;
esac

exec docker compose run --rm runner python -m "$module" "$@"
