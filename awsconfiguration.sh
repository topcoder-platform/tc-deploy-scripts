#!/usr/bin/env bash
# Authentication check only. Credentials are never exported to the caller.
set +x
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" != --manifest ]]; then
  echo 'The Auth0 broker/awsenvconf interface has been removed. Use --manifest FILE to check OIDC identity; master_deploy.sh authenticates internally. See docs/MIGRATION.md.' >&2
  exit 2
fi
exec python3 -I "$script_dir/tcdeploy.py" check-auth "$@"
