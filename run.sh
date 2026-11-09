#!/bin/sh
# Usage:
#   ./run.sh pre  [--config FILE] [--out DIR]
#   ./run.sh post [--manifest out/pre-<run-id>/manifest.json]
#   ./run.sh report --pre out/pre-<run-id> [--post out/post-<run-id>]
#   ./run.sh setup [--delete]     dev only: token, license, repositories
set -eu
cd "$(dirname "$0")"

command="${1:-}"
case "$command" in
  pre|post|report) module=aut ;;
  setup) module=aut.setup; shift ;;
  *) echo "usage: $0 pre|post|report|setup [options]" >&2; exit 64 ;;
esac

if [ "$command" = pre ] || [ "$command" = post ]; then
  docker compose up -d --build docker maven npm pypi helm curl
fi
exec docker compose run --rm --build runner python -m "$module" "$@"
