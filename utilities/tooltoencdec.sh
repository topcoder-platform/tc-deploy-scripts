#!/usr/bin/env bash
set +x
set -euo pipefail
echo 'This legacy secret-file helper is disabled in v2. Deployment must not fetch or source secret configuration. Use a reviewed non-secret manifest and ECS runtime secret references; see docs/MIGRATION.md.' >&2
exit 2
