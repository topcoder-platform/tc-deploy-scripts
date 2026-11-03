#!/usr/bin/env bash
# v2 intentionally rejects the legacy SSM/secret-file CLI. See docs/MIGRATION.md.
set +x
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" != --manifest ]]; then
  echo 'v2 requires --manifest FILE --image CONTAINER=LOCAL_IMAGE. Migrate the pipeline and IAM role first; see docs/MIGRATION.md.' >&2
  exit 2
fi
exec python3 -I "$script_dir/tcdeploy.py" deploy "$@"
