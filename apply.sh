#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$HOME/anime-platform}"
STAMP="$(date +%Y%m%d-%H%M%S)"

copy_with_backup() {
  local src="$1"
  local dst="$2"

  mkdir -p "$(dirname "$dst")"
  if [[ -f "$dst" ]]; then
    cp -a "$dst" "$dst.bak-$STAMP"
    echo "[backup] $dst -> $dst.bak-$STAMP"
  fi
  cp -a "$src" "$dst"
  echo "[update] $dst"
}

copy_with_backup "backend/api.py" "$PROJECT_DIR/backend/api.py"
copy_with_backup "frontend/lib/api.ts" "$PROJECT_DIR/frontend/src/lib/api.ts"
copy_with_backup "frontend/app/watch/[slug]/[episode]/page.tsx" "$PROJECT_DIR/frontend/src/app/watch/[slug]/[episode]/page.tsx"

echo
echo "Primary-media-first patch installed."
echo "Configure PRIMARY_MEDIA_API_URL (and optional token/host allowlist) in the backend environment."
echo "Restart FastAPI and Next.js after changing environment variables."
